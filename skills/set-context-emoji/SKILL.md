---
name: set-context-emoji
description: Manually apply a meaningful emoji prefix to a session, chat, or channel title. Use when asked to label or rename the current conversation with an emoji in any harness or messaging service.
---

# Set Context Emoji

## Workflow

1. Resolve the current session or channel with its native title tool. In Codex, use `set_thread_title`. Otherwise search exposed tools for the host-native title or rename operation; never substitute another host's threads, API, or local storage.
2. If native identity or an authorized rename operation is unavailable, report that exact limitation and do not rename anything.
3. Infer one concise, widely supported emoji from the work's purpose. Cues include development, review, planning, research, operations, documentation, and conversation; prefer the most specific meaning and never use a product logo.
4. Preserve the title text. Keep a fitting leading emoji; replace one conflicting leading emoji; otherwise prepend the chosen emoji and one space. Do not stack prefixes.
5. Invoke the skill only on user request. Rename through the native operation, then read back the title and report the emoji and final title.
