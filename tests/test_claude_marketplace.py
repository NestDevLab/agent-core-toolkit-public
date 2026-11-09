import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"


class ClaudeMarketplaceTest(unittest.TestCase):
    # `claude plugin validate` still passes when a listed skill directory is gone.
    def test_listed_skills_exist(self):
        plugins = json.loads(MARKETPLACE.read_text())["plugins"]
        for plugin in plugins:
            self.assertTrue(plugin["skills"], plugin["name"])
            for skill in plugin["skills"]:
                skill_file = ROOT / skill / "SKILL.md"
                self.assertTrue(skill_file.is_file(), skill)
                self.assertIn(f"name: {Path(skill).name}\n", skill_file.read_text())


if __name__ == "__main__":
    unittest.main()
