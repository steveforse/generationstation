# Generation Station implementation plan

Date: 2026-11-28. Status: the first release is built and in use on a Mac and the Windows desktop (the dashboard, the host API, admission, plugins and workers, generation jobs, chat and the consolidated pages). This document is the architecture and the contracts that stay true; what exists today is in `docs/context.md`, measurements are in `docs/model-notes.md`, and open work is in `docs/todo.md`.

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
| Inference | Model plugins: supervised native processes (Basalt, Strata, oMLX) and per-model Python workers in their own environments | Allow different runtime dependencies and release process-owned allocations on exit. A containerized runtime would need Docker/WSL2 memory accounting in admission. |
| Verification | pytest, frontend unit tests, Playwright | Focus on admission races, recovery, and the actual browser workflow. |

The backend serves the compiled frontend in production, giving one origin and one application endpoint. Node is needed for frontend development/building, not as a production UI server. Start with one API/scheduler process; inference runs outside it. Avoid multiplying scheduler ownership with multiple Uvicorn workers.

Python is recommended because this service manages model runtimes and host resources. Model kernels execute in their runtime implementations; the HTTP layer is unlikely to be the performance bottleneck. Go or Rust remain options for a future standalone supervisor if measurements justify the added language boundary. A TypeScript backend would share a language with the UI but still need bridges to several inference environments.

Rails provides a structured framework for applications centered on accounts, permissions, and conventional database workflows. FastAPI is selected here because the host API, telemetry, and process supervisor can stay in Python beside the model tooling. Capacity admission and process supervision still need explicit implementation in either framework.

## Database and remote connection

- PostgreSQL runs in Docker with a persistent named volume and versioned schema migrations. Use separate local development and desktop database volumes; no automatic replication is implied. Pin the image version and use its documented data mount path at implementation time.
- Keep database credentials external and restrict database access to the application/host. The browser connects to the application API, never directly to PostgreSQL. Volume persistence is separate from backup/restore, which must be documented.
- PostgreSQL runs in Docker Desktop on the Windows desktop; model workers run natively.
- Remote access is through Tailscale. The browser accepts a configurable server origin (scheme and port); no address is baked into application code. Prefer a same-origin UI and API in deployment, with explicit trusted origins if a separate browser client is used. The browser's full remote connection and reconnect flow against the desktop is still to be checked end to end.

Exact dependencies are locked. Measured model peaks are recorded per model in `docs/model-notes.md`.

## Current implementation

