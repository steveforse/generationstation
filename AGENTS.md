# Generation Station project guidance

For implementation work, delegate code creation to Luna (`gpt-6-luna`) when available. The primary agent scopes and guides the implementation, then reviews the result and performs requested verification. Do not delegate all review or project ownership to Luna.

Read `docs/context.md` and `docs/plan.md` before implementation. Stack decisions are proposals until accepted by the user. The deployment target is a separate desktop; never infer its capabilities from this laptop.

Repository Markdown is authoritative for project design. BookStack mirrors and page IDs are listed in `docs/bookstack.json`. Keep corresponding pages synchronized after substantive context or plan changes, using the shared `../bookstack-agent-cli` client and its external credential configuration. Read the current page before updating and use the expected revision timestamp guard. If synchronization is unavailable, record that fact rather than claiming it succeeded.

Keep model weights, generated outputs, credentials, and runtime caches out of source control. The host API must enforce capacity checks independently of the browser. Unknown/stale capacity must not permit a normal load.
