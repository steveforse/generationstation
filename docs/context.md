# Project context

Updated: 2026-11-21.

## Confirmed requirements

- Working name: Generation Station (formerly ModelDock).
- Web interface accessed from a browser; service and inference run on the desktop. Planned (2026-11-11): the web app moves to a Proxmox homelab server and calls the desktop, which keeps running the models.
- The primary user is non-technical and wants to make music, images, and video; licensing is not a concern for this personal use.
- Multiple AI models installed, with explicit load and unload controls, including choosing which GPU a model uses and stopping Basalt to make room for a media model.
- Display current host RAM and VRAM usage.
- Refuse a load when sufficient host capacity cannot be established.
- Workloads: Basalt text models (DeepSeek V4.1 Flash, Qwen3.8 Flash-Next), YuE2 music, Qwen Image 2.1 images, MiniMax H3 video. These are targets, not a promise that all fit at once.
- The user prefers a Generation Station inference runtime independent of ComfyUI; ComfyUI is a source of already-downloaded model weights, not the intended runtime. ComfyUI and biniou were evaluated as products on 2026-11-11 and rejected (interface too complex; biniou lacks the target models and runs UI and models in one process).

## Accepted stack and connectivity decisions

- React + TypeScript + Vite for the frontend, and Python + FastAPI for the native host API/supervisor; the user accepted this stack on 2026-10-08 after comparing FastAPI with Rails.
- PostgreSQL in Docker with a persistent named volume replaces the SQLite proposal. Since 2026-11-11 it runs on Docker Desktop on Windows; the earlier WSL Docker database was retired.
- SQLAlchemy 2 and Alembic are selected for PostgreSQL access and schema migrations. PostgreSQL 17 is pinned to the maintained 17.11 Bookworm image; update the patch tag after checking official release/image metadata.
- Model weights and generated outputs remain files outside the database and source control.
- Model plugins (accepted 2026-11-11): each runtime kind is a plugin in this repository (`backend/generationstation/plugins/`). Media models run in workers (`workers/`) under their own Python environments, speaking one HTTP protocol. See `docs/plugins.md`.
- Qwen Image 2.1 runs in a native Windows worker (`workers/qwen_image_worker.py`, Diffusers + torchao), like YuE2's; this replaced the 2026-10-10 SGLang-Diffusion-in-Docker plan when the plugin was built (2026-11-14/15). The user chose NVFP4 weights on both cards (2026-11-15), with the text encoder on the processor so nothing moves between the card and system RAM per picture (the user's objection to the 4080 setup was the swapping).
- Tailscale provides current remote access. Desktop IP: `100.109.129.35`; it may change. The dashboard keeps a list of hosts; since 2026-11-12 it saves each host's address and access token in that browser's storage (the user chose "remember on this device"), with Forget per host, and sends bearer authentication. On 2026-10-09, the laptop reached the desktop API on port 8000; an unauthenticated API request returned HTTP 401, and the Vite-origin CORS preflight succeeded. The full laptop-browser connection and reconnect path remains to be checked. SSH works through the local `generationstation-desktop` alias; update its `HostName` if the Tailscale address changes. The API currently listens on 127.0.0.1 during development.

## Engineering recommendations and pending decisions

1. Python + FastAPI is accepted for the host API and supervisor. Use SQLAlchemy and Alembic for database access and migrations.
2. REST commands and server-sent events for telemetry and lifecycle updates.
3. One desktop and one scheduler owner initially; serialize model lifecycle operations.
4. Run PostgreSQL in Docker. Keep the API, host telemetry and process supervision native on Windows. Model workers run as native Windows processes in per-model Python environments; a containerized worker (such as SGLang) would need Docker/WSL2 memory accounting in admission, as the 2026-10-10 attempt designed.
5. Manual model management first; automatic eviction, generation workflows, and concurrency later.

## Desktop inventory

Hardware was reported on 2026-10-08 and changed since. Windows checks on 2026-11-11 measured:

