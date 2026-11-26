# Generation Station

Generation Station is a browser dashboard for running AI models on your own machine. You start and stop models from a web page, it refuses to start one that will not fit in memory, and you use the models from the same page: chat with a text model, make pictures, songs, speech and video, and turn meeting recordings into transcripts and notes. Everything runs locally. Nothing is sent to a cloud service unless you point it at one.

It runs on two kinds of host:

| Host | Models it runs | Guide |
| --- | --- | --- |
| Windows 11 desktop with an NVIDIA card | Pictures, songs, speech, video, text models, meeting notes | [docs/development.md](docs/development.md) |
| Apple-silicon Mac (developed on an M5 Max, 64 GB) | Text models and meeting notes | [docs/setup-macos.md](docs/setup-macos.md) |

You can browse the dashboard from any other machine on your network or tailnet; only the host needs the models.

## What it does

- **Models page.** Every model in your `runtimes.json` appears as a card with its presets, memory estimate and a Start or Stop button. A start is checked against live RAM and GPU memory on the host, and it is refused when the model would not fit. The check is made by the API, not the browser, and a stale or missing measurement never allows a start.
- **Chat.** Talk to a running text model. It can start songs, pictures and the other generators for you, search the web (through a SearXNG instance you run) and read pages.
- **Generators.** Songs (YuE2), pictures (Qwen Image), video and picture editing (MiniMax H3), and speech (OmniVoice, Qwen3-TTS). Each has a form built from the model's plugin, a queue, and a results list with the settings each result was made with.
- **Meeting notes.** Add a meeting recording (audio or video; a Zoom MP4 is the tested case) or a transcript file. You get a transcript with who said what, optional correction of misheard words, and a summary with action items and decisions. For Zoom video, speaker names are read from the on-screen name tags. Transcripts can be edited afterwards.
- **Logs and host settings** behind the gear menu.

Which of these a host offers depends on its `runtimes.json` and on the models installed there. No model weights are included in this repository.

## How it fits together

```
 browser (any machine) ──HTTP, bearer token──▶  API (FastAPI)  ──▶  PostgreSQL (container)
                                                   │
                                                   ├─▶ model servers and workers (one process per model)
                                                   └─▶ host telemetry (RAM, GPU, per-model memory)
```

- The API and the database live on the host, so memory readings describe the real machine. The API runs natively, not in a container.
- A model is a **plugin** (`backend/generationstation/plugins/`) plus an entry in `runtimes.json`. Media models run in small workers (`workers/`) in the model's own Python environment, so model dependencies never mix with the app's. See [docs/plugins.md](docs/plugins.md).
- `runtimes.json` is yours: model paths, presets and memory estimates for your machine. It is not committed. Start from `runtimes.example.json` (Windows desktop) or `runtimes.mac.example.json` (Mac).
- Every `/api` request needs the bearer token that `scripts/init_env.py` writes into your private `.env`.

## Quick start (Windows, PowerShell)

Requirements: Docker Desktop with Compose, [uv](https://docs.astral.sh/uv/getting-started/installation/) (`winget install --id=astral-sh.uv -e`), [Node.js 24 LTS](https://nodejs.org/en/about/previous-releases) with npm, and PowerShell. From the repository root:

```powershell
uv python install 3.12
uv sync --locked --project backend --python 3.12
uv run --project backend python scripts/init_env.py
docker compose up -d --wait db
uv run --locked --project backend alembic -c backend/alembic.ini upgrade head
```

Start the API in one terminal and the frontend in another:

```powershell
uv run --locked --project backend uvicorn generationstation.app:create_app --factory --host 0.0.0.0 --port 8000
```

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open the URL Vite prints (normally `http://localhost:5173`). The API's health check is `http://127.0.0.1:8000/health`. The dashboard asks for the host address and the token from `.env` the first time you connect. Never put the token in a URL, commit `.env`, or share it in logs or screenshots.

This starts the dashboard with no models. To add real models, copy `runtimes.example.json` to `runtimes.json`, fix the paths, and follow the model sections of [docs/development.md](docs/development.md). On a Mac, follow [docs/setup-macos.md](docs/setup-macos.md) instead of the commands above.

To stop: Ctrl+C in both terminals, then `docker compose down`. This keeps the database volume. Do not add `-v` unless you mean to erase the database.

## Repository layout

| Path | What is in it |
| --- | --- |
| `backend/` | FastAPI app, plugins, admission and telemetry, Alembic migrations, tests |
| `frontend/` | React, TypeScript and Vite dashboard, Playwright tests |
| `workers/` | One worker per media model, and the meeting-notes pipeline |
| `scripts/` | `init_env.py`, which creates the private `.env` |
| `compose.yaml` | PostgreSQL for the app, bound to loopback |
| `runtimes.example.json`, `runtimes.mac.example.json` | Templates for your machine's `runtimes.json` |
| `docs/` | Decisions, plan, setup guides and plugin notes (below) |

## Documentation

| Document | Read it for |
| --- | --- |
| [docs/setup-macos.md](docs/setup-macos.md) | Setting up and running on an Apple-silicon Mac |
| [docs/development.md](docs/development.md) | Windows setup, each model's install, migrations, tests, backups, Tailscale access |
| [docs/plugins.md](docs/plugins.md) | Adding a model: the plugin and worker contracts |
| [docs/context.md](docs/context.md) | Decisions and measured results, newest facts first in each section |
| [docs/plan.md](docs/plan.md) | Architecture and milestones |
| [docs/ui-redesign.md](docs/ui-redesign.md) | The dashboard's design decisions |
| [AGENTS.md](AGENTS.md) | How AI coding assistants should work in this repository |

## Tests

```sh
uv run --locked --project backend pytest backend/tests -m "not database"
uv run --locked --project backend ruff check backend
cd frontend && npm ci && npx playwright install chromium   # the browser, once
npx tsc -b && npx playwright test
```

The `database` tests need a disposable PostgreSQL database; see [docs/development.md](docs/development.md).

## Keeping the repository clean

Model weights, generated outputs, credentials, `.env`, `runtimes.json` and runtime caches stay out of Git (see `.gitignore`). Do not paste real names, recordings or transcripts from your own meetings into tests or docs; use invented ones.
