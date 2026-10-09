# Generation Station session handoff

> Update, 2026-10-09: renamed to **Generation Station**, now at `/home/sforse/git/generationstation`. Desktop: Ryzen 7 5800X3D, 32 GB DDR4 RAM, 2 TB NVMe SSD (total capacity). GPU: NVIDIA RTX 5090 with 32 GB VRAM. OS: Windows 11. Free storage remains unknown. Accepted stack: React/TypeScript/Vite, native Windows Python/FastAPI, SQLAlchemy/Alembic, and PostgreSQL 17.11 in a persistent Docker container. Tailscale desktop address: `100.109.129.35` (configurable, may change). Local M1/M2 implementation and available checks pass, but live PostgreSQL integration and target-desktop acceptance remain pending. M2's process-local fake worker performs no inference. M3 remains pending. See `docs/context.md`, `docs/plan.md`, and `docs/development.md` for current status and setup; the original handoff below is a historical snapshot.

Prepared: 2026-10-08. Current project path: `/home/sforse/git/generationstation`.

## Current handoff

The stack decision and local M1/M2 prototype are implemented. Backend pytest reports 69 passed and one PostgreSQL-only integration test skipped because `GS_TEST_DATABASE_URL` was not set; Ruff passes. The frontend build and all 11 Playwright tests pass. Compose configuration and Alembic offline SQL validate, but no live PostgreSQL migration/admission run occurred. M1 still needs a Windows desktop deployment, real RAM/VRAM comparison, and authenticated Tailscale browser acceptance; do not mark it complete based on laptop-only work. M2's fixed fake worker tests lifecycle only: it performs no inference and loads no model weights. PostgreSQL-backed admission and target desktop validation remain pending. M3 real-model verification is pending. The first workload and exact checkpoint/runtime remain undecided. Never claim candidate model support until it is demonstrated on the desktop.

The first-session notes below are retained as a historical record and contain superseded questions and paths. For current facts and decisions, use `docs/context.md` and `docs/plan.md`.

## Historical first-session handoff

Read `AGENTS.md`, `docs/context.md`, and `docs/plan.md`. The user is moving into a fresh session in this project directory to continue planning and then implementation.

## What the user wants

ModelDock is a web application that manages multiple AI models on a desktop with limited system RAM and VRAM. The laptop is a browser client and development machine; the separate desktop hosts inference and supplies the memory telemetry.

Confirmed requirements:

- Working project name: **ModelDock**.
- Explicit **Load** and **Unload** controls for models.
- Show current desktop RAM and VRAM usage.
- Refuse model loading when the desktop lacks sufficient capacity. Enforce this in the backend, independently of browser controls.
- Use BookStack for persistent project context, following sister projects such as Playtab.

Candidate models named by the user: MiniMax H3 for video, Qwen-Image 2.1 for images, YuE2 for music, and Qwen3.8-Flash-Next for agentic coding. These are desired candidates; compatibility and fit on the desktop have not been established. Source links are in the plan. Validate exact checkpoints, quantizations, and runtimes before promising support.

## Proposed stack — not yet explicitly accepted

- Frontend: **React + TypeScript + Vite**, matching Playtab's frontend stack.
- Backend: **Python + FastAPI**, served by Uvicorn.
- Persistence: **SQLite**; weights and generated artifacts stay on the desktop filesystem.
- Browser communication: REST commands and server-sent events for live telemetry/status.
- Monitoring: psutil for RAM; GPU vendor adapters, using NVML if the desktop has NVIDIA GPUs.
- Execution: supervised worker subprocesses with separate runtime environments.
- Deployment: backend serves compiled frontend assets; one desktop service and one scheduler owner initially.

The user asked for a language/framework recommendation, received these recommendations, then requested this handoff. Do not record the stack as an explicitly approved user decision.

## Plan and first usable release

The detailed plan in `docs/plan.md` includes architecture, API sketch, lifecycle, admission policy, interface behavior, acceptance criteria, and validation.

