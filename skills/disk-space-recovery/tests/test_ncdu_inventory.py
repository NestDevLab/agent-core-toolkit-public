import importlib.util
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('ncdu_inventory', Path(__file__).parents[1] / 'scripts/ncdu_inventory.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from ncdu_stream import summary as stream_summary


class InventoryTests(unittest.TestCase):
    def test_configured_state_cannot_bypass_source_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'source'
            repo.mkdir()
            (repo / '.git').mkdir()
            state = repo / 'state'
            state.mkdir()
            with patch.dict(MODULE.os.environ, {'XDG_STATE_HOME': str(state)}):
                with self.assertRaises(ValueError):
                    MODULE.outside_checkout(state / 'audit.gz')

    def test_streaming_reader_rejects_truncation(self):
        with self.assertRaises(ValueError):
            stream_summary(io.StringIO('[1,2,{},[{\"name\":\"/\"}]'))
        with self.assertRaises(ValueError):
            stream_summary(io.StringIO('[1,2,{},[{\"name\":'))

    def test_streaming_reader_matches_fixture_totals(self):
        tree = [1, 2, {}, [{'name': '/', 'dev': 1}, {'name': 'a', 'dsize': 100}, [{'name': 'nested'}, {'name': 'b', 'dsize': 50}]]]
        self.assertEqual(stream_summary(io.StringIO(json.dumps(tree)))['allocatedBytes'], 150)

    def test_hardlinks_inherit_directory_device(self):
        tree = [1, 2, {}, [{'name': '/', 'dev': 5, 'dsize': 4},
                {'name': 'a', 'dsize': 10, 'hlnkc': True, 'ino': 7},
                [{'name': 'child', 'dsize': 4},
                 {'name': 'b', 'dsize': 10, 'hlnkc': True, 'ino': 7}]]]
        self.assertEqual(MODULE.summarize(tree)['allocatedBytes'], 18)

    def test_incomplete_inventory_is_not_clean(self):
        tree = [1, 2, {}, [{'name': '/'}, {'name': 'denied', 'read_error': True}]]
        self.assertEqual(MODULE.summarize(tree)['status'], 'incomplete')

    def test_lane_reports_hidden_database_and_never_follows_links(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as external:
            root = Path(tmp)
            (root / 'hash-named-backup').write_bytes(b'SQLite format 3\x00payload')
            (root / 'node_modules').mkdir()
            (root / 'node_modules' / 'payload.js').write_text('module.exports = 1;')
            (root / 'external').symlink_to(external, target_is_directory=True)
            (root / 'main.py').write_text('print(1)')
            (root / 'backup.tar').write_bytes(b'archive')
            result = MODULE.lane_payloads(root)
            self.assertEqual({r['kind'] for r in result['findings']},
                             {'sqlite-header', 'generated-payload', 'symlink-review', 'archive-review'})
            self.assertEqual((root / 'hash-named-backup').read_bytes(), b'SQLite format 3\x00payload')

    def test_empty_generated_placeholders_are_not_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'dist').mkdir()
            (root / 'dist' / '.gitkeep').touch()
            self.assertEqual(MODULE.lane_payloads(root)['status'], 'clean')
            (root / 'dist' / 'bundle.js').write_text('compiled')
            self.assertEqual(MODULE.lane_payloads(root)['status'], 'violations')

    def test_reports_cannot_live_in_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.git').write_text('gitdir: somewhere')
            with self.assertRaises(ValueError):
                MODULE.outside_checkout(root / 'result.json.gz')

    def test_failed_scan_retains_partial_without_success_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'audit.json.gz'
            with patch.object(MODULE.subprocess, 'run') as run:
                run.return_value.returncode = 1
                with self.assertRaises(RuntimeError):
                    MODULE.scan(tmp, output, 1)
            self.assertFalse(output.exists())
            self.assertEqual(len(list(Path(tmp).glob('*.partial'))), 1)

    def test_explicit_state_below_dotfiles_repo_allows_only_external_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.git').mkdir()
            state = root / 'state'
            state.mkdir()
            with patch.dict(MODULE.os.environ, {'XDG_STATE_HOME': str(state)}), patch.object(MODULE.Path, 'home', return_value=root):
                self.assertEqual(MODULE.outside_checkout(state / 'audit.gz'), state / 'audit.gz')
                nested = state / 'checkout'
                nested.mkdir()
                (nested / '.git').write_text('gitdir: elsewhere')
                with self.assertRaises(ValueError):
                    MODULE.outside_checkout(nested / 'audit.gz')


if __name__ == '__main__':
    unittest.main()