- CPU: AMD Ryzen 9 9950X3D, 16 cores / 32 threads (Windows check 2026-11-15; the 2026-11-11 notes said Ryzen 7 5800X3D).
- System RAM: about 125.5 GiB (Windows `TotalPhysicalMemory`); it was 32 GB at the October check.
- Storage: 2 TB NVMe SSD; C: had about 571 GB free on 2026-11-11 after compacting the WSL disk. D: (about 2 TB) is the AI drive since 2026-11-21: all model weights live under `D:\ai\models`; environments (`C:\ai\envs`) and Basalt (`C:\ai\basalt-win`) stay on C:. Generated files moved to `D:\ai\outputs` on 2026-11-21. The move's verification flagged the DeepSeek V4.1 Flash `.basalt` file on D: as not matching its source (the C: original is gone); the owner chose to keep using that copy.
- GPUs, in NVML/PCI order: index 0 NVIDIA RTX 5090 (32 GB), index 1 NVIDIA RTX 4080 (16 GB). The 4080 drives the display, so its free VRAM moves with desktop and game use.
- OS: Windows 11.

Historical sample from the October inventory (32 GB RAM, single GPU): the native Windows API reported a live host-scoped sample at `2026-10-09T14:12:44Z`: system RAM 34,280,030,208 bytes total, 24,476,930,048 available, and 9,803,100,160 used; RTX 5090 VRAM 34,190,917,632 bytes total, 32,506,490,880 available, and 1,684,426,752 used. The sample was 0.81 seconds old and `stale=false`. `nvidia-smi` reported driver 617.14. These are changing baseline measurements, not a model-fit result. On 2026-10-10, `%USERPROFILE%\.wslconfig` was raised to 26 GB and WSL was restarted; `docker info` then reported 27,313,496,064 bytes (25.44 GiB) total memory. That cap limits Docker Desktop's Linux engine; check it before running large containers now that the desktop has about 125 GiB of RAM.

### Image model files

Recorded 2026-10-10. The installed ComfyUI files were inventoried by path, filename, size, and SHA256; no weights were loaded into a model runtime and ComfyUI was not started. The model files are under `C:\Users\Steve\Documents\ComfyUI\models`:

- Qwen Image 2.1 set: `diffusion_models\qwen_image_2.1_int8_convrot.safetensors` (7,256,783,064 bytes; SHA256 `cb74113cb03faecd79611b01fd7fd642f0aa60d6f0b95086abee214d75eaa57d`), `text_encoders\qwen3vl_8b_int8_convrot.safetensors` (9,350,798,360 bytes; SHA256 `8bfd0f6e12abf2d2d697ecc888e5e90b0d6741d6708f05799f53afa560452e8f`), and `vae\qwen_image_2.1_vae_bf16.safetensors` (675,509,688 bytes; SHA256 `bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9`).
- Krea 2 Turbo set: `diffusion_models\krea2_turbo_nvfp4.safetensors` (7.15 GiB) or `diffusion_models\krea2_turbo_int8_convrot.safetensors` (12.57 GiB), `text_encoders\qwen3vl_4b_fp8_scaled.safetensors` (4.88 GiB), and `vae\qwen_image_vae.safetensors` (0.24 GiB).

A set of 15 small config/tokenizer files, 16 MB total, from `Qwen/Qwen-Image-2.1` revision `d26bb61231c349cf6b7896fa83353113880e1ba3` is staged at `C:\Users\Steve\Documents\ComfyUI\models\diffusers\Qwen-Image-2.1-generationstation-config`. It supplies configuration/tokenizer assets, not model weights.

The pinned image `lmsysorg/sglang@sha256:2dbe4c7f53230b09aaa8fa41891c13c51d9d2e253f486a70822aaf08783fff75` (SGLang 0.5.21, 52.6 GB unpacked, nvcc 13.0.88) is pulled into Docker Desktop and was still present on 2026-11-12; it lacks `comfy-kitchen`. A one-shot GPU passthrough container ran `nvidia-smi` and saw the RTX 5090. The official Qwen 2.1 cookbook recommends a nightly image containing the integration and says no published Docker image is verified, so this pinned image's compatibility is unverified. No model container, real load, or image inference has run.

