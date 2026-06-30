---
name: decision-interview
description: Use when the user asks to be interviewed with focused questions before a decision, answer, opinion, plan, or recommendation; wants QAO/question-answer-opinion mode; wants continued questioning until confidence is high; or challenges an answer and wants a correction loop.
---

# Decision Interview

Use this skill to converge on a well-supported answer or opinion before acting.
It supports the QAO pattern: the session alternates between focused questions, provisional answers,
and explicit opinions until the remaining uncertainty is acceptable or the user redirects.

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

When the harness exposes a structured question UI and using it is allowed, prefer it for short,
answerable choice points. Use it when the user can answer with one of 2-3 mutually exclusive
options, such as goal type, risk tolerance, preference, scope, or next-step priority.

- Ask one question at a time.
- Put the recommended option first and mark it as recommended when the UI supports labels.
- Keep option labels short and make descriptions explain the tradeoff.
- Use plain text instead for open-ended context, sensitive nuance, or when the UI is unavailable.
- If the question is helpful but not strictly blocking, allow the session to continue with the
  recommended default when the harness supports auto-resolution.

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

This skill must work standalone. Treat companion skills as optional accelerators, not prerequisites.

- Use `brainstorming` or an equivalent divergent-thinking skill before convergence when the option
  space is too narrow, the user is still exploring, or a premature answer would hide better paths.
- Use `good-thinking` or an equivalent reasoning-audit skill when confidence matters and the
  evidence, assumptions, or tradeoffs need a deliberate quality pass.
- Use `grill-me` or an equivalent stress-test skill when the user wants a plan, design, or opinion
  challenged aggressively before finalizing it.
- Use `plan-task` or an equivalent planning skill when the conversation becomes an implementation
  plan with ordered steps, validation, or approval gates.
- Use domain-specific skills whenever the target answer depends on specialized tools, schemas,
  policies, or source material.

If companion suggestions are not installed, continue with the standalone loop. If the user asks to
complete the setup through Agentwheel, use the package suggestions rather than turning companions
into hard dependencies.
