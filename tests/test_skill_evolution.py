import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills" / "skill-evolution" / "scripts" / "skill_evolution.py"
OBSERVER_SCRIPT = Path(__file__).parents[1] / "skills" / "skill-evolution" / "scripts" / "observe_hook.py"
SCOPE_SCRIPT = Path(__file__).parents[1] / "skills" / "skill-evolution" / "scripts" / "check_runtime_scope.py"
SPEC = importlib.util.spec_from_file_location("skill_evolution", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)
OBSERVER_SPEC = importlib.util.spec_from_file_location("skill_evolution_observer", OBSERVER_SCRIPT)
OBSERVER = importlib.util.module_from_spec(OBSERVER_SPEC)
assert OBSERVER_SPEC.loader
OBSERVER_SPEC.loader.exec_module(OBSERVER)
SCOPE_SPEC = importlib.util.spec_from_file_location("skill_evolution_scope", SCOPE_SCRIPT)
SCOPE = importlib.util.module_from_spec(SCOPE_SPEC)
assert SCOPE_SPEC.loader
SCOPE_SPEC.loader.exec_module(SCOPE)


class SkillEvolutionTest(unittest.TestCase):
    def event(self):
        return {
            "schema": MODULE.SCHEMA,
            "signalKind": "deterministic-improvement",
            "target": {
                "sourceKind": "owned",
                "source": "github:example/toolkit",
                "revision": "abc123",
                "artifact": "skills/demo/SKILL.md",
            },
            "baseHash": "sha256:base",
            "check": "format-json",
            "evidenceFingerprint": "sha256:evidence",
            "summary": "Formatter produced a stable correction.",
            "enforcement": {
                "disposition": "script-created",
                "affectedPaths": ["skills/demo/SKILL.md", "scripts/fix_demo.py", "tests/test_fix_demo.py"],
                "scriptPaths": ["scripts/fix_demo.py"],
                "testPaths": ["tests/test_fix_demo.py"],
                "idempotence": {
                    "firstRunHash": "sha256:stable",
                    "secondRunHash": "sha256:stable",
                    "secondRunChanged": False,
                },
            },
        }

    def policy(self, auto=False):
        return {
            "schemaVersion": 1,
            "autoPromote": auto,
            "constitutionalPaths": ["skills/skill-evolution/**", "hooks/**"],
            "deterministicChecks": {
                "format-json": {
                    "allowedPaths": ["skills/demo/**", "scripts/**", "tests/**"],
                    "transformer": "scripts/fix_demo.py",
                    "checks": ["python3 -m unittest tests.test_fix_demo"],
                }
            },
        }

    def write_json(self, root, name, value):
        path = Path(root) / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_dry_run_is_deterministic_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as root:
            event = self.write_json(root, "event.json", self.event())
            policy = self.write_json(root, "policy.json", self.policy(True))
            environment = {"SKILL_EVOLUTION_STATE_DIR": str(Path(root) / "state")}
            first = MODULE.ingest(event, policy, False, environment)
            second = MODULE.ingest(event, policy, False, environment)
            self.assertEqual(first["id"], second["id"])
            self.assertEqual("deterministic", first["classification"])
            self.assertEqual("script-created", first["enforcementDisposition"])
            self.assertEqual("trial-script-and-tests", first["requiredNextAction"])
            self.assertTrue(first["autoPromoteEligible"])
            self.assertFalse((Path(root) / "state").exists())

    def test_apply_persists_once_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as root:
            event = self.write_json(root, "event.json", self.event())
            policy = self.write_json(root, "policy.json", self.policy())
            environment = {"SKILL_EVOLUTION_STATE_DIR": str(Path(root) / "state")}
            first = MODULE.ingest(event, policy, True, environment)
            second = MODULE.ingest(event, policy, True, environment)
            self.assertFalse(first["deduplicated"])
            self.assertTrue(second["deduplicated"])
            self.assertEqual(1, len(MODULE.list_status(environment)))

    def test_constitutional_and_unknown_sources_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            value = self.event()
            value["target"]["artifact"] = "skills/skill-evolution/SKILL.md"
            value["target"]["sourceKind"] = "unknown"
            event = self.write_json(root, "event.json", value)
            policy = self.write_json(root, "policy.json", self.policy(True))
            result = MODULE.ingest(event, policy, False, {"SKILL_EVOLUTION_STATE_DIR": str(Path(root) / "state")})
            self.assertEqual("semantic", result["classification"])
            self.assertEqual("blocked", result["status"])
            self.assertFalse(result["autoPromoteEligible"])

    def test_secret_shaped_evidence_is_rejected(self):
        value = self.event()
        value["apiToken"] = "do-not-store"
        with self.assertRaises(MODULE.ContractError):
            MODULE.normalize_event(value)

    def test_deterministic_candidate_without_script_enforcement_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            value = self.event()
            value["enforcement"] = {
                "disposition": "skill-updated",
                "affectedPaths": ["skills/demo/SKILL.md"],
            }
            event = self.write_json(root, "event.json", value)
            policy = self.write_json(root, "policy.json", self.policy())
            with self.assertRaisesRegex(MODULE.ContractError, "deterministic candidates require"):
                MODULE.ingest(event, policy, False, {"SKILL_EVOLUTION_STATE_DIR": str(Path(root) / "state")})

    def test_second_run_change_is_rejected(self):
        value = self.event()
        value["enforcement"]["idempotence"]["secondRunHash"] = "sha256:changed"
        value["enforcement"]["idempotence"]["secondRunChanged"] = True
        with self.assertRaisesRegex(MODULE.ContractError, "second-run idempotence"):
            MODULE.normalize_event(value)

    def test_semantic_skill_update_has_review_action(self):
        with tempfile.TemporaryDirectory() as root:
            value = self.event()
            value["signalKind"] = "activation-gap"
            value["enforcement"] = {
                "disposition": "skill-updated",
                "affectedPaths": ["skills/demo/SKILL.md"],
            }
            event = self.write_json(root, "event.json", value)
            policy = self.write_json(root, "policy.json", self.policy())
            result = MODULE.ingest(event, policy, False, {"SKILL_EVOLUTION_STATE_DIR": str(Path(root) / "state")})
            self.assertEqual("semantic", result["classification"])
            self.assertEqual("skill-updated", result["enforcementDisposition"])
            self.assertEqual("review-authoritative-skill-update", result["requiredNextAction"])

    def test_nondeterministic_requires_concrete_evidence(self):
        value = self.event()
        value["enforcement"] = {
            "disposition": "nondeterministic",
            "affectedPaths": ["skills/demo/SKILL.md"],
        }
        with self.assertRaisesRegex(MODULE.ContractError, "nondeterminismEvidence"):
            MODULE.normalize_event(value)

    def test_paths_must_be_relative_and_bounded(self):
        value = self.event()
        value["enforcement"]["scriptPaths"] = ["../outside.py"]
        with self.assertRaisesRegex(MODULE.ContractError, "relative path"):
            MODULE.normalize_event(value)

    def test_deterministic_paths_outside_policy_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            value = self.event()
            value["enforcement"]["affectedPaths"].append("unrelated/file.md")
            event = self.write_json(root, "event.json", value)
            policy = self.write_json(root, "policy.json", self.policy())
            with self.assertRaisesRegex(MODULE.ContractError, "outside policy"):
                MODULE.ingest(event, policy, False, {"SKILL_EVOLUTION_STATE_DIR": str(Path(root) / "state")})

    def test_hook_is_opt_in_fail_open_and_stores_only_fingerprints(self):
        with tempfile.TemporaryDirectory() as root:
            payload = {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": "private output", "cwd": "/private/repo"}
            self.assertIsNone(OBSERVER.observe(payload, {"SKILL_EVOLUTION_STATE_DIR": root}))
            path = OBSERVER.observe(payload, {
                "SKILL_EVOLUTION_STATE_DIR": root,
                "SKILL_EVOLUTION_HOOKS_ENABLED": "1",
                "SKILL_EVOLUTION_HARNESS": "claude",
            })
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("private output", json.dumps(stored))
            self.assertNotIn("/private/repo", json.dumps(stored))
            self.assertEqual("claude", stored["harness"])

    def test_runtime_scope_covers_every_future_skill_and_rejects_openclaw_or_hermes(self):
        manifest = Path(__file__).parents[1] / "openpack.json"
        self.assertEqual(2, SCOPE.validate_manifest(manifest))

        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["compositionRules"][0]["runtimes"].append("openclaw")
        with tempfile.TemporaryDirectory() as root:
            invalid = self.write_json(root, "openpack.json", value)
            with self.assertRaisesRegex(SCOPE.ScopeError, "must target only"):
                SCOPE.validate_manifest(invalid)


if __name__ == "__main__":
    unittest.main()
