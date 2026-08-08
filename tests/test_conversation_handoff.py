import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "skills" / "conversation-handoff" / "scripts" / "handoff.py"
SPEC = importlib.util.spec_from_file_location("conversation_handoff", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class HandoffTest(unittest.TestCase):
    def test_scaffold_requires_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.md"
            path.write_text(MODULE.scaffold("Continue safely", Path(directory)), encoding="utf-8")
            self.assertIn("unresolved placeholder: State", MODULE.validate(path))

    def test_completed_handoff_passes(self):
        content = MODULE.scaffold("Continue safely", Path.cwd())
        replacements = {
            "[TODO: current state and evidence]": "checked with git status",
            "[TODO: authoritative artifacts]": "docs/plan.md is authoritative",
            "[TODO: remaining assumptions or none]": "none",
            "[TODO: decision, rationale, and rejected option if still relevant]": "keep validation local",
            "[TODO: owner, blocker or approval gate, and resume condition]": "agent owns local checks; no blocker",
            "[TODO: one concrete action valid without crossing a remaining gate]": "run the validator",
            "[TODO: path or URL; purpose]": "docs/plan.md; plan",
            "[TODO: installed skills or bounded catalogue searches worth using]": "conversation-handoff",
        }
        for source, target in replacements.items():
            content = content.replace(source, target)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.md"
            path.write_text(content, encoding="utf-8")
            self.assertEqual([], MODULE.validate(path))

    def test_secret_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.md"
            path.write_text(MODULE.scaffold("token=supersecretvalue1234567890", Path(directory)), encoding="utf-8")
            self.assertIn("potential secret detected", MODULE.validate(path))


if __name__ == "__main__":
    unittest.main()
