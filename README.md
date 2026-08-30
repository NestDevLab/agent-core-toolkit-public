# Agent Core Toolkit Public

A public, reusable, runtime-neutral toolkit for agent instructions.

It provides a canonical `AGENTS.md` contract, generic role overlays, starter skills, and rule snippets. Everything in this repository is intended to be generic, synthetic, and publishable.

## Contents

```text
AGENTS.md                         # Base public agent contract
openpack.json                     # OpenPack package manifest
roles/<role>/AGENTS.md            # Generic role overlays
skills/<skill>/SKILL.md           # Reusable public skills
rules/<rule>.md                   # Runtime-neutral rule snippets
plugins/README.md                 # Plugin structure guidance
LICENSE                           # MIT license
```

## Quick Start

Install agentwheel:

```sh
npm i -g agentwheel
```

Install from the GitHub source:

```sh
agentwheel init
agentwheel add github:NestDevLab/agent-core-toolkit-public --adapter openclaw --mode tracking
agentwheel update --dry-run
agentwheel update
```

After this package is available in the public registry, the short name works too:

```sh
agentwheel registry update
agentwheel add nestdev-core-toolkit --adapter openclaw --mode tracking
agentwheel update --dry-run
agentwheel update
```

For one-off preview/sync without saving a package entry:

```sh
agentwheel sync github:NestDevLab/agent-core-toolkit-public --adapter openclaw --dry-run
```

agentwheel supports bundled adapters such as `openclaw`, `claude`, `codex`, `hermes`, and `copilot`, plus custom/private adapters.

## Codex Suggested Next Message Hook

The package includes a Codex-only `Stop` hook that can append a context-aware,
copyable **Suggested next message** block after a response. It is
installed inert and performs no model call until Codex is started with:

```sh
CODEX_SUGGESTED_NEXT_MESSAGE_ENABLED=1 codex
```

When enabled, it runs an ephemeral, read-only `gpt-5.6-luna` child at `low`
reasoning effort. The child receives the final answer and the latest user
message from a bounded transcript tail; it may also receive a compact,
explicitly supplied context summary through
`CODEX_SUGGESTED_NEXT_MESSAGE_CONTEXT`. It never loads an unbounded transcript
or retains the inputs or generated suggestion after the hook finishes.
Failures and timeouts leave the main response unchanged.

Review and trust the generated Codex hook before installation. See
[`skills/codex-suggested-next-message/SKILL.md`](skills/codex-suggested-next-message/SKILL.md)
for prerequisites, context limits, and the optional script-path override.

## agentwheel Package

`openpack.json` exposes:

- `instructions` -> `AGENTS.md`
- `rules` -> `rules/`
- `skills` -> `skills/`
- `hooks` -> opt-in Codex, Claude, and Copilot configurations

## Skill Evolution

OpenPack v3 injects `fragments/skill-evolution.md` into every rendered skill when this toolkit is
a configured graph root, except the evolution skill itself. The `skill-evolution` composite resolves authoritative source and
ownership before preparing any improvement. Its runner validates, deduplicates, and classifies
bounded events with explicit `--dry-run` and `--apply` modes. Deterministic candidates require an
authoritative script, focused tests, policy-bounded paths, and second-run idempotence proof.

Selecting a Codex or Claude failure-observer hook activates it; omission is the opt-out. The
standalone observer still requires `SKILL_EVOLUTION_HOOKS_ENABLED=1`. Observers retain fingerprints,
not prompts, transcripts, commands, or tool output. The Copilot hook stays environment-gated;
OpenClaw and Hermes observers are not part of v0.1.

The `roles/` directory contains generic role overlays for humans or future adapter support. It is not currently mapped as an agentwheel `subagents` artifact because this repository stores roles as nested `roles/<role>/AGENTS.md` folders, while the current package manifest flow expects directly installable files or supported artifact directories.

## Skills And Rules

Starter skills:

- `code-review`: findings-first technical review.
- `conversation-handoff`: verified context transfer between sessions or agents.
- `plan-task`: ordered planning with assumptions and stop points.
- `decision-interview`: focused questions before a confident answer, opinion, decision, or plan.
- `write-docs`: durable technical documentation.

Starter rules:

- `engineering-standards.md`
- `public-audience-privacy.md`
- `safe-actions.md`

The base instructions also include bounded capability discovery when substantive work exposes a missing reusable capability.

## Public Boundary

This repository must stay generic and safe to publish. Do not add real identities, organizations, clients, hostnames, IP addresses, secrets, private workspace paths, transcripts, or operational details.

Contributions should use synthetic examples and runtime-neutral language. Deployment-specific overlays belong in separate private layers.
