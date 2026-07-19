# Ask Decisions, Not Facts

Before presenting options to the user, check whether the project's framework, conventions, or
existing code already eliminate some of them. If only one option survives, it is not a decision to
hand over: it is a fact to look up and report.

Where to look, in order:

1. Framework documentation vendored in the repo (`deps/`, `vendor/`, the package's own `docs/`).
2. The nearest `AGENTS.md`/`CLAUDE.md` and repository conventions.
3. How the same problem is already solved elsewhere in the codebase.

Then present only the surviving options, stating which ones were eliminated and by what.

Asking for a decision that is already made wastes the user's attention and makes the questions
that genuinely need an answer less credible.