### Qwen Image 2.1 worker

Measured 2026-11-14/15 on the desktop, 1024x1024, outside the API (benchmark scripts, then the worker started exactly as the plugin launches it and driven over the worker protocol). The API-managed run is recorded below.

- Files under `D:\ai\models\qwen-image-2.1\`: `uncensored\` (ChatR Labs Uncensored Omni: Qwen-Image-2.1 with their rank-128 adapter merged; NVFP4 ComfyUI file and other builds), `turbo-quant\` (official Qwen-Image-2.1-Turbo, NVFP4 and FP8), `turbo\` (Turbo's Diffusers folder: text encoder Qwen3-VL 8B, VAE, processor, scheduler), `base\` (Qwen-Image-2.1 scheduler and configs), `lightning\` (4-step Lightning adapter, used for "quick").
- Worker environment `C:\ai\envs\qwen-image-worker`: torch 2.14.1+cu130, diffusers 0.43.0, transformers 5.22.2, torchao 0.18.0, peft 0.21.2, torchvision 0.29.1, triton-windows 3.9.0.post30 (needed for compiling; without it the worker runs uncompiled and NVFP4 is slower than FP8). The environment has no pip; install with `uv pip install --python <env python>`.
- NVFP4 on the RTX 5090 runs real 4-bit maths (torchao, Blackwell only). The RTX 4080 has no 4-bit maths: the worker keeps the weights in 4 bits on the card and expands each layer to FP8 just before its matmul (checked against torchao's decoder: 0.1% difference, BF16 rounding).
- Each transformer block is compiled (Diffusers regional compilation). The first picture at each quality and shape after a start is slower; compiled kernels are cached on disk, so later starts warm up faster (5090: 21 s first time, 9 s later). Diffusers' prompt KV cache is off: with compiling it recompiled for every prompt length and saved nothing measurable.
- The text encoder stays in system RAM in BF16 and runs on the processor: 0.4-0.6 s per prompt. Swapping parts between RAM and the card was slower, and keeping the encoder on the 4080 next to the transformer overflowed it: Windows then backs PyTorch's cached memory with system RAM and each step took 40-120 s instead of about 1 s.
- Times per picture after warm-up, through the worker: RTX 5090 uncensored quick 1.7 s, best (35 steps, CFG 5) 15.2 s; RTX 4080 uncensored quick 3.6 s, best 42.3 s, Turbo (8 steps) 5.5 s. Earlier benchmark, 5090 Turbo NVFP4 1.9 s. For comparison, the 4080 with FP8 weights swapped per picture took 7.8 s / 45.8 s / 10.7 s.
- Card memory: peak 12.9 GiB reserved on the 5090 and 12.5-12.6 GiB on the 4080 (plus the CUDA context); between pictures the worker returns its cache, leaving about 5-5.6 GiB in use. Estimates: 15 GiB free on the 5090, 14 GiB on the 4080, 28 GiB RAM (measured 25.6 GiB committed, 18.6 GiB peak working set, with the prompt reader on the CPU).
- First run through the API, 2026-11-15, RTX 5090, Uncensored preset: start, three pictures (quick square 2.2 s, quick portrait 2.1 s, best square 19.6 s including its first-time preparation) fetched as PNGs, then stop. Stop freed the card to 0 MiB.
- NVFP4 small lettering at best quality is weaker than FP8's. Community INT4 (SVDQuant/Nunchaku) builds exist only for the stock model, need a Nunchaku fork with Linux wheels, and official Nunchaku does not support 2.1 yet (checked 2026-11-15).

### MiniMax H3 worker

Measured 2026-11-15 to 2026-11-21 on the RTX 5090, 960x544, 124 frames (5.2 s at 24 fps) with sound.

- Files under `D:\ai\models\minimax-h3\`: `diffusers\` (MiniMaxAI/MiniMax-H3 configs, tokenizer, schedulers, video and audio decoders), `nvfp4\minimax_h3_fl2va_pruned_nvfp4.safetensors` (11.7 GiB, ComfyUI NVFP4 "pruned" transformer), `uncensored\heretic-bf16\` (llmfan46's abliterated Qwen3-VL-32B-Instruct, BF16), `turbo-v4\` (larryvrh Turbo v4 step-600 EMA add-on and the `h3_silu_temb_grid` it needs), `comfy\loras\` (Comfy-Org Turbo v1.0, unused). Environment `C:\ai\envs\minimax-h3-worker`: the Qwen Image environment's pins plus PyAV 19.0.2 and psutil.
- The pruned checkpoint replaces H3's timestep embedder with a 1025x8 table and has ComfyUI tensor names; Diffusers 0.43's converter refuses it, so the worker maps names, splits fused q/k/v, swaps the feed-forward halves, and projects the table row without SiLU. MiniMax's own text encoder is byte-identical to stock Qwen3-VL-32B; H3 reads the un-normed hidden state after decoder layer 50, so only 50 layers are loaded (BF16, on the processor, about 2 s per prompt). An uncensored NVFP4 encoder from another uploader decoded to garbage and was deleted.
- Build comparison (2026-11-16, page "MiniMax H3 Build Test"): NVFP4 and ComfyUI FP8 looked equivalent; FP8 did not fit on the card with a Turbo add-on unless the video decoder streamed from RAM, and was 12% slower per step. Turbo v4 looked crisper than Comfy-Org's v1.0. NVFP4 + Turbo v4 was chosen; the FP8 file was deleted.
- H3 is trained on a structured prompt (`integrated_multimodal_description: [Shot 1] ...`, `overall_soundscape:`, `non_diegetic_music:`; spoken lines as `(S1) says: <d>[English] ...</d>`). The worker builds it from the form's description, sounds, music and look, turns `says: "..."` into a spoken line (one speaker), and passes a prompt that already starts with the structure through unchanged.
- First API-managed run, 2026-11-21: ready in 43 s (worker 22 s); quick (Turbo v4, 4 steps) 5 s clips 38-39 s after a 92 s first clip that compiles; best (20 steps) 164 s including its first compile (about 143 s warm in the comparison). Peak 24.4-24.6 GiB reserved; between clips about 20.5 GiB stays in use (transformer and decoders). The worker's peak working set was 51-54 GiB and its committed memory 87-89 GiB (Windows also counts the card's allocations there). Stop freed the 5090 to 10 MiB.
- A 10 s clip (243 frames) worked but took 135 s at quick and peaked at 29.7 GiB, above the 29.4 GiB admission allows on the 5090 after headroom, so the plugin offers 5 s only. Estimates: 28 GiB free on the 5090 (the 4080 is not allowed), 60 GiB RAM.

## Open inputs

- The laptop browser's authenticated connection and reconnect experience against the desktop still needs an end-to-end check.
- Priority when coding and media compete for memory.
- Acceptable cold load time and generation latency.

Do not use another machine's hardware as a substitute for the desktop inventory.

## Documentation workflow

- Keep current status, evidence, unresolved questions, and next steps explicit. Distinguish recommendations from accepted decisions and measured facts.

## Current state and next action

M1 and M2, 2026-10-09: on the Windows desktop the API reported fresh RAM and NVML telemetry, PostgreSQL was healthy, and a dedicated PostgreSQL migration/persistence/locking integration check passed. A 1 GiB RAM / 1 GiB RTX 5090 fake-worker profile reached `simulation_ready`, unloaded cleanly, and left zero active capacity reservations. The fake worker starts no process, opens no model files, and runs no inference.

Earlier attempt, 2026-10-10 (code not preserved): a session recorded in earlier project notes implemented a first real-model slice for Qwen Image 2.1 on SGLang-Diffusion: a server-owned Docker container with the pinned image, read-only component mounts, loopback-only port publication, container identity and readiness checks, restart recovery, unload confirmation, and admission that intersected Windows RAM with Docker's WSL2 memory ceiling. Loads stayed disabled pending compatibility testing, and no inference ran. That code was never committed: on 2026-11-12 it was not in either local copy, the Git stash, or GitHub (`main` at `d45befb` only). Only the notes above and the Docker image remain.

Update 2026-11-11 and 2026-11-12 (branch `feature/basalt-runtime`): development moved fully to Windows (`C:\Projects\generationstation` since 2026-11-12; first `C:\Users\Steve\git\generationstation`), with a fresh PostgreSQL on Docker Desktop; the WSL copy and its database are retired. Implemented: a server-side runtime catalog (`runtimes.json`, local and ignored by Git; `runtimes.example.json` committed), the model plugin system with Basalt and YuE2 plugins, process supervision with re-adoption after an API restart and crash detection, real-runtime admission using per-preset estimates, the worker protocol and generation jobs, and a dashboard with model, GPU and advanced-setting choices, a generated "Make a song" form, and a results list with playback. The backend tests (including PostgreSQL tests with stand-in processes) and Playwright tests pass.

On the desktop, a live DeepSeek start was correctly refused while a game held most of the RTX 4080 (about 1 GiB available after headroom against a 10 GiB estimate); no process was started. First real load, 2026-11-11, through the API while a game used the RTX 4080: DeepSeek V4.1 Flash on the RTX 5090 only (`gpus: [0]`), preset defaults except `ram_reserve_mib: 16384`. Ready in 51 s. At ready the 5090 used 27,464 MiB of 32,607 and system RAM use rose by 50.6 GiB; after one chat request it was about 62.7 GiB. The 4080 was not used. A minimal chat completion returned the requested text in 12.1 s (38 prompt and 30 completion tokens, including thinking). Stop through the API finished in 6 s: no `basalt.exe` remained, port 8160 closed, the 5090 returned to 0 MiB used, and the RAM was returned. The DeepSeek RAM estimate was raised from 8 to 16 GiB beyond the overflow-expert budget to match this. After the plugin refactor, the same start reached readiness in 55 s and stopped cleanly. Still open: repeated cycles, a two-GPU load, and a Flash-Next load.

First song, 2026-11-12: YuE2 3B (`m-a-p/YuE2-3B` + `YuE2-Vae`, `yue2_infer` 0.1.5, torch 2.10.0+cu128) on the RTX 5090 through the API, while a game used the RTX 4080. The worker was ready in 15 s using 7.4 GB VRAM and about 1 GiB RAM. A two-section English song (verse and chorus, seed 42) took 41 s to produce 49 s of 48 kHz audio; VRAM peaked at 9.8 GB. The FLAC (9.1 MB) and the melody score were fetched through the API. Stop freed the card to 0 MiB and left no worker process. The YuE2 RAM estimate was lowered from 24 to 8 GiB; the VRAM estimate stays at 14 GiB, the model card's peak at maximum context. Windows PyTorch has the FlashAttention op but not its kernels, and YuE2 chose it by checking only for the op; the worker now tests FlashAttention at load and uses YuE2's cuDNN attention path when it is missing.

Qwen Image plugin, 2026-11-15: `qwen_image` with "Qwen Image 2.1 Uncensored" (default; quick with Lightning, best at 35 steps) and "Qwen Image 2.1 Turbo" presets, NVFP4 on either card; measurements above. Its first API-managed run (start, pictures, stop on the RTX 5090) passed on 2026-11-15; the RTX 4080 has run only outside the API.

MiniMax H3 plugin, 2026-11-21: `minimax_h3` with one preset, "MiniMax H3 Uncensored" (NVFP4 transformer, uncensored prompt reader on the processor; quick with Turbo v4 at 4 steps, best at 20 steps), RTX 5090 only, 5 s clips in landscape, portrait or square; measurements above. Its first API-managed run (start, five clips, stop) passed on 2026-11-21.

Results, 2026-11-21: each job now keeps the model settings it ran with and what the worker actually used (seed, steps, size, full prompt, seconds taken; also saved as `job.json` beside the files). The generation page lists results in a sidebar with a detail view (prompt, settings, time, model, reuse, download, delete), and the form shows the measured time for the chosen settings. Restart fix: a stopped model's old start stays "ready" in history, and a restart used to mark the model failed because of it even when a newer start had just been re-adopted; restart clean-up now ignores operations superseded by a later start or stop (confirmed: an API restart re-attached a running H3 worker). Later the same day: sidebar thumbnails (workers save `thumbnail.jpg`; earlier H3 clips and Qwen pictures were backfilled), results open in a modal, and jobs can be cancelled while queued or mid-render (at the next step). Workers started before these changes need one stop and start to gain thumbnails, details and cancel. Modes and uploads, 2026-11-21: H3 has tabs "From a description" and "From pictures" (first frame, last frame or both, on the same NVFP4 transformer through Diffusers' `fl2va` workflow with MiniMax's alignment lines). The prompt reader now loads 51 layers plus Qwen3-VL's vision tower and runs Diffusers' own encoding steps on the processor, so pictures are read the way MiniMax intends. API run on the RTX 5090: first-frame 58 s (736x736, "match picture" from a square picture), first-and-last 64 s, last-frame 50 s, text 59 s (first clip after start), peaks 24.9-25.5 GiB; a "best" job cancelled at step 3 stopped within the step. Diffusers documents the reference mode's limits as 9 pictures, 3 videos, 3 audio clips, 12 in all, audio never alone; its NVFP4 transformer (`minimax_h3_ref2va_pruned_nvfp4.safetensors`, lilcheaty, 12.5 GB) is downloaded to `D:\ai\models\minimax-h3\nvfp4`.

H3 phase 2, 2026-11-21:
- A "From references" tab (Diffusers' `ref2va`) takes up to 9 pictures, 3 videos and 3 audio clips. The worker swaps the reference transformer onto the card when this tab is used (6-9 s) and back for the others. It builds MiniMax's six-section reference prompt from the description, optional notes ("Picture 1: ..."), and how videos and audio are used. Reference videos' own sound is dropped, so "audio N" is always the Nth audio clip. Turbo is not offered with references.
- At MiniMax's reference size (2048-pixel short edge) one picture took 726 s, with reading by the CPU prompt reader alone taking minutes. A reference video at the full canvas overflowed the card. "Reference detail" now sets the size: fast 768 / standard 1024 / high 2048 for pictures, and 256 / 352 / 544 for videos.
- Standard detail on the RTX 5090: one picture 202-246 s (reading 42-46 s); two pictures and a voice 324 s; a video used for camera and motion 434 s (reading 72 s, peak 27.6 GiB). Nine pictures at fast detail took 679 s (reading 258 s), peak 25.2 GiB.
- Quality levels: turbo 4 steps (Turbo v4), standard 20, high 30, extreme 50 (MiniMax's default).
- Shapes: 16:9, 9:16, 1:1, 4:5 and 4:3, plus "match picture". Resolutions: 240p, 360p, 480p, 540p and 720p (short edges 256, 352, 480, 544 and 704), or a custom size up to 1280 x 720 worth of pixels.
- Turbo timings for 5 s text clips: 240p 6 s (20.6 GiB), 360p 12 s, 480p 29 s, 540p ~40 s, 720p 89 s (28.1 GiB; portrait 28.3 GiB). Standard at 720p took 372 s. Native 1080p does not fit. The card estimate was raised to 29 GiB for 720p.
- With pictures, a shape that differs from the picture's now crops instead of stretching (Diffusers stretches keyframes). The framing is chosen on a preview: drag the box, use the arrow keys or the zoom slider. A portrait framing of a square picture through the app matched its first frame exactly.
- Tests ran first directly against the worker (outside the app), then through the app.


Next: a simple page for the primary user separate from the admin dashboard, and the Proxmox split. Do not treat fake-worker or stand-in results, or model file sizes, as model support or a memory profile.
