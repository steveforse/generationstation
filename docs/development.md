# Development and desktop operation

This guide covers the initial layout: FastAPI runs natively on Windows so host memory monitoring sees the physical machine; Docker runs PostgreSQL only. Model runtimes are not installed by these steps. The target desktop is Windows 11 with 32 GB system RAM and an RTX 5090 with 32 GB VRAM. Native Windows telemetry confirmed those devices on 2026-10-09; one RAM/VRAM baseline sample and other verified host details are recorded in `docs/context.md`. These measurements change over time and do not establish a real model's memory needs.

## Prerequisites

- Docker Desktop with the Compose plugin.
- `uv` for locked Python dependencies. On Windows, install it with `winget install --id=astral-sh.uv -e`, or use the [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).
- Node.js 24 LTS and npm for Vite development and frontend builds. This matches the current development setup; see the [official Node.js release schedule](https://nodejs.org/en/about/previous-releases).
- PowerShell 7.4 or newer for the documented database backup and restore examples.

The Python project supports Python 3.10 and newer. This guide uses Python 3.12, installed and selected by `uv`; its lockfile records the exact resolved dependencies. The development machine and target desktop each need their own `.env` file. Do not copy credentials from one machine to the other.

## First-time setup

Run these commands from the repository root in PowerShell. `init_env.py` creates a private, machine-specific `.env`; it refuses to overwrite an existing one.

```powershell
uv python install 3.12
uv sync --locked --project backend --python 3.12
uv run --locked --project backend python scripts/init_env.py
docker compose config --quiet
docker compose up -d --wait db
uv run --locked --project backend alembic -c backend/alembic.ini upgrade head
```

The Compose file pins PostgreSQL 17.11 Bookworm, binds its published port to loopback, and stores database files in the `postgres_data` named volume. The default host port is 5439. To change it, set `GS_DB_PORT` in `.env`; keep `GS_DATABASE_URL` in sync with that port. The generator creates matching database credentials in both variables. The PostgreSQL container only reads `POSTGRES_PASSWORD` when it initializes a new volume, so changing `.env` does not rotate a password in an existing database.

## M2 simulation profiles and admission

M2 profiles exercise capacity policy with a fixed simulation worker. The worker starts no process, opens no model files, and performs no inference. Its successful `simulation_ready` status tests only API lifecycle behavior; it is not a claim that a model can load or fit on any GPU.

Current simulation defaults reserve a provisional 4 GiB of system RAM and 2 GiB per assigned GPU as headroom. Override them through `GS_RAM_HEADROOM_BYTES` and `GS_GPU_HEADROOM_BYTES` in the desktop `.env`. These are engineering cushions, not measured allowances for Windows, desktop applications, or model workloads. Keep them conservative until baseline idle usage and real model peaks are measured on the target desktop; never lower them to make an unverified profile pass.

Admission is performed by the API for every load request. It requires a native desktop host with host-scope telemetry, `stale` explicitly false, finite sample age below the stale threshold, valid system RAM data, and complete per-GPU readings. The profile names GPU devices by exact telemetry identifier; the controller does not add VRAM across devices. For each requested resource it subtracts current configured headroom and all active reservations from current available bytes. Missing, stale, malformed, or unmatchable measurements fail closed. Profile numbers in this simulation are fixtures for exercising these rules, not actual model requirements; do not infer them from weight-file size.

The profile fields are `id`, `name`, `workload`, positive `ram_peak_bytes`, `gpu_vram_bytes_by_id`, and `mode: "simulation"`. In the create request, `id` is the model slug; the response gives the profile a separate UUID `id` and includes `model_id`. Use the UUID from `GET /api/host` as a GPU map key; an empty map means the profile requests no GPU memory. Authenticated `GET /api/profiles` lists profiles. `POST /api/profiles` creates a model and profile together; `PUT /api/profiles/{model_id}` updates one and `DELETE /api/profiles/{model_id}` removes the profile while preserving catalog identity and operation history. The same model ID can be profiled again. A profile cannot be modified or removed while its fake worker is active.

To exercise admission through the API, call `POST /api/models/{model_id}/load` with `{"profile_id":"<profile-uuid>"}` and an `Idempotency-Key` header. The accepted response is HTTP 202 and includes both `id` and `operation_id`; poll `GET /api/operations/{operation_id}`. Unload with `POST /api/models/{model_id}/unload`, again using an idempotency key; unload does not depend on fresh telemetry, so a stale sample cannot prevent cleanup. `GET /api/operations?limit=100` returns recent lifecycle records. Statuses include `loading`, `simulation_ready`, `unloading`, `unloaded`, `refused`, `failed`, and `cleanup_failed` (`checking` is not currently emitted). A refusal returns HTTP 409 with a stable reason code and operation ID; resource details include requested bytes, available bytes after headroom/reservations, and headroom bytes. Reusing one idempotency key for a different action or request returns `IDEMPOTENCY_KEY_REUSED`.

The fake worker is an in-memory lifecycle fixture, not an external process: it accepts no command, opens no files, and performs no inference. API operation responses label it `simulation: true` and `worker_type: "fake"`. It reports `simulation_ready` when the adapter's readiness check succeeds. Service restart discards those process-local handles, marks active simulation records failed, and releases their fake-only reservations; this says nothing about how a future real worker should be reconciled.

If Docker reports that the database is unhealthy, inspect `docker compose logs db` and `docker compose ps`. Do not delete the named volume to troubleshoot; it contains persistent application data.

## Real runtimes (Basalt and vLLM)

Real model servers are listed in a local, machine-specific catalog. Copy the example and adjust paths:

```powershell
Copy-Item runtimes.example.json runtimes.json
```

`runtimes.json` is ignored by Git. Set `GS_RUNTIMES_FILE` to use another path; without a file, only simulation profiles are available. A broken file stops the API from starting, so mistakes are not silently ignored. Each runtime defines its executable, port, extra `PATH` entries and environment, and one or more presets. Each preset names its model file, default GPUs (NVML/`nvidia-smi` index order; the service starts Basalt with `CUDA_DEVICE_ORDER=PCI_BUS_ID` so the indices match), Basalt keys that are always written (`fixed`), the user-adjustable `settings` with defaults, and a start `estimate`. The browser can only choose a preset, choose among `allowed_gpus`, and change the preset's listed settings within fixed bounds; it never supplies paths, commands, or other flags.

Estimates are conservative start requirements: free VRAM per GPU index and RAM (plus `resident_budget_gib` when set). They are guesses until measured; edit them in `runtimes.json` as you measure real loads. Admission compares them with live telemetry minus headroom, exactly as for simulation profiles. Basalt itself fills each card except its reserve, so the estimates guard the start, not the steady state. An `llm` card setup may instead use `engine: "vllm"` with `executable`, `working_dir`, `model_path` and `fixed_args`; the service runs `vllm serve` on the chosen cards, and readiness comes from a statusless `/v1/models` list (see [plugins.md](plugins.md)).

- `GET /api/runtimes` lists runtimes, presets, setting definitions and the last start's choices (no paths or environment).
- `POST /api/runtimes/{id}/start` with `{"preset": "ds41", "settings": {...}, "gpus": [0, 1]}` and an `Idempotency-Key` header starts a load. Invalid settings return 422 `SETTINGS_INVALID`; a server already listening on the runtime's port (for example Basalt started with `basalt-start`) returns 409 `PORT_IN_USE`; capacity refusals return 409 as above.
- Stop with `POST /api/models/{id}/unload`.

Each runtime's `kind` selects a model plugin; see [plugins.md](plugins.md) for the plugin contract and how to add one. For each start the service writes the plugin's files (for Basalt, `basalt-config.json`) to `runtime/launch/<operation>/` and the server output to `runtime/logs/<kind>-<operation>.log`. It runs `basalt.exe serve --config <file>` directly (no `.bat` or WSL), waits until `/v1/models` reports `loaded`, and records `ready`. If Basalt exits during the load, the operation fails with the last log lines. Once ready, the capacity reservation is released because telemetry now shows the real memory. Stopping ends only the process tree this service started, after checking the process start time so a reused PID is never touched. A ready Basalt keeps running when the API restarts and is re-adopted on the next start; a process left from an interrupted load is stopped. If a ready Basalt exits on its own, the model is marked failed with `WORKER_EXITED`.

## YuE2 (songs)

YuE2 runs in its own environment, not Generation Station's. On the desktop it was set up like this (CC BY-NC 4.0 weights from Hugging Face `m-a-p`):

```powershell
uv venv C:\ai\envs\yue2-worker --python 3.12
uv pip install --python C:\ai\envs\yue2-worker\Scripts\python.exe "huggingface-hub==0.36.2"
C:\ai\envs\yue2-worker\Scripts\hf.exe download m-a-p/YuE2-3B yue2_infer-0.1.5-py3-none-any.whl --local-dir C:\ai\downloads\yue2
uv pip install --python C:\ai\envs\yue2-worker\Scripts\python.exe C:\ai\downloads\yue2\yue2_infer-0.1.5-py3-none-any.whl
# yue2_infer pins torch==2.10.0, which PyPI serves CPU-only on Windows. Replace it with the CUDA build:
uv pip install --python C:\ai\envs\yue2-worker\Scripts\python.exe "torch==2.10.0" --index-url https://download.pytorch.org/whl/cu128 --reinstall-package torch
C:\ai\envs\yue2-worker\Scripts\hf.exe download m-a-p/YuE2-3B --local-dir D:\ai\models\yue2\YuE2-3B --exclude "*.whl"
C:\ai\envs\yue2-worker\Scripts\hf.exe download m-a-p/YuE2-Vae --local-dir D:\ai\models\yue2\YuE2-Vae
```

Check with `C:\ai\envs\yue2-worker\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"`; it must print a `+cu128` version and `True`. The `yue2` entry in `runtimes.example.json` points at these folders and writes songs to `D:\ai\outputs\yue2`.

## MiniMax H3 (videos)

MiniMax H3 runs in `C:\ai\envs\minimax-h3-worker`: the Qwen Image worker environment's exact package versions (torch 2.14.1+cu130, diffusers 0.43.0, torchao 0.18.0, transformers 5.22.2, peft, triton-windows) plus `av` and `psutil`. It needs an RTX 50-series card. Files, as set up on the desktop on 2026-11-15/16 (use repeated `--include` flags; a single `--exclude` followed by several patterns downloads the whole 500 GB repository):

```powershell
$hf = "C:\ai\envs\qwen-image-worker\Scripts\hf.exe"; $m = "D:\ai\models\minimax-h3"
& $hf download MiniMaxAI/MiniMax-H3 --local-dir $m\diffusers --include "*.json" --include "processor/*" --include "tokenizer/*" --include "text_encoder/*.json" --include "vae/*" --include "audio_vae/*" --include "LICENSE"
& $hf download lilcheaty/MiniMax-H3-NVFP4 minimax_h3_fl2va_pruned_nvfp4.safetensors --local-dir $m\nvfp4
& $hf download larryvrh/MiniMax-H3-Turbo-Lora minimax_h3_turbo_v4_step600_ema.safetensors --local-dir $m\turbo-v4
& $hf download llmfan46/Qwen3-VL-32B-Instruct-ultra-uncensored-heretic --local-dir $m\uncensored\heretic-bf16
```

`h3_silu_temb_grid.safetensors` (needed by the Turbo v4 add-on) comes from the GitHub repository `Larryvrh/ComfyUI-MiniMax-H3-Turbo`; put it in `$m\turbo-v4`. The `minimax_h3` entry in `runtimes.example.json` points at these files and writes clips to `D:\ai\outputs\minimax-h3`.

## Web search for the chat (SearXNG)

The chat's `web_search` tool asks a SearXNG instance; without an address set it is not offered (`read_page` works either way). The owner wants SearXNG on the Proxmox homelab server, not the desktop. On a Docker host there (an LXC or VM):

```sh
mkdir -p ~/searxng/config && cd ~/searxng
cat > docker-compose.yml <<'YAML'
services:
  searxng:
    image: searxng/searxng:latest   # pin a dated tag once it works
    restart: unless-stopped
    ports: ["8080:8080"]
    volumes: ["./config:/etc/searxng"]
    environment:
      SEARXNG_BASE_URL: http://<proxmox-host>:8080/
YAML
docker compose up -d && docker compose down   # writes config/settings.yml
```

In `config/settings.yml`: set `server.secret_key` to a long random string, `server.limiter: false` (only the home network can reach it), and add `json` to `search.formats` (`[html, json]`), which the app needs. Then `docker compose up -d`. Check it from the desktop: `curl "http://<proxmox-host>:8080/search?q=test&format=json"` returns JSON.

Then enter the address under the gear menu → **Host settings** → Web search, press **Test**, and **Save**. It is stored in the host's database (`app_settings`, migration 0008), so it stays with this host, and the chat uses it from its next answer without a restart. `GS_SEARXNG_URL` in `.env` is only a fallback while nothing is saved; saving an empty address turns search off. The owner's instance on the homelab is saved there (HTTP for now: HTTPS on its name failed the TLS handshake with "unrecognized name" on 2026-11-22). Keep the port closed to the internet: SearXNG is reachable from the home network or the tailnet only.

`read_page` refuses addresses on this machine and private networks (also after redirects), so web pages cannot steer it at local services; the chat's instructions treat web text as information, never instructions.

## Run the API and frontend

Use separate PowerShell terminals, from the repository root unless noted.

API:

```powershell
uv run --locked --project backend uvicorn generationstation.app:create_app --factory --host 0.0.0.0 --port 8000
```

Frontend:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open the Vite URL printed by the command, normally `http://localhost:5173`. Vite proxies `/api` and `/health` to the local API. The API's `/health` endpoint does not require a token; `/api/*` requests require `Authorization: Bearer <token>` using `GS_API_TOKEN` from `.env`. For a local API smoke check, read the token locally without pasting it into chat or a URL:

```powershell
$env:GS_API_TOKEN = (Get-Content .env | Where-Object { $_ -match '^GS_API_TOKEN=' } | Select-Object -First 1).Split('=', 2)[1]
Invoke-RestMethod http://127.0.0.1:8000/api/host -Headers @{ Authorization = "Bearer $env:GS_API_TOKEN" }
Remove-Item Env:GS_API_TOKEN
```

The API writes one JSONL access record when response headers are sent, including for streaming endpoints such as `/api/events`. Records contain the method, route template, peer IP, status, timestamp, and time to response headers. Query strings, request headers, and bodies are not logged. Logs go to `runtime/logs/access.jsonl` and stderr; the file rotates at 10 MiB and retains five backups. The `runtime/` directory is ignored by Git.

The root `.env` is ignored by Git. Avoid commands that echo it or include its contents in shell history. The current API token is a host setting. A client connecting to a different machine must supply that machine's bearer token through the app's connection settings; never embed it in the server URL. The browser's server URL is a client preference, not `GS_DATABASE_URL`.

## Migrations and frontend build

After pulling schema changes, apply Alembic migrations from the repository root:

```powershell
uv run --locked --project backend alembic -c backend/alembic.ini upgrade head
```

Create and review a migration when changing persistent schema; do not rely on API startup to create or alter tables. To see the current migration revision:

```powershell
uv run --locked --project backend alembic -c backend/alembic.ini current
```

Build the static frontend bundle:

```powershell
Set-Location frontend
npm ci
npm run build
```

The API serves `frontend/dist` when that directory exists. For local UI work, the Vite development server is more convenient. The frontend build does not package or containerize the API or inference processes.

## Remote browser access through Tailscale

The current Tailscale address `100.109.129.35` is temporary. Configure the browser client with the desktop's current server origin, including scheme and port (for example `http://<current-tailscale-ip>:8000` on a trusted private tailnet). Keep the URL editable in client settings; do not bake the current address into source code or `.env`. Send the API token as an Authorization header, never as a URL query parameter.

The dashboard provides an editable server address and access-token field. It saves each host's address and token in that browser's storage (accepted 2026-11-12; Forget removes both) and sends the token as a bearer header, never in a URL. On 2026-10-09, the laptop reached the desktop API over Tailscale on port 8000; an unauthenticated API request received HTTP 401, and the preflight from `http://localhost:5173` succeeded. Authenticated host telemetry and a fake-worker load/unload were verified on the desktop itself. The laptop browser's full connect, telemetry display, and reconnect path remain to be verified. SSH is configured locally as `generationstation-desktop` with the dedicated key; change its `HostName` if the Tailscale address changes. Restrict the Windows Firewall rule to the Tailscale interface/devices that need access, and confirm the policy on the tailnet. The API process must bind to an address reachable from the laptop (often `0.0.0.0`); do not expose it through router port forwarding. PostgreSQL remains bound to `127.0.0.1` and must not be opened to the tailnet. CORS only controls browser origins and is not authentication. Use HTTPS if the service is reachable outside a trusted Tailscale connection.

For a separately served frontend, put its exact origin in `GS_ALLOWED_ORIGINS` as a JSON list in `.env`, for example `GS_ALLOWED_ORIGINS=["http://localhost:5173"]`. A same-origin production UI normally does not need a CORS origin. Restart the API after changing settings.

## Verification commands

Run the backend checks from the repository root:

```powershell
uv run --locked --project backend pytest backend/tests -m "not database"
uv run --locked --project backend ruff check backend
```

The PostgreSQL integration tests create and remove a random schema, but run them only against a dedicated disposable test database. Create it once:

```powershell
docker compose exec -T db createdb -U generationstation generationstation_test
```

Set the test URL from the generated application URL without printing the credential, then run the database-marked checks:

```powershell
$databaseUrl = (Get-Content .env | Where-Object { $_ -match '^GS_DATABASE_URL=' } | Select-Object -First 1).Split('=', 2)[1]
$env:GS_TEST_DATABASE_URL = $databaseUrl -replace '/generationstation$', '/generationstation_test'
uv run --locked --project backend pytest backend/tests -m database
Remove-Item Env:GS_TEST_DATABASE_URL
```

When finished with the dedicated test database, remove only that database:

```powershell
docker compose exec -T db dropdb -U generationstation generationstation_test
```

Do not set `GS_TEST_DATABASE_URL` to the application database or another database containing data you need. The integration test drops its random schema when it exits.

Run the frontend production type-check/build:

```powershell
Set-Location frontend
npm ci
npm run build
```

Install Playwright's Chromium browser once, then run the end-to-end suite from `frontend/`:

```powershell
Set-Location frontend
npm ci
npx playwright install chromium
npm run test:e2e
```

The Playwright config starts the Vite server on `127.0.0.1:4173` and launches Chromium. Browser tests live under `frontend/tests/`. Database integration tests must use a disposable database configured through `GS_TEST_DATABASE_URL`; never point destructive tests at the working development database.

## Backup and safe restore

Back up PostgreSQL before database upgrades, before restoring, and on a regular schedule once desktop use begins. This saves database rows and schema only; it does not back up model weights, generated outputs, `.env`, or other files. Keep backups in the ignored `backups/` directory and copy them to storage separate from the Docker volume. PowerShell 7.4+ preserves native command output bytes when using `>`; the `<` operator is reserved for future use, so the restore below copies the SQL file into the container and invokes `psql -f`. See Microsoft's [PowerShell language reference](https://learn.microsoft.com/en-us/powershell/scripting/lang-spec/chapter-07#712-redirection-operators) and [redirection guide](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection).

Create a plain SQL backup while the database is running:

```powershell
New-Item -ItemType Directory -Force backups | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
docker compose exec -T db pg_dump --no-owner --no-privileges -U generationstation -d generationstation > "backups/generationstation-$stamp.sql"
if ($LASTEXITCODE -ne 0) { throw 'Database backup failed.' }
```

Restore into a **new empty database** first. This leaves the current database intact for rollback. Set `$backup` to the desired file and choose a fresh database name:

```powershell
$backup = '.\backups\generationstation-YYYYMMDD-HHMMSS.sql'
$backupPath = (Resolve-Path $backup).Path
$restoreDb = 'generationstation_restore'
$containerFile = '/tmp/generationstation-restore.sql'
docker compose exec -T db psql -U generationstation -d postgres -c "CREATE DATABASE $restoreDb OWNER generationstation;"
if ($LASTEXITCODE -ne 0) { throw 'Could not create the empty restore database.' }
try {
    docker compose cp $backupPath "db:$containerFile"
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy the backup into the database container.' }
    docker compose exec -T db psql -v ON_ERROR_STOP=1 -U generationstation -d $restoreDb -f $containerFile
    if ($LASTEXITCODE -ne 0) { throw 'Database restore failed; the original database remains unchanged.' }
} finally {
    docker compose exec -T db rm -f $containerFile
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Could not remove the temporary restore file from the container.' }
}
```

Stop the API before switching it to the restored database. Update `GS_DATABASE_URL` in `.env` to point at `$restoreDb`, restart the API, and verify health and expected records. Keep the original database until verification succeeds. To roll back, stop the API and point `GS_DATABASE_URL` back to `generationstation`. Once the restore is accepted, schedule a separate maintenance window to rename/swap databases; do not drop the original as part of an unverified restore. Never run `docker compose down -v` as a backup or restore step: it deletes the named database volume.

## Stop services

Stop the API and Vite with Ctrl+C, then stop only the database container:

```powershell
docker compose down
```

The named database volume remains. Model weights, generated outputs, and runtime caches belong outside source control and should use their own explicit backup plan.
