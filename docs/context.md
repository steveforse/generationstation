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
- Tailscale provides current remote access. Desktop IP: `100.109.129.35`; it may change. The dashboard now has a configurable server URL and token field: it saves the URL on that device, keeps the token in memory, and sends bearer authentication. Local development uses API port 8000; desktop deployment and remote connectivity are not yet accepted.

## Engineering recommendations and pending decisions

1. Python + FastAPI is accepted for the host API and supervisor. Use SQLAlchemy and Alembic for database access and migrations.
2. REST commands and server-sent events for telemetry and lifecycle updates.
3. One desktop and one scheduler owner initially; serialize model lifecycle operations.
4. Run PostgreSQL in Docker. Initially prefer a native Windows host service for physical host telemetry and process supervision; containerizing the API/workers is a separate decision requiring verified Windows/WSL2 accounting and runtime compatibility.
5. Manual model management first; automatic eviction, generation workflows, and concurrency later.

## Desktop inventory

User-reported on 2026-10-08; not yet measured on the host:

- CPU: AMD Ryzen 7 5800X3D.
- System RAM: 32 GB DDR4.
- Storage: 2 TB NVMe SSD total capacity; free space unknown.
- GPU: NVIDIA RTX 5090 with 32 GB dedicated VRAM.
- OS: Windows 11.

Installed RAM is not the available model budget; admission still requires live host telemetry and headroom.

## Open inputs

- Available SSD space.
- Production application port and desktop deployment access. Local development currently uses API port 8000; the dashboard token-entry flow and bearer-authenticated API requests are implemented, but remote access has not yet been verified on the desktop.
- Which model/workload to support first and exact checkpoint/runtime/quantization.
- Priority when coding and media compete for memory.
- Acceptable cold load time and generation latency.

Do not use this laptop's hardware as a substitute for the desktop inventory.

## Documentation workflow

- Keep current status, evidence, unresolved questions, and next steps explicit. Distinguish recommendations from accepted decisions and measured facts.

## Current state and next action

The local M1/M2 prototype is implemented. Backend pytest reports 69 passed and one PostgreSQL-only integration test skipped because `GS_TEST_DATABASE_URL` was not configured; Ruff passes. The frontend build and all 11 Playwright tests pass. Compose configuration and Alembic offline SQL validate. These local checks do not include a live PostgreSQL migration/admission run or a Windows desktop run. M1 desktop acceptance remains pending: deploy the service, compare actual RAM/VRAM telemetry, and verify Tailscale access. M2's fixed fake worker performs no inference and loads no weights; PostgreSQL-backed reservation/advisory-lock behavior and desktop end-to-end operation remain unverified. M3 (a verified real model) remains pending. No desktop memory measurements, runtime compatibility, or model fit have been established. Tailscale's current address remains configurable and must not be treated as permanent. Next: complete live PostgreSQL and desktop validation, then select a first workload and establish its profile before M3. Do not claim desktop acceptance based on local development or treat a fake worker as model support.
