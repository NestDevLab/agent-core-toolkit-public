# Lightweight pressure observations

`scripts/resource_monitor.py` reads `statvfs`, `/proc/meminfo` and `/proc/stat`.
It never performs recursive scans, runs shell commands, opens databases, kills
processes or changes limits. Run it once per tick; the owning scheduler defines
the interval. A five-minute interval keeps at most one day of samples (288).
The caller must first create a private, owned state directory outside Git trees.
State and latest report are atomically replaced; a nonblocking lock prevents
overlapping writers. Keep one state/config pair per observed machine.

Example configuration (thresholds require the environment owner's selection):

```json
{
  "disks": [{
    "path": "/",
    "warningGiB": 30, "criticalGiB": 10,
    "warningPercent": 15, "criticalPercent": 5
  }],
  "memory": {"warning": 10, "critical": 5},
  "cpu": {"warning": 85, "critical": 95, "consecutiveSamples": 3},
  "growthGiBPerHour": 2
}
```

Disk byte, free-percent and free-inode thresholds are independent: the most
severe wins. Memory thresholds refer to **available** RAM, including reclaimable
cache, rather than free pages. CPU busy time excludes iowait and counts guest
time once. It requires counter deltas from the same boot, at least one second
and at most one hour apart. Initial/reset/stale samples are `warming`.
Confirm that the observed `/proc` view represents the intended container/host;
these counters do not promise per-container cgroup quota accounting.

Growth compares against a sample at least thirty minutes old, with matching
filesystem capacity. A resize invalidates the old capacity baseline. History is
capped at 288 entries and the latest report contains only current checks,
errors and status transitions. Do not append every report to an unbounded log.
`--quiet-unchanged` prints only status transitions while updating current state.

## Physical disk evidence

A guest's virtual disk never proves physical disk health. Without physical-host
evidence, SMART remains `unknown`. An optional `smart` config binds an external
JSON file to `expectedIdentity` and `maxAgeSeconds` (60–604800 seconds):

```json
{
  "evidenceFile": "/external/private/physical-health.json",
  "expectedIdentity": "physical-host",
  "maxAgeSeconds": 86400
}
```

The environment's authorized physical-host collector writes:

```json
{
  "identity": "physical-host",
  "observedAt": "2030-01-01T00:00:00+00:00",
  "disks": [{"device": "physical-disk", "status": "passed", "source": "smartctl"}]
}
```

Allowed device statuses are `passed`, `failed`, `warning`, `unknown`. Empty,
missing, stale, future-dated, identity-mismatched or malformed evidence is
unknown, never healthy. A failed disk is critical. The caller must establish
physical identity, collector provenance and complete disk coverage; the JSON
format cannot prove them. Do not run tests or wake a sleeping disk to fill a
missing observation implicitly.

## Scheduling and alerts

Scheduling and notifications belong to the authorized environment adapter.
Read current reports and deliver actionable transitions through its approved
channel; separately verify scheduler execution **and** notification receipt.
The script never installs a scheduler or sends a message. `unknown` coverage is
actionable. A successfully written JSON file proves neither a delivered alert
nor full monitoring coverage. An optional full `ncdu` inventory is a separate,
bounded diagnostic, never the recurring cheap tick.
