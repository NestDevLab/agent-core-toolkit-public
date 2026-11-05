#!/usr/bin/env python3
"""Read-only ncdu exports and code-lane payload checks. Never deletes data."""
import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess
import tempfile


def outside_checkout(path):
    path = Path(path).resolve()
    state = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')).resolve()
    for parent in (path.parent, *path.parents):
        # A dotfiles repository may own the home directory; its external state
        # directory is allowed, but nested checkouts below state are not.
        if parent == state:
            break
        if (parent / '.git').exists():
            raise ValueError('Reports must be outside Git checkouts and lanes')
    return path


def scan(root, output, timeout):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Scan root must be a directory')
    output = outside_checkout(output)
    if output.exists():
        raise ValueError('Refusing to overwrite an inventory')
    # One pass, one filesystem, no deletion UI, literal symlinks. Partial exports
    # remain visibly incomplete and must never be treated as a successful scan.
    command = ['ncdu', '-r', '-x', '-0', '--exclude-kernfs', '-o', '-', str(root)]
    fd, partial = tempfile.mkstemp(prefix=output.name + '.', suffix='.partial', dir=output.parent)
    try:
        with os.fdopen(fd, 'wb') as raw:
            # Let ncdu write directly: no buffered pipe that can deadlock on errors.
            result = subprocess.run(command, stdout=raw, stderr=subprocess.PIPE,
                                    timeout=timeout, check=False)
        if result.returncode:
            raise RuntimeError('ncdu failed; partial inventory retained at ' + partial)
        # Keep compression separate from collection so an interrupted compressor
        # cannot disguise an incomplete inventory as a successful export.
        with open(partial, 'rb') as source, output.open('xb') as target:
            with gzip.GzipFile(filename='', mode='wb', fileobj=target, mtime=0) as zipped:
                while chunk := source.read(1024 * 1024):
                    zipped.write(chunk)
        os.unlink(partial)
    except subprocess.TimeoutExpired:
        raise RuntimeError('ncdu timed out; partial inventory retained at ' + partial)
    return {'status': 'complete', 'root': str(root), 'export': str(output),
            'command': command, 'scope': 'one-filesystem; symlinks not followed'}


def summarize(tree, limit=20):
    if not isinstance(tree, list) or tree[:2] != [1, 2]:
        raise ValueError('Expected ncdu 1.x export format [1,2,...]')
    rows, seen = [], set()
    incomplete = []

    def visit(node, parent, device=None):
        directory = isinstance(node, list)
        meta = node[0] if directory else node
        name = meta.get('name', '')
        device = meta.get('dev', device)
        path = name if not parent else parent.rstrip('/') + '/' + name
        if meta.get('read_error') or meta.get('excluded'):
            incomplete.append(path)
        size = meta.get('dsize', meta.get('asize', 0))
        if meta.get('hlnkc'):
            key = (device, meta.get('ino'))
            if None in key:
                incomplete.append(path + ': hardlink identity missing')
            elif key in seen:
                size = 0
            else:
                seen.add(key)
        if directory:
            size += sum(visit(child, path, device) for child in node[1:])
            rows.append({'path': path, 'allocatedBytes': size})
        return size

    total = visit(tree[3], '')
    return {'allocatedBytes': total, 'largestDirectories': sorted(
        rows, key=lambda r: (-r['allocatedBytes'], r['path']))[:limit],
        'incomplete': incomplete, 'status': 'incomplete' if incomplete else 'complete',
        'note': 'Directory totals overlap; hardlinks counted once in traversal order. Not reclaimable bytes.'}


def lane_payloads(root):
    """Find forbidden payloads without following symlinks or opening databases."""
    root = Path(root).resolve(strict=True)
    findings, errors = [], []
    forbidden = {'node_modules', '.venv', 'venv', '__pycache__', '.angular', '.next',
                 'coverage', 'test-results', 'playwright-report', 'dist', 'build'}
    database_suffixes = ('.sqlite', '.sqlite3', '.db', '-wal', '-shm')
    def error(exc):
        errors.append(str(exc))
    for base, dirs, files in os.walk(root, followlinks=False, onerror=error):
        for name in list(dirs):
            path = Path(base) / name
            if path.is_symlink():
                findings.append({'path': str(path.relative_to(root)), 'kind': 'symlink-review'})
                dirs.remove(name)
            elif name == '.git':
                dirs.remove(name)
            elif name in forbidden:
                findings.append({'path': str(path.relative_to(root)), 'kind': 'generated-payload'})
                dirs.remove(name)
        for name in files:
            path = Path(base) / name
            if path.is_symlink():
                continue
            if name.endswith(('.tar', '.tar.gz', '.tgz', '.zip', '.pax')):
                findings.append({'path': str(path.relative_to(root)), 'kind': 'archive-review'})
            if name.lower().endswith(database_suffixes):
                findings.append({'path': str(path.relative_to(root)), 'kind': 'database-or-sidecar'})
            # Hash-named backups can conceal database files. Inspect only the
            # SQLite header; never open through SQLite or modify journal state.
            elif name != '.git':
                try:
                    if path.is_file():
                        with path.open('rb') as handle:
                            if handle.read(16) == b'SQLite format 3\x00':
                                findings.append({'path': str(path.relative_to(root)), 'kind': 'sqlite-header'})
                except OSError as exc:
                    errors.append(str(exc))
    return {'root': str(root), 'findings': findings, 'errors': errors,
            'status': 'incomplete' if errors else 'violations' if findings else 'clean',
            'note': 'Read-only. Findings never authorize removal; archives and all external symlink targets remain unclassified.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('scan')
    command.add_argument('--root', required=True)
    command.add_argument('--output', required=True)
    command.add_argument('--timeout', type=int, default=1800)
    command = commands.add_parser('summary')
    command.add_argument('export')
    command.add_argument('--limit', type=int, default=20)
    command = commands.add_parser('lane-check')
    command.add_argument('root')
    args = parser.parse_args()
    if args.command == 'scan':
        result = scan(args.root, args.output, args.timeout)
    elif args.command == 'summary':
        from ncdu_stream import summary
        with gzip.open(args.export, 'rt') as handle:
            result = summary(handle)
        result['status'] = 'incomplete' if result['readErrors'] else 'complete'
        result['largest'] = result['largest'][:args.limit]
    else:
        result = lane_payloads(args.root)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in ('clean', 'complete') else 2


if __name__ == '__main__':
    raise SystemExit(main())
