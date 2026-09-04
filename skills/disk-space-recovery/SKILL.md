---
name: disk-space-recovery
description: Audit disk and RAM pressure across declared hosts, containers, hypervisors, and Windows targets. Use for storage growth, memory pressure, log/cache/archive classification, or safe cleanup planning.
metadata:
  version: "0.2"
---

# Disk and Resource Recovery Base

## Operating contract

This base coordinates evidence; it does not turn size into permission to delete.
Use it when a host or container is filling up, when storage grows again after a
cleanup, or when logs, caches, archives, databases, and worktrees must be classified.

The authoritative source for this skill is the source package that contains this
file. Installed harness copies are generated output and evidence only. Keep reports
and evolution state under local state directories, never in a worktree.

Every run has four separate phases:

1. **Audit** — read-only, bounded, repeatable evidence.
2. **Plan** — classify each candidate with owner, age, lock/process, recovery path,
   and estimated reclaimable bytes.
3. **Apply** — only the exact approved targets, with a preflight and a report.
4. **Verify** — compare `df` and logical usage, check services and open handles,
   and record anything retained or unresolved.

Never use a global prune, global log flush, unrestricted `rm`, unrestricted database
`DELETE`, or filesystem-wide `VACUUM` as a shortcut. Prefer quarantine or a named,
recoverable backup when the approved procedure permits it.

## First pass: declared targets

Use `resource-maintenance.inventory.v1` for target identity, platform, transport,
scan roots, protected paths, thresholds, and authoritative documents. The inventory
is data only: it cannot contain credentials, shell, scripts, or arbitrary commands.
Resolve and read its private architecture references before interpreting live data.

Run `resource_audit.py inventory validate`, then `resource_audit.py audit` once per
target and `resource_audit.py plan` over the result directory. It supports fixed
local, SSH POSIX, SSH PowerShell, and Proxmox LXC transports. Subprocesses use argv,
fixed scripts, bounded output, and timeouts. Remote identity mismatches or unavailable
transports are findings, not evidence that a target is absent.

Normalized evidence includes filesystems, inode capacity, large files, physical
memory, swap/pagefile, top processes, container sizes, and target relationships.
Parent and guest evidence remain separate so a plan cannot double-count space.

The new collector is read-only. It never deletes, rotates, prunes, vacuums,
restarts, kills, changes container state, or edits Git state.

Pass only roots that are explicitly in scope for the current environment:

```bash
python3 skills/disk-space-recovery/scripts/storage_audit.py audit \
  --root /srv --root /var/log --root /var/tmp --skip-du --skip-large-files \
  --output "${XDG_STATE_HOME:-$HOME/.local/state}/disk-space-recovery/audit.json"
```

The script is read-only apart from writing the explicitly requested report. It
collects, without shell interpolation:

- filesystem and inode capacity (`df`), real mounts, hostname, kernel, and
  virtualization/container identity;
- bounded `du` summaries and, when explicitly enabled, large-file candidates only
  below supplied roots;
- deleted-open handles from `lsof`, separating memory-backed mappings such as
  `memfd` from disk-backed regular-file candidates;
- Docker server/root metadata, all container states and sizes, and
  `docker system df -v` when Docker is accessible;
- visibility of Docker, Podman, Incus, LXC, hypervisor-management, and libvirt
  entrypoints.

`--skip-du` and `--skip-large-files` are the safe quick-pass defaults for transient
or unusual mounts. Run each expensive scan later against one explicitly selected
root with `--root <path>` and without the relevant flag. A `du` result can be
marked `complete: false` when protected directories deny access; retain its byte
estimate but do not treat it as a complete filesystem inventory.

The current namespace must be identified before interpreting the result. A guest is
not its hypervisor host: report the host as unavailable unless a separately
authorized and authenticated host view exists. A container runtime is covered only
when its socket/daemon is accessible. Missing management commands are findings, not
evidence that those containers are absent.

Use the JSON report as the only input to ranking. Keep volatile command output out
of skill-evolution events; pass bounded metadata, hashes, counts, and exact source
paths instead of prompts, secrets, or complete payloads.

## Classification before cleanup

For every proposed action, record:

