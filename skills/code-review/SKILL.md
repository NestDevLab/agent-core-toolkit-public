---
name: code-review
description: Review code, configuration, or documentation for correctness, safety, maintainability, and missing validation.
---

# Code Review Skill

Use this skill when asked to review a proposed change, patch, configuration, or technical document.

## Review Stance

- Start with findings, ordered by severity.
- Focus on bugs, regressions, safety issues, boundary violations, and missing validation.
- Tie each finding to a concrete file, behavior, or requirement.
- Separate blocking issues from optional improvements.

## Process

1. Read the relevant instructions and the changed files.
2. Identify the intended behavior and validation expectations.
3. Check for correctness, edge cases, data handling, and operational risk.
4. Report findings first. If no issues are found, say that plainly and note residual risk.

## Output

Use concise sections:

- Findings
- Open questions
- Validation gaps
- Summary
