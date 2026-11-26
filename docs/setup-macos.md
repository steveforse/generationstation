# Setting up Generation Station on an Apple-silicon Mac

This guide takes a Mac from a fresh checkout to a dashboard that runs local text models and turns meeting recordings into transcripts and notes. It was written from a working setup on an M5 Max with 64 GB of memory (macOS 26). Where a figure depends on that machine, the text says so.

## What runs on a Mac

| Works | Does not (needs an NVIDIA card) |
| --- | --- |
| Dashboard, API, database, chat, logs | Pictures (Qwen Image), songs (YuE2), video (MiniMax H3), speech (OmniVoice, Qwen3-TTS) |
| Text models: Qwen3.8 27B, Qwen3.8 Flash-Next, Tencent Hy4-Flash, Inkling 2 Mini | The Basalt runtime and the Windows meeting engines (Nemotron, VibeVoice, DiariZen) |
| Meeting notes: speaker detection, speech recognition, correction, notes, name reading from Zoom video, transcript editing | |
| Web search for the chat through a local SearXNG | |

The Mac reports its shared memory as one pool (`apple-unified-memory`), counted once. There is no separate VRAM figure.

## What it needs

| Model (id in `runtimes.mac.example.json`) | Memory it asks for | Disk | Speed measured on an M5 Max |
| --- | --- | --- | --- |
| `qwen38_27b`, Qwen3.8 27B (4-bit, through oMLX) | 20 GiB | 15 GiB | 16-29 tok/s |
| `inkling2`, Inkling 2 Mini (oQ 4-bit, through oMLX) | 24 GiB | see its Hub page | 60-90 tok/s |
| `flash_next`, Qwen3.8 Flash-Next, Gyro-S / M / L (through Strata) | 34 / 38 / 38 GiB | 58.5 / 92 / 108 GB | 80-110 / 60-70 / 50-55 tok/s |
| `hy4_flash`, Tencent Hy4-Flash, SQ-64 (through Strata) | 36 GiB | about 122 GiB | 14-18 tok/s |
| `meeting_notes` speech steps | 6 GiB | about 3 GiB | about 4 minutes per hour of recording |

The target is a 64 GB Mac, which runs one large text model beside the meeting worker. Smaller Macs have not been tried: compare the memory column with what your Mac has free (plus the headroom described below), and expect only the smaller models to fit. You do not need every model: install the ones you want and delete the others from your `runtimes.json`.

