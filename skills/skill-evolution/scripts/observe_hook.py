#!/usr/bin/env python3
"""Fail-open hook observer that stores bounded failure fingerprints, never raw payloads."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

MAX_INPUT = 65_536


def string_field(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value:
            return value[:256]
    return "unknown"


def observe(payload: dict[str, Any], environment: dict[str, str]) -> Path | None:
    if environment.get("SKILL_EVOLUTION_HOOKS_ENABLED") != "1":
        return None
    event = string_field(payload, "hook_event_name", "eventName", "event")
    error = payload.get("error") or payload.get("tool_error") or payload.get("toolError")
    response = payload.get("tool_response") or payload.get("toolResult")
    failed = "failure" in event.lower() or "error" in event.lower() or bool(error)
    if isinstance(response, dict):
        failed = failed or response.get("success") is False or response.get("exit_code", 0) not in (0, None)
    if not failed:
        return None
    harness = environment.get("SKILL_EVOLUTION_HARNESS", "unknown")[:64]
    tool = string_field(payload, "tool_name", "toolName")
    cwd = string_field(payload, "cwd", "workingDirectory")
    fingerprint = hashlib.sha256(f"{harness}\0{event}\0{tool}\0{type(error).__name__}".encode()).hexdigest()
    state = environment.get("SKILL_EVOLUTION_STATE_DIR")
    root = Path(state).expanduser() if state else Path(environment.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "skill-evolution"
    directory = root.resolve() / "observations"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{fingerprint}.json"
    if path.exists():
        return path
    record = {
        "schema": "skill-evolution.observation.v1",
        "harness": harness,
        "event": event,
        "tool": tool,
        "cwdFingerprint": hashlib.sha256(cwd.encode()).hexdigest(),
        "evidenceFingerprint": fingerprint,
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(record, handle, sort_keys=True)
        handle.write("\n")
    return path


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            return 0
        payload = json.loads(raw or b"{}")
        if isinstance(payload, dict):
            observe(payload, dict(os.environ))
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
