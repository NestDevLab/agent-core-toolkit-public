# Installer

`install.sh` installs the public agent toolkit into supported runtimes.

## Usage

```sh
./install/install.sh --runtime claude --mode symlink
./install/install.sh --runtime all --dry-run
./install/install.sh --runtime codex --mode copy --target "$HOME/.codex"
./install/install.sh --runtime claude --uninstall
```

## Runtimes

- `claude`: writes a thin `CLAUDE.md` wrapper, installs roles to `~/.claude/agents/`, and skills to `~/.claude/skills/`.
- `codex`: writes `~/.codex/AGENTS.md` and installs skills to `~/.codex/skills/`.
- `openclaw`: writes generic instruction and skill files under `~/.openclaw/` by default. Use `--target` to point at another runtime home.
- `hermes`: writes generic instruction and skill files under `~/.hermes/` by default. Use `--target` to point at another runtime home.
- `copilot`: writes `.github/copilot-instructions.md` in the target repository, defaulting to the current directory.

## Modes

- `copy`: copy a portable snapshot into runtime locations.
- `symlink`: symlink runtime locations back to this cloned repository.
- `update`: run `git pull --ff-only`, then apply copy mode.

Existing files are backed up as `*.bak-<timestamp>` before overwrite. `--uninstall` removes installed artifacts and restores the newest backup when one exists.

The installer is dependency-light: Bash, common file utilities, and optionally Git for update mode.
