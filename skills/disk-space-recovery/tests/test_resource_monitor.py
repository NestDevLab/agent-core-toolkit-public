"""Pressure, coverage, counter reset and bounded-state regression checks."""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('resource_monitor', SCRIPTS / 'resource_monitor.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def config():
    return {'disks': [{'path': '/', 'warningGiB': 30, 'criticalGiB': 10, 'warningPercent': 15, 'criticalPercent': 5}],
            'memory': {'warning': 10, 'critical': 5},
            'cpu': {'warning': 85, 'critical': 95, 'consecutiveSamples': 3},
            'growthGiBPerHour': 2}


def sample():
    return {'at': 100000, 'monotonic': 1000, 'boot': 'a', 'errors': [],
            'memory': {'total': 100, 'available': 20}, 'cpu': {'total': 100, 'idle': 50},
            'disks': [{'path': '/', 'total': 100 * m.GIB, 'available': 40 * m.GIB, 'inodeAvailablePercent': 50}]}


class MonitorTests(unittest.TestCase):
    def test_threshold_validation_refuses_inverted_or_nonfinite_limits(self):
        self.assertEqual(m.validate(config()), config())
        for key, value in [('memory', {'warning': 10, 'critical': 20}),
                           ('cpu', {'warning': float('nan'), 'critical': 95, 'consecutiveSamples': 3})]:
            bad = config(); bad[key] = value
            with self.assertRaises(ValueError): m.validate(bad)
        bad = config(); bad['disks'][0]['criticalGiB'] = 40
        with self.assertRaises(ValueError): m.validate(bad)

    def test_bytes_percent_and_inode_thresholds_are_independent(self):
        for change in [{'available': 8 * m.GIB}, {'total': 1000 * m.GIB}, {'inodeAvailablePercent': 1}]:
            current = sample(); current['disks'][0].update(change)
            report, _ = m.assess(config(), current, {})
            self.assertEqual(report['checks']['disk:/']['status'], 'critical')

    def test_memavailable_not_memfree_and_guest_cpu_not_double_counted(self):
        with tempfile.TemporaryDirectory() as root:
            proc = Path(root); (proc / 'sys/kernel/random').mkdir(parents=True)
            (proc / 'meminfo').write_text('MemTotal: 100 kB\nMemFree: 1 kB\nMemAvailable: 20 kB\n')
            (proc / 'stat').write_text('cpu 10 0 10 80 0 0 0 0 8 0\n')
            (proc / 'sys/kernel/random/boot_id').write_text('a')
            observed = m.collect(config(), proc)
            self.assertEqual(observed['memory']['available'], 20 * 1024)
            self.assertEqual(observed['cpu'], {'total': 100, 'idle': 80})

    def test_cpu_requires_sustained_samples_and_resets_on_boot_or_stale_sample(self):
        current = sample(); state = {}
        report, state = m.assess(config(), current, state)
        self.assertEqual(report['checks']['cpu']['status'], 'warming')
        for i in range(1, 4):
            current = copy.deepcopy(current); current['at'] += 60; current['monotonic'] += 60
            current['cpu']['total'] += 100
            report, state = m.assess(config(), current, state)
            self.assertEqual(report['checks']['cpu']['status'], 'critical' if i == 3 else 'ok')
        current['boot'] = 'b'
        report, state = m.assess(config(), current, state)
        self.assertEqual(report['checks']['cpu']['status'], 'warming')
        current['monotonic'] += 4000
        report, _ = m.assess(config(), current, state)
        self.assertEqual(report['checks']['cpu']['status'], 'warming')

    def test_disk_growth_and_resize_baselines(self):
        current = sample()
        old = {'at': current['at'] - 1800, 'disks': {'/': {'total': 100 * m.GIB, 'available': 42 * m.GIB}}}
        report, _ = m.assess(config(), current, {'history': [old]})
        self.assertEqual(report['checks']['disk:/']['status'], 'warning')
        self.assertEqual(report['checks']['disk:/']['growthGiBPerHour'], 4)
        old['disks']['/']['total'] = 90 * m.GIB
        report, _ = m.assess(config(), current, {'history': [old]})
        self.assertNotIn('growthGiBPerHour', report['checks']['disk:/'])

    def test_unknown_health_is_never_reported_as_healthy(self):
        self.assertEqual(m.smart_health(None, 100)['status'], 'unknown')
        with tempfile.TemporaryDirectory() as root:
            p = Path(root) / 'health.json'
            cfg = {'evidenceFile': str(p), 'expectedIdentity': 'physical-host', 'maxAgeSeconds': 3600}
            row = {'identity': 'physical-host', 'observedAt': dt.datetime.fromtimestamp(10000, dt.timezone.utc).isoformat(), 'disks': [{'device': 'physical-disk', 'status': 'passed'}]}
            p.write_text(json.dumps(row))
            self.assertEqual(m.smart_health(cfg, 10001)['status'], 'ok')
            self.assertEqual(m.smart_health(cfg, 14000)['status'], 'unknown')
            row['identity'] = 'virtual-guest'; p.write_text(json.dumps(row))
            self.assertEqual(m.smart_health(cfg, 10001)['status'], 'unknown')
            row['identity'] = 'physical-host'; row['disks'][0]['status'] = 'failed'; p.write_text(json.dumps(row))
            self.assertEqual(m.smart_health(cfg, 10001)['status'], 'critical')

    def test_history_is_bounded_and_unchanged_states_do_not_repeat_transitions(self):
        current = sample()
        report, state = m.assess(config(), current, {})
        self.assertTrue(report['transitions'])
        state['history'] = state['history'] * 400
        report, state = m.assess(config(), current, state)
        self.assertEqual(len(state['history']), 288)
        self.assertEqual(report['transitions'], [])

    def test_state_refuses_checkout_and_symlinks_without_altering_target(self):
        with self.assertRaises(ValueError): m.state_path(str(SCRIPTS / 'state.json'))
        with tempfile.TemporaryDirectory() as root:
            p = Path(root); target = p / 'target'; target.write_text('preserve'); target.chmod(0o600)
            link = p / 'alias'; link.symlink_to(target)
            with self.assertRaises(ValueError): m.state_path(str(link))
            self.assertEqual(target.read_text(), 'preserve')
            output = m.state_path(str(p / 'new.json')); m.atomic(output, {'one': 1})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(output.read_text()), {'one': 1})


if __name__ == '__main__':
    unittest.main()
