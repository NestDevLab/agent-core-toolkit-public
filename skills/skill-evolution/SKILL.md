---
name: skill-evolution
description: Evolve skills after deterministic failures, durable corrections, activation gaps, or recurring problems while preserving source ownership and promotion policy.
license: MIT
metadata:
  author: Yehonal
  version: "0.1"
---

# Skill Evolution

Turn verified improvement signals into source-aware, reversible skill revisions.

## Invariants

- Treat installed and generated copies as evidence, never source.
- Resolve source, revision, owner, license, and policy before drafting.
- Prefer deterministic enforcement; prose alone is incomplete when a script, test, lint, schema, or hook can encode the improvement.
- A candidate cannot approve changes to its classifier, evaluator, policy, promoter, observer, schema, activation fragment, or this skill.
- Persist only bounded, sanitized evidence; never prompts, secrets, or complete tool payloads.

## Workflow

1. Normalize the signal as `skill-evolution.event.v1`; deduplicate by target, base hash, check, and evidence fingerprint.
2. Resolve the authoritative source from manager provenance. Stop on ambiguity or source drift.
3. Route ownership:
   - owned source: revise the origin;
   - redistributable third party: create or update the configured derivative, preserve license and upstream binding, and declare `supersedes`;
   - restricted or unknown license: retain an overlay and block publication.
4. Enforce before drafting. If deterministic, create or update the authoritative transformer and focused tests, register it, and prove second-run no-op. If semantic, invoke `self-improve` on the authoritative skill and add mechanical enforcement where possible. Otherwise record concrete nondeterminism; `not attempted` is not terminal.
5. Build a candidate against an immutable base with the patch, affected paths, checks, evals, rollback, expiry, and enforcement disposition.
6. Classify as deterministic only when its registered transformer is reproducible, policy-authorized, path-bounded, tested, and second-run idempotent. Treat instruction, trigger, intent, and constitutional changes as semantic and pending approval.
7. Trial the candidate in isolation. Reject regressions, unrelated diffs, unstable checks, missing rollback proof, or a prose-only deterministic fix.
8. Promote a deterministic candidate only within its standing policy. Preflight every configured target before merge and rollout; on any failure, restore all targets and block the candidate.
9. Report source choice, enforcement disposition, evidence, diff, evals, promotion state, rollout state, and retained or removed artifacts.

Use `scripts/skill_evolution.py` to validate and persist events. Read `references/contracts.md` before adding a transformer, promoter, or hook integration.

Finish only when every accepted signal has a deduplicated candidate with both a terminal state—promoted, pending approval, blocked, rolled back, or expired—and an enforcement disposition: script created, script updated, skill updated, or nondeterministic with evidence.
