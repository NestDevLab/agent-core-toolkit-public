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
