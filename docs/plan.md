# Generation Station implementation plan

Date: 2026-10-09. Status: React/TypeScript/Vite, native Windows Python/FastAPI, SQLAlchemy/Alembic, and Docker PostgreSQL accepted. The local M1 prototype is implemented and verified; target desktop acceptance is pending. M2 and M3 remain pending.

## Product boundary

Generation Station manages AI model processes and memory on one desktop, controlled through a browser on the desktop or laptop. The first release is a functioning model manager: host telemetry, model catalog, load/unload operations, refusal reasons, and recovery from worker failures.

Generation interfaces, automatic switching, downloads, and agent workflows follow after the memory and lifecycle foundations work. Multiple installed models do not imply simultaneous residency or execution.

## Recommended stack

| Area | Choice | Reason |
| --- | --- | --- |
| Frontend | React, TypeScript, Vite | Familiar from Playtab; suitable for a dashboard with live state. Build static assets for desktop hosting. |
| Styling | CSS modules and shared CSS variables | Small dependency footprint; consistent components and accessible states. |
| Backend | Python, FastAPI, Pydantic, Uvicorn, running natively on Windows | User accepted this choice after comparing Rails; typed API contracts and direct access to host monitoring and model runtime tooling. |
| Persistent state | PostgreSQL 17.11 Bookworm in Docker with a named volume | User-selected database; durable state independent of container replacement. SQLAlchemy 2 + Alembic provide Python access and schema migrations. |
| Host RAM | psutil | Use available physical memory for admission; show used and total separately. |
| GPU telemetry | Vendor adapter; NVML for NVIDIA if applicable | Measure each physical GPU and expose unsupported/error states honestly. |
| Browser updates | REST plus server-sent events | Commands are requests; telemetry and operation status stream to clients. |
| Inference | Supervised subprocesses with independent environments | Allow different runtime dependencies and release process-owned allocations on exit. |
| Verification | pytest, frontend unit tests, Playwright | Focus on admission races, recovery, and the actual browser workflow. |

The backend serves the compiled frontend in production, giving one origin and one application endpoint. Node is needed for frontend development/building, not as a production UI server. Start with one API/scheduler process; inference runs outside it. Avoid multiplying scheduler ownership with multiple Uvicorn workers.

Python is recommended because this service manages model runtimes and host resources. Model kernels execute in their runtime implementations; the HTTP layer is unlikely to be the performance bottleneck. Go or Rust remain options for a future standalone supervisor if measurements justify the added language boundary. A TypeScript backend would share a language with the UI but still need bridges to several inference environments.

Rails provides a structured framework for applications centered on accounts, permissions, and conventional database workflows. FastAPI is selected here because the host API, telemetry, and process supervisor can stay in Python beside the model tooling. Capacity admission and process supervision still need explicit implementation in either framework.

## Database and remote connection

- PostgreSQL runs in Docker with a persistent named volume and versioned schema migrations. Use separate local development and desktop database volumes; no automatic replication is implied. Pin the image version and use its documented data mount path at implementation time.
- Keep database credentials external and restrict database access to the application/host. The browser connects to the application API, never directly to PostgreSQL. Volume persistence is separate from backup/restore, which must be documented.
- Docker is reported available on both machines. This does not establish GPU-container support or make a container's memory view authoritative for the Windows host. The initial recommendation is a containerized database with a native Windows telemetry/supervisor service; verify Docker/WSL2 and driver support before selecting containerized inference.
- Current desktop access is through Tailscale at `100.109.129.35`. The browser now accepts a configurable server origin (including scheme and port); the current IP is not baked into application code. API bearer-token authentication is implemented. The Windows service port, firewall rule, and remote laptop-to-desktop connection still need deployment and verification. Prefer a same-origin UI/API in deployment, with explicit trusted origins if a separate browser client is used.

Exact dependencies are locked for the current prototype. The user reports Windows 11 and an NVIDIA RTX 5090 with 32 GB VRAM on a Ryzen 7 5800X3D desktop with 32 GB DDR4 and a 2 TB NVMe SSD. Free SSD space, driver/runtime compatibility, and memory accounting support remain to be verified; see `docs/context.md`.

## Current implementation status — 2026-10-09

- The API reports the service process's own host identity, RAM, and per-GPU NVML measurements where available. Samples carry age and explicit unknown/stale/degraded states. A Windows-native desktop run has not yet been measured.
- The dashboard accepts a configurable server origin and bearer token; the URL is saved on that browser, while the token stays in memory. It validates host/catalog responses, streams authenticated telemetry, and shows stale, partial, disconnected, and reconnecting states. Model controls are disabled.
- PostgreSQL 17.11 runs as the configured Docker Compose service with a named data volume and Alembic migration. Compose configuration validation passed. The database daemon was unavailable in the development environment, so PostgreSQL migration and persistence integration tests remain unrun here.
- Backend tests: 32 passed; one PostgreSQL-only test skipped without `GS_TEST_DATABASE_URL`. Ruff passes. Frontend production build passes and all 7 Playwright tests pass, including desktop/mobile disconnected layouts and reconnect after an outage longer than the telemetry watchdog.
- This is local prototype verification, not M1 acceptance on the target desktop. M2 capacity admission/fake worker and M3 real inference are not implemented.

