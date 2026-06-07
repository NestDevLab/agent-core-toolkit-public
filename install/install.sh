#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: install.sh --runtime <claude|codex|openclaw|hermes|copilot|all> [--mode copy|symlink|update] [--target <dir>] [--dry-run] [--uninstall]

Modes:
  copy     Copy a portable snapshot into the runtime locations. This is the default.
  symlink  Link runtime locations to this cloned repository so future pulls are live.
  update   Run git pull in this repository, then apply copy behavior.

Options:
  --target <dir>   Override the runtime base directory. For copilot, this is the repository root.
  --dry-run        Print the full plan and make no changes.
  --uninstall      Remove installed artifacts and restore the newest backup where sensible.
USAGE
}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
MANIFEST="$SCRIPT_DIR/manifest.yaml"
RUNTIME=""
MODE="copy"
TARGET=""
DRY_RUN=0
UNINSTALL=0
STAMP=$(date +%Y%m%d%H%M%S)
MARKER="Managed by public agent core toolkit installer"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --runtime) RUNTIME="${2:-}"; shift 2 ;;
    --mode) MODE="${2:-}"; shift 2 ;;
    --target) TARGET="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
  esac
done

[ -n "$RUNTIME" ] || { echo "--runtime is required" >&2; usage; exit 2; }
case "$MODE" in copy|symlink|update) ;; *) echo "Invalid --mode: $MODE" >&2; exit 2 ;; esac
[ -f "$MANIFEST" ] || { echo "Missing manifest: $MANIFEST" >&2; exit 1; }

