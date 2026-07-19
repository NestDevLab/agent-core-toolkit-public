# Skill naming and role guidance

## Skill names

Use a name that makes the ownership boundary clear while keeping public skills portable.

| Scope | Prefix |
| --- | --- |
| Public core toolkit | Bare (no prefix) |
| Private core and organization-private toolkits | Organization prefix (`im-`) |
| Domain-private toolkits | Domain prefix (for example, `tirrenia-`) and hyphens rather than underscores |
| ChromieCraft/Drassil | `cc-` |
| Karan / Vitae | `karan-` / `vitae-` |
| Product skills in their own repositories | Unchanged |
| Third-party skills and forks | Unchanged |

A skill rename updates its directory, `SKILL.md` frontmatter `name`, co-located agent metadata, and internal self-references together.

## Rules and roles

Global rules contain only cross-role invariants. Role-specific guidance belongs in role fragments and is consumed by the relevant subagent or role skill.