A start is refused unless its estimate fits in the memory the Mac has available, less 4 GiB of headroom and what other running models already reserve (see [Memory on a Mac](#memory-on-a-mac)).

## 1. Install the basics

- **Xcode command line tools** (`xcode-select --install`). Building oMLX also needs the Metal toolchain: `xcodebuild -downloadComponent MetalToolchain`.
- **uv**: `brew install uv`, or the [official installer](https://docs.astral.sh/uv/getting-started/installation/).
- **Node.js 24 LTS** with npm, by any route (Homebrew, asdf, nvm). With asdf, `ASDF_NODEJS_VERSION=24.22.3` selects it for one command.
- **ffmpeg**: `brew install ffmpeg`. The meeting worker uses it, so it must be on the `PATH` of the shell that starts the API.
- **A container engine with Compose** for PostgreSQL: Docker Desktop, or Podman with the `docker` command. Any engine that understands `compose.yaml` works.
- **git**.

## 2. Run the app

From the directory where you keep code:

```sh
git clone https://github.com/steveforse/generationstation && cd generationstation
uv python install 3.12
uv sync --locked --project backend --python 3.12
uv run --project backend python scripts/init_env.py        # writes the private .env; refuses to overwrite one
printf '\nGS_HOST_ROLE=desktop\n' >> .env
docker compose up -d --wait db
uv run --locked --project backend alembic -c backend/alembic.ini upgrade head
```

`GS_HOST_ROLE=desktop` is needed on a Mac. Without it the API treats the machine as a development host and refuses every model start with `HOST_ROLE_UNSUPPORTED`. The setting only unlocks starts; capacity checks still apply.

Start the API and the frontend in two terminals:

```sh
uv run --locked --project backend uvicorn generationstation.app:create_app --factory --host 127.0.0.1 --port 8000
```

```sh
cd frontend && npm ci && npm run dev
```

Open `http://localhost:5173`. If it asks for a host address and token, use `http://127.0.0.1:8000` and the `GS_API_TOKEN` value from `.env`. Do not put the token in a URL or share it. The API's health check is `http://127.0.0.1:8000/health`.

### Your `runtimes.json`

`runtimes.json` lists the models this machine offers. It is not committed. Create it from the Mac template, which uses `/Users/YOU` for every path:

```sh
sed "s#/Users/YOU#$HOME#g" runtimes.mac.example.json > runtimes.json
```

The template keeps everything outside the repository under `~/ai` (`envs`, `models`, `tools`) and assumes the folder names used below. Delete the entries for models you will not install. **The API reads `runtimes.json` only when it starts, so restart it after every edit.** The Models page then shows one card per entry.

## 3. Meeting notes

The speech steps run as plain child processes in one Python environment: sherpa-onnx finds who spoke when (pyannote segmentation plus a speaker embedding, on the CPU, no account or token needed), and Qwen3-ASR on MLX transcribes each turn on the GPU. The notes come from whichever text model you choose in the form.

```sh
uv venv ~/ai/envs/meeting-worker --python 3.12
uv pip install --python ~/ai/envs/meeting-worker/bin/python \
  mlx-audio mlx-lm sherpa-onnx soundfile numpy huggingface-hub rapidocr-onnxruntime pillow
HF=~/ai/envs/meeting-worker/bin/hf
$HF download mlx-community/Qwen3-ASR-1.7B-8bit --local-dir ~/ai/models/asr/Qwen3-ASR-1.7B-8bit
mkdir -p ~/ai/models/diar && cd ~/ai/models/diar
curl -LO https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2 && tar xjf sherpa-onnx-pyannote-segmentation-3-0.tar.bz2
curl -LO https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx
```

`rapidocr-onnxruntime` and `pillow` are only for reading speaker names off a Zoom video. Without them everything else works and speakers are numbered.

Then, on the dashboard, start **Meeting notes** from the Models page and open it from the sidebar. Add a recording (audio or video) or a transcript (`.vtt`, `.srt`, `.txt`, `.md`), choose a text model under More options, and press **Make notes**. The first run shows what it did in each step; speech takes about four minutes per hour of recording, and correcting and summarising takes several more depending on the text model.

Things worth knowing:

- Speaker detection is tuned for Zoom recordings (`diar_threshold` 0.9 in the template; lower splits one person into several, higher merges people).
- For video, the speaker's name is read from the name tag at the bottom-left of the active speaker's tile. It needs the OCR packages above and `ffmpeg`. Google Meet has not been tried.
- After you change `workers/` code, **unload** Meeting notes on the Models page and start it again. The worker is a long-running process and keeps the code it started with.

## 4. Text models

Install only what you want. All of them sit outside the repository and are described in the template entry of the same name.

### Qwen3.8 27B and Inkling 2 Mini (oMLX)

[oMLX](https://github.com/jundot/omlx) (Apache-2.0, macOS 15+, Python 3.11-3.13) serves both. Build it from source in its own environment:

```sh
mkdir -p ~/ai/tools && git clone --depth 1 https://github.com/jundot/omlx.git ~/ai/tools/omlx && cd ~/ai/tools/omlx
uv venv ~/ai/envs/omlx --python 3.12
uv pip install --python ~/ai/envs/omlx/bin/python -e .
uv pip install --python ~/ai/envs/omlx/bin/python 'setuptools>=61.0' 'cmake>=3.27' 'nanobind==3.1.0'
PATH=$HOME/ai/envs/omlx/bin:$PATH OMLX_WITH_CUSTOM_KERNEL=1 python setup.py build_ext --inplace --force
```

Each model gets its own folder, because the chat names the first model the server lists:

```sh
HF=~/ai/envs/meeting-worker/bin/hf
mkdir -p ~/ai/models/llm27 ~/ai/models/inkling2
$HF download mlx-community/Qwen3.8-27B-4bit --local-dir ~/ai/models/llm27/Qwen3.8-27B-4bit
$HF download mlx-community/Inkling-2-Mini-oQ4e-mtp --local-dir ~/ai/models/inkling2/Inkling-2-Mini-oQ4e-mtp
```

Use the `oQ` build of Inkling: the plain `Inkling-2-Mini-4bit` checkpoint fails to load in oMLX. Inkling always thinks before it answers; the dashboard offers its lower effort levels to keep that short. oMLX renames its process to `omlx-server`; stop a hand-started one with `kill <pid>` or `omlx stop`, not `pkill -f "omlx serve"`.

### Qwen3.8 Flash-Next (Strata)

[Strata](https://github.com/Niko1221/Strata) (MIT) runs Flash-Next, a 125B mixture of experts with 6B active, on its own Metal engine. Gyro-S, Gyro-M and Gyro-L are trellis-coded quants; the `TQ1_0`-style names are Hub size classes, not bit widths.

```sh
git clone https://github.com/Niko1221/Strata ~/ai/tools/Strata && cd ~/ai/tools/Strata
./setup.sh --family gyro --model Gyro-S --models-dir ~/ai/models/strata --data-dir ~/ai/models/strata \
  --context 32768 --port 8090 --no-start --no-browser --vision no --yes
```

This builds the engine (about 10 minutes) and downloads the 58.5 GB Gyro-S file and its drafters. Run it again with `--model Gyro-M` (92 GB) for the middle quant; stop any running Strata server first. The template's `flash_next` entry has a preset for each quant (`fast` = Gyro-S, `quality` = Gyro-M, the default, `large` = Gyro-L) and its `strata_mac` engine reads the run config Strata wrote, replacing only the port and log path.

Gyro-L is not offered by Strata's Mac setup; it was installed by hand, and the recipe is in the Flash-Next section of [docs/development.md](development.md). Gyro-M is the practical choice: its results matched Gyro-L in our small tests. It runs best with `STRATA_METAL_ARENA_GB=26`, which the template sets.

### Tencent Hy4-Flash (Strata)

Hy4-Flash (220B mixture of experts, 12B active) runs on Strata's `strata-hy4` engine in the `SQ-64` build: a 62 GB model file plus a 67.6 GB lookup table that stays on the SSD, about 122 GiB in all. It reads experts from the SSD into a cache, so it is much slower (14-18 tok/s) than Flash-Next; try it only if you have the disk. Install it into its own checkout so the Flash-Next install is untouched; the exact environment variables are in the template's `hy4_flash` entry (`STRATA_METAL_EXP_CACHE_GB` sets the cache). Thinking is off with `reasoning_effort: "none"`; the model's own levels are `high` (default) and `max`.

## 5. Web search for the chat

Without a search address the chat is not offered the `web_search` tool. Run SearXNG on this Mac, bound to loopback:

```sh
mkdir -p ~/searxng/config && cd ~/searxng
cat > docker-compose.yml <<'YAML'
services:
  searxng:
    image: searxng/searxng:latest   # pin a dated tag once it works
    restart: unless-stopped
    ports: ["127.0.0.1:8888:8080"]
    volumes: ["./config:/etc/searxng"]
    environment:
      SEARXNG_BASE_URL: http://127.0.0.1:8888/
YAML
docker compose up -d && docker compose down   # writes config/settings.yml
```

In `config/settings.yml` set `server.secret_key` to a long random string, set `server.limiter: false`, and add `json` to `search.formats` (`[html, json]`), which the app needs. Then `docker compose up -d`, and check `curl "http://127.0.0.1:8888/search?q=test&format=json"`. Under the gear menu open **Host settings**, enter `http://127.0.0.1:8888` under Web search, press **Test**, then **Save**. The chat uses it from its next answer. Search queries stay on this Mac.

## Memory on a Mac

- **What "available" means.** The app reads the kernel's page counters. *Used* is application memory plus wired plus compressed memory, which is Activity Monitor's Memory Used. Files held in memory, including a running model's memory-mapped weights, count as available cache. This is stricter than psutil's figure, which counts inactive application memory that macOS can free only by compressing or swapping, and which made the Mac look roomier than the engines found it.
- **Headroom.** A start needs its estimate plus 4 GiB free. If it is refused, the message names what is in the way; the app never stops anything for you.
- **The container VM keeps its memory.** Docker Desktop and Podman run containers inside a virtual machine, and macOS does not get memory back from the VM after the containers that used it stop. It can hold far more than the containers need. Give the VM only what the database and SearXNG need (Podman: `podman machine stop`, `podman machine set --memory <MiB>`, `podman machine start`; Docker Desktop: Settings, Resources). If memory is tight, restart the VM when no job is running, since the database lives in it, and compare Activity Monitor before and after.
- **Quit what you do not need** before starting a large model: browsers and chat apps hold gigabytes each.

## Day to day

1. Start the container engine and `docker compose up -d --wait db`.
2. Start the API, then the frontend (section 2).
3. Start a model from the Models page. Wait for **On**.
4. Use it from the sidebar. Stop it when you are done: a large model holds most of the Mac's memory.
5. After editing `runtimes.json`, restart the API. After editing worker code, unload and restart that worker.

To stop: Ctrl+C in both terminals, then `docker compose down` (keeps the database volume; do not add `-v` unless you mean to erase it).

## Troubleshooting

| You see | Cause and fix |
| --- | --- |
| Start refused with `HOST_ROLE_UNSUPPORTED` | `GS_HOST_ROLE=desktop` is missing from `.env`. Add it and restart the API. |
| Start refused, "needs N GiB, M GiB free" | Not enough free memory after headroom. Quit apps, stop another model, or restart the container VM. A smaller preset (Gyro-S) or model needs less. |
| A model you removed or added does not show | The API reads `runtimes.json` at start. Restart it. |
| Chat says it cannot search the web | No search address is saved. See section 5. |
| Inkling fails to load in oMLX | You downloaded the plain 4-bit checkpoint. Use the `oQ` build. |
| Every speaker is "Speaker N" on a video | The OCR packages are missing from the meeting-worker environment, or the video is not a Zoom recording. The job still succeeds. |
| Many speakers for one person | Lower `diar_threshold` splits more; raise it (0.9 is the template value) and restart the API. |
| A fix to worker code has no effect | The worker is still running the old code. Unload Meeting notes and start it again. |
| `ffmpeg: command not found` in a job | Install ffmpeg and start the API from a shell where `ffmpeg` is on the `PATH`. |

## Tests

```sh
uv run --locked --project backend pytest backend/tests -m "not database"
uv run --locked --project backend ruff check backend
cd frontend && npm ci && npx playwright install chromium   # the browser, once
npx tsc -b && npx playwright test
```

The frontend tests use recorded fixtures, so they need no models and no running API.
