---
name: set-visual-title
description: "Refresh a session, chat, or channel title with a concise current topic and fitting emoji; when a project is known, show its icon, the topic icon, and Project: Topic. Use when asked to rename, retitle, label, or improve a conversation title."
---

# Set Visual Title

## Workflow

1. Resolve the current session or channel with its native title operation. In Codex, use `set_thread_title`. Otherwise discover the host-native title or rename operation; never use another host's threads, API, or local storage.
2. If native identity or an authorized rename operation is unavailable, report that exact limitation and do not rename anything.
3. Infer the substantive current topic from the conversation's target, action, and intended outcome. Replace an early, vague, or superseded title with a concise 1–7-word topic in the user's language. Retain an explicit user-supplied topic when it remains accurate.
4. Accept a project only when the active environment supplies a reliable project name and fixed project emoji. Its project policy may resolve it from the session's launch directory first, then established conversation context. Do not invent a project from a weak mention.
5. Select one widely supported topic emoji that represents the actual work. Keep it distinct from the project emoji.
6. When a project is known, set `project emoji topic emoji Project: Topic` — for example, `🧩 🛠️ Project: Update dependencies`. Otherwise set `topic emoji Topic`. Do not retain a conflicting old emoji or filler such as “help”, “chat”, or “task”.
7. Invoke the skill only on user request. Rename through the native operation, verify the returned title, and report the final title.
