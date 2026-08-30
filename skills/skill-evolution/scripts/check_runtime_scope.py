#!/usr/bin/env python3
"""Fail when generic skill-evolution activation escapes its allowed runtimes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_RUNTIMES = frozenset({"codex", "claude"})
SCOPED_SELECTORS = frozenset({
    "rules/self-improve-on-correction.md",
    "skills/self-improve",
    "skills/skill-evolution",
})


class ScopeError(ValueError):
    pass


def _runtime_set(value: object) -> frozenset[str]:
    return frozenset(value) if isinstance(value, list) and all(isinstance(item, str) for item in value) else frozenset()


def validate_manifest(path: Path, allowed: frozenset[str] = DEFAULT_RUNTIMES) -> int:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    checked = 0

    for index, rule in enumerate(manifest.get("compositionRules", [])):
        if not isinstance(rule, dict) or not str(rule.get("include", "")).endswith("fragments/skill-evolution.md"):
            continue
        if rule.get("target") != "skills/*":
            raise ScopeError(f"{path}: compositionRules[{index}] must target skills/*")
        if _runtime_set(rule.get("runtimes")) != allowed:
            raise ScopeError(f"{path}: compositionRules[{index}] must target only {sorted(allowed)}")
        checked += 1

    for alias, dependency in manifest.get("requires", {}).items():
        if not isinstance(dependency, dict):
            continue
        selected = frozenset(dependency.get("select", []))
        if not selected.intersection(SCOPED_SELECTORS):
            continue
        if _runtime_set(dependency.get("runtimes")) != allowed:
            raise ScopeError(f"{path}: dependency {alias!r} exposes generic self-improvement outside {sorted(allowed)}")
        checked += 1

    for index, provided in enumerate(manifest.get("provides", [])):
        if not isinstance(provided, dict) or not str(provided.get("path", "")).endswith("self-improve-activation.md"):
            continue
        if _runtime_set(provided.get("runtimes")) != allowed:
            raise ScopeError(f"{path}: provides[{index}] exposes self-improve activation outside {sorted(allowed)}")
        checked += 1

    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="+", type=Path)
    args = parser.parse_args()
    checked = sum(validate_manifest(path) for path in args.manifest)
    if checked == 0:
        raise ScopeError("no self-improvement runtime contracts found")
    print(f"skill-evolution runtime scope ok: {checked} contract(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
