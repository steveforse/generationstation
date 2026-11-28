# Generation Station project guidance

For implementation work, delegate code creation to Luna (`gpt-6-luna`) when available. The primary agent scopes and guides the implementation, then reviews the result and performs requested verification. Do not delegate all review or project ownership to Luna.

Read `docs/context.md` and `docs/plan.md` before implementation. Stack decisions are proposals until accepted by the user. The deployment target is a separate desktop; never infer its capabilities from this laptop.

Repository Markdown is authoritative for project design.

Keep model weights, generated outputs, credentials, and runtime caches out of source control. The host API must enforce capacity checks independently of the browser. Unknown/stale capacity must not permit a normal load.
