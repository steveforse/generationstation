# Project context

Updated: 2026-11-12.

## Confirmed requirements

- Working name: Generation Station (formerly ModelDock).
- Web interface accessed from a browser; service and inference run on the desktop. Planned (2026-11-11): the web app moves to a Proxmox homelab server and calls the desktop, which keeps running the models.
- The primary user is non-technical and wants to make music, images, and video; licensing is not a concern for this personal use.
- Multiple AI models installed, with explicit load and unload controls, including choosing which GPU a model uses and stopping Basalt to make room for a media model.
- Display current host RAM and VRAM usage.
- Refuse a load when sufficient host capacity cannot be established.
- Use BookStack for persistent project context, following sister projects such as Playtab.
- Workloads: Basalt text models (DeepSeek V4.1 Flash, Qwen3.8 Flash-Next), YuE2 music, Qwen Image 2.1 images, MiniMax H3 video. These are targets, not a promise that all fit at once.
- The user prefers a Generation Station inference runtime independent of ComfyUI; ComfyUI is a source of already-downloaded model weights, not the intended runtime. ComfyUI and biniou were evaluated as products on 2026-11-11 and rejected (interface too complex; biniou lacks the target models and runs UI and models in one process).

## Accepted stack and connectivity decisions

- React + TypeScript + Vite for the frontend, and Python + FastAPI for the native host API/supervisor; the user accepted this stack on 2026-10-08 after comparing FastAPI with Rails.
- PostgreSQL in Docker with a persistent named volume replaces the SQLite proposal. Since 2026-11-11 it runs on Docker Desktop on Windows; the earlier WSL Docker database was retired.
- SQLAlchemy 2 and Alembic are selected for PostgreSQL access and schema migrations. PostgreSQL 17 is pinned to the maintained 17.11 Bookworm image; update the patch tag after checking official release/image metadata.
- Model weights and generated outputs remain files outside the database and source control.
- Model plugins (accepted 2026-11-11): each runtime kind is a plugin in this repository (`backend/generationstation/plugins/`). Media models run in workers (`workers/`) under their own Python environments, speaking one HTTP protocol. See `docs/plugins.md`.
- Earlier decision, 2026-10-10, not yet revisited: SGLang-Diffusion in a server-managed Docker Desktop Linux container as the image runtime for Qwen Image 2.1. Its implementation was not preserved (see "Earlier attempt" below). Decide again when building the Qwen Image plugin: SGLang in Docker, or a native Windows worker like YuE2's.
- Tailscale provides current remote access. Desktop IP: `100.109.129.35`; it may change. The dashboard has a configurable server URL and token field: it saves the URL on that device, keeps the token in memory, and sends bearer authentication. On 2026-10-09, the laptop reached the desktop API on port 8000; an unauthenticated API request returned HTTP 401, and the Vite-origin CORS preflight succeeded. The full laptop-browser connection and reconnect path remains to be checked. SSH works through the local `generationstation-desktop` alias; update its `HostName` if the Tailscale address changes. The API currently listens on 127.0.0.1 during development.

## Engineering recommendations and pending decisions

1. Python + FastAPI is accepted for the host API and supervisor. Use SQLAlchemy and Alembic for database access and migrations.
2. REST commands and server-sent events for telemetry and lifecycle updates.
3. One desktop and one scheduler owner initially; serialize model lifecycle operations.
4. Run PostgreSQL in Docker. Keep the API, host telemetry and process supervision native on Windows. Model workers run as native Windows processes in per-model Python environments; a containerized worker (such as SGLang) would need Docker/WSL2 memory accounting in admission, as the 2026-10-10 attempt designed.
5. Manual model management first; automatic eviction, generation workflows, and concurrency later.

## Desktop inventory

Hardware was reported on 2026-10-08 and changed since. Windows checks on 2026-11-11 measured:

- CPU: AMD Ryzen 7 5800X3D.
- System RAM: about 125.5 GiB (Windows `TotalPhysicalMemory`); it was 32 GB at the October check.
- Storage: 2 TB NVMe SSD; C: had about 571 GB free on 2026-11-11 after compacting the WSL disk.
- GPUs, in NVML/PCI order: index 0 NVIDIA RTX 5090 (32 GB), index 1 NVIDIA RTX 4080 (16 GB). The 4080 drives the display, so its free VRAM moves with desktop and game use.
- OS: Windows 11.

