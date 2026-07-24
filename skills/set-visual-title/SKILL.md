---
name: set-visual-title
description: Refresh a session, chat, or channel title so it accurately summarizes the mature conversation and starts with one meaningful emoji. Use when asked to rename, retitle, label, or improve a conversation title, especially when its initial title is vague or no longer reflects the work.
---

# Set Visual Title

## Workflow

1. Resolve the current session or channel with its native title operation. In Codex, use `set_thread_title`. Otherwise discover the host-native title or rename operation; never use another host's threads, API, or local storage.
2. If native identity or an authorized rename operation is unavailable, report that exact limitation and do not rename anything.
3. Infer the substantive work from the conversation's current state: target, action, and intended outcome. Replace an early, vague, or superseded title with a concise 3–9-word title in the user's language. Retain an explicit user-supplied title when it remains accurate.
4. Select one widely supported emoji. Honor a project emoji supplied by an active private profile when one applies; otherwise select the most specific contextual emoji. Never use a product logo or stack prefixes.
5. Set the title as `emoji concise title`. Do not retain a conflicting old emoji or filler such as “help”, “chat”, or “task”.
6. Invoke the skill only on user request. Rename through the native operation, verify the returned title, and report the final title.
