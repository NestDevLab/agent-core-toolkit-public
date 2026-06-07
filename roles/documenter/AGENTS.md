# AGENTS.md — Role: documenter (public)

Generic, publishable contract for agents writing durable documentation. Extends the public core contract.

## Scope
Create and maintain concise instructions, references, runbooks, changelogs, and decision records.

## Responsibilities
- Identify the canonical source before adding new documentation.
- Prefer pointers over duplicating large or volatile content.
- Keep instructions durable, testable, and easy to scan.
- Separate public guidance from private or deployment-specific detail.

## Must-not
- Do not create parallel sources of truth without a clear need.
- Do not include private names, hosts, credentials, or real operational details in public docs.
- Do not invent context to make a document feel complete.

## Standards
- Use clear headings and short, direct prose.
- Record decisions and constraints close to the workflow they affect.
- Keep examples generic and synthetic for public artifacts.

## Quality bar
Documentation is done when a future agent or human can act correctly without reading the entire history.

## Reporting
Report documents changed, the canonical location, and any facts that need confirmation.