Historical sample from the October inventory (32 GB RAM, single GPU): the native Windows API reported a live host-scoped sample at `2026-10-09T14:12:44Z`: system RAM 34,280,030,208 bytes total, 24,476,930,048 available, and 9,803,100,160 used; RTX 5090 VRAM 34,190,917,632 bytes total, 32,506,490,880 available, and 1,684,426,752 used. The sample was 0.81 seconds old and `stale=false`. `nvidia-smi` reported driver 617.14. These are changing baseline measurements, not a model-fit result. On 2026-10-10, `%USERPROFILE%\.wslconfig` was raised to 26 GB and WSL was restarted; `docker info` then reported 27,313,496,064 bytes (25.44 GiB) total memory. That cap limits Docker Desktop's Linux engine; check it before running large containers now that the desktop has about 125 GiB of RAM.

### Image model files

Recorded 2026-10-10. The installed ComfyUI files were inventoried by path, filename, size, and SHA256; no weights were loaded into a model runtime and ComfyUI was not started. The model files are under `C:\Users\Steve\Documents\ComfyUI\models`:

- Qwen Image 2.1 set: `diffusion_models\qwen_image_2.1_int8_convrot.safetensors` (7,256,783,064 bytes; SHA256 `cb74113cb03faecd79611b01fd7fd642f0aa60d6f0b95086abee214d75eaa57d`), `text_encoders\qwen3vl_8b_int8_convrot.safetensors` (9,350,798,360 bytes; SHA256 `8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f`), and `vae\qwen_image_2.1_vae_bf16.safetensors` (675,509,688 bytes; SHA256 `bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9`).
- Krea 2 Turbo set: `diffusion_models\krea2_turbo_nvfp4.safetensors` (7.15 GiB) or `diffusion_models\krea2_turbo_int8_convrot.safetensors` (12.57 GiB), `text_encoders\qwen3vl_4b_fp8_scaled.safetensors` (4.88 GiB), and `vae\qwen_image_vae.safetensors` (0.24 GiB).

A set of 15 small config/tokenizer files, 16 MB total, from `Qwen/Qwen-Image-2.1` revision `d26bb61231c349cf6b7896fa83353113880e1ba3` is staged at `C:\Users\Steve\Documents\ComfyUI\models\diffusers\Qwen-Image-2.1-generationstation-config`. It supplies configuration/tokenizer assets, not model weights.

The pinned image `lmsysorg/sglang@sha256:2dbe4c7f53230b09aaa8fa41891c13c51d9d2e253f486a70822aaf08783fff75` (SGLang 0.5.21, 52.6 GB unpacked, nvcc 13.0.88) is pulled into Docker Desktop and was still present on 2026-11-12; it lacks `comfy-kitchen`. A one-shot GPU passthrough container ran `nvidia-smi` and saw the RTX 5090. The official Qwen 2.1 cookbook recommends a nightly image containing the integration and says no published Docker image is verified, so this pinned image's compatibility is unverified. No model container, real load, or image inference has run.

## Open inputs

- The laptop browser's authenticated connection and reconnect experience against the desktop still needs an end-to-end check.
- Qwen Image 2.1: choose the runtime (SGLang-Diffusion in Docker, as decided on 2026-10-10, or a native worker), then verify it with the checksummed files above and measure RAM and VRAM before enabling loads.
- Priority when coding and media compete for memory.
- Acceptable cold load time and generation latency.

Do not use another machine's hardware as a substitute for the desktop inventory.

## Documentation workflow

- Repository Markdown is authoritative for the plan and technical decisions; BookStack holds readable mirrors and continuation context.
- Update the repository document first, then its corresponding BookStack page. Record page IDs and URLs in `docs/bookstack.json`.
- Read the current BookStack page before updating; use the shared CLI's expected revision timestamp check where available. This check is best effort, not a server-side compare-and-swap guarantee. If BookStack has content the repository lacks, merge it into the repository first; never overwrite it unseen.
- Keep current status, evidence, unresolved questions, and next steps explicit. Distinguish recommendations from accepted decisions and measured facts.
- BookStack is a development documentation dependency only. Generation Station must operate when BookStack is offline.
- Reuse the shared `bookstack-agent-cli` (Windows copy: `C:\Users\Steve\git\bookstack-agent-cli`) and its external credential configuration. Do not commit credentials or copy them into the application.

