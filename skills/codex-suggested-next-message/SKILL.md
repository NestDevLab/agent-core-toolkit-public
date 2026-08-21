---
name: codex-suggested-next-message
description: Configure the opt-in Codex hook that appends a copyable suggested next user message to each response.
allowed-tools: [Bash]
---

# Codex Suggested Next Message

This skill supplies the executable companion for the `UserPromptSubmit` hook in
`hooks/codex-suggested-next-message.json`. The hook stays inactive until
`CODEX_SUGGESTED_NEXT_MESSAGE_ENABLED=1` is present in the environment that
starts Codex.

## Behavior

For each submitted prompt, the hook asks `gpt-5.6-luna` at `low` reasoning
effort for one concise candidate for the user's next message. It then adds an
`additionalContext` instruction that makes the main Codex response end with a
copyable Markdown block:

````text
### Suggested next message
```text
<candidate>
```
````

The hook is fail-open: a missing dependency, timeout, invalid model output, or
unsupported event produces no suggestion and never blocks the main turn.

## Enable

Install the package's skills and hooks with Agentwheel, review the hook, then
start Codex with:

```sh
CODEX_SUGGESTED_NEXT_MESSAGE_ENABLED=1 codex
```

The hook needs Python 3.9+ and the `codex` CLI. A project-local install resolves
the companion script from `.agents/skills`; a user-level install resolves it
from `~/.agents/skills`. Set `CODEX_SUGGESTED_NEXT_MESSAGE_COMMAND` to an
absolute script path when either layout is unsuitable.

## Context boundary

By default, Luna receives only the newly submitted prompt. An authorized
integration may set `CODEX_SUGGESTED_NEXT_MESSAGE_CONTEXT` to a compact,
redacted conversation summary; the hook limits it to 12,000 characters and
does not write it to persistent storage. Do not point the hook at internal
session files or unbounded conversation transcripts.

The Luna child is ephemeral, runs from an empty temporary directory, ignores
user configuration and rules, and uses a read-only sandbox. It is marked with
an environment guard so this hook does not recursively invoke itself.
