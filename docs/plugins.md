# Model plugins

A plugin teaches Generation Station how to run one kind of local model server. Plugins live in this repository under `backend/generationstation/plugins/` and are registered explicitly; nothing is loaded from outside the repository at runtime.

## What the core does and what a plugin does

The core owns everything that must behave the same for every model: starting the process, writing the plugin's files into a per-start folder, capturing its output, stopping only the process tree it started (checking the process start time so a reused PID is never touched), re-attaching to a ready server after an API restart, detecting a crash, capacity admission against live telemetry, idempotent operations, and the database records.

A plugin supplies only what is specific to its model server:

| Piece | Purpose |
| --- | --- |
| `kind`, `title` | The `kind` value used in `runtimes.json`, and the display name |
| `description` | One or two plain sentences on what the server does, shown on its card. A `runtimes.json` entry may override it with its own `description`, and each preset may add a `description` of its model. |
| `runtime_model` | A Pydantic model for its `runtimes.json` entry (subclass `BaseRuntime`; presets subclass `BasePreset`). Paths and flags that only the owner of the machine may set go here. |
| `settings` | The settings a user may change, each a `SettingSpec` with a label, bounds or options, unit, help text, and `target` (the server's own name for it). A preset lists which of these it exposes and their defaults. |
| `choice_options()` | Optional: options for a choice setting that depend on the preset (Basalt's `kv`). |
| `estimate()` | RAM and per-GPU free VRAM, in GiB, needed before a start. The default reads the preset's `estimate`; override it when a setting changes the need (Basalt adds `resident_budget_gib`). |
| `launch()` | Returns a `LaunchSpec`: the command line, environment, working folder, and any files (written into the start's own folder before the process starts). |
| `probe()` | Asks the running server whether its model is `loaded`, `loading`, or `failed`; `None` means it is not answering yet. |

The browser can only choose a preset, choose GPUs from the preset's `allowed_gpus`, and change the preset's exposed settings within the plugin's bounds. Every value is validated again on the server. A plugin must never turn a browser value into a path or an unvalidated command-line argument.

GPU indices are NVML/`nvidia-smi` order. Plugins that start CUDA programs should set `CUDA_DEVICE_ORDER=PCI_BUS_ID` so the indices match (Basalt does).

## Adding a plugin

1. Create `backend/generationstation/plugins/<name>.py` with a `RuntimePlugin` subclass. Narrow `kind` with `Literal["<name>"]` in its runtime model.
2. Add an instance to the tuple in `plugins/__init__.py`.
3. Add an entry to `runtimes.example.json` and your local `runtimes.json`, with conservative estimates.
4. Add tests. The parametrized contract test in `backend/tests/test_runtimes.py` checks every registered plugin automatically; add plugin-specific tests for its config and launch output, and a stand-in server (like `tests/fake_basalt.py`) to exercise readiness without loading a model.
5. Load it for real on the desktop once, record the measured RAM and VRAM in `docs/context.md`, and update the estimates.

`basalt.py` is the reference plugin.

## Generation plugins (workers)

Media models (YuE2 music, Qwen Image pictures, MiniMax H3 video, OmniVoice and Qwen3-TTS speech) have no server of their own. Each gets a small worker in `workers/`, run with the python of the model's **own environment** (`python` in `runtimes.json`), so model dependencies never mix with Generation Station's or with each other's.

`workers/gs_worker.py` is the shared, standard-library-only worker server. A worker module only supplies `load(config)` and `generate(model, inputs, job)`; see `workers/yue2_worker.py`. The protocol, on 127.0.0.1 only:

| Request | Response |
| --- | --- |
| `GET /health` | `{"status": "loading" \| "loaded" \| "failed", "error"}` |
| `POST /generate` with `{"job_id", "inputs"}` | 202 `{"job_id", "status": "queued", ...}` |
| `GET /jobs/{job_id}` | `{"status": "queued" \| "running" \| "done" \| "failed" \| "cancelled", "progress", "outputs": [{"name", "mime", "bytes"}], "error", "details"}` |
| `POST /jobs/{job_id}/cancel` | the job: a queued one is cancelled at once; a running one shows progress "Cancelling" and stops at its next `job.report` |

Jobs run one at a time. Files go to `<output_dir>/<job_id>/`; `job.output(name, mime)` returns the path and records the file. `job.report(text)` sets the short progress line shown in the browser. `job.detail(seed=..., steps=..., prompt=...)` records what the worker actually used (the seed it picked, the full prompt it sent to the model, size, steps); the worker server adds `seconds`, the time the job took, and writes the inputs and details to `<job_id>/job.json` next to the files. `job.thumbnail(pil_image)` saves a small `thumbnail.jpg` preview shown in the results list. A cancelled job stops at its next `job.report(...)` (raising inside `generate`), so report each step; its partial files are removed. Free GPU memory in a `finally` so a cancel leaves the card clean.

A generation plugin subclasses `WorkerPlugin` (`plugins/worker.py`) and sets:

- `worker_script`: the module in `workers/`.
- `inputs`: the generation form, as `InputSpec`s (text, textarea, int, choice, seed; required, bounds, max length, placeholder, help, and `advanced` to tuck a field under "More options"). The core validates every request against it and refuses unknown fields; the browser builds the form from it, so a new model needs no frontend code.
- `modes` (instead of `inputs`, when a model has several ways of making something): `ModeSpec`s with a label, a one-line help and their own `inputs`. The browser shows one tab per mode; the request carries `"mode"` and only that mode's fields are accepted. `check_inputs(mode, values, files)` adds rules across fields (MiniMax H3's pictures mode needs a first frame, a last frame or both). A mode that makes a different kind of result than the plugin's `output_kind` sets its own `output_kind` (MiniMax H3's picture and edit tabs make images); the page labels that tab's button and its results by it.
- File fields: an `InputSpec` of kind `files` with `accept` (`image`, `video`, `audio`) and `max_count`. The browser shows a picker with previews and drag-and-drop and uploads each file at once (`POST /api/uploads?name=...`, the raw file as the body; the type is checked by content, at most 25 MB for a picture, 300 MB for a video, 60 MB for audio; unused uploads go after a day). The request lists upload IDs; when the job is created the files are copied into `<output_dir>/<job_id>/inputs/`, the stored inputs name those copies (`GET /api/jobs/{id}/inputs/{name}` serves them), and the worker receives `[{"name", "kind", "mime", "original", "path"}]`.
- `output_kind`: `audio`, `image` or `video`, which chooses the button ("Make a song") and the player. `make_label` and `result_noun` override the button and the word for one result when the kind's own do not fit (OmniVoice: "Make speech", "recording").
- `max_gpus`: 1 for single-card models; the UI then offers a single choice.
- `timings`: measured times as `TimingSpec`s (`seconds`, optional `first_seconds` for the first result after a start, and the `when` form choices, `preset` and `gpu` they apply to). The form shows the first one that matches the current choices and the card the model runs on. Record only measured times.
- `chats`: true for a server with an OpenAI-style `/v1/chat/completions` (the `llm` plugin). The dashboard then offers it on the Chat page, where it can call every running generator's tabs as tools (`backend/generationstation/chat.py`); a generator needs nothing extra for that, but clear `help` text on its fields is what the chat model reads.
- `advanced` on a `SettingSpec`: shown under "Advanced settings" on the Models card; the others are shown with the card choice. A plugin that marks none keeps all its settings folded, as before.
- `gpu_limit(preset)`, `check_gpus(preset, gpus)` and `chat_sampling(preset, gpus)`: per-preset card rules and chat sampling. The `llm` plugin uses them so that one model entry can run on different engines depending on the card chosen.

The worker sees only the chosen card(s) (`CUDA_VISIBLE_DEVICES`, in `nvidia-smi` order), so it always uses `cuda:0`. Preset `options` (model folders, and so on) are owner-set and passed through to `load()`; start settings come from the plugin's `settings`.

The core API: `POST /api/models/{id}/jobs` with `{"inputs": {...}}` (the model must be ready), `GET /api/jobs`, `GET /api/jobs/{id}` (refreshed from the worker while it runs), `GET /api/jobs/{id}/files/{name}` (only files the job reported, inside the output folder), `POST /api/jobs/{id}/cancel` (queued or running jobs), and `DELETE /api/jobs/{id}` (a finished job: its record and its folder; refused with `JOB_RUNNING` while it is being made). Jobs are stored in PostgreSQL with the inputs, the worker's `details`, and `launch`, the model settings (preset, cards, start settings) it ran with; finished files stay available after the model stops. A job still running when its model stops is marked failed.

The generation page lists every result of the model in a sidebar with its thumbnail; jobs wait in the worker's queue, and the sidebar shows which one is being made (with its step) and each queued one's place in line, each with a cancel button. Choosing a result opens a modal that shows the file, everything that was typed, what the model actually used, the time it took and the model settings, with "Use these settings" (refills the form), download and delete.

`tests/stub_worker.py` is a stand-in worker (writes a one-second tone) used to test the whole path without a model.
