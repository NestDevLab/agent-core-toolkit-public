# Agent Core Toolkit Public

A public, reusable, runtime-neutral toolkit for agent instructions.

It provides a canonical `AGENTS.md` contract, generic role overlays, starter skills, rule snippets, and a dependency-light installer for several local agent runtimes. Everything in this repository is intended to be generic, synthetic, and publishable.

## Contents

```text
AGENTS.md                         # Base public agent contract
roles/<role>/AGENTS.md            # Generic role overlays
skills/<skill>/SKILL.md           # Reusable public skills
rules/<rule>.md                   # Runtime-neutral rule snippets
plugins/README.md                 # Plugin structure guidance
install/install.sh                # Multi-runtime installer
install/manifest.yaml             # Runtime target map and artifacts
install/adapters/<runtime>.sh     # Runtime helper stubs
LICENSE                           # MIT license
```

## Quick Start

```sh
git clone https://example.com/agent-core-toolkit-public.git
cd agent-core-toolkit-public
./install/install.sh --runtime claude --mode symlink
```

Preview every runtime without writing files:

```sh
./install/install.sh --runtime all --dry-run
```

## Supported Runtimes

- `claude`: installs a thin `CLAUDE.md` wrapper, role overlays, and skills.
- `codex`: installs `AGENTS.md` and skills.
- `openclaw`: installs generic instruction and skill files into an overridable runtime home.
- `hermes`: installs generic instruction and skill files into an overridable runtime home.
- `copilot`: writes `.github/copilot-instructions.md` in a target repository.

Use `--target <dir>` to override a runtime home or, for Copilot, the target repository.

## Install Modes

- `copy`: copy a portable snapshot into runtime locations.
- `symlink`: link runtime locations to this clone so repository updates are reflected immediately.
- `update`: run `git pull --ff-only`, then re-apply copy mode.

Existing files are backed up with a timestamp before overwrite. Use `--uninstall` to remove installed artifacts and restore backups where possible.

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
