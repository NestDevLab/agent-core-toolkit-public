---
name: set-context-emoji
description: Manually apply a meaningful emoji prefix to a session, chat, or channel title. Use when asked to label or rename the current conversation with an emoji in any harness or messaging service.
---

# Set Context Emoji

## Workflow

1. Identify the current conversation and read its title, description, and immediate task context. If the target is unclear, ask; do not rename a different channel.
2. Infer one concise, widely supported emoji from the work's purpose. Treat development, review, planning, research, operations, documentation, and conversation as cues, not a fixed mapping. Prefer the most specific meaning; do not use a platform or product logo.
3. Preserve the title text. Keep a fitting leading emoji; replace one conflicting leading emoji; otherwise prepend the chosen emoji and one space. Do not stack prefixes.
4. Use the harness's actual title or channel-rename operation. Invoke the skill only on user request; do not claim support from the platform name alone. If no authorized update operation is available, report the proposed title without changing anything.
5. Verify the returned title. Report the applied emoji and final title, or the exact reason no update occurred.
