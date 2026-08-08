#!/usr/bin/env python3
"""Create and validate runtime-neutral conversation handoffs."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HEADINGS = (
    "Goal",
    "State",
    "Decisions and constraints",
    "Open work and gates",
    "Next safe action",
    "Artifacts and capabilities",
)
SECRET_PATTERNS = (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}",
    r"\b(?:api[_-]?key|password|secret|token)\s*[:=]\s*[^\s<]{8,}",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"\bsk-[A-Za-z0-9_-]{20,}",
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s:@/]+:[^\s@/]+@",
)


def run(*args: str, cwd: Path) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def git_state(cwd: Path) -> dict[str, str]:
    root = run("git", "rev-parse", "--show-toplevel", cwd=cwd)
    if not root:
        return {"workspace": str(cwd.resolve()), "revision": "not-a-git-workspace", "branch": "n/a", "status": "not checked"}
    repo = Path(root)
    status = run("git", "status", "--short", cwd=repo)
    return {
        "workspace": str(repo.resolve()),
        "revision": run("git", "rev-parse", "HEAD", cwd=repo) or "unknown",
        "branch": run("git", "branch", "--show-current", cwd=repo) or "detached",
        "status": "clean" if not status else "dirty: " + "; ".join(status.splitlines()),
    }


def scaffold(goal: str, cwd: Path) -> str:
    state = git_state(cwd)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return f"""# Conversation handoff

- Created: {created}
- Workspace: {state['workspace']}
- Revision: {state['revision']}
- Branch: {state['branch']}
- Recorded state: {state['status']}

## Goal

{goal}

## State

- Verified: [TODO: current state and evidence]
- Source-backed: [TODO: authoritative artifacts]
- Assumed: [TODO: remaining assumptions or none]

## Decisions and constraints

- [TODO: decision, rationale, and rejected option if still relevant]

## Open work and gates

- [TODO: owner, blocker or approval gate, and resume condition]

## Next safe action

1. [TODO: one concrete action valid without crossing a remaining gate]

## Artifacts and capabilities

- [TODO: path or URL; purpose]
- Skills: [TODO: installed skills or bounded catalogue searches worth using]
"""


def section(content: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$", content, re.MULTILINE)
    if not match:
        return ""
    tail = content[match.end():]
    next_heading = re.search(r"^## ", tail, re.MULTILINE)
    return tail[: next_heading.start() if next_heading else None].strip()


def validate(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    errors: list[str] = []
    for heading in HEADINGS:
        body = section(content, heading)
        if not body:
            errors.append(f"missing or empty section: {heading}")
        elif "[TODO:" in body:
            errors.append(f"unresolved placeholder: {heading}")
    for pattern in SECRET_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            errors.append("potential secret detected")
            break
    state = section(content, "State")
    for label in ("Verified:", "Source-backed:", "Assumed:"):
        if label not in state:
            errors.append(f"state footing missing: {label[:-1]}")
    return errors


def recorded(content: str, key: str) -> str:
    match = re.search(rf"^- {re.escape(key)}:\s*(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def check(path: Path, cwd: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    current = git_state(cwd)
    warnings = validate(path)
    for key, current_key in (("Workspace", "workspace"), ("Revision", "revision"), ("Branch", "branch"), ("Recorded state", "status")):
        old = recorded(content, key)
        if old and old != current[current_key]:
            warnings.append(f"{key.lower()} changed: recorded {old}; current {current[current_key]}")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--goal", required=True)
    create.add_argument("--output", type=Path)
    for name in ("validate", "check"):
        command = sub.add_parser(name)
        command.add_argument("file", type=Path)
    args = parser.parse_args()

    cwd = Path.cwd()
    if args.command == "create":
        if args.output:
            target = args.output.expanduser().resolve()
            if target.exists():
                print(f"ERROR refusing to overwrite: {target}")
                return 2
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, raw = tempfile.mkstemp(prefix="conversation-handoff-", suffix=".md")
            os.close(fd)
            target = Path(raw)
        target.write_text(scaffold(args.goal, cwd), encoding="utf-8")
        print(target)
        return 0

    path = args.file.expanduser().resolve()
    if not path.is_file():
        print(f"ERROR file not found: {path}")
        return 2
    findings = validate(path) if args.command == "validate" else check(path, cwd)
    if findings:
        for finding in findings:
            print(f"ERROR {finding}" if args.command == "validate" else f"WARN {finding}")
        return 1
    print("OK handoff validated" if args.command == "validate" else "OK recorded state matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
