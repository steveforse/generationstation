# Generation Station implementation plan

Date: 2026-11-15. Status: React/TypeScript/Vite, native Windows Python/FastAPI, SQLAlchemy/Alembic, and Docker PostgreSQL accepted. M1/M2 passed desktop acceptance on 2026-10-09. M3 is in progress on `feature/basalt-runtime`: the model plugin system, Basalt (text) and YuE2 (music) plugins, the worker protocol and generation jobs are implemented, and both models ran for real on the desktop (Basalt DeepSeek answered a chat request; YuE2 made a song). The Qwen Image plugin (native worker, NVFP4 on both cards) is implemented and made pictures on both GPUs through its worker, and on 2026-11-15 a start, pictures and stop through the API on the RTX 5090. An earlier Qwen Image 2.1 / SGLang-Diffusion attempt on 2026-10-10 was recorded but its code was not preserved (see M3). The laptop browser's full remote connection/reconnect flow remains pending.

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
| Inference | Model plugins: supervised native processes (Basalt) and per-model Python workers in their own environments (YuE2) | Allow different runtime dependencies and release process-owned allocations on exit. A containerized runtime (SGLang-Diffusion, selected for images on 2026-10-10) remains an option that needs Docker/WSL2 memory accounting. |
| Verification | pytest, frontend unit tests, Playwright | Focus on admission races, recovery, and the actual browser workflow. |

The backend serves the compiled frontend in production, giving one origin and one application endpoint. Node is needed for frontend development/building, not as a production UI server. Start with one API/scheduler process; inference runs outside it. Avoid multiplying scheduler ownership with multiple Uvicorn workers.

Python is recommended because this service manages model runtimes and host resources. Model kernels execute in their runtime implementations; the HTTP layer is unlikely to be the performance bottleneck. Go or Rust remain options for a future standalone supervisor if measurements justify the added language boundary. A TypeScript backend would share a language with the UI but still need bridges to several inference environments.

Rails provides a structured framework for applications centered on accounts, permissions, and conventional database workflows. FastAPI is selected here because the host API, telemetry, and process supervisor can stay in Python beside the model tooling. Capacity admission and process supervision still need explicit implementation in either framework.

## Database and remote connection

- PostgreSQL runs in Docker with a persistent named volume and versioned schema migrations. Use separate local development and desktop database volumes; no automatic replication is implied. Pin the image version and use its documented data mount path at implementation time.
- Keep database credentials external and restrict database access to the application/host. The browser connects to the application API, never directly to PostgreSQL. Volume persistence is separate from backup/restore, which must be documented.
- Docker Desktop runs on the desktop. On 2026-10-10 the user selected Docker Desktop's Linux engine for an SGLang image worker while keeping the API and host telemetry native on Windows, and a one-shot container confirmed RTX 5090 passthrough. A container's memory view is not authoritative for the Windows host: admission for a container must also check Docker's WSL2 memory ceiling (`%USERPROFILE%\.wslconfig`, 26 GB since 2026-10-10). Since 2026-11-11 PostgreSQL runs on Docker Desktop; model workers run natively.
- Current desktop access is through Tailscale at `100.109.129.35`. The browser accepts a configurable server origin (including scheme and port); the current IP is not baked into application code. On 2026-10-09, the laptop reached the API on port 8000, an unauthenticated API request returned 401, and the Vite-origin CORS preflight succeeded. Authenticated host telemetry and simulation operations were exercised on the desktop. The browser's full remote connection/reconnect flow remains pending. A local SSH alias, `generationstation-desktop`, uses the dedicated key and Windows account `Steve`; update its host address if Tailscale changes. Prefer a same-origin UI/API in deployment, with explicit trusted origins if a separate browser client is used.

Exact dependencies are locked for the current prototype. The desktop now has about 125.5 GiB RAM, an RTX 5090 (32 GB) and an RTX 4080 (16 GB, drives the display), and Windows 11; October's sample (32 GB RAM, RTX 5090 only) is kept for history. Measured model peaks are recorded per run in `docs/context.md`.

## Current implementation status — 2026-11-12

