# Conversation handoff prompts

## Source extraction

> Extract the context needed to continue **[objective]** from your available history and
> authoritative artifacts. Reply with the current objective and state, verified outcomes
> with references and dates, decisions and rationale, relevant rejected options, open work,
> blockers, owners, approval boundaries, and the next safe action. Identify superseded
> information, unresolved conflicts, and any history or artifacts you could not inspect.
> Separate observations, source-backed claims, and assumptions. Keep only what the next
> conversation needs. Exclude secrets, raw transcripts, unrelated personal data, and stale
> instructions. This is a read-only request. Return the extraction in this conversation.

## Successor startup

> Continue **[objective]** in **[workspace]**. Read the private handoff at **[path]** and use
> the `conversation-handoff` resume procedure with SHA-256 **[fingerprint]**. Revalidate
> relevant state and authorization against current sources. First acknowledge the fingerprint,
> actual workspace, objective, and next safe action, or report a mismatch or capability gap.
> Proceed only with work covered by the current request and permissions.
