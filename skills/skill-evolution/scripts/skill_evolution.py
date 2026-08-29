#!/usr/bin/env python3
"""Validate, deduplicate, classify, and persist bounded skill-evolution signals."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA = "skill-evolution.event.v1"
MAX_EVENT_BYTES = 32_768
MAX_STRING = 2_048
SECRET_KEY = re.compile(r"(?:secret|token|password|credential|api[_-]?key|private[_-]?key)", re.I)
SIGNAL_KINDS = {"correction", "recurring-failure", "activation-gap", "deterministic-improvement"}
SOURCE_KINDS = {"owned", "third-party-redistributable", "third-party-restricted", "unknown"}
ENFORCEMENT_DISPOSITIONS = {"script-created", "script-updated", "skill-updated", "nondeterministic"}


class ContractError(ValueError):
    pass


def load_object(path: Path, limit: int = MAX_EVENT_BYTES) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"not a regular input file: {path}")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ContractError(f"input exceeds {limit} bytes")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ContractError("input must be a JSON object")
    reject_sensitive(value)
    return value


def reject_sensitive(value: Any, path: str = "event") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SECRET_KEY.search(str(key)):
                raise ContractError(f"secret-shaped key is forbidden: {path}.{key}")
            reject_sensitive(child, f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) > 100:
            raise ContractError(f"list is too large: {path}")
        for index, child in enumerate(value):
            reject_sensitive(child, f"{path}[{index}]")
    elif isinstance(value, str) and len(value) > MAX_STRING:
        raise ContractError(f"string exceeds {MAX_STRING} characters: {path}")


def required_string(container: dict[str, Any], key: str, context: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def relative_paths(container: dict[str, Any], key: str, context: str, required: bool = True) -> list[str]:
    values = container.get(key)
    if values is None and not required:
        return []
    if not isinstance(values, list) or (required and not values):
        raise ContractError(f"{context}.{key} must be a non-empty list")
    normalized: list[str] = []
    for index, value in enumerate(values):
        if not isinstance(value, str) or not value.strip():
            raise ContractError(f"{context}.{key}[{index}] must be a non-empty string")
        path = Path(value.strip())
        if path.is_absolute() or ".." in path.parts:
            raise ContractError(f"{context}.{key}[{index}] must be a relative path without '..'")
        normalized.append(path.as_posix())
    return sorted(set(normalized))


def normalize_enforcement(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("event.enforcement must be an object; deterministic work requires scripts and tests")
    disposition = required_string(value, "disposition", "event.enforcement")
    if disposition not in ENFORCEMENT_DISPOSITIONS:
        raise ContractError(f"unsupported enforcement disposition: {disposition}")
    if disposition == "not-attempted":
        raise ContractError("not-attempted is not a terminal enforcement disposition")
    normalized: dict[str, Any] = {
        "disposition": disposition,
        "affectedPaths": relative_paths(value, "affectedPaths", "event.enforcement"),
    }
    if disposition in {"script-created", "script-updated"}:
        normalized["scriptPaths"] = relative_paths(value, "scriptPaths", "event.enforcement")
        normalized["testPaths"] = relative_paths(value, "testPaths", "event.enforcement")
        declared = set(normalized["affectedPaths"])
        required_paths = set(normalized["scriptPaths"] + normalized["testPaths"])
        if not required_paths.issubset(declared):
            raise ContractError("event.enforcement.affectedPaths must include every script and test path")
        proof = value.get("idempotence")
        if not isinstance(proof, dict):
            raise ContractError("event.enforcement.idempotence must prove the second run is a no-op")
        first = required_string(proof, "firstRunHash", "event.enforcement.idempotence")
        second = required_string(proof, "secondRunHash", "event.enforcement.idempotence")
        if proof.get("secondRunChanged") is not False or first != second:
            raise ContractError("deterministic enforcement failed second-run idempotence")
        normalized["idempotence"] = {
            "firstRunHash": first,
            "secondRunHash": second,
            "secondRunChanged": False,
        }
    elif disposition == "skill-updated":
        if not any(path.endswith("/SKILL.md") or path == "SKILL.md" for path in normalized["affectedPaths"]):
            raise ContractError("skill-updated must include an authoritative SKILL.md path")
    elif disposition == "nondeterministic":
        normalized["nondeterminismEvidence"] = required_string(
            value, "nondeterminismEvidence", "event.enforcement"
        )
    return normalized


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    reject_sensitive(event)
    if event.get("schema") != SCHEMA:
        raise ContractError(f"schema must be {SCHEMA}")
    signal_kind = required_string(event, "signalKind", "event")
    if signal_kind not in SIGNAL_KINDS:
        raise ContractError(f"unsupported signalKind: {signal_kind}")
    target = event.get("target")
    if not isinstance(target, dict):
        raise ContractError("event.target must be an object")
    source_kind = required_string(target, "sourceKind", "event.target")
    if source_kind not in SOURCE_KINDS:
        raise ContractError(f"unsupported target.sourceKind: {source_kind}")
    normalized = {
        "schema": SCHEMA,
        "signalKind": signal_kind,
        "target": {
            "sourceKind": source_kind,
            "source": required_string(target, "source", "event.target"),
            "revision": required_string(target, "revision", "event.target"),
            "artifact": required_string(target, "artifact", "event.target"),
        },
        "baseHash": required_string(event, "baseHash", "event"),
        "check": required_string(event, "check", "event"),
        "evidenceFingerprint": required_string(event, "evidenceFingerprint", "event"),
        "enforcement": normalize_enforcement(event.get("enforcement")),
    }
    if "summary" in event:
        normalized["summary"] = required_string(event, "summary", "event")
    return normalized


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def candidate_id(event: dict[str, Any]) -> str:
    identity = {
        "target": event["target"],
        "baseHash": event["baseHash"],
        "check": event["check"],
        "evidenceFingerprint": event["evidenceFingerprint"],
    }
    return canonical_hash(identity)[:24]


def classify(event: dict[str, Any], policy: dict[str, Any]) -> tuple[str, str]:
    if event["enforcement"]["disposition"] == "nondeterministic":
        return "semantic", "concrete nondeterminism requires human review"
    artifact = event["target"]["artifact"]
    constitutional = policy.get("constitutionalPaths", [])
    if any(fnmatch.fnmatch(artifact, pattern) for pattern in constitutional):
        return "semantic", "constitutional path"
    checks = policy.get("deterministicChecks", {})
    registered = checks.get(event["check"]) if isinstance(checks, dict) else None
    if event["signalKind"] == "deterministic-improvement" and isinstance(registered, dict):
        return "deterministic", "registered deterministic check"
    return "semantic", "human review required"


def validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("schemaVersion") != 1:
        raise ContractError("policy.schemaVersion must be 1")
    checks = policy.get("deterministicChecks", {})
    if not isinstance(checks, dict):
        raise ContractError("policy.deterministicChecks must be an object")
    for name, config in checks.items():
        context = f"policy.deterministicChecks.{name}"
        if not isinstance(config, dict):
            raise ContractError(f"{context} must be an object")
        required_string(config, "transformer", context)
        allowed = config.get("allowedPaths")
        commands = config.get("checks")
        if not isinstance(allowed, list) or not allowed or not all(isinstance(item, str) and item for item in allowed):
            raise ContractError(f"{context}.allowedPaths must be a non-empty string list")
        if not isinstance(commands, list) or not commands or not all(isinstance(item, str) and item for item in commands):
            raise ContractError(f"{context}.checks must be a non-empty string list")


def validate_enforcement_classification(event: dict[str, Any], classification: str) -> None:
    disposition = event["enforcement"]["disposition"]
    if classification == "deterministic" and disposition not in {"script-created", "script-updated"}:
        raise ContractError(
            "deterministic candidates require script-created or script-updated with focused tests and idempotence proof"
        )
    if classification == "semantic" and disposition == "skill-updated":
        return
    if classification == "semantic" and disposition in {"script-created", "script-updated", "nondeterministic"}:
        return


def validate_enforcement_policy(event: dict[str, Any], policy: dict[str, Any], classification: str) -> None:
    if classification != "deterministic":
        return
    config = policy["deterministicChecks"][event["check"]]
    patterns = config["allowedPaths"]
    outside = [
        path for path in event["enforcement"]["affectedPaths"]
        if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
    ]
    if outside:
        raise ContractError(f"deterministic enforcement changes paths outside policy: {', '.join(outside)}")


def required_next_action(classification: str, disposition: str) -> str:
    if classification == "deterministic":
        return "trial-script-and-tests"
    if disposition in {"script-created", "script-updated"}:
        return "review-semantic-change-and-trial-script"
    if disposition == "skill-updated":
        return "review-authoritative-skill-update"
    return "review-nondeterminism-evidence"


def state_root(environment: dict[str, str]) -> Path:
    explicit = environment.get("SKILL_EVOLUTION_STATE_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    xdg = environment.get("XDG_STATE_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "state"
    return (base / "skill-evolution").resolve()


def write_new_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def ingest(event_path: Path, policy_path: Path, apply: bool, environment: dict[str, str]) -> dict[str, Any]:
    event = normalize_event(load_object(event_path))
    policy = load_object(policy_path)
    validate_policy(policy)
    classification, reason = classify(event, policy)
    validate_enforcement_classification(event, classification)
    validate_enforcement_policy(event, policy, classification)
    identifier = candidate_id(event)
    root = state_root(environment)
    candidate_path = root / "candidates" / f"{identifier}.json"
    status = "pending-trial" if classification == "deterministic" else "pending-approval"
    if event["target"]["sourceKind"] in {"third-party-restricted", "unknown"}:
        status = "blocked"
        reason = "publication blocked by source ownership or license"
    candidate = {
        "schema": "skill-evolution.candidate.v1",
        "id": identifier,
        "event": event,
        "classification": classification,
        "classificationReason": reason,
        "enforcementDisposition": event["enforcement"]["disposition"],
        "requiredNextAction": required_next_action(classification, event["enforcement"]["disposition"]),
        "status": status,
        "autoPromoteEligible": bool(classification == "deterministic" and policy.get("autoPromote") is True),
    }
    if candidate_path.exists():
        candidate["deduplicated"] = True
        return candidate
    if apply:
        write_new_json(candidate_path, candidate)
    candidate["deduplicated"] = False
    candidate["dryRun"] = not apply
    return candidate


def list_status(environment: dict[str, str]) -> list[dict[str, Any]]:
    directory = state_root(environment) / "candidates"
    if not directory.exists():
        return []
    return [load_object(path) for path in sorted(directory.glob("*.json")) if not path.is_symlink()]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser("ingest")
    ingest_parser.add_argument("--event", type=Path, required=True)
    ingest_parser.add_argument("--policy", type=Path, required=True)
    mode = ingest_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    commands.add_parser("status")
    return root


def main() -> int:
    arguments = parser().parse_args()
    try:
        result = ingest(arguments.event, arguments.policy, arguments.apply, dict(os.environ)) if arguments.command == "ingest" else list_status(dict(os.environ))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ContractError, json.JSONDecodeError, OSError) as error:
        print(f"skill-evolution: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
