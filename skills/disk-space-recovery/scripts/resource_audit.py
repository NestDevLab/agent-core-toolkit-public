#!/usr/bin/env python3
"""Bounded, deterministic disk and memory evidence for declared targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import shlex
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
SECRET_MARKERS = ("password=", "token=", "secret=", "-----begin", "authorization:", "bearer ")
ENDPOINT_RE = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9_.:-]*$")


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


def _walk_forbidden(value: object, path: str = "root") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).casefold()
            if any(word == key_text or word in key_text for word in PROHIBITED):
                errors.append(f"{path}: prohibited field {key}")
            errors.extend(_walk_forbidden(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_walk_forbidden(child, f"{path}[{index}]"))
    elif isinstance(value, str) and any(marker in value.casefold() for marker in SECRET_MARKERS):
        errors.append(f"{path}: prohibited secret marker")
    return errors


def _valid_endpoint(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith("-") or not ENDPOINT_RE.fullmatch(value):
        return False
    if any(ord(char) < 32 or ord(char) == 127 or char.isspace() for char in value):
        return False
    if value.count("@") > 1 or "@" in value and value.split("@", 1)[1].startswith("-"):
        return False
    return True


def _doc_path(doc: object) -> tuple[str, bool] | None:
    if isinstance(doc, dict) and set(doc) == {"path", "remoteOnly"} and isinstance(doc["path"], str) and isinstance(doc["remoteOnly"], bool):
        return doc["path"], doc["remoteOnly"]
    return None


def validate_inventory(data: object, source_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["inventory must be an object"]
    errors.extend(_walk_forbidden(data))
    root_allowed = {"schemaVersion", "environment", "docRoot", "targets"}
    errors.extend(f"root: unknown field {key}" for key in sorted(set(data) - root_allowed))
    if data.get("schemaVersion") != "resource-maintenance.inventory.v1":
        errors.append("unsupported schemaVersion")
    if not isinstance(data.get("environment"), str) or not data["environment"]:
        errors.append("environment is required")
    doc_root = data.get("docRoot")
    if not isinstance(doc_root, str) or not doc_root or any(ord(char) < 32 or ord(char) == 127 for char in doc_root):
        errors.append("docRoot is required and must be a safe path")
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        return sorted(set(errors + ["targets must be a non-empty list"]))
    ids: set[str] = set()
    allowed = {"id", "platform", "transport", "expectedIdentity", "availability", "parent", "endpoint", "containerId", "authoritativeDocs", "scanRoots", "protectedPaths", "thresholds", "operatorCapability", "procedureRefs", "recoveryRefs", "discoverChildren", "gpuMonitoring"}
    relationships: dict[str, dict[str, object]] = {}
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
        relationships[str(target.get("id"))] = target
        for field in ("expectedIdentity", "authoritativeDocs", "scanRoots", "protectedPaths", "thresholds", "operatorCapability"):
            if field not in target:
                errors.append(f"{prefix}: missing {field}")
        for field in ("authoritativeDocs", "scanRoots", "protectedPaths", "procedureRefs", "recoveryRefs"):
            if field in target and (not isinstance(target[field], list) or not target[field]):
                errors.append(f"{prefix}: {field} must be a list")
        for doc_index, doc in enumerate(target.get("authoritativeDocs", [])):
            parsed_doc = _doc_path(doc)
            if parsed_doc is None:
                errors.append(f"{prefix}.authoritativeDocs[{doc_index}]: expected path and remoteOnly")
            elif Path(parsed_doc[0]).is_absolute() or ".." in Path(parsed_doc[0]).parts:
                errors.append(f"{prefix}.authoritativeDocs[{doc_index}]: path must stay below docRoot")
        for field in ("scanRoots", "protectedPaths", "procedureRefs", "recoveryRefs"):
            if field in target and isinstance(target[field], list) and any(not isinstance(item, str) or not item or any(ord(char) < 32 or ord(char) == 127 for char in item) for item in target[field]):
                errors.append(f"{prefix}: {field} contains an invalid path/reference")
        thresholds = target.get("thresholds")
        if not isinstance(thresholds, dict) or not {"diskFreePercent", "memoryAvailablePercent"} <= set(thresholds):
            errors.append(f"{prefix}: thresholds missing required values")
        elif set(thresholds) - {"diskFreePercent", "inodeFreePercent", "memoryAvailablePercent", "swapUsedPercent", "pagefileUsedPercent", "growthBytesPerHour"}:
            errors.append(f"{prefix}: unknown threshold")
        elif any(not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 100 for key, value in thresholds.items() if key != "growthBytesPerHour") or ("growthBytesPerHour" in thresholds and (not isinstance(thresholds["growthBytesPerHour"], int) or isinstance(thresholds["growthBytesPerHour"], bool) or thresholds["growthBytesPerHour"] < 0)):
            errors.append(f"{prefix}: malformed thresholds")
        transport = target.get("transport")
        if transport not in {"local", "proxmox-pct"} and not isinstance(target.get("endpoint"), str):
            errors.append(f"{prefix}: endpoint required for remote transport")
        if "endpoint" in target and not _valid_endpoint(target["endpoint"]):
            errors.append(f"{prefix}: invalid endpoint")
        if transport == "proxmox-pct" and (not isinstance(target.get("containerId"), int) or isinstance(target.get("containerId"), bool) or target["containerId"] <= 0):
            errors.append(f"{prefix}: containerId required for proxmox-pct")
        if transport == "proxmox-pct" and not target.get("parent"):
            errors.append(f"{prefix}: proxmox-pct target requires a parent")
        if transport != "proxmox-pct" and "containerId" in target:
            errors.append(f"{prefix}: containerId only valid for proxmox-pct")
        valid_pairs = {("linux", "local"), ("linux", "ssh-posix"), ("windows", "ssh-powershell"), ("proxmox", "ssh-posix"), ("container", "ssh-posix"), ("container", "proxmox-pct")}
        if (target.get("platform"), transport) not in valid_pairs:
            errors.append(f"{prefix}: invalid platform/transport combination")
        if target.get("platform") == "windows":
            paths = list(target.get("scanRoots", [])) + list(target.get("protectedPaths", []))
            if any(not isinstance(path, str) or not re.match(r"^[A-Za-z]:[\\/]", path) for path in paths):
                errors.append(f"{prefix}: Windows paths must be drive-qualified")
        else:
            paths = list(target.get("scanRoots", [])) + list(target.get("protectedPaths", []))
            if any(not isinstance(path, str) or not path.startswith("/") for path in paths):
                errors.append(f"{prefix}: POSIX paths must be absolute")
        for key, value in target.items():
            key_text = str(key).casefold()
            if any(word == key_text or word in key_text for word in PROHIBITED):
                errors.append(f"{prefix}: prohibited field {key}")
            if isinstance(value, str) and any(marker in value.casefold() for marker in SECRET_MARKERS):
                errors.append(f"{prefix}: prohibited secret value")
    for target in targets:
        if isinstance(target, dict) and target.get("parent") and target["parent"] not in ids:
            errors.append(f"target {target.get('id')}: parent not found")
        if isinstance(target, dict) and target.get("parent"):
            parent = relationships.get(str(target["parent"]))
            if parent and (
                target.get("platform") != "container"
                or parent.get("platform") != "proxmox"
                or target.get("transport") == "proxmox-pct" and parent.get("transport") != "ssh-posix"
            ):
                errors.append(f"target {target.get('id')}: invalid parent relationship")
    for target_id in ids:
        seen: set[str] = set()
        current = target_id
        while current in relationships and relationships[current].get("parent"):
            if current in seen:
                errors.append(f"target {target_id}: parent cycle")
                break
            seen.add(current)
            current = str(relationships[current]["parent"])
    if source_path is not None and isinstance(doc_root, str):
        root = Path(doc_root) if Path(doc_root).is_absolute() else source_path.parent / doc_root
        for target in targets:
            for doc in target.get("authoritativeDocs", []):
                parsed = _doc_path(doc)
                if parsed and not parsed[1] and not (root / parsed[0]).is_file():
                    errors.append(f"target {target.get('id')}: authoritative document missing: {parsed[0]}")
    return sorted(set(errors))


def load_inventory(path: Path) -> dict[str, object]:
    data = _json(path.read_text(encoding="utf-8"))
    errors = validate_inventory(data, path)
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


def _read_text(path: str, limit: int = 4_000) -> str:
    try:
        return Path(path).read_text(encoding="ascii", errors="ignore")[:limit]
    except OSError:
        return ""


def _local_optional_evidence(runner: Runner, exists: Callable[[str], bool], roots: list[str], protected: list[str], errors: list[str]) -> dict[str, object]:
    evidence: dict[str, object] = {"psi": {}, "oom": {}, "cgroups": {}, "deletedOpen": [], "duSummaries": [], "gpu": []}
    for name in ("cpu", "memory", "io"):
        text = _read_text(f"/proc/pressure/{name}")
        if text:
            evidence["psi"][name] = text
        else:
            errors.append(f"PSI {name} unavailable")
    for name in ("memory.current", "memory.max", "memory.events"):
        text = _read_text(f"/sys/fs/cgroup/{name}")
        if text:
            evidence["cgroups"][name] = text
    if not evidence["cgroups"]:
        errors.append("cgroup memory evidence unavailable")
    evidence["oom"] = evidence["cgroups"].get("memory.events", {})
    if exists("lsof"):
        raw = _run(runner, ["lsof", "+L1", "-nP", "-w"], errors, 20)
        for line in raw.splitlines()[1:MAX_ROWS + 1]:
            if "(deleted)" in line and "/memfd:" not in line:
                fields = line.split(None, 8)
                if len(fields) >= 9:
                    evidence["deletedOpen"].append({"process": fields[0][:128], "pid": _number(fields[1]), "path": fields[-1][:1000], "memoryBacked": False})
    else:
        errors.append("lsof unavailable; deleted-open evidence incomplete")
    for root in sorted(set(roots)):
        raw = _run(runner, ["du", "-x", "-d", "1", "-B1", root], errors, 45)
        for line in raw.splitlines()[:MAX_ROWS]:
            size, separator, path = line.partition("\t")
            if separator and _number(size) is not None:
                evidence["duSummaries"].append({"path": path[:1000], "bytes": int(_number(size) or 0)})
    if exists("nvidia-smi"):
        raw = _run(runner, ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu", "--format=csv,noheader,nounits"], errors, 10)
        evidence["gpu"] = [line[:256] for line in raw.splitlines()[:16]]
    else:
        errors.append("nvidia-smi unavailable")
    return evidence


def _identity_status(target: dict[str, object], report: dict[str, object]) -> dict[str, object]:
    expected = str(target.get("expectedIdentity", ""))
    actual = str(report.get("identity", ""))
    report["expectedIdentity"] = expected
    if report.get("status") == "unavailable":
        return report
    if actual.casefold() != expected.casefold():
        report["status"] = "blocked"
        report.setdefault("errors", []).append(f"identity mismatch: expected {expected}, observed {actual or '<empty>'}")
    else:
        report["status"] = "available"
    report["errors"] = sorted(set(str(error) for error in report.get("errors", [])))
    return report


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
    optional = _local_optional_evidence(runner, exists, [str(item) for item in target.get("scanRoots", [])], [str(item) for item in target.get("protectedPaths", [])], errors)
    report = {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": target["transport"]}, "identity": identity[:128], "filesystems": filesystems, "inodes": inodes, "memory": memory, "processes": processes, "containers": sorted(containers, key=lambda row: (str(row["name"]), str(row["id"]))), "largeFiles": sorted(large_files, key=lambda row: (-int(row["bytes"]), str(row["path"]))), **optional, "errors": sorted(set(errors))}
    return _identity_status(target, report)


WINDOWS_SCRIPT = "$ErrorActionPreference='Stop'; $errors=@(); function Missing([string]$name) {$errors += \"$name unavailable\"}; $volumes=@(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object {$_.Size -gt 0} | ForEach-Object {[ordered]@{filesystem=$_.DeviceID; filesystemType=$_.FileSystem; totalBytes=[int64]$_.Size; usedBytes=([int64]$_.Size-[int64]$_.FreeSpace); availableBytes=[int64]$_.FreeSpace; capacity=(('{0:P2}' -f (([double]$_.Size-[double]$_.FreeSpace)/[double]$_.Size))); mountPoint=$_.DeviceID}}); $os=Get-CimInstance Win32_OperatingSystem; $cs=Get-CimInstance Win32_ComputerSystem; $pagefile=@(Get-CimInstance Win32_PageFileUsage | ForEach-Object {[ordered]@{path=$_.Name; allocatedBytes=([int64]$_.AllocatedBaseSize*1KB); usedBytes=([int64]$_.CurrentUsage*1KB)}}); $memory=[ordered]@{physical=[ordered]@{totalBytes=([int64]$cs.TotalPhysicalMemory); availableBytes=([int64]$os.FreePhysicalMemory*1KB)}; commit=[ordered]@{limitBytes=([int64]$os.TotalVirtualMemorySize*1KB); usedBytes=([int64](($os.TotalVirtualMemorySize-$os.FreeVirtualMemory)*1KB))}; pagefile=$pagefile}; $processes=@(Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 100 | ForEach-Object {[ordered]@{pid=[int]$_.Id; rssBytes=[int64]$_.WorkingSet64; name=$_.ProcessName}}); $hyperv=@(); if (Get-Command Get-VM -ErrorAction SilentlyContinue) {$hyperv=@(Get-VM | Select-Object -First 100 | ForEach-Object {[ordered]@{name=$_.Name; state=$_.State; memoryAssignedBytes=[int64]$_.MemoryAssigned}})} else {$errors += 'Hyper-V cmdlets unavailable'}; $vhd=@(Get-ChildItem -Path $env:SystemDrive\\ -Include *.vhd,*.vhdx -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 100 | ForEach-Object {[ordered]@{path=$_.FullName; bytes=[int64]$_.Length}}); $services=@(Get-CimInstance Win32_Service | Select-Object -First 100 | ForEach-Object {[ordered]@{name=$_.Name; state=$_.State; path=$_.PathName}}); $wsl=[bool](Get-Command wsl.exe -ErrorAction SilentlyContinue); $docker=[bool](Get-Command docker.exe -ErrorAction SilentlyContinue); $gpu=@(); if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) {$gpu=@(& nvidia-smi.exe --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader,nounits | Select-Object -First 16)} else {$errors += 'nvidia-smi unavailable'}; $o=[ordered]@{identity=$env:COMPUTERNAME; volumes=$volumes; inodes=@(); memory=$memory; processes=$processes; containers=@(); largeFiles=$vhd; deletedOpen=@(); psi=@(); oom=@(); cgroups=@(); hyperv=$hyperv; vhd=$vhd; services=$services; wsl=[ordered]@{present=$wsl}; docker=[ordered]@{present=$docker}; gpu=$gpu; errors=$errors}; $o|ConvertTo-Json -Depth 7 -Compress"
POSIX_SCRIPT = r'''import json, os, re, shutil, socket, subprocess, sys
MAX=100
errors=[]
roots=[]
args=sys.argv[1:]
for i,arg in enumerate(args):
    if arg == "--root" and i+1 < len(args): roots.append(args[i+1])
def run(argv, timeout=20):
    try:
        p=subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, p.stdout[:128000], p.stderr[:2000]
    except FileNotFoundError:
        errors.append(argv[0]+" unavailable"); return 127,"","not found"
    except subprocess.TimeoutExpired:
        errors.append(argv[0]+" timed out"); return 124,"","timed out"
def number(value):
    try: return int(str(value).replace(",",""))
    except (TypeError,ValueError): return None
def df(argv, inode=False):
    code,out,_=run(argv)
    rows=[]
    for line in out.splitlines():
        fields=line.split(maxsplit=5 if inode else 6)
        if (len(fields)==6 if inode else len(fields)==7) and fields[0] != "Filesystem":
            if inode:
                fs,total,used,free,capacity,mount=fields
                rows.append({"filesystem":fs,"inodes":number(total),"used":number(used),"available":number(free),"capacity":capacity,"mountPoint":mount})
            else:
                fs,kind,total,used,free,capacity,mount=fields
                rows.append({"filesystem":fs,"filesystemType":kind,"blocks":number(total),"used":number(used),"available":number(free),"capacity":capacity,"mountPoint":mount})
    return sorted(rows,key=lambda x:x["mountPoint"])
def meminfo():
    values={}
    try:
        for line in open("/proc/meminfo",encoding="ascii",errors="ignore"):
            key,val=line.split(":",1); bits=val.split(); values[key]=number(bits[0])*(1024 if len(bits)>1 and bits[1]=="kB" else 1)
    except OSError: errors.append("/proc/meminfo unavailable")
    physical={"totalBytes":values.get("MemTotal"),"availableBytes":values.get("MemAvailable"),"usedBytes":(values.get("MemTotal",0)-values.get("MemAvailable",0))}
    swap={"totalBytes":values.get("SwapTotal"),"availableBytes":values.get("SwapFree"),"usedBytes":(values.get("SwapTotal",0)-values.get("SwapFree",0))}
    return {"physical":physical,"swap":swap,"commit":{"limitBytes":values.get("CommitLimit"),"usedBytes":values.get("Committed_AS")}}
def processes():
    code,out,_=run(["ps","-eo","pid=,rss=,comm="])
    rows=[]
    for line in out.splitlines():
        f=line.split(None,2)
        if len(f)==3 and number(f[0]) is not None: rows.append({"pid":number(f[0]),"rssBytes":number(f[1])*1024,"name":f[2][:128]})
    return sorted(rows,key=lambda x:(-x["rssBytes"],x["pid"]))[:MAX]
def read_text(path):
    try: return open(path,encoding="ascii",errors="ignore").read()[:2000]
    except OSError: return ""
def cgroup():
    result={}
    for name in ("memory.current","memory.max","memory.events"):
        path="/sys/fs/cgroup/"+name; text=read_text(path)
        if text: result[name]=text
    if not result: errors.append("cgroup memory evidence unavailable")
    return result
def psi():
    result={}
    for name in ("cpu","memory","io"):
        text=read_text("/proc/pressure/"+name)
        if text: result[name]=text
        else: errors.append("PSI "+name+" unavailable")
    return result
def deleted_open():
    result=[]
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit(): continue
            fdroot="/proc/"+pid+"/fd"
            for fd in os.listdir(fdroot)[:MAX]:
                try: link=os.readlink(fdroot+"/"+fd)
                except OSError: continue
                if " (deleted)" in link and not link.startswith("/memfd:"):
                    result.append({"pid":int(pid),"fd":fd,"path":link[:1000],"memoryBacked":False})
                    if len(result)>=MAX: return result
    except OSError: errors.append("deleted-open evidence unavailable")
    return result
def large_and_du():
    large=[]; summaries=[]
    for root in sorted(set(roots)):
        code,out,_=run(["du","-x","-d","1","-B1",root],45)
        if code==0:
            for line in out.splitlines()[:MAX]:
                f=line.split("\t",1)
                if len(f)==2 and number(f[0]) is not None: summaries.append({"path":f[1][:1000],"bytes":number(f[0])})
        for base,dirs,files in os.walk(root):
            dirs[:]=sorted(dirs)[:200]
            for name in sorted(files)[:MAX]:
                path=os.path.join(base,name)
                try: size=os.stat(path,follow_symlinks=False).st_size
                except OSError: continue
                if size>200000000: large.append({"path":path[:1000],"bytes":size,"protected":False})
                if len(large)>=MAX: return large,summaries
    return large,summaries
containers=[]
code,out,_=run(["docker","ps","-a","--size","--format","{{json .}}"])
if code==0:
    for line in out.splitlines()[:MAX]:
        try:
            value=json.loads(line); containers.append({"id":str(value.get("ID",""))[:128],"name":str(value.get("Names",""))[:128],"state":str(value.get("State",""))[:32],"size":str(value.get("Size",""))[:128]})
        except json.JSONDecodeError: errors.append("docker ps returned invalid JSON")
code,out,_=run(["docker","stats","--no-stream","--format","{{json .}}"])
if code==0:
    for line in out.splitlines()[:MAX]:
        try: containers.append({"name":json.loads(line).get("Name",""),"memory":json.loads(line).get("MemUsage","")[:128],"memoryNoStream":True})
        except json.JSONDecodeError: errors.append("docker stats returned invalid JSON")
gpu=[]
code,out,_=run(["nvidia-smi","--query-gpu=name,memory.total,memory.used,utilization.gpu","--format=csv,noheader,nounits"])
if code==0: gpu=[line[:256] for line in out.splitlines()[:16]]
large,summaries=large_and_du()
cg=cgroup()
print(json.dumps({"schemaVersion":"resource-maintenance.audit.v1","identity":socket.gethostname()[:128],"filesystems":df(["df","-P","-T"]),"inodes":df(["df","-P","-i"],True),"memory":meminfo(),"processes":processes(),"containers":containers[:MAX],"largeFiles":large[:MAX],"duSummaries":summaries[:MAX],"deletedOpen":deleted_open(),"psi":psi(),"oom":cg.get("memory.events",{}),"cgroups":cg,"gpu":gpu,"errors":sorted(set(errors))},sort_keys=True,separators=(",",":")))'''


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
        "deletedOpen": payload.get("deletedOpen", []) if isinstance(payload.get("deletedOpen"), list) else [],
        "duSummaries": payload.get("duSummaries", []) if isinstance(payload.get("duSummaries"), list) else [],
        "errors": payload.get("errors", []) if isinstance(payload.get("errors"), list) else [],
        "psi": payload.get("psi", {}) if isinstance(payload.get("psi"), dict) else {},
        "oom": payload.get("oom", []) if isinstance(payload.get("oom"), (dict, list)) else [],
        "cgroups": payload.get("cgroups", {}) if isinstance(payload.get("cgroups"), dict) else {},
        "hyperv": payload.get("hyperv", []) if isinstance(payload.get("hyperv"), list) else [],
        "vhd": payload.get("vhd", []) if isinstance(payload.get("vhd"), list) else [],
        "services": payload.get("services", []) if isinstance(payload.get("services"), list) else [],
        "wsl": payload.get("wsl", {}) if isinstance(payload.get("wsl"), dict) else {},
        "docker": payload.get("docker", {}) if isinstance(payload.get("docker"), dict) else {},
        "gpu": payload.get("gpu", []) if isinstance(payload.get("gpu"), list) else [],
    }
    result["processes"] = sorted((item for item in result["processes"] if isinstance(item, dict)), key=lambda row: (-int(row.get("rssBytes", 0)), int(row.get("pid", 0))))[:MAX_ROWS]
    return result


def _normalise_posix(payload: dict[str, object]) -> dict[str, object]:
    result = _normalise_windows(payload)
    result.pop("hyperv", None); result.pop("vhd", None); result.pop("services", None); result.pop("wsl", None)
    return result


def _proxmox_parent_endpoint(
    target: dict[str, object], targets: Iterable[dict[str, object]] | None
) -> tuple[str | None, str | None]:
    parent_id = target.get("parent")
    if not isinstance(parent_id, str) or not parent_id:
        return None, "proxmox-pct parent is missing"
    if targets is None:
        return None, "proxmox-pct target graph is required"
    matches = [item for item in targets if isinstance(item, dict) and item.get("id") == parent_id]
    if len(matches) != 1:
        return None, "proxmox-pct parent is missing or ambiguous"
    parent = matches[0]
    if parent.get("platform") != "proxmox" or parent.get("transport") != "ssh-posix":
        return None, "proxmox-pct parent must be a proxmox ssh-posix target"
    endpoint = parent.get("endpoint")
    if not _valid_endpoint(endpoint):
        return None, "proxmox-pct parent endpoint is invalid"
    return str(endpoint), None


def collect_remote(
    target: dict[str, object],
    runner: Runner = run_command,
    targets: Iterable[dict[str, object]] | None = None,
) -> dict[str, object]:
    transport = str(target["transport"])
    if transport == "proxmox-pct":
        endpoint, parent_error = _proxmox_parent_endpoint(target, targets)
        container_id = target.get("containerId")
        if parent_error:
            return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "blocked", "errors": [parent_error]}
        if not isinstance(container_id, int) or isinstance(container_id, bool) or container_id <= 0:
            return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "blocked", "errors": ["invalid proxmox-pct container ID"]}
        assert endpoint is not None
    else:
        endpoint = str(target.get("endpoint", ""))
    if not _valid_endpoint(endpoint):
        return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "blocked", "errors": ["invalid endpoint rejected before transport"]}
    if transport == "ssh-powershell":
        remote = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", WINDOWS_SCRIPT]
    elif transport == "proxmox-pct":
        remote = ["pct", "exec", str(target["containerId"]), "--", "python3", "-c", POSIX_SCRIPT]
    else:
        remote = ["python3", "-c", POSIX_SCRIPT]
    if transport in {"ssh-posix", "proxmox-pct"}:
        for root in sorted(set(str(item) for item in target.get("scanRoots", []))):
            remote.extend(["--root", root])
    # OpenSSH joins command arguments and evaluates them through the remote
    # user's shell. Quote the complete command as one argv item so the Python
    # and PowerShell scripts cannot be split or interpreted by that shell.
    remote_command = " ".join(shlex.quote(item) for item in remote)
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", endpoint, remote_command]
    result = runner(argv, 30)
    if result.returncode:
        return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "unavailable", "errors": [f"transport failed with exit {result.returncode}"]}
    parsed = _json(result.stdout.strip())
    if isinstance(parsed, dict):
        normalised = _normalise_windows(parsed) if transport == "ssh-powershell" else _normalise_posix(parsed)
        report = {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, **normalised}
        return _identity_status(target, report)
    return {"schemaVersion": SCHEMA, "target": {"id": target["id"], "platform": target["platform"], "transport": transport}, "status": "unavailable", "errors": ["remote response was not JSON"]}


def audit_target(
    target: dict[str, object],
    runner: Runner = run_command,
    exists: Callable[[str], bool] = lambda name: shutil.which(name) is not None,
    targets: Iterable[dict[str, object]] | None = None,
) -> dict[str, object]:
    if target["transport"] == "local" and target["platform"] in {"linux", "proxmox", "container"}:
        return collect_linux(target, runner, exists)
    return collect_remote(target, runner, targets)


def _percent(available: object, total: object) -> float | None:
    try:
        total_number, available_number = float(total), float(available)
        return round(available_number / total_number * 100, 4) if total_number > 0 else None
    except (TypeError, ValueError):
        return None


def _used_percent(used: object, total: object) -> float | None:
    try:
        total_number, used_number = float(total), float(used)
        return round(used_number / total_number * 100, 4) if total_number > 0 else None
    except (TypeError, ValueError):
        return None


def _candidate(target_id: str, target: dict[str, object], kind: str, subject: object, status: str, reason: str, bytes_value: int = 0, urgency: float = 0, growth: float = 0, reclaimability: float = 0, reversibility: float = 0, risk: float = 0, **extra: object) -> dict[str, object]:
    action_id = digest({"target": target_id, "kind": kind, "subject": subject})[7:23]
    return {"actionId": action_id, "target": target_id, "kind": kind, "bytes": bytes_value, "status": status, "reason": reason, "capability": target.get("operatorCapability"), "procedureRefs": target.get("procedureRefs", []), "recoveryRefs": target.get("recoveryRefs", []), "priority": {"urgency": round(urgency, 4), "growth": round(growth, 4), "reclaimability": round(reclaimability, 4), "reversibility": round(reversibility, 4), "risk": round(risk, 4)}, **extra}


def _duplicate_parent(target_id: str, target: dict[str, object], item: dict[str, object], audit_by_id: dict[str, dict[str, object]]) -> bool:
    parent_id = target.get("parent")
    parent = audit_by_id.get(str(parent_id)) if parent_id else None
    if not parent or parent.get("status") != "available":
        return False
    key = (str(item.get("filesystem", "")), str(item.get("mountPoint", "")))
    for parent_item in parent.get("filesystems", []) if isinstance(parent.get("filesystems"), list) else []:
        if isinstance(parent_item, dict) and key == (str(parent_item.get("filesystem", "")), str(parent_item.get("mountPoint", ""))) and key != ("", ""):
            return True
    return False


def build_plan(inventory: dict[str, object], audits: Iterable[dict[str, object]]) -> dict[str, object]:
    targets = {str(target["id"]): target for target in inventory["targets"] if isinstance(target, dict)}
    audit_by_id = {str(audit.get("target", {}).get("id", "")): audit for audit in sorted(audits, key=canonical)}
    candidates: list[dict[str, object]] = []
    target_states: dict[str, str] = {}
    for target_id in sorted(targets):
        target = targets[target_id]
        audit = audit_by_id.get(target_id)
        if target.get("availability") == "unavailable":
            target_states[target_id] = "unavailable"
            candidates.append(_candidate(target_id, target, "target", "unavailable", "unavailable", "target is declared unavailable", risk=10))
            continue
        if audit is None:
            target_states[target_id] = "unavailable"
            candidates.append(_candidate(target_id, target, "target", "missing-audit", "unavailable", "audit evidence missing", risk=10))
            continue
        expected_identity = str(target.get("expectedIdentity", ""))
        observed_identity = str(audit.get("identity", ""))
        identity_mismatch = observed_identity.casefold() != expected_identity.casefold()
        if audit.get("status") != "available" or identity_mismatch:
            status = "unavailable" if audit.get("status") == "unavailable" else "blocked"
            target_states[target_id] = status
            reason = f"identity mismatch: expected {expected_identity}, observed {observed_identity or '<empty>'}" if identity_mismatch else str((audit.get("errors") or ["target is not usable"])[0])
            candidates.append(_candidate(target_id, target, "target", status, status, reason, risk=10))
            continue
        target_states[target_id] = "available"
        thresholds = target.get("thresholds", {})
        growth = float(thresholds.get("growthBytesPerHour", 0) or 0)
        for item in audit.get("filesystems", []) if isinstance(audit.get("filesystems"), list) else []:
            if not isinstance(item, dict): continue
            free = _percent(item.get("available"), item.get("blocks"))
            limit = thresholds.get("diskFreePercent")
            if free is not None and isinstance(limit, (int, float)) and free < limit:
                duplicate = _duplicate_parent(target_id, target, item, audit_by_id)
                candidates.append(_candidate(target_id, target, "filesystem", {"filesystem": item.get("filesystem"), "mountPoint": item.get("mountPoint")}, "blocked" if duplicate else "review", "parent/guest evidence would double count" if duplicate else "filesystem pressure requires named recovery", urgency=max(0, float(limit) - free), growth=growth, reclaimability=max(0, 100-free), reversibility=25, risk=5 if duplicate else 4, filesystem=item, freePercent=free, thresholdPercent=limit))
        for item in audit.get("inodes", []) if isinstance(audit.get("inodes"), list) else []:
            if not isinstance(item, dict): continue
            free = _percent(item.get("available"), item.get("inodes")); limit = thresholds.get("inodeFreePercent")
            if free is not None and isinstance(limit, (int, float)) and free < limit:
                candidates.append(_candidate(target_id, target, "inodes", {"filesystem": item.get("filesystem"), "mountPoint": item.get("mountPoint")}, "review", "inode pressure requires named recovery", urgency=max(0, float(limit)-free), growth=growth, reclaimability=20, reversibility=30, risk=4, inodeEvidence=item, freePercent=free, thresholdPercent=limit))
        physical = audit.get("memory", {}).get("physical", {}) if isinstance(audit.get("memory"), dict) else {}
        free = _percent(physical.get("availableBytes"), physical.get("totalBytes")) if isinstance(physical, dict) else None
        limit = thresholds.get("memoryAvailablePercent")
        if free is not None and isinstance(limit, (int, float)) and free < limit:
            candidates.append(_candidate(target_id, target, "memory", "physical", "review", "physical memory pressure requires named recovery", urgency=max(0, float(limit)-free), growth=growth, reclaimability=10, reversibility=20, risk=5, availablePercent=free, thresholdPercent=limit))
        swap = audit.get("memory", {}).get("swap", {}) if isinstance(audit.get("memory"), dict) else {}
        used = _used_percent(swap.get("usedBytes"), swap.get("totalBytes")) if isinstance(swap, dict) else None
        limit = thresholds.get("swapUsedPercent")
        if used is not None and isinstance(limit, (int, float)) and used > limit:
            candidates.append(_candidate(target_id, target, "swap", "swap", "review", "swap pressure requires named recovery", urgency=max(0, used-float(limit)), growth=growth, reclaimability=5, reversibility=15, risk=5, usedPercent=used, thresholdPercent=limit))
        pagefiles = audit.get("memory", {}).get("pagefile", []) if isinstance(audit.get("memory"), dict) else []
        if isinstance(pagefiles, list) and pagefiles:
            total = sum(float(item.get("allocatedBytes", 0)) for item in pagefiles if isinstance(item, dict)); used_bytes = sum(float(item.get("usedBytes", 0)) for item in pagefiles if isinstance(item, dict)); used = _used_percent(used_bytes, total); limit = thresholds.get("pagefileUsedPercent")
            if used is not None and isinstance(limit, (int, float)) and used > limit:
                candidates.append(_candidate(target_id, target, "pagefile", "pagefile", "review", "pagefile pressure requires named recovery", urgency=max(0, used-float(limit)), growth=growth, reclaimability=5, reversibility=10, risk=6, usedPercent=used, thresholdPercent=limit))
        for item in audit.get("largeFiles", []) if isinstance(audit.get("largeFiles"), list) else []:
            if isinstance(item, dict):
                path = str(item.get("path", "")); protected = bool(item.get("protected")) or path in target.get("protectedPaths", [])
                candidates.append(_candidate(target_id, target, "file", path, "blocked" if protected else "review", "protected path" if protected else "owner, age and recovery still required", int(item.get("bytes", 0)), urgency=35, growth=growth, reclaimability=min(100, int(item.get("bytes", 0))/10_000_000), reversibility=70 if not protected else 0, risk=9 if protected else 6, path=path))
        for process in audit.get("processes", []) if isinstance(audit.get("processes"), list) else []:
            if isinstance(process, dict) and int(process.get("rssBytes", 0)) > 1024 * 1024 * 1024:
                candidates.append(_candidate(target_id, target, "process", process.get("pid"), "blocked", "process termination is never automatic", int(process.get("rssBytes", 0)), urgency=50, growth=growth, reclaimability=10, reversibility=0, risk=10, pid=process.get("pid")))
    candidates.sort(key=lambda row: (-row["priority"]["urgency"], -row["priority"]["growth"], -row["priority"]["reclaimability"], -row["priority"]["reversibility"], row["priority"]["risk"], str(row["target"]), str(row["actionId"])))
    statuses = {str(candidate["status"]) for candidate in candidates}
    state = "blocked" if "blocked" in statuses or "unavailable" in statuses else "review" if candidates else "ready"
    body = {"schemaVersion": PLAN_SCHEMA, "inventoryDigest": digest(inventory), "targets": sorted(targets), "targetStates": target_states, "candidates": candidates, "state": state}
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
            _write(audit_target(target, targets=inventory["targets"]), args.output); return 0
        if args.command == "plan":
            inventory = load_inventory(args.inventory); audits = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(args.audit_dir.glob("*.json"))]
            _write(build_plan(inventory, audits), args.output); return 0
        _write(verify_reports(json.loads(args.before.read_text()), json.loads(args.after.read_text())), None); return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"resource audit failed: {exc}", file=os.sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