| Class | Required evidence | Default treatment |
| --- | --- | --- |
| Safe candidate | exact target, owner, age, no active writer/lock, recovery path | may enter an approved apply batch |
| Review | owner or lifecycle is not proven, or target is a stopped runtime artifact | retain and request category approval |
| Protected | active database, live worktree, runtime state, WAL/SHM, current log, or unknown archive | do not remove from size alone |
| Unavailable | outside the current namespace or runtime access failed | report the boundary and stop there |

Do not classify by size alone. Check `lsof`, service/process ownership, modification
time, Git branch/upstream/dirty/unpushed state, runtime labels, database integrity,
and whether a restore or rebuild has been tested.

### Logs and temporary data

Rotate or truncate only named logs after isolating the writer and using its supported
entrypoint. Target the named application/log only; never use a global log flush.
Configure size-bounded rotation after the immediate recovery. Temporary directories
require stale age, owner, no active process, and a recoverable quarantine or explicit
deletion approval. Exclude unclassified runtime directories.

### Containers and images

Treat stopped containers, unreferenced images, anonymous volumes, and old layers as
review candidates, not automatic garbage. Resolve the owning compose/project or
service and document how it can be recreated before removing anything. Use exact
IDs and named volumes in an approved batch; do not run global prune or volume
pruning commands.

### Databases

Retention is domain-specific. First export or back up, verify the backup, run the
domain maintenance command in dry-run mode, and apply bounded batches. Separate
logical deletion from physical reclamation: `VACUUM`, rebuild, or compaction is a
later action requiring an integrity check and at least 25–30 GB of verified scratch
space, preferably on another filesystem. Stop on locks or `ENOSPC`. Preserve active
settings/state data unless its owner supplies a lossless recovery procedure.

### Git worktrees and archives

Delegate Git inspection to the workspace's Git-maintenance skill. A worktree is
removable only after branch, upstream, merge/absorption, dirty state, unpushed
commits, locks, and recovery are proven. A clean worktree is not automatically
disposable. Archives, dead-letter queues, runtime stores, and backups need an owner
and a restore test; retain them when either is unknown.

## Apply and verify

Before an apply batch, freeze the exact target list and capture a baseline containing
`df -hT`, `df -ih`, logical runtime usage, process/lock checks, and Git status for
any repository involved. Prefer a task-owned quarantine on the same filesystem when
that is part of the approved procedure. Never broaden a target because a larger
directory is nearby.

After each batch:

1. compare filesystem free bytes and logical usage with the baseline;
2. check that no removed log or database file remains open;
3. verify the owning service/container and run its smoke test;
4. confirm no unauthorized Git paths changed;
5. report exact removed, quarantined, retained, and unavailable items.

If free space falls below the emergency floor, stop optional work and perform only
the already-approved named emergency action. If a deleted-open file remains held,
restart only its owning service after a separate runtime restart approval.

## Skill evolution

This skill composes `skill-evolution`; it does not modify the installed copy of
either skill. When a deterministic failure or repeatable correction is found:

1. capture a bounded sanitized observation and normalize it as
   `skill-evolution.event.v1`;
2. resolve the authoritative source, revision, owner, license, and policy;
3. create or update the smallest deterministic script and focused tests first;
4. prove that a second run produces the same result and changes nothing;
5. ingest the event with the installed `skill_evolution.py` using the local policy
   in `references/skill-evolution-policy.json`;
6. trial the candidate in an isolated worktree, then leave semantic skill changes
   pending review unless the standing policy explicitly permits promotion.

Hooks may observe and submit bounded events only. They may not classify, edit,
merge, publish, roll out, delete storage, or restart services. A change to this
skill's instructions is semantic even when its audit script is deterministic.

## Included deterministic tool

`scripts/storage_audit.py` is the canonical read-only collector. Its JSON schema is
stable and intentionally omits timestamps, environment dumps, credentials, and
unbounded command payloads, so identical fixtures produce identical reports. Run
its focused tests before recording a deterministic-improvement event:

```bash
python3 skills/disk-space-recovery/tests/test_storage_audit.py
```

The script is an observer. It never deletes, rotates, prunes, vacuums, restarts,
changes container state, or edits Git state.