## Components and contracts

1. **Web UI:** host summary, model list/detail, load/unload buttons, operation history, connection health, settings.
2. **Host monitor:** timestamped physical RAM and per-device VRAM readings, host identity, telemetry health. Start with a configurable one-second sample interval.
3. **Model registry:** immutable model revision and file paths, runtime version, quantization, device assignment, offload settings, supported operating limits, and memory profile provenance.
4. **Admission controller:** validates telemetry and profiles, calculates incremental requirements, reserves capacity, and records acceptance/refusal atomically under one scheduler owner.
5. **Worker supervisor:** launches approved adapters, waits for readiness, tracks process identity, captures bounded logs, applies timeouts, and stops the owned process tree.
6. **Persistence:** registry/settings, operation records and state transitions. Store large artifacts on disk rather than in PostgreSQL.

Adapters expose start, ready/health, stop, and status. Later adapters add execute, progress, and cancel. A runtime may be a Python package, compiled executable, or managed service. The browser never supplies arbitrary executable commands; adapters validate configuration and permitted model paths.

Suggested API: `GET /api/host`, `GET /api/models`, `POST /api/models/{id}/load`, `POST /api/models/{id}/unload`, `GET /api/operations/{id}`, and `GET /api/events`. Accepted lifecycle commands return operation IDs. Refusals include a stable reason code and required/available RAM and per-GPU VRAM values. Use idempotency keys to avoid duplicate work on browser retries.

Lifecycle: unloaded → checking → loading → ready → unloading → unloaded. Failures produce an explicit error state and cleanup status. A capacity refusal leaves the model unloaded with a recorded refused operation. A process starting is not proof of readiness.

## Capacity policy

Admission is enforced by the backend for every client. A disabled button is explanatory UX only.

For each resource independently, compare additional peak demand with current available capacity minus configured headroom and capacity promised to other operations but not yet reflected in telemetry. RAM and each physical GPU must all pass; GPU capacities cannot simply be summed.

- Profile peak loading memory separately from steady residency and generation memory. Include encoders, decoders, staging copies, caches, and runtime overhead.
- Tie profiles to exact runtime/model/configuration and supported workload bounds. Record whether a value is measured or an explicitly supplied conservative estimate; never derive a reliable peak from file size alone.
- Refuse normal loads with missing profiles, stale/unavailable telemetry, unsupported accounting, or insufficient RAM/VRAM. An explicit profiling workflow comes later; unknown is never silently treated as zero.
- CPU offload must fit available physical RAM. Swap is not ordinary capacity. Unified/shared memory needs dedicated accounting before support is advertised.
- Serialize load/unload operations initially. Reserve inside the scheduler lock before launching; retain reservations through readiness/cleanup. Do not count measured allocations and the same reservation twice. Track only reservation demand not already represented in the current sample; if attribution is unreliable, serialize and wait for fresh post-operation telemetry, conservatively refusing uncertain admissions.
- Loading headroom covers transient allocations; a ready model need not hold its entire loading peak forever. Convert to the appropriate resident/workload policy after readiness and reconciliation.
- Generation Station cannot reserve the GPU against unrelated applications. Monitor external memory changes and handle allocation failure with cleanup and a clear error. Preflight checks reduce risk but cannot guarantee absence of OOM.
- Recheck fresh telemetry after unload. Never credit the model's estimated footprint as if it were already released.
- Before later generation requests, admit additional runtime memory using limits such as context length, resolution, frame count, and batch size. Changing these limits requires a compatible profile.

## Interface behavior

- Persistent header identifies the desktop and connection health. RAM and VRAM cards show used/total, available, and reserved headroom, with per-GPU cards where applicable.
- Model rows show name, workload, configuration, state, and Load/Unload. Details show profile source, expected requirements, runtime, and last error.
- Refused Load actions explain the limiting resource and shortage. Stale or disconnected values visibly stop being presented as live; state-changing controls are disabled until reconnection and a fresh snapshot.
- Loading/unloading show progress when the runtime exposes it, otherwise an honest indeterminate state. Never fabricate a percentage.
- Unload of a busy worker is refused by default. Later provide a distinct cancel-and-unload operation where cancellation is supported.
- Refusals never silently unload another model. Automatic eviction is a later explicit policy.

## Delivery milestones

### M0 — Context and desktop inventory

Deliver repository plan, project context, stack decision, desktop inventory, and first model/runtime choice. The stack and user-reported inventory are recorded; selecting a first feasible workload and verifying desktop capabilities remain open. Check actual available weights and runtime compatibility. Done when we can identify one bounded workload that should fit the target host; candidates too large for the machine remain unsupported.

