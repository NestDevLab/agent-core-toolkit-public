import importlib.util
import stat
import subprocess
import sys
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

    def completed_handoff(self, workspace):
        content = MODULE.scaffold("Continue safely", workspace)
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
        return content

    def test_completed_handoff_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.md"
            path.write_text(self.completed_handoff(Path(directory)), encoding="utf-8")
            self.assertEqual([], MODULE.validate(path))

    def test_launch_fingerprint_rejects_changed_or_unfinished_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            path = workspace / "handoff.md"
            path.write_text(MODULE.scaffold("Continue safely", workspace), encoding="utf-8")
            command = [sys.executable, str(SCRIPT), "fingerprint", str(path)]
            unfinished = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(unfinished.returncode, 0)
            self.assertIn("unresolved placeholder", unfinished.stdout)

            content = self.completed_handoff(workspace)
            path.write_text(content, encoding="utf-8")
            fingerprint = subprocess.check_output(command, text=True).strip()
            self.assertRegex(fingerprint, r"^[0-9a-f]{64}$")
            self.assertEqual([], MODULE.check(path, workspace, fingerprint))
            path.write_text(content + "\nNew note.\n", encoding="utf-8")
            received = subprocess.run(
                [sys.executable, str(SCRIPT), "check", str(path), "--sha256", fingerprint],
                cwd=workspace, text=True, capture_output=True,
            )
            self.assertNotEqual(received.returncode, 0)
            self.assertIn("handoff fingerprint mismatch", received.stdout)

    def test_named_output_is_private_and_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.md"
            command = [sys.executable, str(SCRIPT), "create", "--goal", "Continue safely", "--output", str(path)]
            subprocess.run(command, check=True, capture_output=True, umask=0o022)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            original = path.read_bytes()
            repeated = subprocess.run(command, capture_output=True)
            self.assertEqual(repeated.returncode, 2)
            self.assertEqual(path.read_bytes(), original)

    def test_secret_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "handoff.md"
            path.write_text(MODULE.scaffold("token=supersecretvalue1234567890", Path(directory)), encoding="utf-8")
            self.assertIn("potential secret detected", MODULE.validate(path))


if __name__ == "__main__":
    unittest.main()
