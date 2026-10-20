---
name: session-archive
description: Session archive with a durable summary outside primary memory. Invoke manually or through explicitly delegated lifecycle management.
license: MIT
metadata:
  author: NestDevLab
  version: "1.0"
---

# Session archive

## Authorization

A user invocation authorizes preservation and native archiving of the current session or another
explicitly identified session. An orchestrator may invoke this skill only under an explicit user
delegation covering lifecycle management and archival of that session. Resolve the delegation
and exact target before acting; do not infer authority from completion, inactivity, discovery,
or another agent's recommendation. Respect user exclusions, revocation, and narrower scope.
Creating, installing, or discovering this skill never invokes it.

Every invocation must save and verify the durable summary below before requesting native archival.

## Preserve first

1. Resolve harness, profile, session ID, and workspace from live metadata, never recency alone.
   Summarize available history; disclose gaps. Include UTC capture time, identity, goal, outcome,
   decisions and rationale, useful discoveries, unresolved work with owners/resume conditions,
   approval boundaries, and references to authoritative artifacts. Label unverified claims.
2. Save through a configured episodic/session-note writer that creates a separate durable record.
   Otherwise write a Markdown note in the configured durable notes directory, falling back to the
   user's local data directory (`$XDG_DATA_HOME/session-archive` or
   `~/.local/share/session-archive` on Unix). Partition by harness/profile; use a safe session ID
   and unique UTC suffix. Never overwrite an existing note or use temporary/public locations.
3. Never update `MEMORY.md`, equivalent primary memory, startup indexes, instructions, or core
   memory slots, including links or later promotion. Keep summaries private and redact secrets.
   Reference existing work items; the note is historical context, not a competing task store.
   Satisfy any workspace requirement to transfer pending work before archiving.
4. Read the record back and verify identity, content, and location. On retry reuse a matching
   verified record; preserve changed context as a new revision. A pending proposal, compaction,
   or retained transcript alone is insufficient. If persistence fails, stop before archiving.

## Archive natively

Discover the installed version's capabilities before using these examples.

| Harness | Native mechanism when available |
| --- | --- |
| Codex | Exposed archive action/directive or app-server `thread/archive`. |
| Claude desktop | Exposed `archive_session` or UI Archive. |
| OpenClaw | Gateway `sessions.patch` with `archived` set to true, or UI Archive. |
| Hermes | Desktop/dashboard Archive or an API/CLI selecting the exact session. |
| Other/version without support | Discover its native archive; otherwise report unavailable. |

Target only the identified session; inspect cascade effects and respect active-turn/main-session
restrictions. Never force, alter databases/transcripts/runtime internals, or substitute deletion,
pruning, reset, `/new`, compaction, or `/exit`. If native archive fails or is unavailable, retain
the note and report the exact supported manual action when known.

Invoke `/session-archive` where skill slash commands are supported, or `$session-archive` in
Codex. Never substitute the built-in `/archive`, which can skip preservation.

Verify archived state through native read-back. If archiving ends the turn, report the note
first and mark archive requested, not verified. Return the note path/ID, whether it is indexed
or only recoverable by path, archive status (`verified`, `requested`, `failed`, `unavailable`),
and any remaining manual step. Do not promise indexing or backups without evidence.
