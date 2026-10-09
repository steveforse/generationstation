# Generation Station implementation plan

Date: 2026-10-09. Status: React/TypeScript/Vite, native Windows Python/FastAPI, SQLAlchemy/Alembic, and Docker PostgreSQL accepted. Local M1/M2 implementation and available checks pass; live PostgreSQL integration and Windows target desktop acceptance remain pending. M3 remains pending.

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
- The dashboard accepts a configurable server origin and bearer token; the URL is saved on that browser, while the token stays in memory. It validates host/catalog/profile/operation responses, streams authenticated telemetry, and shows stale, partial, disconnected, and reconnecting states. It exposes explicitly labeled simulation-profile and fake-worker controls when host data permits; the backend still checks every load request.
- PostgreSQL 17.11 runs as the configured Docker Compose service with a named data volume and Alembic migration. Compose configuration and Alembic offline SQL validation passed; the PostgreSQL integration test was skipped because `GS_TEST_DATABASE_URL` was not configured, so no live database migration, persistence, or admission transaction was exercised.
- Backend pytest: 69 passed, 1 PostgreSQL-only test skipped. Ruff passes. Frontend production build passes and all 11 Playwright tests pass. These are local checks, not a Windows desktop run.
- M2 profile/admission routes and the process-local fake-worker lifecycle are implemented. M2 tests exercise refusal, per-device accounting, reservations, idempotency, operation cleanup, and restart reconciliation through test fixtures. The fake worker starts no OS process, opens no model files, and runs no inference. PostgreSQL-backed reservation/advisory-lock integration and target desktop end-to-end validation remain pending. M3 real inference remains unimplemented.

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

Deliver repository plan, BookStack context, stack decision, desktop inventory, and first model/runtime choice. The stack and user-reported inventory are recorded; selecting a first feasible workload and verifying desktop capabilities remain open. Check actual available weights and runtime compatibility. Done when we can identify one bounded workload that should fit the target host; candidates too large for the machine remain unsupported.

### M1 — Web shell and real host telemetry

Create the frontend/backend shell, PostgreSQL migrations and Docker Compose database service, settings, monitoring adapters, and event stream. The local prototype is implemented and verified; target desktop telemetry and remote access acceptance remain pending. Use fake telemetry only in clearly marked browser-test fixtures. Done when the laptop browser shows the desktop's measured RAM/VRAM, stale data is visible, and reconnect restores a fresh snapshot. Remote access must authenticate users and protect state-changing requests; the bearer-token API is implemented, but the desktop firewall and connection still require verification.

### M2 — Admission controller and lifecycle with a fake worker

The local implementation and application tests are complete. It adds explicit per-model simulation profiles and backend-enforced admission, serializes lifecycle transitions, exposes operation/refusal status, and exercises a fixed fake worker for load/unload behavior. The fake worker is a lifecycle fixture only: it performs no inference, loads no model weights, and cannot establish real memory needs, desktop fit, or runtime compatibility. A successful simulation load must never be presented as support for a real model.

Current simulation headroom defaults are 4 GiB of system RAM and 2 GiB for each assigned GPU, configurable with `GS_RAM_HEADROOM_BYTES` and `GS_GPU_HEADROOM_BYTES`. These are provisional engineering cushions, not values measured from the target desktop or a model. Admission requires desktop/host scope, a non-stale sample with finite age below its stale window, valid RAM measurements, and complete per-GPU accounting with unique identifiers. For each requested resource independently, subtract the configured headroom and all active reservations from currently available bytes; match GPUs by their exact reported identifiers rather than pooling VRAM. Document any later change from measured desktop baseline.

The simulation profile contract is `id`, `name`, `workload`, positive `ram_peak_bytes`, `gpu_vram_bytes_by_id` keyed by exact host device IDs, and `mode: "simulation"`. In the create request, `id` is the model slug; the response has a separate profile UUID `id` and `model_id`. Profiles can be created with `POST /api/profiles`, inspected with `GET /api/profiles`, updated with `PUT /api/profiles/{model_id}`, and removed with `DELETE /api/profiles/{model_id}`. Deleting a profile preserves its model identity and operation history, so the same model ID can be profiled again. A profile cannot be changed or deleted while its fake worker is active. Each load uses `POST /api/models/{model_id}/load` with the profile UUID as `profile_id` and an `Idempotency-Key` header; unload uses `POST /api/models/{model_id}/unload` with its own idempotency key. Both return HTTP 202 and an asynchronous operation record with an operation ID; poll `GET /api/operations/{operation_id}` or read recent records through `GET /api/operations?limit=100`. Unload remains available even when telemetry is stale. A refusal returns HTTP 409 with `{code,message,operation_id,resources}`; resource entries contain `resource`, `required_bytes`, `available_bytes`, and `headroom_bytes`. Key reuse for another request returns `IDEMPOTENCY_KEY_REUSED`. This entire API is authenticated with the host bearer token.

M2 operation responses set `simulation: true` and `worker_type: "fake"`. Persisted statuses are `loading`, `simulation_ready`, `unloading`, `unloaded`, `refused`, `failed`, and `cleanup_failed`; a future `checking` status is not currently emitted. Refusal codes include `HOST_ROLE_UNSUPPORTED`, `TELEMETRY_STALE`, `TELEMETRY_UNKNOWN`, `GPU_ACCOUNTING_UNSUPPORTED`, `PROFILE_NOT_FOUND`, `PROFILE_INVALID`, `MODEL_BUSY`, `INSUFFICIENT_RAM`, and `INSUFFICIENT_VRAM`.

Profile values must be explicit; do not infer model memory from file size. The API must reject profiles that are missing or invalid, and fail closed on stale/unknown host capacity or unsupported resource accounting. Checks must apply to direct API calls, not only disabled browser controls. Normal real-model loads remain unavailable until a real adapter and measured profile are established.

Local backend pytest reports 69 passed and one PostgreSQL-only test skipped; Ruff passes. Application tests cover over-admission with the test store, idempotency, resource refusals, cleanup failures, and restart reconciliation. The skipped PostgreSQL integration test means live database transaction/advisory-lock behavior is not verified. Complete M2 acceptance after the PostgreSQL-backed integration and deployed-host checks; this milestone does not prove model fit. The fake adapter is process-local and starts no OS process; after service restart, reconcile simulation operations as failed and clear their reservations because no fake handle survived. Restart/reconciliation behavior must not trust stale ready state or terminate unrelated processes.

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
  docs/                     plan, decisions, host profiles, BookStack mapping
```

## Sources consulted

- Local Playtab `package.json` confirms React/TypeScript/Vite; `docs/design/appearance-settings.md` describes an authoritative repository document mirrored to BookStack.
- Shared `../bookstack-agent-cli/README.md` documents credential configuration and revision-aware page updates.
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
