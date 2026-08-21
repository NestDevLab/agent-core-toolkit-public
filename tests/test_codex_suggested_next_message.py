import importlib.util
import json
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "skills"
    / "codex-suggested-next-message"
    / "scripts"
    / "suggest_next_message.py"
)
HOOK_CONFIG = Path(__file__).parents[1] / "hooks" / "codex-suggested-next-message.json"
SPEC = importlib.util.spec_from_file_location("codex_suggested_next_message", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class SuggestedNextMessageTest(unittest.TestCase):
    def test_disabled_hook_does_not_invoke_luna(self):
        invoked = False

        def invoke(*_args):
            nonlocal invoked
            invoked = True
            return "Proceed with the requested change."

        output = MODULE.run_hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "Update the documentation."},
            {},
            invoke,
        )

        self.assertIsNone(output)
        self.assertFalse(invoked)

    def test_hook_appends_copyable_box_through_additional_context(self):
        output = MODULE.run_hook(
            {"hook_event_name": "UserPromptSubmit", "prompt": "Update the documentation."},
            {MODULE.ENABLE_ENV: "1", MODULE.CONTEXT_ENV: "A documentation-only task."},
            lambda *_args: "Please make the documentation change and show the diff.",
        )

        self.assertIsNotNone(output)
        self.assertEqual("UserPromptSubmit", output["hookSpecificOutput"]["hookEventName"])
        additional_context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("### Suggested next message", additional_context)
        self.assertIn("```text\nPlease make the documentation change and show the diff.\n```", additional_context)
        self.assertIn("At the very end", additional_context)
        self.assertIn("untrusted display text", additional_context)

    def test_recursive_child_and_non_user_events_are_ignored(self):
        invoke = lambda *_args: "This must not be emitted."
        payload = {"hook_event_name": "UserPromptSubmit", "prompt": "Any task"}

        self.assertIsNone(MODULE.run_hook(payload, {MODULE.ENABLE_ENV: "1", MODULE.ACTIVE_ENV: "1"}, invoke))
        self.assertIsNone(MODULE.run_hook({"hook_event_name": "Stop", "prompt": "Any task"}, {MODULE.ENABLE_ENV: "1"}, invoke))

    def test_unsafe_or_oversized_model_output_is_rejected(self):
        self.assertIsNone(MODULE.normalize_suggestion("```text\nunsafe\n```"))
        self.assertIsNone(MODULE.normalize_suggestion("x" * (MODULE.MAX_SUGGESTION_CHARS + 1)))
        self.assertEqual("Ask for the validation results.", MODULE.normalize_suggestion(" Ask for the validation results. "))

    def test_child_is_ephemeral_and_read_only(self):
        command = MODULE.child_command(Path("/tmp/output.txt"), "/tmp/empty")

        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("gpt-5.6-luna", command)
        self.assertIn('model_reasoning_effort="low"', command)
        self.assertIn("read-only", command)

    def test_child_environment_excludes_unrelated_values(self):
        environment = {
            "PATH": "/usr/bin",
            "HOME": "/home/example",
            "CODEX_HOME": "/home/example/.codex",
            "OPENAI_API_KEY": "must-not-be-forwarded",
            MODULE.CONTEXT_ENV: "must-not-be-forwarded",
        }

        child = MODULE.child_environment(environment)

        self.assertEqual(child["PATH"], "/usr/bin")
        self.assertEqual(child["HOME"], "/home/example")
        self.assertEqual(child[MODULE.ACTIVE_ENV], "1")
        self.assertNotIn("OPENAI_API_KEY", child)
        self.assertNotIn(MODULE.CONTEXT_ENV, child)

    def test_hook_does_not_automatically_execute_a_project_controlled_script(self):
        config = json.loads(HOOK_CONFIG.read_text(encoding="utf-8"))
        command = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]

        self.assertIn("CODEX_SUGGESTED_NEXT_MESSAGE_COMMAND", command)
        self.assertIn("${HOME}/.agents/skills", command)
        self.assertNotIn("${PWD}", command)


if __name__ == "__main__":
    unittest.main()
