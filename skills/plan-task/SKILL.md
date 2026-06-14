---
name: plan-task
description: Plan ambiguous, exploratory, multi-step, or high-impact requests before implementation; clarify with concise questions, options, assumptions, and approval gates.
---

# Plan Task

Use this skill when a request needs sequencing, risk control, or coordination before implementation.
Use when the user is brainstorming, says something like "we should", gives several tasks at once,
or leaves scope/intent unclear. Do not implement during intake unless the user explicitly confirms
execution or the change is obvious, narrow, low-risk, and reversible.

## Planning Rules

- Resolve what the codebase can answer; ask only for choices the code cannot settle.
- Ask one focused question at a time when a decision blocks the plan.
- Prefer selectable options when the UI/tool supports them; otherwise give short recommended
  choices in plain text.
- Put irreversible, external, costly, privileged, or ambiguous edits behind approval gates.
- Treat "go ahead", "procedi", "do it", or equivalent confirmation as the implementation handoff.
- Make validation part of the plan, not an afterthought.

## Plan Shape

A useful plan includes:

- Goal and scope
- Current-state observations
- Ordered execution steps
- Validation checks
- Approval gates
- Risks and open questions

Keep the plan specific enough that an implementer can execute it without hidden context.