## Current state and next action

M1 and M2, 2026-10-09: on the Windows desktop the API reported fresh RAM and NVML telemetry, PostgreSQL was healthy, and a dedicated PostgreSQL migration/persistence/locking integration check passed. A 1 GiB RAM / 1 GiB RTX 5090 fake-worker profile reached `simulation_ready`, unloaded cleanly, and left zero active capacity reservations. The fake worker starts no process, opens no model files, and runs no inference.

Earlier attempt, 2026-10-10 (code not preserved): a session recorded in BookStack implemented a first real-model slice for Qwen Image 2.1 on SGLang-Diffusion: a server-owned Docker container with the pinned image, read-only component mounts, loopback-only port publication, container identity and readiness checks, restart recovery, unload confirmation, and admission that intersected Windows RAM with Docker's WSL2 memory ceiling. Loads stayed disabled pending compatibility testing, and no inference ran. That code was never committed: on 2026-11-12 it was not in either local copy, the Git stash, or GitHub (`main` at `d45befb` only). Only the notes above and the Docker image remain.

Update 2026-11-11 and 2026-11-12 (branch `feature/basalt-runtime`): development moved fully to Windows (`C:\Users\Steve\git\generationstation`), with a fresh PostgreSQL on Docker Desktop; the WSL copy and its database are retired. Implemented: a server-side runtime catalog (`runtimes.json`, local and ignored by Git; `runtimes.example.json` committed), the model plugin system with Basalt and YuE2 plugins, process supervision with re-adoption after an API restart and crash detection, real-runtime admission using per-preset estimates, the worker protocol and generation jobs, and a dashboard with model, GPU and advanced-setting choices, a generated "Make a song" form, and a results list with playback. 95 backend tests (including PostgreSQL tests with stand-in processes) and 15 Playwright tests pass.

On the desktop, a live DeepSeek start was correctly refused while a game held most of the RTX 4080 (about 1 GiB available after headroom against a 10 GiB estimate); no process was started. First real load, 2026-11-11, through the API while a game used the RTX 4080: DeepSeek V4.1 Flash on the RTX 5090 only (`gpus: [0]`), preset defaults except `ram_reserve_mib: 16384`. Ready in 51 s. At ready the 5090 used 27,464 MiB of 32,607 and system RAM use rose by 50.6 GiB; after one chat request it was about 62.7 GiB. The 4080 was not used. A minimal chat completion returned the requested text in 12.1 s (38 prompt and 30 completion tokens, including thinking). Stop through the API finished in 6 s: no `basalt.exe` remained, port 8160 closed, the 5090 returned to 0 MiB used, and the RAM was returned. The DeepSeek RAM estimate was raised from 8 to 16 GiB beyond the overflow-expert budget to match this. After the plugin refactor, the same start reached readiness in 55 s and stopped cleanly. Still open: repeated cycles, a two-GPU load, and a Flash-Next load.

First song, 2026-11-12: YuE2 3B (`m-a-p/YuE2-3B` + `YuE2-Vae`, `yue2_infer` 0.1.5, torch 2.10.0+cu128) on the RTX 5090 through the API, while a game used the RTX 4080. The worker was ready in 15 s using 7.4 GB VRAM and about 1 GiB RAM. A two-section English song (verse and chorus, seed 42) took 41 s to produce 49 s of 48 kHz audio; VRAM peaked at 9.8 GB. The FLAC (9.1 MB) and the melody score were fetched through the API. Stop freed the card to 0 MiB and left no worker process. The YuE2 RAM estimate was lowered from 24 to 8 GiB; the VRAM estimate stays at 14 GiB, the model card's peak at maximum context. Windows PyTorch has the FlashAttention op but not its kernels, and YuE2 chose it by checking only for the op; the worker now tests FlashAttention at load and uses YuE2's cuDNN attention path when it is missing.

Next: Qwen Image and MiniMax H3 plugins, a simple page for the primary user separate from the admin dashboard, and the Proxmox split. Do not treat fake-worker or stand-in results, or model file sizes, as model support or a memory profile.
