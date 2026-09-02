#!/usr/bin/env python3
"""Focused deterministic tests for storage_audit.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = (Path(__file__).parent / ".." / "scripts" / "storage_audit.py").resolve()
SPEC = importlib.util.spec_from_file_location("storage_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["storage_audit"] = MODULE
SPEC.loader.exec_module(MODULE)


class FixtureRunner:
    def __init__(self) -> None:
        self.responses = {
            ("df", "-P", "-T"): MODULE.CommandResult(
                0,
                "Filesystem Type 1024-blocks Used Available Capacity Mounted on\n"
                "/dev/root ext4 100000 60000 40000 60% /\n",
            ),
            ("df", "-P", "-i"): MODULE.CommandResult(
                0,
                "Filesystem Inodes IUsed IFree IUse% Mounted on\n"
                "/dev/root 1000 400 600 40% /\n",
            ),
            ("findmnt", "-rn", "-o", "TARGET,FSTYPE,SOURCE,OPTIONS"): MODULE.CommandResult(
                0, "/ ext4 /dev/root rw,relatime\n"
            ),
            ("lsof", "-nP", "+L1"): MODULE.CommandResult(
                0,
                "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NLINK NODE NAME\n"
                "worker 12 user 3u REG 8,1 250000000 0 1 /var/log/old.log (deleted)\n"
                "devtunnel 13 user 8u REG 0,1 6490449504 0 2 /memfd:doublemapper (deleted)\n",
            ),
            ("du", "-x", "-s", "-B1", "--", "/srv"): MODULE.CommandResult(0, "123456789\t/srv\n"),
            ("du", "-x", "-s", "-B1", "--", "/var/log"): MODULE.CommandResult(0, "987654\t/var/log\n"),
            (
                "find", "/srv", "-xdev", "-type", "f", "-size", "+209715200c", "-printf", "%s\\t%p\\n"
            ): MODULE.CommandResult(0, "300000000\t/srv/large.bin\n"),
            (
                "find", "/var/log", "-xdev", "-type", "f", "-size", "+209715200c", "-printf", "%s\\t%p\\n"
            ): MODULE.CommandResult(0, "250000000\t/var/log/old.log\n"),
            ("hostname",): MODULE.CommandResult(0, "fixture-host\n"),
            ("systemd-detect-virt",): MODULE.CommandResult(0, "lxc\n"),
            ("uname", "-srmo"): MODULE.CommandResult(0, "Linux 6.8 x86_64 GNU/Linux\n"),
            ("docker", "info", "--format", "{{json .}}"): MODULE.CommandResult(
                0,
                '{"ServerVersion":"28.3.1","DockerRootDir":"/var/lib/docker",'
                '"Containers":8,"Images":28}\n',
            ),
            (
                "docker", "ps", "-a", "--size", "--no-trunc", "--format", "{{json .}}"
            ): MODULE.CommandResult(
                0,
                '{"ID":"abc","Names":"old-service","Image":"old:latest",'
                '"State":"exited","Status":"Exited (0)"}\n',
            ),
            ("docker", "system", "df", "-v"): MODULE.CommandResult(
                0, "TYPE TOTAL ACTIVE SIZE RECLAIMABLE\nImages 2 1 3GB 1GB\n"
            ),
        }

    def __call__(self, argv: list[str], timeout: int) -> MODULE.CommandResult:
        return self.responses.get(tuple(argv), MODULE.CommandResult(127, "", "missing fixture"))

    @staticmethod
    def exists(command: str) -> bool:
        return command in {"docker", "findmnt", "lsof"}


class StorageAuditTests(unittest.TestCase):
    def test_parsers_classify_memory_backed_deleted_open_handles(self) -> None:
        result = MODULE.parse_deleted_open(
            "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NLINK NODE NAME\n"
            "p 1 u 1u REG 0,1 500 0 1 /memfd:x (deleted)\n"
            "p 2 u 2u REG 8,1 1000 0 2 /tmp/x (deleted)\n"
        )
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["memoryBackedCount"], 1)
        self.assertEqual(len(result["diskBackedCandidates"]), 1)

    def test_same_fixture_produces_same_report(self) -> None:
        runner = FixtureRunner()
        first = MODULE.collect_audit(
            runner=runner, exists=runner.exists, roots=("/var/log", "/srv", "/var/log")
        )
        second = MODULE.collect_audit(
            runner=runner, exists=runner.exists, roots=("/var/log", "/srv", "/var/log")
        )
        self.assertEqual(first, second)
        self.assertEqual(first["host"]["virtualization"], "lxc")
        self.assertEqual(first["docker"]["containers"][0]["state"], "exited")
        self.assertTrue(first["runtimeAccess"]["docker"]["daemonAccessible"])
        self.assertFalse(first["runtimeAccess"]["hypervisor-management"]["executable"])
        self.assertEqual(first["largeFiles"][0]["bytes"], 300000000)


if __name__ == "__main__":
    unittest.main()
