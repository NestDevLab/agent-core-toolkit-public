---
name: convergent-dialogue
description: Use when the user asks for convergent dialogue, QAO/question-answer-opinion mode, a high-confidence answer or opinion through clarifying questions, continued questioning until enough context is gathered, or a correction loop after challenging a prior answer.
---

# Convergent Dialogue

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

When a structured question UI is available, use it for short, answerable choices. Otherwise ask in
plain text.

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

- Use `plan-task` or an equivalent planning skill when the conversation becomes an implementation plan with steps, validation, or approval gates.
- Use `grill-me` or an equivalent stress-test skill when the user wants a plan, design, or opinion challenged aggressively.
- Use domain-specific skills whenever the target answer depends on specialized tools, schemas, policies, or source material.