1. **M0:** Agree on stack, obtain desktop inventory, select first feasible model/runtime.
2. **M1:** Web shell and real desktop RAM/VRAM telemetry, including stale/disconnected states.
3. **M2:** Admission controller and lifecycle with a fake worker; reservations, refusal reasons, idempotency, cleanup, and restart reconciliation.
4. **M3:** First real model on the desktop; load, prove inference works, unload, verify memory release, and refuse an oversized load.
5. **M4:** Second runtime and reliable switching between model types.
6. **M5:** Generation jobs, outputs, cancellation, remaining compatible modalities, and coding-client integration.
7. **M6:** Priority/eviction policies, measured concurrency, and desktop service operation.

**M3 is the first usable release.** Prioritize reliable manual model management before automatic scheduling and elaborate generation interfaces.

## Important architectural constraints

- Monitor the desktop host, not the laptop or an accidentally isolated container's memory view.
- Check RAM and each relevant GPU independently, with configurable headroom and loading peaks. VRAM cannot simply be pooled across GPUs.
- Unknown profiles, stale telemetry, or unsupported accounting refuse normal loading.
- Tie profiles to exact model/runtime/configuration and workload limits. Weight file size alone is insufficient.
- Serialize lifecycle operations initially. Reserve capacity atomically and avoid double counting reservations already represented in telemetry.
- CPU offload consumes RAM; swap is not ordinary available capacity.
- Recheck actual telemetry after unload; do not assume the estimated footprint was released.
- External applications can allocate memory after admission. Handle allocation failure and cleanup; do not promise an absolute OOM guarantee.
- Later generation requests require their own memory checks for context length, resolution, duration, batch size, and other workload settings.
- Keep model execution outside the API process. Handle readiness, process trees, crashes, and stale persisted state explicitly.
- BookStack is for development context; application operation must not depend on its availability.

## BookStack and continuity

Book: [ModelDock](https://bookstack.forse.co/books/modeldock), ID **63**.

| Page | ID | Local authoritative source |
| --- | --- | --- |
| [Project Context and Decisions](https://bookstack.forse.co/books/modeldock/page/project-context-and-decisions) | 64 | `docs/context.md` |
| [Architecture and Implementation Plan](https://bookstack.forse.co/books/modeldock/page/architecture-and-implementation-plan) | 65 | `docs/plan.md` |

Both pages were created and read back successfully; their Markdown matches the local sources apart from BookStack stripping trailing whitespace. `docs/bookstack.json` records IDs, URLs, and the observed revision timestamps. Fetch current revisions before updates rather than treating those saved timestamps as current forever.

Shared client: `/home/sforse/git/bookstack-agent-cli`. Credentials are loaded from external configuration at `~/.config/bookstack/codex.env`; never print or commit them. The executable was not on PATH in the previous session, so invoke the module:

```sh
PYTHONPATH=/home/sforse/git/bookstack-agent-cli/src python3 -m bookstack_agent_cli page 64 --markdown
PYTHONPATH=/home/sforse/git/bookstack-agent-cli/src python3 -m bookstack_agent_cli page 65 --markdown
```

Read the sibling client's README for update commands. Update local authoritative documents first, then mirror them using the current page's expected revision timestamp. The timestamp guard is a best-effort client check. This handoff is a local session snapshot; the two existing BookStack pages remain the persistent plan/context mirrors.

## Work completed and not completed

Completed: inspected Playtab's frontend stack and documentation convention; accessed BookStack through the shared client; created the project directory, README, AGENTS guidance, plan, context, and BookStack mapping; published and read back the two BookStack pages.

No application code, dependency installation, runtime installation, model downloads, deployment, tests, or desktop benchmarks have been performed. No project Git initialization or commit was performed. Check repository boundaries before the first Git operation because this folder lives among sister projects in a shared workspace.

## Missing inputs and next action

The user has not yet supplied:

- Desktop OS, CPU, GPU vendor/model/count, per-GPU VRAM, system RAM, and available SSD space.
- Desktop network access method or existing VPN/private network.
- First model/workload to implement and acceptable loading/generation latency.
- Priority when coding and media jobs compete for memory.

Resume by briefly confirming the proposed stack and asking for desktop specifications. Continue hardware-independent design/scaffolding when authorized, but do not infer desktop capabilities from this laptop. Record accepted decisions and supplied hardware in the context, then keep its BookStack mirror synchronized.
