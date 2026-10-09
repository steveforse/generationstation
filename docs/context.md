# Project context

Updated: 2026-10-09.

## Confirmed requirements

- Working name: Generation Station (formerly ModelDock).
- Web interface accessed from a laptop; service and inference run on a separate desktop.
- Multiple AI models installed, with explicit load and unload controls.
- Display current host RAM and VRAM usage.
- Refuse a load when sufficient host capacity cannot be established.
- Use BookStack for persistent project context, following sister projects such as Playtab.
- Initial candidate workloads: MiniMax H3 video, Qwen-Image 2.1 images, YuE2 music, Qwen3.8-Flash-Next coding. These are candidates, not a promise that all fit the target desktop.

## Accepted stack and connectivity decisions

- React + TypeScript + Vite for the frontend, and Python + FastAPI for the native host API/supervisor; the user accepted this stack on 2026-10-08 after comparing FastAPI with Rails.
- PostgreSQL in Docker with a persistent named volume replaces the SQLite proposal. Docker is available on both the development laptop and desktop (user-reported).
- SQLAlchemy 2 and Alembic are selected for PostgreSQL access and schema migrations. PostgreSQL 17 is pinned to the maintained 17.11 Bookworm image; update the patch tag after checking official release/image metadata.
- Model weights and generated outputs remain files outside the database and source control.
- Tailscale provides current remote access. Desktop IP: `100.109.129.35`; it may change. The dashboard has a configurable server URL and token field: it saves the URL on that device, keeps the token in memory, and sends bearer authentication. On 2026-10-09, the laptop reached the desktop API on port 8000; an unauthenticated API request returned HTTP 401, and the Vite-origin CORS preflight succeeded. Authenticated host telemetry and a simulation lifecycle were verified on the desktop. The full laptop-browser connection and reconnect path remains to be checked. SSH works through the local `generationstation-desktop` alias; update its `HostName` if the Tailscale address changes.

## Engineering recommendations and pending decisions

1. Python + FastAPI is accepted for the host API and supervisor. Use SQLAlchemy and Alembic for database access and migrations.
2. REST commands and server-sent events for telemetry and lifecycle updates.
3. One desktop and one scheduler owner initially; serialize model lifecycle operations.
4. Run PostgreSQL in Docker. Initially prefer a native Windows host service for physical host telemetry and process supervision; containerizing the API/workers is a separate decision requiring verified Windows/WSL2 accounting and runtime compatibility.
5. Manual model management first; automatic eviction, generation workflows, and concurrency later.

## Desktop inventory

Hardware was reported on 2026-10-08. Windows checks on 2026-10-09 confirmed the CPU, OS, RAM capacity, and GPU; memory type and SSD model remain user-reported:

- CPU: AMD Ryzen 7 5800X3D.
- System RAM: 32 GB DDR4.
- Storage: 2 TB NVMe SSD; the Windows C: volume reports 2,047,359,315,968 bytes total and 448,952,270,848 bytes free at the inventory check.
- GPU: NVIDIA RTX 5090 with 32 GB dedicated VRAM.
- OS: Windows 11.

The native Windows API reported a live host-scoped sample at `2026-10-09T14:12:44Z`: system RAM 34,280,030,208 bytes total, 24,476,930,048 available, and 9,803,100,160 used; RTX 5090 VRAM 34,190,917,632 bytes total, 32,506,490,880 available, and 1,684,426,752 used. The sample was 0.81 seconds old and `stale=false`. `nvidia-smi` reported driver 617.14. These are changing baseline measurements, not a model-fit result. The CPU was confirmed as an AMD Ryzen 7 5800X3D, and the C: volume had about 418 GiB free. Runtime compatibility and peak memory during real inference remain unverified.

## Open inputs

- The laptop browser's authenticated connection and reconnect experience against the desktop still needs an end-to-end check. The API is reachable over the current Tailscale route on port 8000; the address is temporary.
- Which model/workload to support first and exact checkpoint/runtime/quantization.
- Priority when coding and media compete for memory.
- Acceptable cold load time and generation latency.

Do not use this laptop's hardware as a substitute for the desktop inventory.

## Documentation workflow

- Repository Markdown is authoritative for the plan and technical decisions; BookStack holds readable mirrors and continuation context.
- Update the repository document first, then its corresponding BookStack page. Record page IDs and URLs in `docs/bookstack.json`.
- Read the current BookStack page before updating; use the shared CLI's expected revision timestamp check where available. This check is best effort, not a server-side compare-and-swap guarantee.
- Keep current status, evidence, unresolved questions, and next steps explicit. Distinguish recommendations from accepted decisions and measured facts.
- BookStack is a development documentation dependency only. Generation Station must operate when BookStack is offline.
- Reuse the shared `bookstack-agent-cli` and its external credential configuration. Do not commit credentials or copy them into the application.

## Current state and next action

The local M1/M2 prototype is implemented. On the Windows desktop, the API reported fresh RAM and NVML telemetry, the PostgreSQL application database was healthy at Alembic revision `0002 (head)`, and a dedicated PostgreSQL migration/persistence/locking integration check passed. A 1 GiB RAM / 1 GiB RTX 5090 fake-worker profile reached `simulation_ready`, unloaded cleanly, and left zero active capacity reservations; the temporary profile was deleted while its model identity and operation history were retained by design. The fake worker starts no operating-system process, opens no model files, and runs no inference. The Windows backend suite passed 69 tests and Ruff passed. The local frontend build and 11 Playwright tests pass. Desktop API routing and bearer authentication were verified, but the laptop browser's full connection/reconnect path remains open. M3 (a verified real model) remains pending: select a workload, then check its exact model, runtime, available weights, and measured memory profile. Do not treat a fake-worker result as model support.
