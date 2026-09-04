#!/usr/bin/env python3
"""Bounded, deterministic disk and memory evidence for declared targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Callable, Iterable

SCHEMA = "resource-maintenance.audit.v1"
PLAN_SCHEMA = "host-resource-recovery.plan.v1"
MAX_OUTPUT = 128_000
MAX_ROWS = 100
ALLOWED_PLATFORMS = {"linux", "windows", "proxmox", "container"}
ALLOWED_TRANSPORTS = {"local", "ssh-posix", "ssh-powershell", "proxmox-pct"}
PROHIBITED = ("token", "password", "secret", "privatekey", "private_key", "command", "script", "shell", "argv")


class CommandResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


Runner = Callable[[list[str], int], CommandResult]


def run_command(argv: list[str], timeout: int = 20) -> CommandResult:
    """Run fixed argv without a shell and with bounded output."""
    try:
        result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return CommandResult(127, "", "not found")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "timed out")
    return CommandResult(result.returncode, result.stdout[:MAX_OUTPUT], result.stderr[:2_000])


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


def _number(value: object) -> int | float | None:
    try:
        raw = str(value).replace(",", "")
        return float(raw) if "." in raw else int(raw)
    except (TypeError, ValueError):
        return None


def _json(text: str) -> object | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def validate_inventory(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["inventory must be an object"]
    if data.get("schemaVersion") != "resource-maintenance.inventory.v1":
        errors.append("unsupported schemaVersion")
    if not isinstance(data.get("environment"), str) or not data["environment"]:
        errors.append("environment is required")
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        return sorted(set(errors + ["targets must be a non-empty list"]))
    ids: set[str] = set()
    allowed = {"id", "platform", "transport", "expectedIdentity", "availability", "parent", "endpoint", "containerId", "authoritativeDocs", "scanRoots", "protectedPaths", "thresholds", "operatorCapability", "procedureRefs", "recoveryRefs", "discoverChildren", "gpuMonitoring"}
    for index, target in enumerate(targets):
        prefix = f"targets[{index}]"
        if not isinstance(target, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(f"{prefix}: unknown field {key}" for key in sorted(set(target) - allowed))
        target_id = target.get("id")
        if not isinstance(target_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", target_id):
            errors.append(f"{prefix}: invalid id")
        elif target_id in ids:
            errors.append(f"{prefix}: duplicate id")
        else:
            ids.add(target_id)
        if target.get("platform") not in ALLOWED_PLATFORMS:
            errors.append(f"{prefix}: invalid platform")
        if target.get("transport") not in ALLOWED_TRANSPORTS:
            errors.append(f"{prefix}: invalid transport")
        for field in ("expectedIdentity", "authoritativeDocs", "scanRoots", "protectedPaths", "thresholds"):
            if field not in target:
                errors.append(f"{prefix}: missing {field}")
        for field in ("authoritativeDocs", "scanRoots", "protectedPaths"):
            if field in target and (not isinstance(target[field], list) or (field != "protectedPaths" and not target[field])):
                errors.append(f"{prefix}: {field} must be a list")
        thresholds = target.get("thresholds")
        if not isinstance(thresholds, dict) or not {"diskFreePercent", "memoryAvailablePercent"} <= set(thresholds):
            errors.append(f"{prefix}: thresholds missing required values")
        transport = target.get("transport")
        if transport != "local" and not isinstance(target.get("endpoint"), str):
            errors.append(f"{prefix}: endpoint required for remote transport")
        if transport == "proxmox-pct" and not isinstance(target.get("containerId"), int):
            errors.append(f"{prefix}: containerId required for proxmox-pct")
        if target.get("platform") == "windows" and transport == "ssh-posix":
            errors.append(f"{prefix}: Windows target cannot use ssh-posix")
        if target.get("platform") != "windows" and transport == "ssh-powershell":
            errors.append(f"{prefix}: ssh-powershell requires Windows target")
        for key, value in target.items():
            key_text = str(key).casefold()
            if any(word == key_text or word in key_text for word in PROHIBITED):
                errors.append(f"{prefix}: prohibited field {key}")
            if isinstance(value, str) and any(marker in value.casefold() for marker in ("password=", "token=", "secret=", "-----begin")):
                errors.append(f"{prefix}: prohibited secret value")
    for target in targets:
        if isinstance(target, dict) and target.get("parent") and target["parent"] not in ids:
            errors.append(f"target {target.get('id')}: parent not found")
    return sorted(set(errors))


def load_inventory(path: Path) -> dict[str, object]:
    data = _json(path.read_text(encoding="utf-8"))
    errors = validate_inventory(data)
    if errors:
        raise ValueError("invalid inventory: " + "; ".join(errors))
    assert isinstance(data, dict)
    return data


def _parse_df(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        fields = line.split(maxsplit=6)
        if len(fields) == 7 and fields[0] != "Filesystem":
            fs, fstype, blocks, used, available, capacity, mount = fields
            rows.append({"filesystem": fs, "filesystemType": fstype, "blocks": _number(blocks), "used": _number(used), "available": _number(available), "capacity": capacity, "mountPoint": mount})
    return sorted(rows, key=lambda row: str(row["mountPoint"]))


def _parse_inodes(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and fields[0] != "Filesystem":
            filesystem, inodes, used, available, capacity, mount = fields
            rows.append({"filesystem": filesystem, "inodes": _number(inodes), "used": _number(used), "available": _number(available), "capacity": capacity, "mountPoint": mount})
    return sorted(rows, key=lambda row: str(row["mountPoint"]))


def _parse_free(text: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for line in text.splitlines():
        fields = line.split()
        if fields and fields[0] in {"Mem:", "Swap:"} and len(fields) >= 4:
            label = "physical" if fields[0] == "Mem:" else "swap"
            available = fields[6] if label == "physical" and len(fields) > 6 else fields[3]
            result[label] = {"totalBytes": _number(fields[1]), "usedBytes": _number(fields[2]), "availableBytes": _number(available)}
    return result


def _parse_ps(text: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and _number(fields[0]) is not None:
            rows.append({"pid": int(_number(fields[0]) or 0), "rssBytes": int(_number(fields[1]) or 0) * 1024, "name": fields[2][:128]})
    return sorted(rows, key=lambda row: (-int(row["rssBytes"]), int(row["pid"])))[:MAX_ROWS]


def _run(runner: Runner, argv: list[str], errors: list[str], timeout: int = 20) -> str:
    result = runner(argv, timeout)
    if result.returncode:
        errors.append(f"{' '.join(argv[:2])}: exit {result.returncode}")
        return ""
    return result.stdout


def collect_linux(target: dict[str, object], runner: Runner = run_command, exists: Callable[[str], bool] = lambda name: shutil.which(name) is not None) -> dict[str, object]:
    errors: list[str] = []
    filesystems = _parse_df(_run(runner, ["df", "-P", "-T"], errors))
    inodes = _parse_inodes(_run(runner, ["df", "-P", "-i"], errors))
    memory = _parse_free(_run(runner, ["free", "-b"], errors))
    processes = _parse_ps(_run(runner, ["ps", "-eo", "pid=,rss=,comm="], errors))
    containers: list[dict[str, object]] = []
    if exists("docker"):
        raw = _run(runner, ["docker", "ps", "-a", "--size", "--format", "{{json .}}"], errors)
        for line in raw.splitlines():
            value = _json(line)
            if isinstance(value, dict):
                containers.append({"id": str(value.get("ID", ""))[:128], "name": str(value.get("Names", ""))[:128], "state": str(value.get("State", ""))[:32], "size": str(value.get("Size", ""))[:128]})
    large_files: list[dict[str, object]] = []
    for root in sorted(set(str(item) for item in target.get("scanRoots", []))):
        raw = _run(runner, ["find", root, "-xdev", "-type", "f", "-size", "+200000000c", "-printf", "%s\\t%p\\n"], errors, 45)
        for line in raw.splitlines():
            size, separator, path = line.partition("\t")
            if separator and _number(size) is not None:
                large_files.append({"bytes": int(_number(size) or 0), "path": path[:1000], "protected": path in target.get("protectedPaths", [])})
    identity = _run(runner, ["hostname"], errors).strip() or socket.gethostname()
    return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": target["transport"]}, "identity": identity[:128], "filesystems": filesystems, "inodes": inodes, "memory": memory, "processes": processes, "containers": sorted(containers, key=lambda row: (str(row["name"]), str(row["id"]))), "largeFiles": sorted(large_files, key=lambda row: (-int(row["bytes"]), str(row["path"]))), "errors": sorted(set(errors))}


WINDOWS_SCRIPT = "$ErrorActionPreference='Stop'; $volumes=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object {$_.Size -gt 0} | ForEach-Object {[ordered]@{filesystem=$_.DeviceID; filesystemType=$_.FileSystem; totalBytes=[int64]$_.Size; usedBytes=([int64]$_.Size-[int64]$_.FreeSpace); availableBytes=[int64]$_.FreeSpace; capacity=(('{0:P2}' -f (([double]$_.Size-[double]$_.FreeSpace)/[double]$_.Size))); mountPoint=$_.DeviceID}}); $os=Get-CimInstance Win32_OperatingSystem; $cs=Get-CimInstance Win32_ComputerSystem; $pagefile=@(Get-CimInstance Win32_PageFileUsage | ForEach-Object {[ordered]@{path=$_.Name; allocatedBytes=([int64]$_.AllocatedBaseSize*1KB); usedBytes=([int64]$_.CurrentUsage*1KB)}}); $memory=[ordered]@{physical=[ordered]@{totalBytes=([int64]$cs.TotalPhysicalMemory); availableBytes=([int64]$os.FreePhysicalMemory*1KB)}; commit=[ordered]@{limitBytes=([int64]$os.TotalVirtualMemorySize*1KB); usedBytes=([int64](($os.TotalVirtualMemorySize-$os.FreeVirtualMemory)*1KB))}; pagefile=$pagefile}; $processes=@(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 100 | ForEach-Object {[ordered]@{pid=[int]$_.Id; rssBytes=[int64]$_.WorkingSet64; name=$_.ProcessName}}); $o=[ordered]@{identity=$env:COMPUTERNAME; volumes=$volumes; inodes=@(); memory=$memory; processes=$processes; containers=@(); largeFiles=@(); errors=@()}; $o|ConvertTo-Json -Depth 6 -Compress"
POSIX_SCRIPT = "set -eu; hostname; free -b; df -P -T; df -P -i; ps -eo pid=,rss=,comm="


def _normalise_windows(payload: dict[str, object]) -> dict[str, object]:
    """Accept only the fixed PowerShell payload shape and expose audit fields."""
    result: dict[str, object] = {
        "identity": str(payload.get("identity", ""))[:128],
        "filesystems": payload.get("volumes", []) if isinstance(payload.get("volumes"), list) else [],
        "inodes": payload.get("inodes", []) if isinstance(payload.get("inodes"), list) else [],
        "memory": payload.get("memory", {}) if isinstance(payload.get("memory"), dict) else {},
        "processes": payload.get("processes", []) if isinstance(payload.get("processes"), list) else [],
        "containers": payload.get("containers", []) if isinstance(payload.get("containers"), list) else [],
        "largeFiles": payload.get("largeFiles", []) if isinstance(payload.get("largeFiles"), list) else [],
        "errors": payload.get("errors", []) if isinstance(payload.get("errors"), list) else [],
    }
    result["processes"] = sorted((item for item in result["processes"] if isinstance(item, dict)), key=lambda row: (-int(row.get("rssBytes", 0)), int(row.get("pid", 0))))[:MAX_ROWS]
    return result


def collect_remote(target: dict[str, object], runner: Runner = run_command) -> dict[str, object]:
    transport = str(target["transport"])
    endpoint = str(target.get("endpoint", ""))
    if transport == "ssh-powershell":
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", endpoint, "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT]
    elif transport == "proxmox-pct":
        argv = ["pct", "exec", str(target["containerId"]), "--", "/bin/sh", "-c", POSIX_SCRIPT]
    else:
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", endpoint, "/bin/sh", "-c", POSIX_SCRIPT]
    result = runner(argv, 30)
    if result.returncode:
        return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "unavailable", "errors": [f"transport failed with exit {result.returncode}"]}
    parsed = _json(result.stdout.strip())
    if transport == "ssh-powershell" and isinstance(parsed, dict):
        return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "available", **_normalise_windows(parsed)}
    return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "available", "remoteOutput": parsed if parsed is not None else result.stdout[:MAX_OUTPUT], "errors": [] if parsed is not None else ["remote response was not JSON"]}


def audit_target(target: dict[str, object], runner: Runner = run_command, exists: Callable[[str], bool] = lambda name: shutil.which(name) is not None) -> dict[str, object]:
    if target["transport"] == "local" and target["platform"] in {"linux", "proxmox", "container"}:
        return collect_linux(target, runner, exists)
    return collect_remote(target, runner)


def build_plan(inventory: dict[str, object], audits: Iterable[dict[str, object]]) -> dict[str, object]:
    targets = {str(target["id"]): target for target in inventory["targets"] if isinstance(target, dict)}
    candidates: list[dict[str, object]] = []
    for audit in audits:
        target_id = str(audit.get("target", {}).get("id", "unknown"))
        target = targets.get(target_id, {})
        for item in audit.get("largeFiles", []) if isinstance(audit.get("largeFiles"), list) else []:
            if isinstance(item, dict):
                protected = bool(item.get("protected")) or str(item.get("path", "")) in target.get("protectedPaths", [])
                candidates.append({"actionId": digest({"target": target_id, "kind": "file", "path": item.get("path")})[7:23], "target": target_id, "kind": "file", "path": item.get("path"), "bytes": int(item.get("bytes", 0)), "capability": target.get("operatorCapability"), "status": "blocked" if protected else "review", "reason": "protected path" if protected else "owner, age and recovery still required"})
        for process in audit.get("processes", []) if isinstance(audit.get("processes"), list) else []:
            if isinstance(process, dict) and int(process.get("rssBytes", 0)) > 1024 * 1024 * 1024:
                candidates.append({"actionId": digest({"target": target_id, "kind": "process", "pid": process.get("pid")})[7:23], "target": target_id, "kind": "process", "pid": process.get("pid"), "bytes": int(process.get("rssBytes", 0)), "status": "blocked", "reason": "process termination is never automatic"})
        if audit.get("status") == "unavailable":
            candidates.append({"actionId": digest({"target": target_id, "kind": "unavailable"})[7:23], "target": target_id, "kind": "target", "status": "unavailable", "reason": "transport unavailable"})
    candidates.sort(key=lambda row: (row["status"], -int(row.get("bytes", 0)), str(row["target"]), str(row["actionId"])))
    body = {"schemaVersion": PLAN_SCHEMA, "inventoryDigest": digest(inventory), "targets": sorted(targets), "candidates": candidates, "state": "review" if candidates else "ready"}
    body["planDigest"] = digest(body)
    return body


def verify_reports(before: dict[str, object], after: dict[str, object]) -> dict[str, object]:
    return {"schemaVersion": "host-resource-recovery.verify.v1", "beforeDigest": digest(before), "afterDigest": digest(after), "diskEvidenceChanged": before.get("filesystems") != after.get("filesystems"), "memoryEvidenceChanged": before.get("memory") != after.get("memory"), "errors": sorted(set((before.get("errors", []) if isinstance(before.get("errors"), list) else []) + (after.get("errors", []) if isinstance(after.get("errors"), list) else [])))}


def _write(value: object, output: Path | None) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_text(text, encoding="utf-8")
        os.chmod(output, 0o600)
    print(text, end="")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    inv = commands.add_parser("inventory").add_subparsers(dest="inventory_command", required=True)
    validate = inv.add_parser("validate"); validate.add_argument("--inventory", type=Path, required=True)
    audit = commands.add_parser("audit"); audit.add_argument("--inventory", type=Path, required=True); audit.add_argument("--target", required=True); audit.add_argument("--output", type=Path, required=True)
    plan = commands.add_parser("plan"); plan.add_argument("--inventory", type=Path, required=True); plan.add_argument("--audit-dir", type=Path, required=True); plan.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify"); verify.add_argument("--before", type=Path, required=True); verify.add_argument("--after", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "inventory":
            inventory = load_inventory(args.inventory); _write({"valid": True, "schemaVersion": inventory["schemaVersion"], "targetCount": len(inventory["targets"])}, None); return 0
        if args.command == "audit":
            inventory = load_inventory(args.inventory); target = next((item for item in inventory["targets"] if item.get("id") == args.target), None)
            if target is None: raise ValueError("target not found")
            _write(audit_target(target), args.output); return 0
        if args.command == "plan":
            inventory = load_inventory(args.inventory); audits = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.audit_dir.glob("*.json"))]
            _write(build_plan(inventory, audits), args.output); return 0
        _write(verify_reports(json.loads(args.before.read_text()), json.loads(args.after.read_text())), None); return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"resource audit failed: {exc}", file=os.sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