- Runtime catalog (`runtimes.json`, local; `runtimes.example.json` committed) selects a plugin per entry with `kind`. Plugins: `basalt` (native LLM server; DeepSeek V4.1 Flash and Qwen3.8 Flash-Next presets) and `yue2` (song worker). The browser can only choose a preset, GPUs, and the plugin's bounded settings.
- Process supervision owns each started process tree, checks PID start times before stopping, re-adopts a ready process after an API restart, stops orphans of interrupted loads, detects crashes, and refuses `PORT_IN_USE` when a runtime runs outside the app. Estimate-based admission reserves capacity until readiness.
- Generation: workers speak the `workers/gs_worker.py` protocol; jobs are stored in PostgreSQL (migration 0004) with inputs validated against each plugin's form; finished files are served only from the job's own output folder.
- Dashboard (multi-host since 2026-11-12, branch `feature/multi-host-ui`): sidebar with Overview, Connections, and a section per saved host listing Models and its generating services (the simulation Test profiles page is linked from the bottom of Models, not the sidebar); hash routes (`#/overview`, `#/connections`, `#/hosts/<host>/models`, `#/hosts/<host>/services/<model>`, `#/hosts/<host>/profiles`). Each host has its own session (telemetry stream, catalog, actions), and saved hosts reconnect on the next visit. Loading is separate from generating (2026-11-12): the Models page holds every model server's model, GPU and advanced settings, start/stop, refusals naming the GPU, and start/stop history. A service page exists only for a service with a plugin generation form; it shows whether the service is running (linking to Models otherwise), the form ("Make a song") while it runs, and results with playback and download. Basalt has no generation form, so it appears only on Models. The Models page also shows the host's RAM and VRAM cards. Their bars split used memory into each running model's share and "Other programs" (hover for sizes), and each running model's card states its RAM and per-GPU VRAM.
- Per-model memory (2026-11-12, display only): the host snapshot's `model_memory` maps each running runtime's model ID to `ram_bytes` (working set of its owned process tree), `gpus` (VRAM bytes by GPU UUID) and `error`. NVML reports no per-process VRAM for WDDM GPUs, so on Windows it comes from the `GPU Process Memory(*)\Dedicated Usage` performance counters, matched to NVML GPUs by PCI bus through D3DKMT adapter addresses; other hosts use NVML's per-process figures. Verified on the desktop: a 2 GiB PyTorch allocation on the RTX 5090 read 2,479.6 MiB, matching nvidia-smi. Admission never uses these figures.
- Start preview (2026-11-12, display only): `POST /api/runtimes/{id}/estimate` takes the start body (`preset`, `settings`, `gpus`) and returns what that start would ask admission for (`ram_bytes`, `gpu_vram_bytes_by_id`), the configured headroom, and active reservations; it writes nothing. A stopped model's card shows each resource as needed versus free after headroom and reservations, with Fits or the shortfall, and the Models page draws the hovered or focused model's need as a hatched segment after current use (red when it won't fit). The start request is still checked independently.
- The backend tests (including PostgreSQL tests with stand-in Basalt and worker processes) and Playwright tests pass; Ruff passes.

## Implementation status — 2026-10-10 (from earlier project notes; code not preserved)

- The Windows backend suite passed (the PostgreSQL-only test skipped) with a first SGLang-Diffusion container lifecycle slice; Playwright could not launch because Chromium was absent. See "Earlier attempt" under M3.

## Implementation status — 2026-10-09

- The Windows-native API reports host identity and live physical RAM/NVML measurements. On 2026-10-09 it identified the desktop as Windows, reported the RTX 5090 and a fresh host-scope sample (`stale=false`), with sample age below one second.
- The dashboard accepts a configurable server origin and bearer token; each host's URL and token are saved in that browser (accepted 2026-11-12). It validates host/catalog/profile/operation responses, streams authenticated telemetry, and shows stale, partial, disconnected, and reconnecting states. It exposes explicitly labeled simulation-profile and fake-worker controls when host data permits; the backend still checks every load request.
- PostgreSQL 17.11 runs as the configured Docker Compose service with a named data volume. The application database was healthy at Alembic revision `0002 (head)`. The PostgreSQL migration/persistence/scheduler-lock integration test passed on a separate disposable test database. A live fake-worker load/unload also exercised desktop PostgreSQL admission and reservation release; active reservations returned to zero.
- The Windows backend suite and Ruff passed. The PostgreSQL-only test passed separately against a disposable database. Frontend production build and the Playwright tests pass. The browser's authenticated remote connection/reconnect flow has not yet been exercised end to end.
- M2 profile/admission routes and the process-local fake-worker lifecycle are implemented. Unit tests cover refusal, per-device accounting, reservations, idempotency, operation cleanup, and restart reconciliation. On the desktop, an explicit low-resource fake profile reached `simulation_ready`, then `unloaded`; it reserved no active capacity afterward. Its temporary profile was deleted while model identity and operation history were retained, as designed. The fake worker starts no OS process, opens no model files, and runs no inference. M3 real inference remains unimplemented.

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

### M0 — Context and desktop inventory

Deliver repository plan, project context, stack decision, desktop inventory, and first model/runtime choice. Done. On 2026-10-10 image generation (Qwen Image 2.1 on SGLang-Diffusion) was chosen first and Qwen Image 2.1 and Krea 2 Turbo weights were found on the desktop; on 2026-11-11 Basalt became the first runtime actually delivered, followed by YuE2. Candidates too large for the machine remain unsupported.

### M1 — Web shell and real host telemetry

Create the frontend/backend shell, PostgreSQL migrations and Docker Compose database service, settings, monitoring adapters, and event stream. On 2026-10-09, the desktop reported fresh native Windows RAM/NVML telemetry; the API was reachable over Tailscale, unauthenticated access returned 401, and the Vite-origin CORS preflight succeeded. The laptop browser's connection, stale-state, and reconnect flow still needs end-to-end verification. Use fake telemetry only in clearly marked browser-test fixtures. Done when the laptop browser shows the desktop's measured RAM/VRAM, stale data is visible, and reconnect restores a fresh snapshot. State-changing requests must remain protected by backend bearer authentication and capacity checks.

### M2 — Admission controller and lifecycle with a fake worker

The local implementation and application tests are complete. It adds explicit per-model simulation profiles and backend-enforced admission, serializes lifecycle transitions, exposes operation/refusal status, and exercises a fixed fake worker for load/unload behavior. The fake worker is a lifecycle fixture only: it performs no inference, loads no model weights, and cannot establish real memory needs, desktop fit, or runtime compatibility. A successful simulation load must never be presented as support for a real model.

Current simulation headroom defaults are 4 GiB of system RAM and 2 GiB for each assigned GPU, configurable with `GS_RAM_HEADROOM_BYTES` and `GS_GPU_HEADROOM_BYTES`. These are provisional engineering cushions, not values measured from the target desktop or a model. Admission requires desktop/host scope, a non-stale sample with finite age below its stale window, valid RAM measurements, and complete per-GPU accounting with unique identifiers. For each requested resource independently, subtract the configured headroom and all active reservations from currently available bytes; match GPUs by their exact reported identifiers rather than pooling VRAM. Document any later change from measured desktop baseline.

The simulation profile contract is `id`, `name`, `workload`, positive `ram_peak_bytes`, `gpu_vram_bytes_by_id` keyed by exact host device IDs, and `mode: "simulation"`. In the create request, `id` is the model slug; the response has a separate profile UUID `id` and `model_id`. Profiles can be created with `POST /api/profiles`, inspected with `GET /api/profiles`, updated with `PUT /api/profiles/{model_id}`, and removed with `DELETE /api/profiles/{model_id}`. Deleting a profile preserves its model identity and operation history, so the same model ID can be profiled again. A profile cannot be changed or deleted while its fake worker is active. Each load uses `POST /api/models/{model_id}/load` with the profile UUID as `profile_id` and an `Idempotency-Key` header; unload uses `POST /api/models/{model_id}/unload` with its own idempotency key. Both return HTTP 202 and an asynchronous operation record with an operation ID; poll `GET /api/operations/{operation_id}` or read recent records through `GET /api/operations?limit=100`. Unload remains available even when telemetry is stale. A refusal returns HTTP 409 with `{code,message,operation_id,resources}`; resource entries contain `resource`, `required_bytes`, `available_bytes`, and `headroom_bytes`. Key reuse for another request returns `IDEMPOTENCY_KEY_REUSED`. This entire API is authenticated with the host bearer token.

M2 operation responses set `simulation: true` and `worker_type: "fake"`. Persisted statuses are `loading`, `simulation_ready`, `unloading`, `unloaded`, `refused`, `failed`, and `cleanup_failed`; a future `checking` status is not currently emitted. Refusal codes include `HOST_ROLE_UNSUPPORTED`, `TELEMETRY_STALE`, `TELEMETRY_UNKNOWN`, `GPU_ACCOUNTING_UNSUPPORTED`, `PROFILE_NOT_FOUND`, `PROFILE_INVALID`, `MODEL_BUSY`, `INSUFFICIENT_RAM`, and `INSUFFICIENT_VRAM`.

Profile values must be explicit; do not infer model memory from file size. The API must reject profiles that are missing or invalid, and fail closed on stale/unknown host capacity or unsupported resource accounting. Checks must apply to direct API calls, not only disabled browser controls. Normal real-model loads remain unavailable until a real adapter and measured profile are established.

The Windows backend suite reports 69 passed and Ruff passes; the dedicated PostgreSQL integration test also passes against a disposable database. Application tests cover over-admission, idempotency, resource refusals, cleanup failures, and restart reconciliation. Desktop acceptance verified fresh telemetry, authenticated API access, PostgreSQL-backed simulation admission, load/unload, and reservation release. This milestone does not prove model fit. The fake adapter is process-local and starts no OS process; after service restart, reconcile simulation operations as failed and clear their reservations because no fake handle survived. Restart/reconciliation behavior must not trust stale ready state or terminate unrelated processes.

### M3 — First real model on the desktop

Implement one compatible adapter and establish its memory profile on the desktop. Done when the browser loads the model to actual readiness, a minimal inference proves it works, unload ends the worker, telemetry confirms release, and an oversized profile is refused without launching a process. Repeat load/unload cycles to identify retained allocations. Record versions and measurements.

This is the first usable release: manual model management with trustworthy host telemetry and capacity refusal.

Status 2026-11-11: in progress on `feature/basalt-runtime`. The first runtime is Basalt with DeepSeek V4.1 Flash and Qwen3.8 Flash-Next presets. Implemented: a local runtime catalog with allow-listed, bounded advanced settings (main-card and second-card VRAM reserve, RAM for overflow experts, RAM guard, conversation cache, context, KV precision where supported) and per-run GPU choice; generated Basalt configs; process supervision with readiness from `/v1/models`; estimate-based admission whose reservation is released at readiness; restart re-adoption; crash detection; `PORT_IN_USE` for a Basalt started elsewhere; and a dashboard panel. Verified: the full backend suite including PostgreSQL runtime tests with a stand-in process, and a live refusal on the desktop that started no process. A first real DeepSeek load on the RTX 5090 alone reached readiness in 51 s, answered a minimal chat request, and stopped in 6 s with VRAM and RAM released (measurements in `docs/context.md`). Remaining for acceptance: repeated load/unload cycles to look for retained allocations, a two-GPU load, a Flash-Next load, and the browser walkthrough.

Model plugins (accepted 2026-11-11): every runtime kind is a plugin in this repository (`backend/generationstation/plugins/`), registered explicitly; Basalt is the first. The core keeps process supervision, admission and persistence; a plugin supplies its config schema, user settings, estimate, launch description and readiness probe. Contract and how-to: `docs/plugins.md`. After the refactor, a real DeepSeek start on the RTX 5090 reached readiness in 55 s, answered a chat request, and stopped with VRAM released. The generation worker protocol (`workers/gs_worker.py`), the `WorkerPlugin` base, generation jobs (migration 0004, `/api/models/{id}/jobs`, `/api/jobs`), the dashboard's form-from-plugin and results list, and the YuE2 plugin are implemented. A real YuE2 song was made, fetched, and the worker stopped cleanly (`docs/context.md`). The Qwen Image plugin followed on 2026-11-15 as a native worker rather than SGLang (measurements in `docs/context.md`), and the MiniMax H3 video plugin on 2026-11-21 (NVFP4 with the Turbo v4 add-on and an uncensored prompt reader, RTX 5090 only). Generation pages now keep every result in a sidebar with its prompt, settings, model settings and time taken, and results can be reused or deleted (migration 0005). On 2026-11-22 H3 gained 10 and 14.4 s clips (the video decoder and transformer take turns on the card) and "1080p (AI upscale)", which renders 540p and enlarges it with FlashVSR+ in its own environment; the MiniMax latent upscaler was tried and not offered. OmniVoice (2026-11-21) and Qwen3-TTS (2026-11-22) add speech. Next: a simple page for the primary user separate from the admin dashboard, and the Proxmox split.

#### Plugins and setup (summary of `docs/plugins.md` and `docs/development.md`)

A plugin supplies its `runtimes.json` schema, user settings with bounds, a memory estimate, a launch description (command, environment, files) and a readiness probe; generation plugins add a form (`inputs`), an `output_kind`, and job submission. Workers run under the model's own Python and speak `GET /health`, `POST /generate`, `GET /jobs/{id}`, writing files to `<output_dir>/<job_id>/`. The core API adds `POST /api/models/{id}/jobs`, `GET /api/jobs`, `GET /api/jobs/{id}` and `GET /api/jobs/{id}/files/{name}`. On the desktop: Basalt at `C:\ai\basalt-win` with models under `D:\ai\models\basalt-*`; YuE2 weights at `D:\ai\models\yue2`, its environment at `C:\ai\envs\yue2-worker` (torch 2.10.0+cu128; the package's PyPI torch is CPU-only on Windows and must be replaced), songs written to `D:\ai\outputs\yue2`. All model weights live on D: (`D:\ai\models\<model>`); Qwen Image and MiniMax H3 environments are `C:\ai\envs\qwen-image-worker` and `C:\ai\envs\minimax-h3-worker`.

