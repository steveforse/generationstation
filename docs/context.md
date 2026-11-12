# Project context

Updated: 2026-10-09.

## Confirmed requirements

- Working name: Generation Station (formerly ModelDock).
- Web interface accessed from a laptop; service and inference run on a separate desktop.
- Multiple AI models installed, with explicit load and unload controls.
- Display current host RAM and VRAM usage.
- Refuse a load when sufficient host capacity cannot be established.
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

Hardware was reported on 2026-10-08 and changed since. Windows checks on 2026-11-11 measured:

- CPU: AMD Ryzen 7 5800X3D.
- System RAM: about 125.5 GiB (Windows `TotalPhysicalMemory`); it was 32 GB at the October check.
- Storage: 2 TB NVMe SSD; C: had about 571 GB free on 2026-11-11 after compacting the WSL disk.
- GPUs, in NVML/PCI order: index 0 NVIDIA RTX 5090 (32 GB), index 1 NVIDIA RTX 4080 (16 GB). The 4080 drives the display, so its free VRAM moves with desktop and game use.
- OS: Windows 11.

Historical sample from the October inventory (32 GB RAM, single GPU): the native Windows API reported a live host-scoped sample at `2026-10-09T14:12:44Z`: system RAM 34,280,030,208 bytes total, 24,476,930,048 available, and 9,803,100,160 used; RTX 5090 VRAM 34,190,917,632 bytes total, 32,506,490,880 available, and 1,684,426,752 used. The sample was 0.81 seconds old and `stale=false`. `nvidia-smi` reported driver 617.14. These are changing baseline measurements, not a model-fit result. The CPU was confirmed as an AMD Ryzen 7 5800X3D, and the C: volume had about 418 GiB free. Runtime compatibility and peak memory during real inference remain unverified.

## Open inputs

- The laptop browser's authenticated connection and reconnect experience against the desktop still needs an end-to-end check. The API is reachable over the current Tailscale route on port 8000; the address is temporary.
- First workload chosen on 2026-11-11: Basalt (native Windows LLM server, `C:\ai\basalt-win`) with two presets, DeepSeek V4.1 Flash and Qwen3.8 Flash-Next. Their start estimates in `runtimes.json` are conservative guesses, not measurements.
- Priority when coding and media compete for memory.
- Acceptable cold load time and generation latency.

Do not use this laptop's hardware as a substitute for the desktop inventory.

## Documentation workflow

- Keep current status, evidence, unresolved questions, and next steps explicit. Distinguish recommendations from accepted decisions and measured facts.

## Current state and next action

The local M1/M2 prototype is implemented. On the Windows desktop, the API reported fresh RAM and NVML telemetry, the PostgreSQL application database was healthy at Alembic revision `0002 (head)`, and a dedicated PostgreSQL migration/persistence/locking integration check passed. A 1 GiB RAM / 1 GiB RTX 5090 fake-worker profile reached `simulation_ready`, unloaded cleanly, and left zero active capacity reservations; the temporary profile was deleted while its model identity and operation history were retained by design. The fake worker starts no operating-system process, opens no model files, and runs no inference. The Windows backend suite passed 69 tests and Ruff passed. The local frontend build and 11 Playwright tests pass. Desktop API routing and bearer authentication were verified, but the laptop browser's full connection/reconnect path remains open. M3 (a verified real model) remains pending: select a workload, then check its exact model, runtime, available weights, and measured memory profile. Do not treat a fake-worker result as model support.

Update 2026-11-11 (branch `feature/basalt-runtime`): development moved fully to Windows (`C:\Users\Steve\git\generationstation`), with a fresh PostgreSQL on Docker Desktop; the WSL copy and its database are retired. M3 implementation is in progress: a server-side runtime catalog (`runtimes.json`, local and ignored by Git; `runtimes.example.json` committed), a Basalt process adapter, real-runtime admission using per-preset estimates, re-adoption of a ready process after a service restart, crash detection, and a dashboard panel with model choice, GPU choice and allow-listed advanced settings. 87 backend tests pass, including PostgreSQL runtime tests with a stand-in Basalt process. On the desktop, a live DeepSeek start was correctly refused while a game held most of the RTX 4080 (about 1 GiB available after headroom against a 10 GiB estimate); no process was started. First real load, 2026-11-11, through the API while a game used the RTX 4080: DeepSeek V4.1 Flash on the RTX 5090 only (`gpus: [0]`), preset defaults except `ram_reserve_mib: 16384`. Ready in 51 s. At ready the 5090 used 27,464 MiB of 32,607 and system RAM use rose by 50.6 GiB; after one chat request it was about 62.7 GiB. The 4080 was not used. A minimal chat completion returned the requested text in 12.1 s (38 prompt and 30 completion tokens, including thinking). Stop through the API finished in 6 s: no `basalt.exe` remained, port 8160 closed, the 5090 returned to 0 MiB used, and the RAM was returned. The DeepSeek RAM estimate was raised from 8 to 16 GiB beyond the overflow-expert budget to match this. Still open: repeated cycles, a two-GPU load, and a Flash-Next load.

Product direction recorded 2026-11-11: the primary user is non-technical (creating music, images, and video); the web app will eventually run on a Proxmox homelab server and call this desktop, which runs the models. ComfyUI and biniou were evaluated and rejected. The UI must start and stop models, choose GPUs, and stop Basalt to make room for media models.