- The runtime catalog (`runtimes.json`, local; templates `runtimes.example.json` and `runtimes.mac.example.json` committed) selects a plugin per entry with `kind`. The browser can only choose a preset, GPUs and the plugin's bounded settings.
- Process supervision owns each started process tree, checks PID start times before stopping, re-adopts a ready process after an API restart, stops orphans of interrupted loads, detects crashes, and refuses `PORT_IN_USE` when a runtime runs outside the app. Estimate-based admission reserves capacity until readiness.
- Generation: workers speak the `workers/gs_worker.py` protocol; jobs are stored in PostgreSQL (migration 0004) with inputs validated against each plugin's form; finished files are served only from the job's own output folder.
- The dashboard is multi-host: each saved host has its own session (telemetry stream, catalog, actions) and hash routes (`#/hosts/<host>/models`, `#/hosts/<host>/images` and so on). The Models page holds every model's settings, start and stop, refusals naming the GPU, start and stop history and the host's RAM and VRAM cards, with each running model's share; kinds that share a page (Images, Music, Speech, Video, Transcription, Decision, Chat) have one page each. Hosted chat models and workflows have tabs of their own.
- Per-model memory (2026-11-12, display only): the host snapshot's `model_memory` maps each running runtime's model ID to `ram_bytes` (working set of its owned process tree), `gpus` (VRAM bytes by GPU UUID) and `error`. NVML reports no per-process VRAM for WDDM GPUs, so on Windows it comes from the `GPU Process Memory(*)\Dedicated Usage` performance counters, matched to NVML GPUs by PCI bus through D3DKMT adapter addresses; other hosts use NVML's per-process figures. Verified on the desktop: a 2 GiB PyTorch allocation on the RTX 5090 read 2,479.6 MiB, matching nvidia-smi. Admission never uses these figures.
- Start preview (2026-11-12, display only): `POST /api/runtimes/{id}/estimate` takes the start body (`preset`, `settings`, `gpus`) and returns what that start would ask admission for (`ram_bytes`, `gpu_vram_bytes_by_id`), the configured headroom, and active reservations; it writes nothing. A stopped model's card shows each resource as needed versus free after headroom and reservations, with Fits or the shortfall, and the Models page draws the hovered or focused model's need as a hatched segment after current use (red when it won't fit). The start request is still checked independently.
- Chat, the help assistant, the chat tools, optional hosted chat models and meeting notes are described in `docs/context.md`.

## Components and contracts

1. **Web UI:** host summary, model servers with start/stop and settings, generation forms built from plugins and their results, simulation profiles, operation history, connection health, settings.
2. **Host monitor:** timestamped physical RAM and per-device VRAM readings, host identity, telemetry health. Start with a configurable one-second sample interval.
3. **Model registry:** immutable model revision and file paths, runtime version, quantization, device assignment, offload settings, supported operating limits, and memory profile provenance.
4. **Admission controller:** validates telemetry and profiles, calculates incremental requirements, reserves capacity, and records acceptance/refusal atomically under one scheduler owner.
5. **Worker supervisor:** launches only approved plugin launch descriptions, waits for readiness, tracks process (or, for a container runtime, container) identity, captures bounded logs, applies timeouts, and stops only the owned worker. Uncertain ownership or exit retains the capacity reservation.
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

M0 to M3 are done: the context and inventory, the web shell with real host telemetry, the admission controller with a lifecycle fixture (simulation profiles and a fake worker, kept for testing the capacity rules; their routes remain but have no page), and the first real models (Basalt text, then the generators). Repeated load and unload cycles to look for retained allocations are still worth running on the desktop.

### M2 contracts (still enforced)

Current simulation headroom defaults are 4 GiB of system RAM and 2 GiB for each assigned GPU, configurable with `GS_RAM_HEADROOM_BYTES` and `GS_GPU_HEADROOM_BYTES`. These are provisional engineering cushions, not values measured from the target desktop or a model. Admission requires desktop/host scope, a non-stale sample with finite age below its stale window, valid RAM measurements, and complete per-GPU accounting with unique identifiers. For each requested resource independently, subtract the configured headroom and all active reservations from currently available bytes; match GPUs by their exact reported identifiers rather than pooling VRAM. Document any later change from measured desktop baseline.

The simulation profile contract is `id`, `name`, `workload`, positive `ram_peak_bytes`, `gpu_vram_bytes_by_id` keyed by exact host device IDs, and `mode: "simulation"`. In the create request, `id` is the model slug; the response has a separate profile UUID `id` and `model_id`. Profiles can be created with `POST /api/profiles`, inspected with `GET /api/profiles`, updated with `PUT /api/profiles/{model_id}`, and removed with `DELETE /api/profiles/{model_id}`. Deleting a profile preserves its model identity and operation history, so the same model ID can be profiled again. A profile cannot be changed or deleted while its fake worker is active. Each load uses `POST /api/models/{model_id}/load` with the profile UUID as `profile_id` and an `Idempotency-Key` header; unload uses `POST /api/models/{model_id}/unload` with its own idempotency key. Both return HTTP 202 and an asynchronous operation record with an operation ID; poll `GET /api/operations/{operation_id}` or read recent records through `GET /api/operations?limit=100`. Unload remains available even when telemetry is stale. A refusal returns HTTP 409 with `{code,message,operation_id,resources}`; resource entries contain `resource`, `required_bytes`, `available_bytes`, and `headroom_bytes`. Key reuse for another request returns `IDEMPOTENCY_KEY_REUSED`. This entire API is authenticated with the host bearer token.

M2 operation responses set `simulation: true` and `worker_type: "fake"`. Persisted statuses are `loading`, `simulation_ready`, `unloading`, `unloaded`, `refused`, `failed`, and `cleanup_failed`; a future `checking` status is not currently emitted. Refusal codes include `HOST_ROLE_UNSUPPORTED`, `TELEMETRY_STALE`, `TELEMETRY_UNKNOWN`, `GPU_ACCOUNTING_UNSUPPORTED`, `PROFILE_NOT_FOUND`, `PROFILE_INVALID`, `MODEL_BUSY`, `INSUFFICIENT_RAM`, and `INSUFFICIENT_VRAM`.

Profile values must be explicit; do not infer model memory from file size. The API must reject profiles that are missing or invalid, and fail closed on stale/unknown host capacity or unsupported resource accounting. Checks must apply to direct API calls, not only disabled browser controls. Normal real-model loads remain unavailable until a real adapter and measured profile are established.

### M3 — Plugins and setup

Model plugins (accepted 2026-11-11): every runtime kind is a plugin in this repository (`backend/generationstation/plugins/`), registered explicitly; Basalt is the first. The core keeps process supervision, admission and persistence; a plugin supplies its config schema, user settings, estimate, launch description and readiness probe. Contract and how-to: `docs/plugins.md`.

A plugin supplies its `runtimes.json` schema, user settings with bounds, a memory estimate, a launch description (command, environment, files) and a readiness probe; generation plugins add a form (`inputs`), an `output_kind`, and job submission. Workers run under the model's own Python and speak `GET /health`, `POST /generate`, `GET /jobs/{id}`, writing files to `<output_dir>/<job_id>/`. The core API adds `POST /api/models/{id}/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}` and `GET /api/jobs/{id}/files/{name}`. On the desktop: Basalt at `C:\ai\basalt-win` with models under `D:\ai\models\basalt-*`; YuE2 weights at `D:\ai\models\yue2`, its environment at `C:\ai\envs\yue2-worker` (torch 2.10.0+cu128; the package's PyPI torch is CPU-only on Windows and must be replaced), songs written to `D:\ai\outputs\yue2`. All model weights live on D: (`D:\ai\models\<model>`); Qwen Image and MiniMax H3 environments are `C:\ai\envs\qwen-image-worker` and `C:\ai\envs\minimax-h3-worker`.

