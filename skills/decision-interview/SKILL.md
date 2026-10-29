---
name: decision-interview
description: Use for focused decision interviews, QAO or correction loops, or an unresolved user choice that changes the next action.
---

# Decision Interview

Use this skill to converge on a well-supported answer or opinion before acting.
It supports the QAO pattern: the session alternates between focused questions, provisional answers,
and explicit opinions until the remaining uncertainty is acceptable or the user redirects.

## Entry gate

Do not start a structured decision step when goals, information, and the authorized next action
are already clear from standing rules, earlier approvals, sensible defaults, or facts the agent
can verify. Act and report; never ask as filler. A default cannot supply required approval.
If a specific method is needed, select it through Composition; do not run every companion or
reproduce its process here. Use the Core Loop for focused uncertainty; a single unresolved
choice needs only the Structured Question UI, not an interview.

## Core Loop

1. Classify the target: factual answer, judgment/opinion, decision, plan, diagnosis, or creative direction.
2. State the current uncertainty in one sentence when it affects the next move.
3. Ask the smallest useful next question. Prefer one question at a time.
4. If the answer can be found by inspecting local context, tools, docs, or reliable sources, inspect instead of asking.
5. Continue until one of these is true:
   - confidence is high enough to answer;
   - the remaining uncertainty no longer changes the recommendation;
   - the user chooses speed over more intake;
   - progress is blocked by unavailable private context, credentials, or a decision only the user can make.
6. Give the answer or opinion with confidence, assumptions, and what would change the conclusion.

## Question Style

- Ask concrete questions that reduce decision-relevant uncertainty.
- Explain why the question matters only when that is not obvious.
- Offer a recommended default when the user can choose among plausible options.
- Avoid interrogating for its own sake; stop once more answers would not materially improve the result.
- Do not ask for facts that should be checked with available tools or source material.

### Structured Question UI

For discrete choices, use the first available UI permitted in the current mode: project/thread
decision card (`request_decision` or buttons returning action IDs), terminal `AskUserQuestion`
when the user is at the terminal, then the harness-native equivalent. Use a short numbered text
list only when no native UI is usable; never invent a tool or change modes to obtain one.
Open-ended context and sensitive nuance can remain plain text.

Put one decision in each box, with 2–4 mutually exclusive options within the UI's limits.
Put the recommended option first and label it “Recommended”; give each option a one-line
consequence. Make the question self-contained for a notification preview. Batch independent
choices only as separate boxes or a multi-question box supported by that UI; never bury a choice
in prose. Preserve the chosen workflow's dependency order and stopping conditions.

Use stable option IDs and act on the returned ID, not its label. If the host returns only labels,
resolve them through an explicit label-to-ID map; reject ambiguous, stale, or unmatched answers.
Silence or a preselected option is not an answer. After acting, update the card with the outcome
when supported and record the decision, option ID, timestamp, and outcome in the workflow's
existing ledger/work item, without a parallel decision store.

Irreversible, payment, and external-send approvals retain their written procedures and scope.
The UI collects approval; it does not bypass a gate. If an authorized default already resolves
an optional question, skip the question rather than treating non-response as consent.

## Answer Shape

When ready, answer in this compact shape:

- **Conclusion:** the answer, opinion, or recommendation.
- **Confidence:** high, medium, or low, with the main reason.
- **Basis:** key evidence, constraints, and assumptions.
- **Change trigger:** the fact or user correction most likely to change the answer.
- **Next move:** ask a follow-up only if the answer is still not actionable.

For opinions, be direct. A useful opinion can be uncertain, but it must name the tradeoff it is
choosing.

## Correction Loop

If the user says the answer is wrong, weak, incomplete, or not sufficiently justified:

1. Treat that as new evidence, not as a debate to win.
2. Identify which assumption, missing fact, or value judgment likely failed.
3. Ask the next question that would most reduce that failure.
4. Revise the answer and explicitly mark what changed.

Repeat until the user accepts the answer, chooses to stop, or the blocker is explicit.

## Composition

This skill must work standalone. Select only the existing method the task needs; companions are
optional accelerators, not prerequisites. Their discrete choices use Structured Question UI
above; this changes presentation, not their process. Clear authorized work uses none.

- Use `brainstorming` or an equivalent divergent-thinking skill before convergence when the option
  space is too narrow, the user is still exploring, or a premature answer would hide better paths.
- Use `good-thinking` or an equivalent reasoning-audit skill when confidence matters and the
  evidence, assumptions, or tradeoffs need a deliberate quality pass.
- Use `grilling` or an equivalent stress-test skill when the user wants a plan, design, or opinion
  challenged aggressively before finalizing it; `grill-me` is the user-invoked alias.
- Use `plan-task` or an equivalent planning skill when the conversation becomes an implementation
  plan with ordered steps, validation, or approval gates.
- Use domain-specific skills whenever the target answer depends on specialized tools, schemas,
  policies, or source material.

If companion suggestions are not installed, continue with the standalone loop. If the user asks to
complete the setup through Agentwheel, use the package suggestions rather than turning companions
into hard dependencies.