#### Earlier attempt: Qwen Image 2.1 on SGLang-Diffusion (2026-10-10, code not preserved)

Recorded in earlier project notes on 2026-10-10; on 2026-11-12 the code was not found in any local copy, the Git stash, or GitHub. Kept for reference; the Qwen Image plugin was built as a native worker instead (2026-11-15).

Image generation was selected as the first modality, SGLang-Diffusion as the runtime, and Qwen Image 2.1 as the initial model candidate. Docker Desktop was running and the pinned SGLang 0.5.21 image (`lmsysorg/sglang@sha256:2dbe4c7f53230b09aaa8fa41891c13c51d9d2e253f486a70822aaf08783fff75`) was pulled; it is still present. A one-shot GPU passthrough container saw the RTX 5090. The desktop has the Comfy-Org Qwen Image 2.1 INT8 ConvRot DiT, Qwen3-VL 8B encoder, and BF16 VAE files at the documented model paths; their SHA256s are recorded in `docs/context.md`. Official sources establish that SGLang supports Qwen Image 2.1, exposes `--model-type diffusion`, `--model-id`, and `--component-weights-paths.<component>`, and has ConvRot INT8 support through its JIT kernels. This supports feasibility in principle but does not validate this exact DiT/encoder/VAE combination with this image. A set of 15 small config/tokenizer files totaling 16 MB from Qwen revision `d26bb61231c349cf6b7896fa83353113880e1ba3` is staged at the documented Diffusers path and was read-only mounted and tested. The official Qwen recipe requires this pipeline config structure; that staged set holds no model weights. The pulled image lacks `comfy-kitchen`; the official Qwen cookbook calls for a nightly image and says no published Docker image is verified. Its general 22.7 GiB RTX 4090 peak is not a measurement for this target or these quantized files. No model container, inference, or load/inference profile exists. Do not infer peak memory or fit from file sizes.

