# Skill Evolution Contracts

## State

The runner writes only below `${XDG_STATE_HOME:-~/.local/state}/skill-evolution`. Set
`SKILL_EVOLUTION_STATE_DIR` to use a different root. Event files are immutable; candidate status
changes are separate records. The runner rejects symlinks and paths outside the state root.

## Event

`skill-evolution.event.v1` requires a signal kind, authoritative target, immutable base hash,
registered check, evidence fingerprint, and enforcement result. Evidence is metadata, not a
transcript. Values are bounded and secret-shaped keys are rejected.

Script enforcement names every affected script and focused test, and proves idempotence with equal
first- and second-run hashes plus `secondRunChanged: false`. `skill-updated` is semantic.
`nondeterministic` requires concrete evidence. Missing enforcement and `not-attempted` are invalid.

## Classification

The default is `semantic`. A signal is `deterministic` only when its check is registered in the
policy and the target is outside the constitutional boundary. It must use `script-created` or
`script-updated`; semantic signals may use those or `skill-updated`. `nondeterministic` remains
semantic. Classification permits trial, not publication.

## Ownership

- `owned`: patch the authoritative source.
- `third-party-redistributable`: use the configured derivative and retain license/upstream data.
- `third-party-restricted` or `unknown`: overlay only; publication is blocked.

## Promotion

Policy is immutable input to a run. Automatic promotion requires all of: an allowlisted check,
bounded paths, reproducible transformer, second-run no-op, configured preflight targets, rollback
proof, and an explicit `autoPromote` policy. Constitutional paths always require human approval.

Hooks are observers. They may submit bounded events but may not classify, patch, merge, publish, or
roll out candidates.
