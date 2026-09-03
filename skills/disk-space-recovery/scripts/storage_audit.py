#!/usr/bin/env python3
"""Collect bounded, read-only host and container storage evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

SCHEMA = "disk-space-recovery.audit.v1"
MAX_OUTPUT = 128_000
MAX_LSOF_ROWS = 100
RUNTIME_COMMANDS = {
    "docker": "docker",
    "podman": "podman",
    "incus": "incus",
    "lxc": "lxc",
    "hypervisor-management": "pct",
    "libvirt": "virsh",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[list[str], int], CommandResult]
Exists = Callable[[str], bool]


def run_command(argv: list[str], timeout: int = 20) -> CommandResult:
    """Run one argv without a shell and bound the captured output."""
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return CommandResult(127, "", "not found")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "timed out")
    return CommandResult(completed.returncode, completed.stdout[:MAX_OUTPUT], completed.stderr[:2_000])


def _text(result: CommandResult) -> str | None:
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _error(label: str, result: CommandResult) -> str | None:
    return None if result.returncode == 0 else f"{label}: command failed with exit code {result.returncode}"


def _parse_int(value: str) -> int | None:
    try:
        return int(value.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def parse_df(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("Filesystem"):
            continue
        fields = line.split(maxsplit=6)
        if len(fields) != 7:
            continue
        filesystem, fstype, blocks, used, available, capacity, mounted = fields
        rows.append(
            {
                "filesystem": filesystem,
                "filesystemType": fstype,
                "blocks": _parse_int(blocks),
                "used": _parse_int(used),
                "available": _parse_int(available),
                "capacity": capacity,
                "mountPoint": mounted,
            }
        )
    return rows


def parse_inode_df(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("Filesystem"):
            continue
        fields = line.split(maxsplit=5)
        if len(fields) != 6:
            continue
        filesystem, inodes, used, free, capacity, mounted = fields
        rows.append(
            {
                "filesystem": filesystem,
                "inodes": _parse_int(inodes),
                "used": _parse_int(used),
                "free": _parse_int(free),
                "capacity": capacity,
                "mountPoint": mounted,
            }
        )
    return rows


def parse_mounts(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        fields = line.split(maxsplit=3)
        if len(fields) == 4:
            target, fstype, source, options = fields
            rows.append({"target": target, "filesystemType": fstype, "source": source, "options": options})
    return rows


def parse_large_files(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        size_text, separator, path = line.partition("\t")
        size = _parse_int(size_text)
        if separator and size is not None and path:
            rows.append({"bytes": size, "path": path[:1_000]})
    return sorted(rows, key=lambda row: (-int(row["bytes"]), str(row["path"])))


def parse_deleted_open(text: str) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        if line.startswith("COMMAND ") or not line.strip():
            continue
        fields = line.split(maxsplit=9)
        if len(fields) < 10 or "(deleted)" not in fields[9]:
            continue
        command, pid, _user, fd, file_type, _device, size_off, _nlink, _node, name = fields
        size = _parse_int(size_off) or 0
        normalized_name = name.lstrip("/")
        memory_backed = normalized_name.startswith("memfd:") or name.startswith("/dev/shm/")
        rows.append(
            {
                "command": command[:128],
                "pid": _parse_int(pid),
                "fd": fd[:32],
                "type": file_type[:16],
                "sizeOrOffset": size,
                "memoryBacked": memory_backed,
                "name": name[:1_000],
            }
        )
    rows.sort(key=lambda row: (-int(row["sizeOrOffset"]), str(row["name"])))
    return {
        "count": len(rows),
        "memoryBackedCount": sum(1 for row in rows if row["memoryBacked"]),
        "memoryBackedBytesOrOffsets": sum(int(row["sizeOrOffset"]) for row in rows if row["memoryBacked"]),
        "diskBackedCandidates": [row for row in rows if not row["memoryBacked"]][:MAX_LSOF_ROWS],
        "largest": rows[:MAX_LSOF_ROWS],
    }


def _json_lines(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def collect_docker(runner: Runner, exists: Exists) -> tuple[dict[str, object], list[str]]:
    if not exists("docker"):
        return {"available": False, "reason": "docker executable not found"}, []
    errors: list[str] = []
    info_result = runner(["docker", "info", "--format", "{{json .}}"], 20)
    info: dict[str, object] = {}
    info_text = _text(info_result)
    if info_text:
        try:
            raw = json.loads(info_text)
            if isinstance(raw, dict):
                for key in (
                    "ServerVersion",
                    "DockerRootDir",
                    "Driver",
                    "Containers",
                    "Images",
                    "OperatingSystem",
                    "KernelVersion",
                ):
                    if key in raw:
                        info[key] = raw[key]
        except json.JSONDecodeError:
            errors.append("docker info: invalid JSON response")
    else:
        errors.append(_error("docker info", info_result) or "docker info: no response")

    ps_result = runner(
        ["docker", "ps", "-a", "--size", "--no-trunc", "--format", "{{json .}}"],
        20,
    )
    containers: list[dict[str, object]] = []
    for row in _json_lines(ps_result.stdout if ps_result.returncode == 0 else ""):
        containers.append(
            {
                "id": str(row.get("ID", ""))[:128],
                "name": str(row.get("Names", ""))[:256],
                "image": str(row.get("Image", ""))[:256],
                "state": str(row.get("State", ""))[:64],
                "status": str(row.get("Status", ""))[:256],
                "size": str(row.get("Size", ""))[:256],
            }
        )
    if ps_result.returncode != 0:
        errors.append(_error("docker ps", ps_result) or "docker ps: failed")
    containers.sort(key=lambda row: (str(row["name"]), str(row["id"])))

    usage_result = runner(["docker", "system", "df", "-v"], 30)
    usage = {
        "exitCode": usage_result.returncode,
        "summary": usage_result.stdout[:MAX_OUTPUT] if usage_result.returncode == 0 else "",
    }
    if usage_result.returncode != 0:
        errors.append(_error("docker system df", usage_result) or "docker system df: failed")
    return {"available": True, "info": info, "containers": containers, "systemDf": usage}, errors


def runtime_access(exists: Exists, docker: dict[str, object]) -> dict[str, dict[str, object]]:
    """Describe namespace-visible runtime entrypoints without probing mutations."""
    result: dict[str, dict[str, object]] = {}
    for name, command in RUNTIME_COMMANDS.items():
        executable = exists(command)
        if name == "docker":
            result[name] = {
                "executable": executable,
                "daemonAccessible": bool(docker.get("available")),
                "reason": "daemon responded" if docker.get("available") else docker.get("reason", "unavailable"),
            }
        elif executable:
            result[name] = {
                "executable": True,
                "daemonAccessible": False,
                "reason": "entrypoint present; no read-only inventory probe configured",
            }
        else:
            result[name] = {
                "executable": False,
                "daemonAccessible": False,
                "reason": "entrypoint not found in current namespace",
            }
    return result


def _host_value(runner: Runner, argv: list[str], fallback: str | None = None) -> str | None:
    result = runner(argv, 10)
    return _text(result) or fallback


def collect_audit(
    runner: Runner = run_command,
    exists: Exists = lambda command: shutil.which(command) is not None,
    roots: Iterable[str] = (),
    large_file_bytes: int = 200 * 1024 * 1024,
    include_docker: bool = True,
    include_lsof: bool = True,
    include_du: bool = True,
    include_large_files: bool = True,
) -> dict[str, object]:
    """Collect a stable report from explicitly bounded roots and available tools."""
    normalized_roots = sorted({str(Path(root).expanduser()) for root in roots})
    errors: list[str] = []
    df_result = runner(["df", "-P", "-T"], 20)
    inode_result = runner(["df", "-P", "-i"], 20)
    mounts_result = runner(["findmnt", "-rn", "-o", "TARGET,FSTYPE,SOURCE,OPTIONS"], 20)
    lsof_result = (
        runner(["lsof", "-nP", "+L1"], 30)
        if include_lsof and exists("lsof")
        else CommandResult(127)
    )
    for label, result in (("df", df_result), ("inode df", inode_result), ("findmnt", mounts_result)):
        failure = _error(label, result)
        if failure:
            errors.append(failure)
    if include_lsof and exists("lsof"):
        failure = _error("lsof", lsof_result)
        if failure:
            errors.append(failure)

    directories: list[dict[str, object]] = []
    large_files: list[dict[str, object]] = []
    for root in normalized_roots:
        du_value: int | None = None
        du_complete = False
        if include_du:
            du_result = runner(["du", "-x", "-s", "-B1", "--", root], 30)
            for line in reversed(du_result.stdout.splitlines()):
                fields = line.split(maxsplit=1)
                if fields:
                    du_value = _parse_int(fields[0])
                    if du_value is not None:
                        break
            du_complete = du_result.returncode == 0
            if du_result.returncode != 0:
                errors.append(_error(f"du {root}", du_result) or f"du {root}: failed")
        directories.append({"path": root, "bytes": du_value, "complete": du_complete})

        if include_large_files:
            find_result = runner(
                [
                    "find",
                    root,
                    "-xdev",
                    "-type",
                    "f",
                    "-size",
                    f"+{large_file_bytes}c",
                    "-printf",
                    "%s\\t%p\\n",
                ],
                45,
            )
            if find_result.returncode == 0:
                large_files.extend(parse_large_files(find_result.stdout))
            else:
                errors.append(_error(f"find {root}", find_result) or f"find {root}: failed")

    docker, docker_errors = (
        collect_docker(runner, exists) if include_docker else ({"available": False, "reason": "disabled by request"}, [])
    )
    errors.extend(docker_errors)
    return {
        "schemaVersion": SCHEMA,
        "scope": {
            "roots": normalized_roots,
            "largeFileThresholdBytes": large_file_bytes,
            "duScan": include_du,
            "largeFileScan": include_large_files,
            "deletedOpenScan": include_lsof,
            "containerRuntimes": sorted(RUNTIME_COMMANDS) if include_docker else [],
        },
        "host": {
            "hostname": _host_value(runner, ["hostname"], socket.gethostname()),
            "virtualization": _host_value(runner, ["systemd-detect-virt"], "unknown"),
            "kernel": _host_value(runner, ["uname", "-srmo"]),
        },
        "filesystems": parse_df(df_result.stdout if df_result.returncode == 0 else ""),
        "inodes": parse_inode_df(inode_result.stdout if inode_result.returncode == 0 else ""),
        "mounts": parse_mounts(mounts_result.stdout if mounts_result.returncode == 0 else ""),
        "directories": sorted(directories, key=lambda row: str(row["path"])),
        "largeFiles": sorted(
            {json.dumps(row, sort_keys=True): row for row in large_files}.values(),
            key=lambda row: (-int(row["bytes"]), str(row["path"])),
        ),
        "deletedOpen": parse_deleted_open(lsof_result.stdout if include_lsof and lsof_result.returncode == 0 else ""),
        "docker": docker,
        "runtimeAccess": runtime_access(exists, docker),
        "errors": sorted(set(errors)),
    }


def write_report(report: dict[str, object], output: Path | None) -> None:
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="collect read-only storage evidence")
    audit.add_argument("--root", action="append", dest="roots", help="explicit root to inspect; repeatable")
    audit.add_argument("--large-file-mb", type=int, default=200)
    audit.add_argument("--output", type=Path)
    audit.add_argument("--no-docker", action="store_true")
    audit.add_argument("--skip-lsof", action="store_true")
    audit.add_argument("--skip-du", action="store_true")
    audit.add_argument("--skip-large-files", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.command != "audit":
        return 2
    if not arguments.roots:
        raise SystemExit("at least one explicit --root is required")
    if arguments.large_file_mb < 1:
        raise SystemExit("--large-file-mb must be positive")
    report = collect_audit(
        roots=arguments.roots,
        large_file_bytes=arguments.large_file_mb * 1024 * 1024,
        include_docker=not arguments.no_docker,
        include_lsof=not arguments.skip_lsof,
        include_du=not arguments.skip_du,
        include_large_files=not arguments.skip_large_files,
    )
    write_report(report, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
