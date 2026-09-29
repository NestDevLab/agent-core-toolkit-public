#!/usr/bin/env python3
"""Tests for the generic disk and memory collector."""

from __future__ import annotations

import base64
import contextlib
import gzip
import importlib.util
import io
import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = (Path(__file__).parent / ".." / "scripts" / "resource_audit.py").resolve()
SPEC = importlib.util.spec_from_file_location("resource_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["resource_audit"] = MODULE
SPEC.loader.exec_module(MODULE)
INVENTORY = json.loads((Path(__file__).parent / ".." / "references" / "resource-maintenance.synthetic.json").read_text())


def proxmox_targets(parent_endpoint: str = "synthetic-proxmox") -> list[dict[str, object]]:
    common = {
        "authoritativeDocs": [{"path": "docs/synthetic.md", "remoteOnly": True}],
        "scanRoots": ["/srv/example"],
        "protectedPaths": ["/srv/example/live.db"],
        "thresholds": {"diskFreePercent": 15, "memoryAvailablePercent": 10},
        "operatorCapability": "synthetic-read-only",
    }
    parent = {
        **common,
        "id": "proxmox-parent",
        "platform": "proxmox",
        "transport": "ssh-posix",
        "endpoint": parent_endpoint,
        "expectedIdentity": "synthetic-proxmox",
    }
    child = {
        **common,
        "id": "container-child",
        "platform": "container",
        "transport": "proxmox-pct",
        "containerId": 42,
        "parent": "proxmox-parent",
        "expectedIdentity": "synthetic-container",
    }
    return [parent, child]


def posix_payload(identity: str = "synthetic-container") -> dict[str, object]:
    return {
        "identity": identity,
        "filesystems": [{"filesystem": "/dev/root", "available": 50, "blocks": 100, "mountPoint": "/"}],
        "inodes": [{"filesystem": "/dev/root", "available": 50, "inodes": 100, "mountPoint": "/"}],
        "memory": {"physical": {"totalBytes": 1000, "availableBytes": 400}, "swap": {"totalBytes": 100, "usedBytes": 20}},
        "processes": [{"pid": 3, "rssBytes": 800, "name": "worker"}],
        "psi": {"memory": "some avg10=1"},
        "oom": {"oom": 2},
        "cgroups": {"memory.current": "10"},
        "deletedOpen": [{"pid": 3, "path": "/tmp/deleted", "memoryBacked": False}],
        "duSummaries": [{"path": "/srv/example", "bytes": 900}],
        "largeFiles": [],
        "incompleteEvidence": [],
        "errors": [],
    }


def execute_posix_script(
    roots: list[str], runner: object, monotonic: object
) -> dict[str, object]:
    def open_file(path: object, *args: object, **kwargs: object) -> io.StringIO:
        if str(path) == "/proc/meminfo":
            return io.StringIO("MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 100 kB\nSwapFree: 80 kB\n")
        raise OSError("synthetic unavailable")

    output = io.StringIO()
    argv = ["resource-audit", *[part for root in roots for part in ("--root", root)]]
    with (
        patch("builtins.open", side_effect=open_file),
        patch("os.listdir", side_effect=OSError("synthetic unavailable")),
        patch("socket.gethostname", return_value="synthetic-linux"),
        patch("subprocess.run", side_effect=runner),
        patch("time.monotonic", side_effect=monotonic),
        patch.object(sys, "argv", argv),
        contextlib.redirect_stdout(output),
    ):
        exec(MODULE.POSIX_SCRIPT, {})
    return json.loads(output.getvalue())


class Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.responses = {
            ("df", "-P", "-T"): MODULE.CommandResult(0, "Filesystem Type 1024-blocks Used Available Capacity Mounted on\n/dev/root ext4 100 50 50 50% /\n"),
            ("df", "-P", "-i"): MODULE.CommandResult(0, "Filesystem Inodes IUsed IFree IUse% Mounted on\n/dev/root 100 50 50 50% /\n"),
            ("free", "-b"): MODULE.CommandResult(0, "              total        used        free      shared  buff/cache   available\nMem: 1000 400 100 0 500 600\nSwap: 100 20 80\n"),
            ("ps", "-eo", "pid=,rss=,comm="): MODULE.CommandResult(0, " 12 2000000 worker\n 13 100 idle\n"),
            ("find", "/srv/example", "-xdev", "-type", "f", "-size", "+200000000c", "-printf", "%s\\t%p\\n"): MODULE.CommandResult(0, "300000000\t/srv/example/cache.bin\n"),
            ("find", "/var/log/example", "-xdev", "-type", "f", "-size", "+200000000c", "-printf", "%s\\t%p\\n"): MODULE.CommandResult(0, ""),
            ("hostname",): MODULE.CommandResult(0, "synthetic-linux\n"),
        }

    def __call__(self, argv: list[str], timeout: int) -> MODULE.CommandResult:
        self.calls.append(argv)
        return self.responses.get(tuple(argv), MODULE.CommandResult(127, "", "missing fixture"))


class ResourceAuditTests(unittest.TestCase):
    def test_inventory_is_strict_and_synthetic(self) -> None:
        self.assertEqual(MODULE.validate_inventory(INVENTORY), [])
        bad = json.loads(json.dumps(INVENTORY))
        bad["targets"][0]["command"] = "rm -rf"
        self.assertTrue(MODULE.validate_inventory(bad))
        bad = json.loads(json.dumps(INVENTORY)); bad["unexpected"] = True
        self.assertTrue(MODULE.validate_inventory(bad))
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][0]["thresholds"]["nested"] = {}
        self.assertTrue(MODULE.validate_inventory(bad))

    def test_inventory_rejects_endpoint_injection_and_bad_relationships(self) -> None:
        for endpoint in ("-oProxyCommand=bad", "user@host\nnext", "user@@host", "user@", "host name"):
            bad = json.loads(json.dumps(INVENTORY)); bad["targets"][1]["endpoint"] = endpoint
            self.assertTrue(MODULE.validate_inventory(bad), endpoint)
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][0]["parent"] = "windows-lab"
        self.assertTrue(MODULE.validate_inventory(bad))
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][0]["parent"] = "windows-lab"; bad["targets"][1]["parent"] = "linux-lab"
        self.assertTrue(MODULE.validate_inventory(bad))
        self.assertIn("parent cycle", " ".join(MODULE.validate_inventory(bad)))
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][0]["parent"] = "windows-lab"; bad["targets"][1]["parent"] = "linux-lab"
        bad["targets"][0]["authoritativeDocs"] = [{"path": "x", "remoteOnly": False}]
        self.assertTrue(MODULE.validate_inventory(bad))

    def test_inventory_accepts_pct_endpoint_from_valid_parent(self) -> None:
        inventory = {
            "schemaVersion": "resource-maintenance.inventory.v1",
            "environment": "synthetic",
            "docRoot": ".",
            "targets": proxmox_targets(),
        }
        self.assertEqual(MODULE.validate_inventory(inventory), [])
        bad = json.loads(json.dumps(inventory))
        bad["targets"][0]["endpoint"] = "-oProxyCommand=bad"
        self.assertTrue(MODULE.validate_inventory(bad))
        bad = json.loads(json.dumps(inventory))
        bad["targets"][1]["parent"] = "missing"
        self.assertTrue(MODULE.validate_inventory(bad))

    def test_inventory_rejects_recursive_secrets_empty_lists_and_path_mismatch(self) -> None:
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][0]["thresholds"]["secretMarker"] = "password=bad"
        self.assertTrue(MODULE.validate_inventory(bad))
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][0]["protectedPaths"] = []
        self.assertTrue(MODULE.validate_inventory(bad))
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][1]["scanRoots"] = ["/not-windows"]
        self.assertTrue(MODULE.validate_inventory(bad))
        bad = json.loads(json.dumps(INVENTORY)); bad["targets"][0]["parent"] = "windows-lab"; bad["targets"][1]["parent"] = "linux-lab"
        bad["targets"][0]["platform"] = "container"; bad["targets"][1]["platform"] = "container"
        bad["targets"][0]["transport"] = "ssh-posix"; bad["targets"][1]["transport"] = "ssh-posix"
        self.assertTrue(MODULE.validate_inventory(bad))

    def test_inventory_docroot_and_remote_only_validation(self) -> None:
        self.assertEqual(MODULE.validate_inventory(INVENTORY), [])
        with __import__("tempfile").TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            value = json.loads(json.dumps(INVENTORY)); value["targets"][0]["authoritativeDocs"] = [{"path": "docs/present.md", "remoteOnly": False}]
            (Path(directory) / "docs").mkdir(); (Path(directory) / "docs/present.md").write_text("synthetic\n")
            path.write_text(json.dumps(value))
            self.assertEqual(MODULE.validate_inventory(value, path), [])
            value["targets"][0]["authoritativeDocs"][0]["path"] = "docs/missing.md"
            self.assertTrue(MODULE.validate_inventory(value, path))
            value["targets"][0]["authoritativeDocs"][0] = {"path": "docs/missing.md", "remoteOnly": True}
            self.assertEqual(MODULE.validate_inventory(value, path), [])
            value["targets"][0]["authoritativeDocs"][0] = {"path": "../outside.md", "remoteOnly": True}
            self.assertTrue(MODULE.validate_inventory(value, path))

    def test_linux_normalizes_disk_memory_and_processes(self) -> None:
        report = MODULE.collect_linux(INVENTORY["targets"][0], runner=Runner(), exists=lambda _: False)
        self.assertEqual(report["identity"], "synthetic-linux")
        self.assertEqual(report["largeFiles"][0]["bytes"], 300000000)
        self.assertEqual(report["memory"]["physical"]["availableBytes"], 600)
        self.assertEqual(report["inodes"][0]["available"], 50)
        self.assertEqual(report["processes"][0]["pid"], 12)

    def test_plan_and_digest_are_stable(self) -> None:
        report = MODULE.collect_linux(INVENTORY["targets"][0], runner=Runner(), exists=lambda _: False)
        first = MODULE.build_plan(INVENTORY, [report])
        self.assertEqual(first, MODULE.build_plan(INVENTORY, [report]))
        self.assertTrue(first["planDigest"].startswith("sha256:"))
        self.assertIn("review", {candidate["status"] for candidate in first["candidates"]})
        self.assertIn("blocked", {candidate["status"] for candidate in first["candidates"]})

    def test_remote_transport_is_fixed_and_fail_closed(self) -> None:
        seen: list[list[str]] = []
        def runner(argv: list[str], timeout: int) -> MODULE.CommandResult:
            seen.append(argv)
            return MODULE.CommandResult(1, "", "unavailable")
        report = MODULE.collect_remote(INVENTORY["targets"][1], runner=runner)
        self.assertEqual(report["status"], "unavailable")
        self.assertIn("-NoProfile", seen[0][-1])
        self.assertNotIn("shell=True", SCRIPT.read_text())

    def test_posix_remote_roots_survive_shell_serialization(self) -> None:
        roots = [
            "/srv/space root",
            "/srv/single'quote",
            '/srv/double"quote',
            "/srv/semi;colon",
            "/srv/$() literal",
        ]
        target = {
            "id": "remote",
            "platform": "linux",
            "transport": "ssh-posix",
            "endpoint": "synthetic-host",
            "expectedIdentity": "synthetic-linux",
            "scanRoots": roots,
            "protectedPaths": ["/srv/example/live.db"],
        }
        seen: list[list[str]] = []
        MODULE.collect_remote(target, runner=lambda argv, timeout: seen.append(argv) or MODULE.CommandResult(1))
        command = shlex.split(seen[0][6])
        self.assertEqual(command[:3], ["python3", "-c", MODULE.POSIX_SCRIPT])
        self.assertEqual(command[3:], [part for root in sorted(roots) for part in ("--root", root)])

    def test_powershell_script_and_roots_survive_encoded_command(self) -> None:
        roots = [
            "C:\\Space Root",
            "D:\\single'quote",
            'E:\\double"quote',
            "F:\\semi;root",
            "G:\\$() literal",
            "H:\\pipe|and&root",
        ]
        target = dict(INVENTORY["targets"][1])
        target["scanRoots"] = roots
        seen: list[list[str]] = []
        MODULE.collect_remote(target, runner=lambda argv, timeout: seen.append(argv) or MODULE.CommandResult(1))

        command = seen[0][6]
        prefix = "powershell.exe -NoProfile -NonInteractive -EncodedCommand "
        self.assertTrue(command.startswith(prefix))
        self.assertEqual(command, MODULE._powershell_remote_command(sorted(roots)))
        encoded = command.removeprefix(prefix)
        self.assertRegex(encoded, r"^[A-Za-z0-9+/]+={0,2}$")
        payload = base64.b64decode(encoded, validate=True).decode("utf-16-le")
        loader_match = re.fullmatch(
            r"\$bytes=\[Convert\]::FromBase64String\('([A-Za-z0-9+/]+={0,2})'\); \$input=New-Object IO\.MemoryStream\(,\$bytes\); \$gzip=New-Object IO\.Compression\.GzipStream\(\$input,\[IO\.Compression\.CompressionMode\]::Decompress\); \$reader=New-Object IO\.StreamReader\(\$gzip,\[Text\.Encoding\]::UTF8\); & \(\[ScriptBlock\]::Create\(\$reader\.ReadToEnd\(\)\)\)",
            payload,
        )
        self.assertIsNotNone(loader_match)
        assert loader_match is not None
        inner_payload = gzip.decompress(base64.b64decode(loader_match.group(1), validate=True)).decode("utf-8")
        self.assertTrue(inner_payload.endswith(MODULE.WINDOWS_SCRIPT))
        arguments_match = re.fullmatch(
            r"\$auditArgsJson=\[Text\.Encoding\]::UTF8\.GetString\(\[Convert\]::FromBase64String\('([A-Za-z0-9+/]+={0,2})'\)\); \$auditArgs=@\(ConvertFrom-Json -InputObject \$auditArgsJson\); \$roots=@\(for\(\$i=0;\$i -lt \$auditArgs\.Count-1;\$i\+\+\)\{if\(\$auditArgs\[\$i\] -eq '--root'\)\{\$auditArgs\[\$i\+1\]\}\}\); ",
            inner_payload[: -len(MODULE.WINDOWS_SCRIPT)],
        )
        self.assertIsNotNone(arguments_match)
        assert arguments_match is not None
        decoded_arguments = json.loads(base64.b64decode(arguments_match.group(1), validate=True).decode("utf-8"))
        self.assertEqual(decoded_arguments, [part for root in sorted(roots) for part in ("--root", root)])
        self.assertNotRegex(command, r"[|&;'\"$()]")
        self.assertLess(len(command), 8_191)

    def test_posix_and_pct_remote_transports_normalize_json(self) -> None:
        payload = posix_payload("synthetic-linux")
        target = {"id": "remote", "platform": "linux", "transport": "ssh-posix", "endpoint": "synthetic-host", "expectedIdentity": "synthetic-linux", "scanRoots": ["/srv/example"], "protectedPaths": ["/srv/example/live.db"]}
        seen: list[list[str]] = []
        timeouts: list[int] = []
        def runner(argv: list[str], timeout: int) -> MODULE.CommandResult:
            seen.append(argv); timeouts.append(timeout); return MODULE.CommandResult(0, json.dumps(payload))
        report = MODULE.collect_remote(target, runner=runner)
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["filesystems"][0]["mountPoint"], "/")
        self.assertEqual(report["memory"]["physical"]["availableBytes"], 400)
        self.assertEqual(report["processes"][0]["pid"], 3)
        self.assertEqual(report["psi"]["memory"], "some avg10=1")
        self.assertTrue(report["deletedOpen"])
        self.assertEqual(timeouts, [30])
        self.assertEqual(seen[0][:6], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "synthetic-host"])
        self.assertEqual(shlex.split(seen[0][6])[:3], ["python3", "-c", MODULE.POSIX_SCRIPT])

        targets = proxmox_targets()
        child = targets[1]
        payload = posix_payload()
        seen = []
        def pct_runner(argv: list[str], timeout: int) -> MODULE.CommandResult:
            seen.append(argv); return MODULE.CommandResult(0, json.dumps(payload))
        report = MODULE.audit_target(child, runner=pct_runner, targets=targets)
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["identity"], "synthetic-container")
        self.assertEqual(seen[0][:6], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "synthetic-proxmox"])
        command = shlex.split(seen[0][6])
        self.assertEqual(command[:7], ["pct", "exec", "42", "--", "python3", "-c", MODULE.POSIX_SCRIPT])
        self.assertNotIn("/bin/sh", command)
        compile(MODULE.POSIX_SCRIPT, "resource_audit.POSIX_SCRIPT", "exec")

    def test_platform_normalization_preserves_native_disk_evidence(self) -> None:
        filesystems = [{"filesystem": "/dev/root", "mountPoint": "/"}]
        inodes = [{"filesystem": "/dev/root", "mountPoint": "/", "available": 50}]
        posix = MODULE._normalise_posix({"filesystems": filesystems, "inodes": inodes})
        self.assertEqual(posix["filesystems"], filesystems)
        self.assertEqual(posix["inodes"], inodes)

        volumes = [{"filesystem": "C:", "mountPoint": "C:\\"}]
        windows = MODULE._normalise_windows({"filesystems": filesystems, "volumes": volumes, "inodes": []})
        self.assertEqual(windows["filesystems"], volumes)
        self.assertEqual(windows["inodes"], [])

    def test_posix_optional_budget_preserves_baseline_and_stops_commands(self) -> None:
        calls: list[tuple[list[str], float]] = []
        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((argv, float(kwargs["timeout"])))
            if argv == ["df", "-P", "-T"]:
                stdout = "Filesystem Type 1024-blocks Used Available Capacity Mounted on\n/dev/root ext4 100 50 50 50% /\n"
            elif argv == ["df", "-P", "-i"]:
                stdout = "Filesystem Inodes IUsed IFree IUse% Mounted on\n/dev/root 100 50 50 50% /\n"
            elif argv and argv[0] == "lsblk":
                stdout = '{"blockdevices":[]}'
            else:
                stdout = ""
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        ticks = iter([0.0, *([21.0] * 100)])
        report = execute_posix_script(["/scan-b", "/scan-a"], runner, lambda: next(ticks))
        self.assertEqual([argv for argv, _ in calls], [["df", "-P", "-T"], ["df", "-P", "-i"]])
        self.assertEqual(report["identity"], "synthetic-linux")
        self.assertEqual(report["filesystems"][0]["mountPoint"], "/")
        self.assertEqual(report["inodes"][0]["available"], 50)
        self.assertEqual(report["memory"]["physical"]["availableBytes"], 409600)
        self.assertEqual(report["incompleteEvidence"], [
            {"evidence": "diskHealth", "reason": "lsblk-unavailable", "root": "/dev"},
            {"evidence": "duSummaries", "reason": "budget-exhausted", "root": "/scan-a"},
            {"evidence": "largeFiles", "reason": "budget-exhausted", "root": "/scan-a"},
            {"evidence": "duSummaries", "reason": "budget-exhausted", "root": "/scan-b"},
            {"evidence": "largeFiles", "reason": "budget-exhausted", "root": "/scan-b"},
        ])

    def test_posix_large_file_scan_uses_budgeted_find(self) -> None:
        calls: list[tuple[list[str], float]] = []
        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append((argv, float(kwargs["timeout"])))
            if argv == ["find", "/scan", "-xdev", "-type", "f", "-size", "+200000000c", "-printf", "%s\\t%p\\n"]:
                return subprocess.CompletedProcess(argv, 0, "300000000\t/scan/cache.bin\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        report = execute_posix_script(["/scan"], runner, lambda: 0.0)
        find_calls = [(argv, timeout) for argv, timeout in calls if argv and argv[0] == "find"]
        self.assertEqual(find_calls[0][0], ["find", "/scan", "-xdev", "-type", "f", "-size", "+200000000c", "-printf", "%s\\t%p\\n"])
        self.assertGreater(find_calls[0][1], 0)
        self.assertLessEqual(find_calls[0][1], 20)
        self.assertEqual(report["largeFiles"], [{"bytes": 300000000, "path": "/scan/cache.bin", "protected": False}])
        self.assertNotIn("os.walk", MODULE.POSIX_SCRIPT)

    def test_posix_incomplete_evidence_is_deterministic_for_scan_timeouts(self) -> None:
        def collect() -> dict[str, object]:
            def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                if argv and argv[0] in {"du", "find"}:
                    raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
                if argv and argv[0] == "lsblk":
                    return subprocess.CompletedProcess(argv, 0, '{"blockdevices":[]}', "")
                return subprocess.CompletedProcess(argv, 0, "", "")
            return execute_posix_script(["/scan-b", "/scan-a", "/scan-b"], runner, lambda: 0.0)

        first = collect()
        second = collect()
        expected = [
            {"evidence": "duSummaries", "reason": "timeout", "root": "/scan-a"},
            {"evidence": "largeFiles", "reason": "timeout", "root": "/scan-a"},
            {"evidence": "duSummaries", "reason": "timeout", "root": "/scan-b"},
            {"evidence": "largeFiles", "reason": "timeout", "root": "/scan-b"},
        ]
        self.assertEqual(first["incompleteEvidence"], expected)
        self.assertEqual(second["incompleteEvidence"], expected)

    def test_transport_errors_are_bounded_and_explain_unavailable_windows(self) -> None:
        target = {"id": "windows", "platform": "windows", "transport": "ssh-powershell",
                  "endpoint": "synthetic-host", "expectedIdentity": "SYNTHETIC", "scanRoots": ["C:\\Synthetic"],
                  "protectedPaths": ["C:\\Synthetic\\protected"]}
        def failing(stderr: str) -> dict[str, object]:
            return MODULE.collect_remote(target, runner=lambda argv, timeout: MODULE.CommandResult(255, "", stderr))
        self.assertEqual(failing("ssh: Could not resolve hostname synthetic-host: Name or service not known")["errors"],
                         ["endpoint DNS resolution failed"])
        self.assertEqual(failing("Connection reset by synthetic-host port 22")["errors"],
                         ["transport connection reset"])
        self.assertNotIn("synthetic-host", json.dumps(failing("Connection reset by synthetic-host port 22")))

    def test_disk_health_skips_virtual_disks_and_reads_physical_health_passively(self) -> None:
        calls: list[list[str]] = []
        def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(argv)
            if argv and argv[0] == "lsblk":
                return subprocess.CompletedProcess(argv, 0, json.dumps({"blockdevices": [
                    {"name": "sda", "type": "disk", "model": "Virtual Disk"},
                    {"name": "nvme0n1", "type": "disk", "model": "Physical NVMe"},
                ]}), "")
            if argv and argv[0] == "smartctl":
                return subprocess.CompletedProcess(argv, 0, '{"smart_status":{"passed":true}}', "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        report = execute_posix_script([], runner, lambda: 0.0)
        self.assertEqual(report["diskHealth"], [
            {"device": "/dev/sda", "status": "virtual", "source": "lsblk"},
            {"device": "/dev/nvme0n1", "status": "passed", "source": "smartctl"},
        ])
        self.assertEqual([c for c in calls if c and c[0] == "smartctl"],
                         [["smartctl", "-n", "standby", "-H", "-j", "/dev/nvme0n1"]])

    def test_windows_health_is_normalized_without_recursive_drive_scan(self) -> None:
        payload = {"identity": "SYNTHETIC-WINDOWS", "volumes": [], "memory": {},
                   "diskHealth": [{"device": "synthetic-disk", "status": "warning", "source": "windows-physical-disk"}]}
        normalized = MODULE._normalise_windows(payload)
        self.assertEqual(normalized["diskHealth"], payload["diskHealth"])
        self.assertIn("Get-PhysicalDisk", MODULE.WINDOWS_SCRIPT)
        self.assertIn("Get-VMHardDiskDrive", MODULE.WINDOWS_SCRIPT)
        self.assertNotIn("Get-ChildItem -Path $env:SystemDrive", MODULE.WINDOWS_SCRIPT)

    def test_failed_disk_health_requires_review(self) -> None:
        inventory = json.loads(json.dumps(INVENTORY))
        target = inventory["targets"][0]
        audit = posix_payload(target["expectedIdentity"])
        audit.update({"target": {"id": target["id"]}, "status": "available", "diskHealth": [
            {"device": "/dev/sdb", "status": "failed", "source": "smartctl"},
        ]})
        plan = MODULE.build_plan(inventory, [audit])
        disks = [c for c in plan["candidates"] if c["kind"] == "disk-health"]
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0]["status"], "review")
        self.assertEqual(disks[0]["device"], "/dev/sdb")

    def test_protected_descendants_are_not_cleanup_candidates(self) -> None:
        inventory = json.loads(json.dumps(INVENTORY))
        target = inventory["targets"][0]
        target["protectedPaths"] = ["/var/lib/postgresql"]
        audit = posix_payload(target["expectedIdentity"])
        audit.update({"target": {"id": target["id"]}, "status": "available", "largeFiles": [
            {"path": "/var/lib/postgresql/16/main/base/123", "bytes": 300000000, "protected": False},
            {"path": "/var/lib/postgresql-backup/old", "bytes": 300000000, "protected": False},
        ]})
        plan = MODULE.build_plan(inventory, [audit])
        files = {c["path"]: c for c in plan["candidates"] if c["kind"] == "file"}
        self.assertEqual(files["/var/lib/postgresql/16/main/base/123"]["status"], "blocked")
        self.assertEqual(files["/var/lib/postgresql/16/main/base/123"]["priority"]["reclaimability"], 0)
        self.assertEqual(files["/var/lib/postgresql-backup/old"]["status"], "review")
        self.assertTrue(MODULE._protected_path(r"c:\\data\\active\\db.vhdx", [r"C:\\Data\\Active"], "windows"))
        self.assertFalse(MODULE._protected_path(r"C:\\Data\\Active-old\\db.vhdx", [r"C:\\Data\\Active"], "windows"))

    def test_identity_matching_partial_posix_report_remains_available(self) -> None:
        payload = posix_payload("synthetic-linux")
        payload["incompleteEvidence"] = [{"evidence": "largeFiles", "reason": "timeout", "root": "/scan"}]
        target = {"id": "remote", "platform": "linux", "transport": "ssh-posix", "endpoint": "synthetic-host", "expectedIdentity": "synthetic-linux", "scanRoots": ["/scan"], "protectedPaths": ["/scan/live.db"]}
        report = MODULE.collect_remote(target, runner=lambda argv, timeout: MODULE.CommandResult(0, json.dumps(payload)))
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["incompleteEvidence"], payload["incompleteEvidence"])
        self.assertNotIn("incompleteEvidence", MODULE._normalise_windows({"volumes": [], "incompleteEvidence": payload["incompleteEvidence"]}))

    def test_pct_missing_or_invalid_parent_fails_before_runner(self) -> None:
        targets = proxmox_targets()
        child = targets[1]
        seen: list[list[str]] = []
        def runner(argv: list[str], timeout: int) -> MODULE.CommandResult:
            seen.append(argv); return MODULE.CommandResult(0, json.dumps(posix_payload()))
        for graph in (None, [child], [targets[0], targets[0], child]):
            report = MODULE.collect_remote(child, runner=runner, targets=graph)
            self.assertEqual(report["status"], "blocked")
        invalid_parent = {**targets[0], "endpoint": "-oProxyCommand=bad"}
        report = MODULE.collect_remote(child, runner=runner, targets=[invalid_parent, child])
        self.assertEqual(report["status"], "blocked")
        wrong_parent = {**targets[0], "platform": "linux"}
        report = MODULE.collect_remote(child, runner=runner, targets=[wrong_parent, child])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(seen, [])

    def test_command_line_audit_passes_inventory_target_graph(self) -> None:
        inventory = {
            "schemaVersion": "resource-maintenance.inventory.v1",
            "environment": "synthetic",
            "docRoot": ".",
            "targets": proxmox_targets(),
        }
        with tempfile.TemporaryDirectory() as directory:
            inventory_path = Path(directory) / "inventory.json"
            output_path = Path(directory) / "audit.json"
            inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
            expected = {"schemaVersion": MODULE.SCHEMA, "status": "blocked"}
            with patch.object(MODULE, "audit_target", return_value=expected) as audit:
                self.assertEqual(MODULE.main(["audit", "--inventory", str(inventory_path), "--target", "container-child", "--output", str(output_path)]), 0)
            audit.assert_called_once_with(inventory["targets"][1], targets=inventory["targets"])
            self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), expected)

    def test_endpoint_is_checked_before_runner_and_identity_mismatch_is_blocked(self) -> None:
        called = False
        def runner(argv: list[str], timeout: int) -> MODULE.CommandResult:
            nonlocal called; called = True; return MODULE.CommandResult(0, "{}")
        bad = dict(INVENTORY["targets"][1]); bad["endpoint"] = "-oProxyCommand=bad"
        report = MODULE.collect_remote(bad, runner=runner)
        self.assertEqual(report["status"], "blocked"); self.assertFalse(called)
        bad = dict(INVENTORY["targets"][1]); bad["expectedIdentity"] = "other"
        report = MODULE.collect_remote(bad, runner=lambda argv, timeout: MODULE.CommandResult(0, json.dumps({"identity": "synthetic-windows", "volumes": [], "memory": {}, "processes": []})))
        self.assertEqual(report["status"], "blocked")
        target = {"id": "remote", "platform": "linux", "transport": "ssh-posix", "endpoint": "synthetic-host", "expectedIdentity": "other", "scanRoots": ["/srv/example"], "protectedPaths": ["/srv/example/live.db"]}
        report = MODULE.collect_remote(target, runner=lambda argv, timeout: MODULE.CommandResult(0, json.dumps({"identity": "synthetic-linux", "volumes": [], "memory": {}, "processes": []})))
        self.assertEqual(report["status"], "blocked")
        targets = proxmox_targets(); targets[1]["expectedIdentity"] = "other"
        report = MODULE.collect_remote(targets[1], runner=lambda argv, timeout: MODULE.CommandResult(0, json.dumps(posix_payload())), targets=targets)
        self.assertEqual(report["status"], "blocked")
        local = dict(INVENTORY["targets"][0]); local["expectedIdentity"] = "other"
        report = MODULE.collect_linux(local, runner=Runner(), exists=lambda _: False)
        self.assertEqual(report["status"], "blocked")

    def test_remote_timeout_and_invalid_json_are_unavailable(self) -> None:
        target = INVENTORY["targets"][1]
        timeout = MODULE.collect_remote(target, runner=lambda argv, timeout: MODULE.CommandResult(124, "", "timed out"))
        self.assertEqual(timeout["status"], "unavailable")
        invalid = MODULE.collect_remote(target, runner=lambda argv, timeout: MODULE.CommandResult(0, "not-json"))
        self.assertEqual(invalid["status"], "unavailable")

    def test_missing_optional_tools_are_bounded_findings(self) -> None:
        report = MODULE.collect_linux(INVENTORY["targets"][0], runner=Runner(), exists=lambda _: False)
        self.assertIn("lsof unavailable; deleted-open evidence incomplete", report["errors"])
        self.assertIn("nvidia-smi unavailable", report["errors"])

    def test_windows_optional_evidence_is_preserved(self) -> None:
        payload = {"identity": "synthetic-windows", "volumes": [], "memory": {}, "processes": [], "hyperv": [{"name": "vm", "memoryAssignedBytes": 5}], "vhd": [{"path": "C:\\vm.vhdx", "bytes": 6}], "services": [{"name": "svc", "state": "Running"}], "wsl": {"present": True}, "docker": {"present": False}, "gpu": ["GPU 0"], "errors": ["Hyper-V cmdlets unavailable"]}
        target = INVENTORY["targets"][1]
        report = MODULE.collect_remote(target, runner=lambda argv, timeout: MODULE.CommandResult(0, json.dumps(payload)))
        self.assertEqual(report["hyperv"][0]["name"], "vm")
        self.assertEqual(report["vhd"][0]["path"], "C:\\vm.vhdx")
        self.assertTrue(report["wsl"]["present"])
        self.assertEqual(report["gpu"], ["GPU 0"])

    def test_planner_evaluates_thresholds_rank_and_deduplicates_parent(self) -> None:
        inventory = json.loads(json.dumps(INVENTORY)); inventory["targets"][0]["thresholds"].update({"diskFreePercent": 60, "inodeFreePercent": 60, "memoryAvailablePercent": 50, "swapUsedPercent": 10})
        inventory["targets"].append({"id": "child", "platform": "container", "transport": "ssh-posix", "endpoint": "synthetic-child", "expectedIdentity": "synthetic-child", "parent": "linux-lab", "authoritativeDocs": [{"path": "docs/child.md", "remoteOnly": True}], "scanRoots": ["/srv/example"], "protectedPaths": ["/srv/example/live.db"], "thresholds": {"diskFreePercent": 60, "memoryAvailablePercent": 10}})
        first = MODULE.collect_linux(INVENTORY["targets"][0], runner=Runner(), exists=lambda _: False)
        child = {"schemaVersion": MODULE.SCHEMA, "target": {"id": "child"}, "status": "available", "identity": "synthetic-child", "filesystems": first["filesystems"], "inodes": [], "memory": {}, "processes": [], "largeFiles": []}
        plan = MODULE.build_plan(inventory, [first, child])
        self.assertEqual(plan, MODULE.build_plan(inventory, [first, child]))
        self.assertEqual(plan["state"], "blocked")
        self.assertTrue(any(candidate["kind"] == "filesystem" and candidate["status"] == "blocked" for candidate in plan["candidates"]))
        priorities = [candidate["priority"] for candidate in plan["candidates"]]
        self.assertEqual(priorities, sorted(priorities, key=lambda p: (-p["urgency"], -p["growth"], -p["reclaimability"], -p["reversibility"], p["risk"])))

    def test_planner_blocks_identity_mismatch_even_if_audit_lies_about_status(self) -> None:
        audit = {"schemaVersion": MODULE.SCHEMA, "target": {"id": "linux-lab"}, "status": "available", "identity": "unexpected", "filesystems": [], "inodes": [], "memory": {}, "processes": [], "largeFiles": []}
        plan = MODULE.build_plan(INVENTORY, [audit])
        target_candidate = next(item for item in plan["candidates"] if item["target"] == "linux-lab" and item["kind"] == "target")
        self.assertEqual(target_candidate["status"], "blocked")
        self.assertEqual(plan["targetStates"]["linux-lab"], "blocked")
        self.assertNotEqual(plan["state"], "ready")

    def test_planner_blocks_declared_unavailable_target(self) -> None:
        inventory = json.loads(json.dumps(INVENTORY)); inventory["targets"][0]["availability"] = "unavailable"
        audit = {"schemaVersion": MODULE.SCHEMA, "target": {"id": "linux-lab"}, "status": "available", "identity": "synthetic-linux", "filesystems": [], "inodes": [], "memory": {}, "processes": [], "largeFiles": []}
        plan = MODULE.build_plan(inventory, [audit])
        candidate = next(item for item in plan["candidates"] if item["target"] == "linux-lab")
        self.assertEqual(candidate["status"], "unavailable")
        self.assertEqual(plan["targetStates"]["linux-lab"], "unavailable")
        self.assertNotEqual(plan["state"], "ready")

    def test_windows_remote_normalizes_fixed_payload(self) -> None:
        def runner(argv: list[str], timeout: int) -> MODULE.CommandResult:
            return MODULE.CommandResult(0, json.dumps({
                "identity": "synthetic-windows",
                "volumes": [{"mountPoint": "C:\\", "availableBytes": 500}],
                "memory": {"physical": {"totalBytes": 1000, "availableBytes": 400}, "pagefile": []},
                "processes": [{"pid": 9, "rssBytes": 900, "name": "worker"}],
            }))
        report = MODULE.collect_remote(INVENTORY["targets"][1], runner=runner)
        self.assertEqual(report["status"], "available")
        self.assertEqual(report["identity"], "synthetic-windows")
        self.assertEqual(report["filesystems"][0]["availableBytes"], 500)
        self.assertEqual(report["memory"]["physical"]["availableBytes"], 400)


if __name__ == "__main__":
    unittest.main()
