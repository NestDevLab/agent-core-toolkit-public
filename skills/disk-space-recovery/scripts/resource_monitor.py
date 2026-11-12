#!/usr/bin/env python3
"""Cheap local Linux pressure observations; no cleanup, scans, or service changes."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time

from ncdu_inventory import outside_checkout

GIB = 1024 ** 3
LEVEL = {'ok': 0, 'warming': 1, 'unknown': 1, 'warning': 2, 'critical': 3}


def load_json(path, limit=1024 * 1024):
    with Path(path).open('rb') as handle:
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('JSON input exceeds size bound')
    return json.loads(raw)


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Invalid numeric threshold')
    return value


def validate(config):
    if set(config) - {'disks', 'memory', 'cpu', 'growthGiBPerHour', 'smart'}:
        raise ValueError('Unknown monitor configuration field')
    disks = config.get('disks', [])
    if not isinstance(disks, list) or not 1 <= len(disks) <= 16:
        raise ValueError('Declare one to sixteen filesystem paths')
    for disk in disks:
        if set(disk) != {'path', 'warningGiB', 'criticalGiB', 'warningPercent', 'criticalPercent'} or not isinstance(disk['path'], str) or not Path(disk['path']).is_absolute():
            raise ValueError('Invalid filesystem configuration')
        for suffix, maximum in [('GiB', 1000000), ('Percent', 100)]:
            critical = number(disk['critical' + suffix], 0, maximum)
            number(disk['warning' + suffix], critical, maximum)
    if len({d['path'] for d in disks}) != len(disks):
        raise ValueError('Duplicate filesystem path')
    for key in ['memory', 'cpu']:
        values = config[key]
        expected = {'warning', 'critical'} | ({'consecutiveSamples'} if key == 'cpu' else set())
        if set(values) != expected:
            raise ValueError('Invalid ' + key + ' thresholds')
        warning = number(values['warning'], 0, 100)
        critical = number(values['critical'], 0, 100)
        if (key == 'memory' and critical > warning) or (key == 'cpu' and critical < warning):
            raise ValueError('Threshold order is inverted')
    count = config['cpu']['consecutiveSamples']
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 60:
        raise ValueError('Invalid CPU observation count')
    number(config.get('growthGiBPerHour', 2), 0.01, 1000000)
    smart = config.get('smart')
    if smart is not None:
        if set(smart) != {'evidenceFile', 'expectedIdentity', 'maxAgeSeconds'} or not isinstance(smart['evidenceFile'], str) or not Path(smart['evidenceFile']).is_absolute() or not isinstance(smart['expectedIdentity'], str) or not 1 <= len(smart['expectedIdentity']) <= 128:
            raise ValueError('Invalid physical-host evidence binding')
        number(smart['maxAgeSeconds'], 60, 604800)
    return config


def cpu_counters(proc):
    fields = (proc / 'stat').read_text().splitlines()[0].split()
    if fields[0] != 'cpu' or len(fields) < 9:
        raise ValueError('CPU counters unavailable')
    # guest/guest_nice are already included in user/nice; do not count twice.
    values = list(map(int, fields[1:9]))
    return {'total': sum(values), 'idle': values[3] + values[4]}


def collect(config, proc=Path('/proc')):
    sample = {'at': time.time(), 'monotonic': time.monotonic(), 'disks': [], 'errors': []}
    for disk in config['disks']:
        try:
            usage = os.statvfs(disk['path'])
            total = usage.f_blocks * usage.f_frsize
            if total <= 0:
                raise ValueError('Filesystem has no measurable capacity')
            sample['disks'].append({'path': disk['path'], 'total': total,
                                    'available': usage.f_bavail * usage.f_frsize,
                                    'inodeAvailablePercent': 100 * usage.f_favail / usage.f_files if usage.f_files else None})
        except (OSError, ValueError) as exc:
            sample['disks'].append({'path': disk['path'], 'error': type(exc).__name__})
    try:
        memory = {}
        for line in (proc / 'meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            memory[key] = int(value.split()[0]) * 1024
        if memory['MemTotal'] <= 0 or not 0 <= memory['MemAvailable'] <= memory['MemTotal']:
            raise ValueError('Invalid memory counters')
        sample['memory'] = {'total': memory['MemTotal'], 'available': memory['MemAvailable']}
    except (OSError, KeyError, ValueError) as exc:
        sample['errors'].append('memory: ' + type(exc).__name__)
    try:
        sample['cpu'] = cpu_counters(proc)
        sample['boot'] = (proc / 'sys/kernel/random/boot_id').read_text().strip()
    except (OSError, ValueError) as exc:
        sample['errors'].append('cpu: ' + type(exc).__name__)
    return sample


def smart_health(config, now):
    """Consume fresh identity-bound physical-host evidence; never infer from a VM."""
    if not config:
        return {'status': 'unknown', 'reason': 'Physical-host SMART evidence is not configured'}
    try:
        evidence = load_json(config['evidenceFile'], 65536)
        timestamp = dt.datetime.fromisoformat(evidence['observedAt'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            raise ValueError('Timestamp must include timezone')
        age = now - timestamp.timestamp()
        if evidence['identity'] != config['expectedIdentity'] or not 0 <= age <= config['maxAgeSeconds']:
            raise ValueError('Physical-host identity mismatch or stale evidence')
        disks = evidence['disks']
        if not isinstance(disks, list) or not 1 <= len(disks) <= 32:
            raise ValueError('Physical disk inventory is empty or too large')
        statuses = [d['status'] for d in disks]
        if not all(s in {'passed', 'failed', 'warning', 'unknown'} for s in statuses):
            raise ValueError('Unknown physical disk status')
        status = 'critical' if 'failed' in statuses else 'warning' if 'warning' in statuses else 'unknown' if 'unknown' in statuses else 'ok'
        return {'status': status, 'ageSeconds': round(age), 'identity': evidence['identity'], 'disks': disks}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {'status': 'unknown', 'reason': str(exc)[:256]}


def low_level(value, warning, critical):
    return 'critical' if value <= critical else 'warning' if value <= warning else 'ok'


def assess(config, sample, previous):
    checks, counts = {}, {}
    old = previous.get('last', {})
    elapsed = sample['monotonic'] - old.get('monotonic', sample['monotonic'])
    comparable = old.get('boot') == sample.get('boot') and 1 <= elapsed <= 3600 and bool(sample.get('boot'))
    history = previous.get('history', [])[-287:]
    for disk, usage in zip(config['disks'], sample['disks']):
        key = 'disk:' + disk['path']
        if 'error' in usage:
            checks[key] = {'status': 'unknown', 'reason': usage['error']}
            continue
        free = usage['available']
        percent = 100 * free / usage['total']
        status = max([low_level(free / GIB, disk['warningGiB'], disk['criticalGiB']),
                      low_level(percent, disk['warningPercent'], disk['criticalPercent'])], key=LEVEL.get)
        inode = usage['inodeAvailablePercent']
        if inode is not None:
            status = max(status, low_level(inode, disk['warningPercent'], disk['criticalPercent']), key=LEVEL.get)
        checks[key] = {'status': status, 'availableBytes': free, 'availablePercent': round(percent, 2), 'inodeAvailablePercent': inode}
        # At least thirty minutes; ignore capacity changes and backwards wall clocks.
        baseline = next((row for row in reversed(history) if 1800 <= sample['at'] - row['at'] <= 86400 and row.get('disks', {}).get(disk['path'], {}).get('total') == usage['total']), None)
        if baseline:
            rate = (baseline['disks'][disk['path']]['available'] - free) * 3600 / (sample['at'] - baseline['at']) / GIB
            checks[key]['growthGiBPerHour'] = round(rate, 3)
            if rate >= config.get('growthGiBPerHour', 2):
                checks[key]['status'] = max(checks[key]['status'], 'warning', key=LEVEL.get)
    memory = sample.get('memory')
    if memory:
        available = 100 * memory['available'] / memory['total']
        checks['memory'] = {'status': low_level(available, config['memory']['warning'], config['memory']['critical']), 'availablePercent': round(available, 2), 'availableBytes': memory['available'], 'scope': 'local /proc view; confirm container counter virtualization'}
    else:
        checks['memory'] = {'status': 'unknown', 'reason': 'Memory counters unavailable'}
    checks['cpu'] = {'status': 'warming' if sample.get('cpu') else 'unknown'}
    if comparable and sample.get('cpu') and old.get('cpu'):
        total = sample['cpu']['total'] - old['cpu']['total']
        idle = sample['cpu']['idle'] - old['cpu']['idle']
        if total > 0 and 0 <= idle <= total:
            busy = 100 * (total - idle) / total
            for level in ['warning', 'critical']:
                counts[level] = previous.get('cpuCounts', {}).get(level, 0) + 1 if busy >= config['cpu'][level] else 0
            checks['cpu'] = {'status': 'critical' if counts['critical'] >= config['cpu']['consecutiveSamples'] else 'warning' if counts['warning'] >= config['cpu']['consecutiveSamples'] else 'ok', 'busyPercent': round(busy, 2), 'sustainedSamples': counts}
    checks['smart'] = smart_health(config.get('smart'), sample['at'])
    statuses = {key: value['status'] for key, value in checks.items()}
    transitions = [{'check': key, 'before': previous.get('statuses', {}).get(key), 'after': value} for key, value in statuses.items() if previous.get('statuses', {}).get(key) != value]
    history.append({'at': sample['at'], 'disks': {d['path']: {k: d[k] for k in ['total', 'available']} for d in sample['disks'] if 'error' not in d}})
    state = {'schema': 1, 'last': sample, 'cpuCounts': counts, 'statuses': statuses, 'history': history}
    report = {'schema': 1, 'observedAt': dt.datetime.fromtimestamp(sample['at'], dt.timezone.utc).isoformat(), 'status': max(statuses.values(), key=LEVEL.get), 'checks': checks, 'transitions': transitions, 'errors': sample['errors'], 'note': 'Observation only. No cleanup, process limits, or notification delivery is implied.'}
    return report, state


def state_path(value):
    original = Path(value)
    if not original.is_absolute() or any(p.is_symlink() for p in [original, *original.parents]):
        raise ValueError('State paths must be absolute and symlink-free')
    path = outside_checkout(value)
    info = path.parent.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('State parent must already exist, be private and caller-owned')
    if path.exists():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
            raise ValueError('State file must be a private caller-owned regular file')
    return path


def atomic(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
    try:
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--quiet-unchanged', action='store_true')
    args = parser.parse_args()
    config = validate(load_json(args.config, 16384))
    state, report = state_path(args.state), state_path(args.report)
    lock_path = state_path(str(state) + '.lock')
    if state == report or report == lock_path:
        raise ValueError('State, report and lock paths must differ')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = load_json(state) if state.exists() else {}
        if old and old.get('schema') != 1:
            raise ValueError('Unknown monitor state schema')
        digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        if old.get('configDigest') != digest:
            old['cpuCounts'] = {}
        result, updated = assess(config, collect(config), old)
        updated['configDigest'] = digest
        atomic(state, updated)
        atomic(report, result)
    if not args.quiet_unchanged or result['transitions']:
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
