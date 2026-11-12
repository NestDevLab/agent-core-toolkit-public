---
name: plexus-ledger-view
description: Show, filter or sort the Plexus ledger list with linked sessions and app threads.
license: MIT
metadata:
  version: "1.0"
---

# Plexus ledger view

Use the installed Agent Mesh command and its private view profile. The same
`plexus.ledger-view/v1` schema serves CLI and gateway consumers.

```bash
mesh-graph query view --format md
mesh-graph query view --sort due:asc,priority:asc,size:asc --format md
mesh-graph query view --filter 'waitingOnOwner=true' --format md
mesh-graph query view --filter '{"fields.example":{"contains":"value"}}' --format md
```

If `mesh-graph` is absent from PATH, use the configured Agent Mesh installation's
`bin/mesh-graph.mjs` through Node. If neither is available, report the missing command.

Translate the requested ordering and predicates into command arguments. Nested fields
use dotted paths, including `sessions.role` and `groups.ref`. Filters accept scalar
equality or `eq`, `ne`, `in`, `lt`, `lte`, `gt`, `gte`, `contains`, `exists`. Repeat
`--filter` to combine fields. Default order is waiting for the owner first, due date,
priority, size, with empty dates last within each partition.

Return the command's Markdown and preserve its links and unknown values. Report source
errors. Describe project fallbacks explicitly when `--fallback project` is requested.
The default fallback is the configured project Director thread. Thread mappings,
project aliases and sort ranks belong in private configuration.

For an authenticated API request, call `mesh_plexus_work_items` with
`view: "plexus.ledger-view/v1"` and `format: "md"`. Carry the verified principal on
every request. Follow `structuredContent.next_cursor` with the same query to obtain all
Markdown pages. JSON mode exposes `next_cursor` directly. Preserve row numbering and
combine pages without repeated headings. Report an incomplete read if paging fails.
The versioned view requires the owner principal. Each page rechecks grants and source
revisions. On a stale cursor, restart the query and discard prior pages.