Later Basalt work: one server holding both presets and switching with `POST /v1/load`; changing VRAM while running with `POST /v1/vram` to make room for a media model without a reload; showing VRAM as "Basalt may use up to N GiB" per card instead of the reserve to leave free.

### M4 — Second runtime and switching

Add a different modality and environment. Done when model A can unload, model B can load and work, and A can return without manual process management. Preserve user data outside worker memory; persist conversations but acknowledge that unloaded inference caches may need rebuilding.

### M5 — Jobs and remaining modalities

Add durable job queue, per-request capacity checks, output library, cancellation, and the remaining compatible video/music/coding adapters. Expose an endpoint compatible with the chosen coding client's streaming and tool-call requirements. A coding model endpoint alone is not a complete coding agent. Mark interrupted jobs explicitly on restart; never promise arbitrary checkpoint/resume.

### M6 — Scheduling and desktop operation

Add explicit priority/eviction policies, measured concurrency, bounded logs/history, startup service, upgrade procedure, and authenticated remote access hardening. Profile larger workloads individually. Concurrent execution is enabled only for measured combinations with sufficient headroom; the user still needs to choose coding-versus-media priority.

### M7 — Meeting notes from a recording (built)

A recording (audio or video) or a transcript file becomes a speaker-labelled transcript, corrected wording, a summary, action items and a decision log, all downloadable and editable afterwards with a change history. One job runs several models in turn through the normal admission checks. Details, models and measurements are in `docs/model-notes.md` (Meeting notes) and `docs/context.md`. Not built: naming speakers in a form the person confirms before the notes, and one file per participant.

## Validation and operational recovery

- Unit tests: capacity boundaries, headroom, per-device accounting, missing/stale samples, profile mismatches.
- Integration tests: concurrent admissions, crashes during load, readiness timeout, unload failure, duplicate commands, service restart and orphaned workers.
- Browser tests: telemetry, refusal explanation, state transitions, reconnect and busy-worker controls.
- Desktop acceptance: compare host measurements with OS/vendor tools; measure peaks during load and inference; confirm unload and repeated cycles; exercise one external-memory-pressure scenario under controlled conditions.
- On restart, reconcile persisted state with verified owned processes and fresh telemetry before permitting new loads. Never trust stored `ready` flags or a reused PID alone. Do not terminate unrelated processes.

## Proposed project layout

```text
generationstation/
  frontend/                       React dashboard and Playwright tests
  backend/generationstation/
    app.py                        HTTP and event endpoints
    telemetry.py                  RAM and GPU providers
    admission.py                  budgets and reservations
    lifecycle.py, process_worker.py  lifecycle and process ownership
    runtimes.py                   runtime catalog, settings and input validation
    generation.py                 generation jobs
    plugins/                      one module per model kind (basalt, yue2, worker base)
    storage.py                    persistence; migrations in backend/migrations
  backend/tests/                  unit, PostgreSQL and stand-in process tests
  workers/                        gs_worker protocol and model workers (run in model environments)
  docs/                           plan, decisions, plugins
  runtimes.example.json           catalog template (runtimes.json is local)
```

## Sources consulted

- [React: building from scratch](https://react.dev/learn/build-a-react-app-from-scratch)
- [Vite guide](https://vite.dev/guide/)
- [Rails getting started](https://guides.rubyonrails.org/getting_started.html)
- [PostgreSQL official Docker image](https://hub.docker.com/_/postgres)
- [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/) and [official image tags](https://hub.docker.com/_/postgres) (checked 2026-10-08; 17.11 is the current maintained 17.x minor and has a matching Bookworm tag).
- [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [SQLAlchemy engine configuration](https://docs.sqlalchemy.org/en/20/core/engines.html)
- [FastAPI deployment concepts](https://fastapi.tiangolo.com/deployment/concepts/)
- [psutil memory documentation](https://psutil.readthedocs.io/stable/index.html)
- [NVIDIA NVML reference](https://docs.nvidia.com/deploy/nvml-api/latest/)
- [YuE2-3B model card](https://huggingface.co/m-a-p/YuE2-3B) and [YuE2-Vae](https://huggingface.co/m-a-p/YuE2-Vae) (weights, `yue2_infer` package, VRAM and timing claims); the installed `yue2` package source for the pipeline API.
- Basalt's local documentation in `C:\ai\basalt-win\docs` (configuration reference, models and router, running).
Model sources to check again for exact checkpoints when their plugins are built: [MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3), [Qwen-Image 2.1](https://qwen.ai/blog?id=qwen-image-2.1), and [Qwen3.8-Flash-Next architecture](https://arxiv.org/abs/2608.30320). Desktop fit is established only for the measured runs in `docs/model-notes.md`.
