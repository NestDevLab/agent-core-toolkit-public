#!/usr/bin/env python3
"""Tests for the generic disk and memory collector."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).parent / ".." / "scripts" / "resource_audit.py").resolve()
SPEC = importlib.util.spec_from_file_location("resource_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["resource_audit"] = MODULE
SPEC.loader.exec_module(MODULE)
INVENTORY = json.loads((Path(__file__).parent / ".." / "references" / "resource-maintenance.synthetic.json").read_text())


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
        self.assertIn("-NoProfile", seen[0])
        self.assertNotIn("shell=True", SCRIPT.read_text())

    def test_posix_and_pct_remote_transports_normalize_json(self) -> None:
        payload = {"identity": "synthetic-linux", "volumes": [{"filesystem": "/dev/root", "available": 50, "blocks": 100, "mountPoint": "/"}], "inodes": [{"filesystem": "/dev/root", "available": 50, "inodes": 100, "mountPoint": "/"}], "memory": {"physical": {"totalBytes": 1000, "availableBytes": 400}, "swap": {"totalBytes": 100, "usedBytes": 20}}, "processes": [{"pid": 3, "rssBytes": 800, "name": "worker"}], "psi": {"memory": "some avg10=1"}, "oom": {"oom": 2}, "cgroups": {"memory.current": "10"}, "deletedOpen": [{"pid": 3, "path": "/tmp/deleted", "memoryBacked": False}], "duSummaries": [{"path": "/srv/example", "bytes": 900}], "largeFiles": [], "errors": []}
        for transport in ("ssh-posix", "proxmox-pct"):
            target = {"id": "remote", "platform": "container" if transport == "proxmox-pct" else "linux", "transport": transport, "endpoint": "synthetic-host", "expectedIdentity": "synthetic-linux", "scanRoots": ["/srv/example"], "protectedPaths": ["/srv/example/live.db"], "containerId": 42} if transport == "proxmox-pct" else {"id": "remote", "platform": "linux", "transport": transport, "endpoint": "synthetic-host", "expectedIdentity": "synthetic-linux", "scanRoots": ["/srv/example"], "protectedPaths": ["/srv/example/live.db"]}
            seen: list[list[str]] = []
            def runner(argv: list[str], timeout: int) -> MODULE.CommandResult:
                seen.append(argv); return MODULE.CommandResult(0, json.dumps(payload))
            report = MODULE.collect_remote(target, runner=runner)
            self.assertEqual(report["status"], "available")
            self.assertEqual(report["filesystems"][0]["mountPoint"], "/")
            self.assertEqual(report["memory"]["physical"]["availableBytes"], 400)
            self.assertEqual(report["processes"][0]["pid"], 3)
            self.assertEqual(report["psi"]["memory"], "some avg10=1")
            self.assertTrue(report["deletedOpen"])
            self.assertIn("python3", seen[0]); self.assertNotIn("/bin/sh", seen[0])
        compile(MODULE.POSIX_SCRIPT, "resource_audit.POSIX_SCRIPT", "exec")

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
        for transport in ("ssh-posix", "proxmox-pct"):
            target = {"id": "remote", "platform": "container", "transport": transport, "endpoint": "synthetic-host", "expectedIdentity": "other", "scanRoots": ["/srv/example"], "protectedPaths": ["/srv/example/live.db"], "containerId": 42} if transport == "proxmox-pct" else {"id": "remote", "platform": "linux", "transport": transport, "endpoint": "synthetic-host", "expectedIdentity": "other", "scanRoots": ["/srv/example"], "protectedPaths": ["/srv/example/live.db"]}
            report = MODULE.collect_remote(target, runner=lambda argv, timeout: MODULE.CommandResult(0, json.dumps({"identity": "synthetic-linux", "volumes": [], "memory": {}, "processes": []})))
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
        self.assertEqual(plan["targetStates"]["linux-lab"], "available")
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