expand_path() {
  local p="$1"
  case "$p" in
    \~) printf '%s\n' "$HOME" ;;
    \~/*) printf '%s/%s\n' "$HOME" "${p#\~/}" ;;
    /*) printf '%s\n' "$p" ;;
    *) printf '%s/%s\n' "$PWD" "$p" ;;
  esac
}

manifest_value() {
  local runtime="$1" key="$2"
  awk -v r="$runtime" -v k="$key" '
    $0 ~ "^  " r ":" { in_runtime=1; next }
    in_runtime && $0 ~ /^  [A-Za-z0-9_-]+:/ { in_runtime=0 }
    in_runtime && $1 == k":" {
      sub("^[^:]+:[ ]*", "")
      gsub(/^[ \t]+|[ \t]+$/, "")
      print
      exit
    }
  ' "$MANIFEST"
}

runtimes_for_request() {
  if [ "$RUNTIME" = "all" ]; then
    printf '%s\n' claude codex openclaw hermes copilot
  else
    printf '%s\n' "$RUNTIME"
  fi
}

run_cmd() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf 'DRY-RUN: %s\n' "$*"
  else
    "$@"
  fi
}

backup_path() {
  local path="$1"
  [ -e "$path" ] || [ -L "$path" ] || return 0
  run_cmd mv "$path" "$path.bak-$STAMP"
}

copy_item() {
  local src="$1" dst="$2"
  backup_path "$dst"
  run_cmd mkdir -p "$(dirname "$dst")"
  if [ -d "$src" ]; then
    run_cmd mkdir -p "$dst"
    if [ "$DRY_RUN" -eq 0 ]; then
      cp -R "$src"/. "$dst"/
    else
      printf 'DRY-RUN: cp -R %s/. %s/\n' "$src" "$dst"
    fi
  else
    if [ "$DRY_RUN" -eq 0 ]; then
      cp "$src" "$dst"
    else
      printf 'DRY-RUN: cp %s %s\n' "$src" "$dst"
    fi
  fi
}

link_item() {
  local src="$1" dst="$2"
  backup_path "$dst"
  run_cmd mkdir -p "$(dirname "$dst")"
  run_cmd ln -s "$src" "$dst"
}

write_file() {
  local dst="$1" content="$2"
  backup_path "$dst"
  run_cmd mkdir -p "$(dirname "$dst")"
  if [ "$DRY_RUN" -eq 0 ]; then
    printf '%s\n' "$content" > "$dst"
  else
    printf 'DRY-RUN: write %s\n' "$dst"
  fi
}

restore_backup() {
  local path="$1"
  local latest
  latest=$(ls -1t "$path".bak-* 2>/dev/null | head -n 1 || true)
  if [ -n "$latest" ]; then
    run_cmd mv "$latest" "$path"
  fi
}

remove_managed() {
  local path="$1"
  if [ -L "$path" ] || [ -e "$path" ]; then
    run_cmd rm -rf "$path"
  fi
  restore_backup "$path"
}

install_collection() {
  local src_dir="$1" dst_dir="$2" mode="$3" item src dst
  [ -d "$src_dir" ] || return 0
  printf 'Plan: merge items from %s into %s\n' "$src_dir" "$dst_dir"
  run_cmd mkdir -p "$dst_dir"
  for src in "$src_dir"/*; do
    [ -e "$src" ] || continue
    item=$(basename "$src")
    dst="$dst_dir/$item"
    if [ "$mode" = "symlink" ]; then
      link_item "$src" "$dst"
    else
      copy_item "$src" "$dst"
    fi
  done
}

uninstall_collection() {
  local src_dir="$1" dst_dir="$2" item src dst
  [ -d "$src_dir" ] || return 0
  printf 'Plan: uninstall items from %s in %s\n' "$src_dir" "$dst_dir"
  for src in "$src_dir"/*; do
    [ -e "$src" ] || continue
    item=$(basename "$src")
    dst="$dst_dir/$item"
    remove_managed "$dst"
  done
}

support_dir_for() {
  local runtime="$1" base="$2" support
  support=$(manifest_value "$runtime" support_dir)
  [ -n "$support" ] || support="$base/agent-core-toolkit"
  if [ -n "$TARGET" ]; then
    printf '%s\n' "$base/agent-core-toolkit"
  else
    expand_path "$support"
  fi
}

runtime_path() {
  local runtime="$1" key="$2" base="$3" value
  value=$(manifest_value "$runtime" "$key" || true)
  [ -n "$value" ] || return 0
  if [ -n "$TARGET" ]; then
    printf '%s/%s\n' "$base" "$(basename "$value")"
  else
    expand_path "$value"
  fi
}

apply_common_assets() {
  local runtime="$1" base="$2" mode="$3" support roles_dst skills_dst rules_dst
  support=$(support_dir_for "$runtime" "$base")
  roles_dst=$(runtime_path "$runtime" roles "$base")
  skills_dst=$(runtime_path "$runtime" skills "$base")
  rules_dst="$support/rules"
  printf 'Plan: common assets support=%s rules=%s\n' "$support" "$rules_dst"

  if [ "$mode" = "symlink" ]; then
    link_item "$REPO_ROOT/AGENTS.md" "$support/AGENTS.md"
  else
    copy_item "$REPO_ROOT/AGENTS.md" "$support/AGENTS.md"
  fi
  install_collection "$REPO_ROOT/rules" "$rules_dst" "$mode"
  if [ -n "$skills_dst" ]; then
    install_collection "$REPO_ROOT/skills" "$skills_dst" "$mode"
  fi
  if [ -n "$roles_dst" ]; then
    install_collection "$REPO_ROOT/roles" "$roles_dst" "$mode"
  fi
}

uninstall_common_assets() {
  local runtime="$1" base="$2" support roles_dst skills_dst rules_dst
  support=$(support_dir_for "$runtime" "$base")
  roles_dst=$(runtime_path "$runtime" roles "$base")
  skills_dst=$(runtime_path "$runtime" skills "$base")
  rules_dst="$support/rules"
  remove_managed "$support/AGENTS.md"
  uninstall_collection "$REPO_ROOT/rules" "$rules_dst"
  if [ -n "$skills_dst" ]; then
    uninstall_collection "$REPO_ROOT/skills" "$skills_dst"
  fi
  if [ -n "$roles_dst" ]; then
    uninstall_collection "$REPO_ROOT/roles" "$roles_dst"
  fi
}

install_runtime() {
  local runtime="$1"
  case "$runtime" in claude|codex|openclaw|hermes|copilot) ;; *) echo "Unsupported runtime: $runtime" >&2; exit 2 ;; esac
  local instruction base support
  instruction=$(manifest_value "$runtime" instruction)
  [ -n "$instruction" ] || { echo "No instruction target for $runtime in manifest" >&2; exit 1; }

  if [ "$runtime" = "copilot" ]; then
    base="${TARGET:-$PWD}"
    instruction="$base/$instruction"
    if [ "$UNINSTALL" -eq 1 ]; then
      printf 'Plan: uninstall copilot instruction %s\n' "$instruction"
      remove_managed "$instruction"
      return
    fi
    printf 'Plan: install copilot instruction=%s mode=%s\n' "$instruction" "$MODE"
    write_file "$instruction" "<!-- $MARKER -->
# Repository Instructions

Follow the public agent core contract from this repository. Keep repository-specific private details in repository-local instructions, not in this shared public file.

Source: AGENTS.md"
    printf 'Note: Copilot custom instruction support varies by product surface; this installer writes a repository instruction file only.\n'
    return
  fi

  if [ -n "$TARGET" ]; then
    base="$TARGET"
    instruction="$base/$(basename "$instruction")"
  else
    instruction=$(expand_path "$instruction")
    base=$(dirname "$instruction")
  fi

  if [ "$UNINSTALL" -eq 1 ]; then
    support=$(support_dir_for "$runtime" "$base")
    printf 'Plan: uninstall %s instruction=%s support=%s\n' "$runtime" "$instruction" "$support"
    remove_managed "$instruction"
    uninstall_common_assets "$runtime" "$base"
    return
  fi

  printf 'Plan: install %s mode=%s instruction=%s\n' "$runtime" "$MODE" "$instruction"
  support=$(support_dir_for "$runtime" "$base")
  apply_common_assets "$runtime" "$base" "$MODE"

  if [ "$runtime" = "claude" ]; then
    write_file "$instruction" "<!-- $MARKER -->
# Runtime Instructions

Read and follow: $support/AGENTS.md"
  elif [ "$MODE" = "symlink" ]; then
    link_item "$REPO_ROOT/AGENTS.md" "$instruction"
  else
    copy_item "$REPO_ROOT/AGENTS.md" "$instruction"
  fi
}

if [ "$MODE" = "update" ] && [ "$UNINSTALL" -eq 0 ]; then
  if command -v git >/dev/null 2>&1 && [ -d "$REPO_ROOT/.git" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf 'DRY-RUN: git -C %s pull --ff-only\n' "$REPO_ROOT"
    else
      git -C "$REPO_ROOT" pull --ff-only
    fi
  else
    echo "Update mode requires git and a cloned repository" >&2
    exit 1
  fi
  MODE="copy"
fi

printf 'Manifest: %s\n' "$MANIFEST"
for rt in $(runtimes_for_request); do
  install_runtime "$rt"
done
