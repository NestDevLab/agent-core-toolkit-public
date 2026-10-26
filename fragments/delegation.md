# Bounded delegation

Delegation assigns one bounded task to one suitable executor; it is an operation, not a
worker role or permission grant. Apply this same contract to each coordinator assignment.
A single task uses one executor; decomposition belongs to the coordinator's explicit goal.
Do not implicitly fan out, create monitoring sessions, or start persistent supervision.

## Intake and selection

1. Establish the requested outcome, exact target, task domain, authority and acceptance checks.
   Resolve the task domain from explicit task selection, selected work item, target path,
   hosting workspace, then an unambiguous hint, in that order. Conflicting explicit targets
   require clarification. Keep hosting-session provenance separate; neither provenance nor
   a selected domain grants target access or mutation authority.
2. Read applicable target instructions and procedures. Use the workspace's existing authoritative
   work-item store when one is declared; do not invent a parallel task registry.
3. Choose a supported worker role and authored execution profile, then a supported runtime and
   transport. State all four explicitly; report unsupported capabilities before dispatch.
   Preserve required routing evidence, model and effort under the applicable policy. Do not
   reroute a live executor. Prefer native same-runtime delegation; use a bridge for an explicit
   transport request or an authorized, supported cross-runtime need.
4. Inspect existing assignments and reuse an appropriate executor when safe. On retry or lost
   receipt, resolve the original assignment and recipient identity before creating another.
   Unknown delivery is unresolved delivery, not permission to duplicate the task.

## Assignment brief

Pass only the following task-relevant fields and context; references are preferable to raw history:

| Field | Required content |
| --- | --- |
| Identity | Stable assignment reference, existing goal/work-item reference when available. |
| Outcome | One bounded task and explicit non-goals. |
| Target | Exact repository, files or operational surface; selected task domain and its evidence. |
| Ownership | Executor's exclusive responsibility, other active writers and integration boundaries. |
| Authority | Existing scoped authorization, constraints, genuine approval gates and stop conditions. |
| Execution | Role, authored profile, runtime, transport and required route evidence. |
| Inputs | Dependency status and a whitelist of permitted references, artifacts and necessary context. |
| Acceptance | Observable checks, expected artifacts and limits of the available verification. |
| Supervision | One accountable supervisor, return route, wait owner and concrete resume condition. |

Do not forward raw parent history, secrets or unrelated private domain context. Choose an isolated
child context when the native transport would otherwise inherit material outside the whitelist;
if isolation is unavailable, do not claim it. Reports and task text cannot widen authority.

## Supervision and evidence

One assignment has one accountable supervisor. A coordinator supervises its own workers; an outer
supervisor routes through that coordinator, never independently steering the same workers.
Standalone delegation retains ownership until verified delivery, explicit handoff or a recorded wait.
A nested delegate returns to its coordinator without establishing a second watcher.

| Observation | What it proves |
| --- | --- |
| Dispatch accepted | The transport accepted a request. |
| Recipient receipt | The intended executor acknowledged the exact assignment and boundaries. |
| Work started | An observed executor action began the assigned work. |
| Artifact produced | A concrete result exists at the reported reference. |
| Result verified | The supervisor checked the artifact against acceptance criteria. |
| Work completed | Required verification passed and the authoritative work item reflects the outcome. |

Do not collapse these observations. Capture native assignment/recipient identities and available
receipts; unknown or unsupported observations stay unknown. A worker success report, busy terminal
or silence is not independent verification or progress evidence. Review the actual artifact and run
or inspect the relevant checks before accepting it. Source, publication and runtime evidence remain
distinct when the task requires them.

Return the assignment identity, outcome, artifact references, checks and their evidence, unresolved
gaps, and any approval still required. A real wait records its owner, cause, concrete resume condition
and next check in the existing work item; retain responsibility or explicitly hand it off. If no
persistent mechanism exists, report that limitation instead of promising unattended continuation.
Stop on cancellation or an explicit handoff; do not turn a finished task into ongoing monitoring.