### M1 — Web shell and real host telemetry

Create the frontend/backend shell, PostgreSQL migrations and Docker Compose database service, settings, monitoring adapters, and event stream. The local prototype is implemented and verified; target desktop telemetry and remote access acceptance remain pending. Use fake telemetry only in clearly marked browser-test fixtures. Done when the laptop browser shows the desktop's measured RAM/VRAM, stale data is visible, and reconnect restores a fresh snapshot. Remote access must authenticate users and protect state-changing requests; the bearer-token API is implemented, but the desktop firewall and connection still require verification.

### M2 — Admission controller and lifecycle with a fake worker

Implement profiles, operations, scheduler ownership, reservations, refusal explanations, readiness timeouts, process-tree cleanup, and restart reconciliation. Done when simultaneous browser requests cannot over-admit, duplicate commands are idempotent, stale/unknown capacity refuses loading, and failed workers release their reservations after cleanup. Backend refusal must work even when the API is called directly.

### M3 — First real model on the desktop

Implement one compatible adapter and establish its memory profile on the desktop. Done when the browser loads the model to actual readiness, a minimal inference proves it works, unload ends the worker, telemetry confirms release, and an oversized profile is refused without launching a process. Repeat load/unload cycles to identify retained allocations. Record versions and measurements.

This is the first usable release: manual model management with trustworthy host telemetry and capacity refusal.

### M4 — Second runtime and switching

Add a different modality and environment. Done when model A can unload, model B can load and work, and A can return without manual process management. Preserve user data outside worker memory; persist conversations but acknowledge that unloaded inference caches may need rebuilding.

### M5 — Jobs and remaining modalities

Add durable job queue, per-request capacity checks, output library, cancellation, and the remaining compatible video/music/coding adapters. Expose an endpoint compatible with the chosen coding client's streaming and tool-call requirements. A coding model endpoint alone is not a complete coding agent. Mark interrupted jobs explicitly on restart; never promise arbitrary checkpoint/resume.

### M6 — Scheduling and desktop operation

Add explicit priority/eviction policies, measured concurrency, bounded logs/history, startup service, upgrade procedure, and authenticated remote access hardening. Profile larger workloads individually. Concurrent execution is enabled only for measured combinations with sufficient headroom; the user still needs to choose coding-versus-media priority.

## Validation and operational recovery

- Unit tests: capacity boundaries, headroom, per-device accounting, missing/stale samples, profile mismatches.
- Integration tests: concurrent admissions, crashes during load, readiness timeout, unload failure, duplicate commands, service restart and orphaned workers.
- Browser tests: telemetry, refusal explanation, state transitions, reconnect and busy-worker controls.
- Desktop acceptance: compare host measurements with OS/vendor tools; measure peaks during load and inference; confirm unload and repeated cycles; exercise one external-memory-pressure scenario under controlled conditions.
- On restart, reconcile persisted state with verified owned processes and fresh telemetry before permitting new loads. Never trust stored `ready` flags or a reused PID alone. Do not terminate unrelated processes.

## Proposed project layout

```text
generationstation/
  frontend/                 React application
  backend/generationstation/
    api/                    HTTP and event endpoints
    telemetry/              RAM and GPU providers
    admission/              budgets and reservations
    supervisor/             lifecycle and process ownership
    adapters/               runtime integrations
    storage/                persistence and migrations
  tests/                    integration and desktop acceptance helpers
  docs/                     plan, decisions, host profiles
```

## Sources consulted

- Local Playtab `package.json` confirms React/TypeScript/Vite.
- [React: building from scratch](https://react.dev/learn/build-a-react-app-from-scratch)
- [Vite guide](https://vite.dev/guide/)
- [Rails getting started](https://guides.rubyonrails.org/getting_started.html)
- [PostgreSQL official Docker image](https://hub.docker.com/_/postgres)
- [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/) and [official image tags](https://hub.docker.com/_/postgres) (checked 2026-10-08; 17.11 is the current maintained 17.x minor and has a matching Bookworm tag).
- [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [SQLAlchemy engine configuration](https://docs.sqlalchemy.org/en/20/core/engines.html)
- [Docker Desktop GPU support on Windows](https://docs.docker.com/desktop/features/gpu/)
- [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/)
- [psutil memory documentation](https://psutil.readthedocs.io/stable/index.html)
- [NVIDIA NVML reference](https://docs.nvidia.com/deploy/nvml-api/latest/)

Previously identified model sources must be checked again for the exact selected checkpoints at M0: [MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3), [Qwen-Image 2.1](https://qwen.ai/blog?id=qwen-image-2.1), [YuE2](https://arxiv.org/abs/2609.33757), [Qwen3.8-Flash-Next architecture](https://arxiv.org/abs/2608.30320). No desktop fit or runtime compatibility has been established in this planning session.