The design that was implemented then: a server-side SGLang-Diffusion container adapter requiring a digest-pinned image already installed locally, a pinned local Qwen Diffusers config snapshot including every required component directory, exact allowlisted local component filenames, an explicit compatibility-verification gate, a measured per-device profile, and sufficient Docker/WSL2 memory in addition to physical Windows RAM. The web Load route could not pull images or download model assets; SGLang ran offline and component files mounted read-only. Container ownership was tied to a persisted nonce, runtime fingerprint, name, and Docker ID. Readiness checked the container's running state and loopback port mapping, then `/health` and `/v1/models` for the expected model ID. On uncertain cleanup or restart inspection, capacity stayed reserved. Automated Docker/HTTP fixtures validated this without starting a container or loading weights. Done-criteria then: verify the staged files against a supported pinned build, validate the checkpoint combination, and record host/VM RAM and VRAM peaks, runtime and model versions, checkpoint hashes, resolution, and generation settings before enabling loads.

To rebuild it as a plugin: decide between SGLang in Docker (needs a container-aware supervisor and WSL2 memory admission) and a native Windows worker using Diffusers in its own environment (fits the existing worker protocol).

Later Basalt work: one server holding both presets and switching with `POST /v1/load`; changing VRAM while running with `POST /v1/vram` to make room for a media model without a reload; showing VRAM as "Basalt may use up to N GiB" per card instead of the reserve to leave free.

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

