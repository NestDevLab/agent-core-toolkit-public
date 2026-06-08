# Agent Core Toolkit Public

A public, reusable, runtime-neutral toolkit for agent instructions.

It provides a canonical `AGENTS.md` contract, generic role overlays, starter skills, and rule snippets. Everything in this repository is intended to be generic, synthetic, and publishable.

## Contents

```text
AGENTS.md                         # Base public agent contract
agentwheel.json                   # agentwheel package manifest
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

## agentwheel Package

`agentwheel.json` exposes:

- `instructions` -> `AGENTS.md`
- `rules` -> `rules/`
- `skills` -> `skills/`

The `roles/` directory contains generic role overlays for humans or future adapter support. It is not currently mapped as an agentwheel `subagents` artifact because this repository stores roles as nested `roles/<role>/AGENTS.md` folders, while the current package manifest flow expects directly installable files or supported artifact directories.

## Skills And Rules

Starter skills:

- `code-review`: findings-first technical review.
- `plan-task`: ordered planning with assumptions and stop points.
- `write-docs`: durable technical documentation.

Starter rules:

- `engineering-standards.md`
- `safe-actions.md`

## Public Boundary

This repository must stay generic and safe to publish. Do not add real identities, organizations, clients, hostnames, IP addresses, secrets, private workspace paths, transcripts, or operational details.

Contributions should use synthetic examples and runtime-neutral language. Deployment-specific overlays belong in separate private layers.