- [YuE2-3B model card](https://huggingface.co/m-a-p/YuE2-3B) and [YuE2-Vae](https://huggingface.co/m-a-p/YuE2-Vae) (weights, `yue2_infer` package, VRAM and timing claims); the installed `yue2` package source for the pipeline API.
- Basalt's local documentation in `C:\ai\basalt-win\docs` (configuration reference, models and router, running).
- Gathered 2026-10-10 for Qwen Image (from earlier project notes): [Qwen Image 2.1 official model card](https://huggingface.co/Qwen/Qwen-Image-2.1), [Qwen Image 2.1 Diffusers pipeline](https://huggingface.co/docs/diffusers/main/api/pipelines/qwenimage21), [Comfy-Org's Qwen Image 2.1 model-file guide](https://github.com/Comfy-Org/docs/blob/main/tutorials/image/qwen/qwen-image-2-1.mdx); [Krea 2 official model card](https://huggingface.co/krea/Krea-2-Turbo), [Krea 2 Diffusers pipeline](https://huggingface.co/docs/diffusers/main/api/pipelines/krea2), [Krea's official inference code](https://github.com/krea-ai/krea-2), [Comfy-Org's Krea 2 model-file guide](https://github.com/Comfy-Org/docs/blob/main/tutorials/image/krea/krea-2.mdx); [Qwen Image 2.1 on GitHub](https://github.com/QwenLM/Qwen-Image-2.1), [SGLang-Diffusion quantization guide](https://docs.sglang.io/docs/sglang-diffusion/quantization), [installation guide](https://github.com/sgl-project/sglang/blob/main/docs/docs/sglang-diffusion/installation.mdx), and [Qwen Image 2.1 recipe](https://docs.sglang.io/cookbook/diffusion/Qwen/Qwen-Image-2.1).
- [SGLang Qwen Image 2.1 pipeline source](https://github.com/sgl-project/sglang/blob/main/python/sglang/multimodal_gen/runtime/pipelines/qwen_image21.py) lists required config modules; [the official Qwen cookbook](https://github.com/sgl-project/sglang/blob/main/docs/cookbook/diffusion/Qwen-Image/Qwen-Image-2.1.mdx) specifies its local checkpoint directory and warns that no published Docker image is verified. The cookbook's tested configurations are not evidence that the desktop's exact quantized components or stable image work.
- [Docker system info](https://docs.docker.com/reference/cli/docker/system/info/) reports daemon total memory; [Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/) reports running-container memory usage (Linux CLI usage subtracts cache). A container runtime must intersect this live Docker capacity with host telemetry and still apply configured RAM headroom.

Model sources to check again for exact checkpoints when their plugins are built: [MiniMax H3](https://github.com/MiniMax-AI/MiniMax-H3), [Qwen-Image 2.1](https://qwen.ai/blog?id=qwen-image-2.1), and [Qwen3.8-Flash-Next architecture](https://arxiv.org/abs/2608.30320). Desktop fit is established only for the measured runs in `docs/context.md`.
