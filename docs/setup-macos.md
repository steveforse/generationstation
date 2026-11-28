# Setting up Generation Station on an Apple-silicon Mac

This guide takes a Mac from a fresh checkout to a dashboard that runs local text models and turns meeting recordings into transcripts and notes. It was written from a working setup on an M5 Max with 64 GB of memory (macOS 26). Where a figure depends on that machine, the text says so.

## What runs on a Mac

| Works | Does not (needs an NVIDIA card) |
| --- | --- |
| Dashboard, API, database, chat, logs | HunyuanVideo 1.5 |
| Video: Wan 2.2 TI2V 5B through mlx-video, 832x480 clips of up to 1.4 s; FastMetal-QAD (distilled Wan, up to 5 s at 1280x704 or 832x480); LongCat-Video (832x480, up to 4 s, slow); LTX-2.5 with sound, up to 5 s at 1280x704 (personal use) | |
| Video: MiniMax H3 through h3.c, with sound, from a description or first and last pictures (personal use only) | H3's reference modes and picture editing |
| Images: Qwen Image 2.1 Turbo, Z-Image Turbo and Qwen-Image 2512 through mflux (MLX) | |
| Songs: YuE2 through the MLX port (mlx-Yue), ACE-Step 1.5 (MIT, work use) and MiniMax Music 3 (community licence, work use while the app stays internal) | |
| Decide: Torchcast 4B and 31B (text), pplx-decider 27B and H2O-Lightning 4B (read pictures), all Apache-2.0 and work use; one probability per answer in well under a second | |
| Speech through mlx-audio: Qwen3-TTS, OmniVoice, Fish Drama 3, Fish S2 Pro, Breeze TTS 2 | |
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
| `qwen_image`, Qwen Image 2.1 Turbo (8-bit, through mflux) | 10 GiB, held only while a picture is made | 18 GB | 17-23 s for a 1024x1024 picture |
| `yue2`, YuE2 3B (8-bit language model, through mlx-Yue) | 14 GiB | about 10 GB | 0.5-1.1 times the song's length |
| `minimax_music`, MiniMax Music 3 (8-bit, mlx-audio) | 20 GiB | 13 GB | 30 s of music in about 65 s |
| `ace_step`, ACE-Step 1.5 turbo (MLX) | 22 GiB (14 GiB resident, 21 GiB peak at two minutes) | 10 GB | 30 s of music in 12 s, 2 min in 38 s |
| `qwen_image` preset `qwen21`, the full Qwen Image 2.1 (8-bit) | 18 GiB, while a picture is made | 17 GB | about 100 s for 1024x1024 |
| `z_image`, Z-Image Turbo (8-bit) | 9 GiB, while a picture is made | 10 GB | 16-22 s for 1024x1024 |
| `qwen_image_2512`, Qwen-Image 2512 (8-bit) | 38 GiB, while a picture is made | 34 GB | about 3 min for 768x1152 |
| `h3_video`, MiniMax H3 (BF16 streamed from the SSD) | 14 GiB, while a clip is made | 134 GB | 5 s at 480p: about 3 min as a draft, 16 min at standard |
| `fastmetal_video`, FastMetal-QAD 5B / 14B (INT8) | 26 GiB / 30 GiB (a new description briefly needs 24 GiB for the text encoder) | 18 GB / 39 GB | 5B: 3 s clip in about 64 s (35 s faster mode); 14B: 3 s clip in about 2.5 min (67 s faster mode) |
| `longcat_video`, LongCat-Video 13.6B (8-bit) | 40 GiB (19 to 37 GiB while a clip is made) | 31 GB | 0.6 s clip in about 43 s, 1.1 s in 80 s; 2.2 s and 4 s take about 3 and 6 minutes |
| `ltx_video`, LTX-2.5 distilled (4-bit) | 22 GiB (14 GiB at the peak up to 1280x704) | 26 GB | 4 s clip: about 32 s quick, 150 s sharp |
| `wan_video`, Wan 2.2 TI2V 5B (8-bit) | 30 GiB, while a clip is made | 18 GB | about 70-100 s for a 1.4 s clip |
| `qwen3_tts` (8-bit, three 1.7B models, one at a time) | 8 GiB | 9 GB | a few seconds per sentence |
| `omnivoice` (bf16) | 6 GiB | 1.5 GB | a few seconds per sentence |
| `fish_drama3`, Drama 3 (3-bit) | 26 GiB | 18 GB | about real time |
| `fish_s2`, S2 Pro (8-bit) | 14 GiB | 6 GB | about 0.6 times real time |
| `breeze_tts`, Breeze TTS 2 (8-bit) | 9 GiB | 4 GB | a few seconds per sentence |

The target is a 64 GB Mac, which runs one large text model beside the meeting worker. Smaller Macs have not been tried: compare the memory column with what your Mac has free (plus the headroom described below), and expect only the smaller models to fit. You do not need every model: install the ones you want and delete the others from your `runtimes.json`.

A start is refused unless its estimate fits in the memory the Mac has available, less 4 GiB of headroom and what other running models already reserve (see [Memory on a Mac](#memory-on-a-mac)).

## Personal and work models

The Mac template marks each model with a licence verdict. In short: Qwen3.8 27B, Flash-Next, Hy4-Flash, Inkling 2 Mini, Qwen-Image 2512, Z-Image Turbo, Qwen3-TTS, Wan 2.2, FastMetal, LongCat-Video, ACE-Step, MiniMax Music 3 and meeting notes are work use; Qwen Image 2.1, LTX-2.5, YuE2, OmniVoice, Drama 3, S2 Pro, Breeze TTS 2 and MiniMax H3 are personal use only. If colleagues will use the app, delete the personal entries from their `runtimes.json` (or hide them behind a separate host) and see the filter on the Models page. The details of each model give the clause behind its verdict.

## Models page: sections and quality chart

The Models page is grouped like the sidebar (Text, Speech, Images, Video, Music). Above each group's cards, a folded chart ranks the models that have a published score on the same measure:

Each section has a Sort control: default order, name, or quality (using the ranking chosen in the chart), with a button to reverse it. Models without a score on that ranking stay last in either direction.

Claude Haiku, Sonnet and Opus 5.5 appear on the text rankings as outlined "reference" bars (the `references` list in the catalog): hosted models that are not run here, shown for scale. A group can offer several rankings (a model carries extra scores in `rankings`); buttons above the chart switch between them, and models missing from the chosen ranking are named under it.

| Group | Measure | Source |
| --- | --- | --- |
| Text | Intelligence Index v5 | Artificial Analysis (independent; no score for Hy4-Flash) |
| Text | LLM Stats score | llm-stats.com, an aggregate of mostly vendor-reported benchmarks (all four models) |
| Text | DeepSWE v1.1 | Vendor-reported agentic coding scores (all four; harnesses differ, Hy4-Flash's is second-hand) |
| Text | Arena text Elo | LMArena human votes, read through its Hugging Face dataset because arena.ai blocks scripts (Qwen3.8 27B and Inkling 2 Mini only) |
| Text | GPQA Diamond | The vendors' model cards (Qwen3.8 27B, Flash-Next, Inkling); Hy4-Flash only has an indicative OpenRouter figure. Claude references are OpenRouter measurements, which score lower than card figures |
| Text | Terminal-Bench 4.0 | Vals AI, mini-swe-agent (independent; Qwen3.8 27B and Flash-Next are not on it) |
| Text | Terminal-Bench 2.1 | Mixed sources, each stated per bar (Qwen and Thinking Machines cards, Artificial Analysis through BenchLM, Vals for Claude); sources disagree by 20 points or more for the same model |
| Text | LiveBench coding | LiveBench 2.0 release 2026-11-06, independent (Qwen3.8 27B and Inkling 2 Mini only) |
| Speech | Speech arena Elo | Artificial Analysis |
| Music | SongBench average (WildSongBench) | The YuE2 authors' model card, so vendor-run and scored by automatic metrics |
| Images | Image arena Elo | Artificial Analysis |
| Video | Text-to-video arena Elo | Arena AI (read through the benchmarklist.com mirror) |

These are scores for the hosted, full-precision models, not for the quantised builds that run here, so they are a proxy. A hatched bar with "est." is an estimate: the score was not published for that exact build (every text quant, Qwen3-TTS, Qwen-Image 2512 and Wan 2.2 5B). Hover or focus a bar to see how it was derived, or open the Table under the chart for the sources. Hy4-Flash and OmniVoice have no score anywhere yet and are listed as such. Only a Mac template carries scores for now; the Windows template does not.

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
- Licences, checked 2026-11-26: Qwen3-ASR Apache-2.0; pyannote segmentation 3.0 MIT; NVIDIA TitaNet-S Apache-2.0 (covered by the NeMo toolkit licence, per its NGC card); sherpa-onnx and RapidOCR (with its PaddleOCR models) Apache-2.0; mlx-audio and mlx-lm MIT; ffmpeg is run as a separate program. All permissive, so the meeting-notes pipeline is work use. The notes come from the text model you pick, which has its own licence (see the Models page). On Windows, the DiariZen speaker model (CC BY-NC 4.0) makes that engine personal use only; the Nemotron engine (OpenMDW-1.1) is not.
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

## 5. Images and songs

Both run as workers in their own environments, outside the repository, and are started from the Models page like any other model.

All picture models share one **Images** page (in the sidebar, with Chat, Decide, Meeting notes and Speech). A dropdown lists the running picture models with their licence; the description, shape and seed carry over when you switch, and anything the new model has no place for (the Avoid list on Z-Image Turbo, which is distilled and has no negative prompt) is named on the page and kept for the way back. The mflux models make one quality per preset, so the form has no Quality field; the Windows model keeps it. The mflux models also take a **custom size** (width and height, 256 to 2048, rounded to 16) and an optional **Steps** under More options. Z-Image Turbo alone also takes **Start from a picture** (one picture the new one begins from, with a percentage: 10 to 20 changes the style, such as an ink drawing, while keeping the layout; 40 and up stays close to the original; or the shape "Match the starting picture"). It does not follow instructions such as "make the coat blue" (that needs an edit model such as qwen-image-edit-2511, which is not installed). The Qwen models have no such field: given a picture, they repaint it and ignore the prompt at every strength tried (an ink-drawing prompt, and even a different subject, came back as the same photo of the fox), although the same prompt from nothing gives a good ink drawing. mflux begins from the picture at step `int(steps x strength)`, the same rule for both models, so this is the models' behaviour, not a setting. The preset option `"start_picture": true` in `runtimes.json` turns the field on for a model. The Windows model has only the four shapes. In the chat, every running picture model is reached through one `make_image` tool (description, shape, size, quality, things to avoid, seed, earlier results to start from, which model). A video model with picture tabs (H3 on Windows) shows those tabs on Images and keeps its clip tabs on its own page.

### Qwen Image 2.1 Turbo (mflux)

[mflux](https://github.com/filipstrand/mflux) runs Qwen Image on MLX. The worker loads the model once, when it starts, and keeps it loaded (all three picture models work this way): a picture costs only its painting time, about half of what starting a fresh mflux process per picture took (Z-Image Turbo at 1344x768: 14 s against 28 s). To keep the memory down it gives back the text encoder (the largest part after the transformer) once each description has been encoded, replacing it with a fresh one whose weights are read from disk for the next picture, and it decodes pictures in tiles. Measured on the M5 Max (held while idle / peak during a 1344x768 picture): Z-Image Turbo 1.5 / 7.1 GiB, Qwen Image 2.1 Turbo 9 / 12.6 GiB, Qwen Image 2.1 full 9 / 15.6 GiB, Qwen-Image 2512 22.5 / 35.3 GiB, against 7.5, 8.5, 15.8 and 37 GiB peaks (nothing held) when each picture was its own `--low-ram` process. Keeping everything loaded and skipping this (the first version) peaked at 11.5, 28.5, 29 and 48 GiB. The catalog's estimates are the peaks plus a margin (9, 14, 18 and 38 GiB). Turbo has one quality and no negative prompt, so those form fields have no effect.

```sh
uv venv ~/ai/envs/mflux --python 3.12
uv pip install --python ~/ai/envs/mflux/bin/python mflux pillow
~/ai/envs/meeting-worker/bin/hf download mflux-community/qwen-image-2-1-turbo-mflux-q8 \
  --local-dir ~/ai/models/qwen-image-mac/qwen-image-2-1-turbo-mflux-q8
```

The weights are Qwen's research licence, which is not a general commercial licence; read it before using pictures for anything but your own work. The template's `qwen_image` entry points at these folders and sets `worker_script` to `qwen_image_mflux_worker.py`.

### The Music page

All song models share one **Music** page (in the sidebar, with Chat, Decide, Images, Meeting notes and Speech). A dropdown lists the running song models with their licence; the style, lyrics, language, tempo, seed and a song to start from carry over when you switch, and anything the new model has no place for is named on the page and kept for the way back. Chips above the lyrics insert the part tags ([Verse], [Chorus], ...) where the cursor is. Leaving the lyrics empty asks for an instrumental on all three models, but they differ: ACE-Step and MiniMax are built for it, while YuE2 is a singing model and is given instrumental sections instead (`[Intro: Instrumental]`, `[Instrumental Break]`, `[Outro: Instrumental]`). That is not reliable: in four tests, with blank lyrics, with the placeholders and with "no vocals, no singing" in the style, a transcription still heard sung words in the first minute. The reliable YuE2 route is an instrumental version of a song you give it (below).

What each model has:

- **YuE2**: style, lyrics, melody planning, seed and a song to start from. The song is as long as its lyrics, so there is no length. Starting from a song makes a new version: SheetSage2 and MERT2 read its melody and structure, and YuE2 sings it again with your style and lyrics (the sound of the original is not kept). It needs the melody-reading extras: `uv pip install --python ~/ai/tools/mlx-Yue/.venv/bin/python mido==1.3.3 mir-eval==0.8.2 pretty-midi==0.2.11.post0 "scipy>=1.13,<2"` and two downloads (CC BY-NC 4.0, like YuE2): `~/ai/envs/meeting-worker/bin/hf download m-a-p/SheetSage2 --revision eab522a8168e8b8b8c4856bf8609cd86198f01fe --include config.json model.safetensors` and the same for `m-a-p/MERT-v2-FullSong --revision d8ba1c745e733b3908ce6ad16ebeb17ac7600a42` (2.8 GB together). A 30 s source became a 95 s new version in 53 s, with the key, tempo and words right. The melody planning cannot be off. The Windows worker has no melody reader. **With the lyrics left empty the new version is an instrumental**: the sung melody is moved to the instrument voice and the style gets "Instrumental, ..., no vocals, no singing". That needs helpers mlx-Yue's `cover --instrumental` calls but the upstream repository does not ship (`lyra.music_tools.instrumentalize`, `instrumental` and `compile_score`). They exist in the fork `fitchmultz/mlx-Yue`, commit `6b998ce` (Apache-2.0, adapted from the official YuE repository's MIT-licensed instrumental skill): copy those three files from that commit into `~/ai/tools/mlx-Yue/src/lyra/music_tools/`, and in `src/lyra/commands.py` add `"instrumental"` to the keys `cover` leaves out when it validates the request (`if k not in {"abc_sampling", "semantic_sampling", "instrumental"}`). Reviewed before use: the only thing they run is ffmpeg. Without them an instrumental version stops with a message saying so. Results: a 30 s song became a 34 s instrumental in 18 s with a transcription hearing only "Oh, oh, oh"; a 95 s sung song became a 100 s one in 60 s, but there the transcription still heard sung syllables, so it is much closer to an instrumental than YuE2's other attempts and still not a guarantee.
- **ACE-Step**: three tabs. *New song* has a length (30, 60 or 120 s), a tempo in BPM (the planning model picks one if it is left empty) and, under More options, the key, time signature and language. *New version of a song* (cover) takes a song, a style, optional new lyrics and how closely it follows the original (percent; 20 to 30 changes the sound a lot, 80 keeps the harmony). *Redo a section* takes a song, a start and an end in seconds and what to put there; the rest of the song comes back unchanged (checked: the parts outside the section were identical to the original), and an end past the end of the song extends it (a 30 s song with the section 20 to 45 s became 45 s). The song to start from is an earlier result (its **Use as source song** button) or a file from your computer. Cover and repaint skip the planning model, so they finish in a few seconds. Measured: tempo followed (a requested 140 BPM measured 140.6; 90 and 170 measured at double and two thirds of that, the usual ambiguity of the estimate); the key is passed to the model but not verified by ear.
- **MiniMax Music 3**: a length (a maximum, 30 to 180 s), and under More options a step count (1 to 30, 30 if empty): 8 steps took 38 s for a 30 s song against 69 s for 30 steps, with the sung words equally clear.

In the chat, every running song model is reached through one `make_song` tool (style, lyrics, length, language, tempo, key, time signature, steps, seed, an earlier song to start from, which model).

### YuE2 songs (mlx-Yue)

[mlx-Yue](https://github.com/vanch007/mlx-Yue) is an MLX port of YuE2-3B. The worker keeps the 8-bit language model loaded, so a song starts at once, and runs one song at a time. A verse and a chorus (about 55 s of music) took about 30 s; a three-minute song took about as long as the song. The weights are CC BY-NC 4.0 (**non-commercial**).

```sh
git clone https://github.com/vanch007/mlx-Yue ~/ai/tools/mlx-Yue && cd ~/ai/tools/mlx-Yue
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -e . soundfile
.venv/bin/lyra prepare --output ~/ai/models/yue2-mlx/mlx-Yue2-3B --precision 8bit   # downloads the checkpoints and the decoder
```

`prepare` leaves the decoder in the Hugging Face cache; copy or point `vae_dir` at it. The port checks the model folder strictly and refuses stray files (a `.cache` folder, a `vae` folder, a `.gitattributes`), so keep only the files it wrote there. The worker sets `MLX_ENABLE_TF32=0`, as the port documents.

### Qwen Image 2.1 (full), Z-Image Turbo and Qwen-Image 2512

Qwen Image 2.1 Turbo and full are presets of the `qwen_image` entry; 2512 (`qwen_image_2512`) and Z-Image Turbo (`z_image`) are separate entries, since they are different models. All use the same worker, which passes the preset's `command`, `steps`, `guidance` and `base_model` to mflux.

```sh
HF=~/ai/envs/meeting-worker/bin/hf
$HF download mflux-community/qwen-image-2-1-mflux-q8 --local-dir ~/ai/models/qwen-image-mac/qwen-image-2-1-mflux-q8
$HF download mflux-community/z-image-turbo-mflux-q8 --local-dir ~/ai/models/qwen-image-mac/z-image-turbo-mflux-q8
$HF download mflux-community/qwen-image-2512-mflux-q8 --local-dir ~/ai/models/qwen-image-mac/qwen-image-2512-mflux-q8
```

Qwen Image 2.1 full is the quality option next to Turbo: about 130 s per picture at 30 steps. Z-Image Turbo (Tongyi-MAI, Apache-2.0) is the fast alternative: about 14 s. Qwen-Image 2512 (Apache-2.0) is a base model with a negative prompt and 20 guided steps. Even at 8 bits it holds about 22 GiB and peaks near 35 GiB, taking about 8 s per step (a 4-bit conversion peaked lower but was slower), so only start it with the other large models stopped.

### MiniMax Music 3 songs

MiniMax Music 3 (`mlx-community/MiniMax-Music3-mxfp8`, 13 GB) runs through mlx-audio's `mlx_audio.music`, in the `mlx-tts` environment. It makes songs with vocals from a style and lyrics, 30 s to 3 min. A 30 s song took 65 s through the app and the lyrics came back correctly; a 60 s instrumental works too. The model refuses an empty lyric, so the worker sends `[instrumental]` when the lyrics box is empty. The community licence asks for "MiniMax-Music3" to be shown on a commercial interface, written authorisation above US$20M yearly revenue from products built on it, safeguards when offered to third parties, and indemnification. The card says "work" because this app is an internal tool, which is the owner's reading rather than legal advice; revisit it if the app is ever offered outside the company.

```sh
~/ai/envs/meeting-worker/bin/hf download mlx-community/MiniMax-Music3-mxfp8 --local-dir ~/ai/models/music/MiniMax-Music3-mxfp8
```

Set `model_dir` to that folder in the `minimax_music` entry, which already points at the `mlx-tts` Python.

### ACE-Step 1.5 songs

[ACE-Step 1.5](https://github.com/ace-step/ACE-Step-1.5) (MIT code and weights) makes songs with vocals, in 50+ languages, or instrumentals, from a style and lyrics. A 1.7B language model plans the song and a turbo diffusion model makes the audio, natively on MLX: 30 s of music took 12 s, 60 s took 17 s and 120 s took 38 s on an M5 Max, at about 14 GiB resident and 21 GiB peak for two minutes. In our one test the lyrics came back word for word; the research run found only some lines recovered at 30 s with different lyrics, so listen before relying on it for lyric-critical songs (the 4B planner, `acestep-5Hz-lm-4B`, is an extra download and untested). Leave the lyrics empty for an instrumental. The Artificial Analysis music arena lists no model we can run, so the Music chart uses the SongBench average instead (below).

```sh
git clone https://github.com/ace-step/ACE-Step-1.5 ~/ai/tools/ACE-Step-1.5
uv venv ~/ai/envs/ace-step --python 3.12
uv pip install --python ~/ai/envs/ace-step/bin/python -e ~/ai/tools/ACE-Step-1.5 soundfile pillow
~/ai/envs/meeting-worker/bin/hf download ACE-Step/Ace-Step1.5 --local-dir ~/ai/tools/ACE-Step-1.5/checkpoints   # about 10 GB
```

Its training-data claim (licensed, royalty-free and synthetic data) is the vendor's own and unverified, so have the data reviewed before company use. HeartMuLa 3B (Apache-2.0) was also tested: its lyrics were better in a 30 s test, but it ran 3.3 times slower than real time through PyTorch and peaked at 24 GB, and its tokenizer file is Meta's Llama 3.2 one; it is not set up.

### Wan 2.2 video (mlx-video)

[mlx-video](https://github.com/Blaizzy/mlx-video) runs Wan 2.2 on MLX; the PyPI package of that name is a different project, so install from git. Wan 2.2 and its weights are Apache-2.0. Each clip is one process under a 26 GiB MLX memory limit and peaks near 29 GiB, so stop the large text models first. Clips are 832x480 (or 480x832, 640x640) and 17 or 33 frames at 24 fps: 81 frames peaked at 61 GiB and are not offered.

```sh
uv venv ~/ai/envs/mlx-video --python 3.12
uv pip install --python ~/ai/envs/mlx-video/bin/python "git+https://github.com/Blaizzy/mlx-video.git" soundfile pillow torch
~/ai/envs/meeting-worker/bin/hf download Wan-AI/Wan2.2-TI2V-5B --local-dir ~/ai/models/wan/wan22-ti2v-5b   # 32 GB
~/ai/envs/mlx-video/bin/python -m mlx_video.models.wan_2.convert --checkpoint-dir ~/ai/models/wan/wan22-ti2v-5b \
  --output-dir ~/ai/models/wan/wan22-ti2v-5b-mlx-q8 --quantize --bits 8   # peaks near 54 GB; run it with other models stopped
```

The worker needs `google/umt5-xxl`'s tokenizer in the Hugging Face cache (the first generation without `HF_HUB_OFFLINE` fetches it). HunyuanVideo 1.5 is not set up: the only MLX port found is gated, and a GGUF run through stable-diffusion.cpp took about 80 s per step at 480x272. Its licence also excludes the EU, UK and South Korea.

### FastMetal-QAD video (FastVideo)

[FastMetal-QAD](https://haoailab.com/blogs/fastmetal/) (Hao AI Lab) are Wan models distilled to 3 denoising steps and quantised to INT8 for MLX: the 5B is Wan 2.2 TI2V 5B (1280x704 or 704x1280, up to 121 frames at 24 fps), the 14B is Wan 2.1 T2V 14B (832x480 or 480x832, up to 81 frames at 16 fps), and a 1.3B exists too (not in the template). Weights and code are Apache-2.0. The runtime is text-to-video only: no first picture and no sound. "Faster" mode makes about half the frames and fills the rest in with RIFE interpolation (the 14B drops from 338 s to 135 s). Each clip is one FastVideo script process, so nothing stays resident between clips; a new description first runs the UMT5 text encoder (up to 24 GiB resident for a few seconds, then the clip itself needs 12 GiB for the 5B and 22 GiB for the 14B). The encoded description is cached, so the same description again is quicker.

```sh
git clone --depth 1 --filter=blob:none https://github.com/hao-ai-lab/FastVideo.git ~/ai/src/FastVideo   # a full clone kept dropping the connection here
cd ~/ai/src/FastVideo
git sparse-checkout init --no-cone
git sparse-checkout set /LICENSE /pyproject.toml /README.md /docs/ /examples/inference/basic/ /fastvideo/
git checkout
uv venv --python 3.12 --seed ~/ai/envs/fastmetal
VIRTUAL_ENV=~/ai/envs/fastmetal uv pip install -e ".[mlx]"     # large: the base dependencies include torch, gradio and ray, none of them CUDA on a Mac
~/ai/envs/meeting-worker/bin/hf download FastVideo/FastMetal-5B-QAD  --local-dir ~/ai/models/video/fastmetal/5B    # 18 GB
~/ai/envs/meeting-worker/bin/hf download FastVideo/FastMetal-14B-QAD --local-dir ~/ai/models/video/fastmetal/14B   # 39 GB
```

Set `python` to `~/ai/envs/fastmetal/bin/python`, and each preset's `model_dir` and `repo_dir` (the FastVideo checkout) in the `fastmetal_video` entry. The first clip downloads a small TAEHV decoder file from GitHub into `~/.cache/fastvideo/taehv/`; after that the worker runs offline.

### LongCat-Video (MLX port)

[LongCat-Video](https://huggingface.co/meituan-longcat/LongCat-Video) (Meituan, 13.6B, MIT) makes clips from a description at 832x480 and 15 fps, without sound. It runs through the community MLX port [xocialize/longcat-video-mlx](https://github.com/xocialize/longcat-video-mlx) (`mlx-community/LongCat-Video-q8` and `-q4`). It is slow: the 50-step default took 15 minutes for 9 frames, so the worker uses the 8-step fast LoRA, which still takes about 43 s for 0.6 s of video, 80 s for 1.1 s, and about 3 and 6 minutes for 2.2 and 4 s (4-bit is no faster than 8-bit and only saves about 6 GiB). Peaks of the MLX memory: 18.5 GiB at 9 frames, 26 at 17, 28 at 33, 37 at 61.

The port needs fixes that `workers/longcat_driver.py` makes without editing it: the fast LoRA cannot merge into 4- or 8-bit weights (`longcat_qlora_patch.py` dequantizes, adds and requantizes, which is slightly lossy), the first-frame and continuation pipelines never give the clean reference latents timestep 0 (the output is rainbow garbage without that), and it keeps the text encoder and the DiT in memory through decoding (the driver frees them, which brings a 33-frame peak from 44 GiB to 28). The repository has no LICENSE file; its `pyproject.toml` and README say MIT. The driver also does image-to-video and video continuation, but the app offers neither: with the 8-step path image-to-video garbled about half of the clips (seeds 3, 7 and 8 of six were wrong, 1, 2 and 42 were clean, with the same picture), and continuation needs a prior clip.

```sh
uv venv ~/ai/envs/longcat --python 3.12
git clone https://github.com/xocialize/longcat-video-mlx ~/ai/tools/longcat-video-mlx   # tested at commit 3ce48c9
uv pip install --python ~/ai/envs/longcat/bin/python -e ~/ai/tools/longcat-video-mlx transformers sentencepiece av
~/ai/envs/meeting-worker/bin/hf download mlx-community/LongCat-Video-q8 --local-dir ~/ai/models/video/longcat-q8   # 31 GB
mkdir -p ~/ai/models/video/longcat-layout && ln -s ~/ai/models/video/longcat-q8 ~/ai/models/video/longcat-layout/LongCat-Video-q8
```

The port wants a folder holding `LongCat-Video-q8/`, hence the symlink folder. Set `python` to `~/ai/envs/longcat/bin/python`, and `weights_dir` (that folder) and `repo_dir` (the checkout) in the `longcat_video` entry.

### LTX-2.5 video (ltx-2-mlx)

[LTX-2.5](https://huggingface.co/Lightricks) makes clips with a sound track, from a description or a first picture. It is personal use only here: the LTX-2.x Community License needs a paid licence for any use by an entity with US$10M or more annual revenue (affiliates included), apart from a company's testing and evaluation in a non-production environment. The code (ltx-2-mlx) is MIT.

It runs from a fork of `dgrauet/ltx-2-mlx` pinned to the tag below, because the ungated 4-bit pack (Phosphene's conversion, by `Mrbizarro`) will not load in mainline. The `dgrauet` weights themselves are gated: accept the licence on their page and log in with `hf auth login` if you want them instead. Only the distilled pack exists here, so there is no negative prompt and no guidance setting. Each clip is one process under a 26 GiB MLX limit (a soft limit). Sizes are multiples of 64 (quick 704x448, sharp 1280x704) and clips are 2, 4 or 5 s at 24 fps. On an M5 Max a 4 s quick clip took 32 s and a sharp one 149 s, both peaking at 13.8 GiB; 1920x1088 at 5 s took 595 s at 29.8 GiB and is not offered. The sound is quiet ambience.

```sh
git clone --branch "v0.14.19+ltx25.9" --depth 1 https://github.com/mrbizarro/ltx-2-mlx ~/ai/src/ltx-2-mlx-fork
cd ~/ai/src/ltx-2-mlx-fork
for f in packages/*/pyproject.toml; do sed -i '' '/^readme = "..\/..\/README.md"/d' $f; done   # hatchling rejects that path
UV_PROJECT_ENVIRONMENT=~/ai/envs/ltx25 uv sync --python 3.12    # do not use --all-extras: the trainer extras hang
~/ai/envs/meeting-worker/bin/hf download Mrbizarro/ltx-2.5-mlx-q4 --local-dir ~/ai/models/video/ltx25-q4-mrbizarro      # 19 GB
~/ai/envs/meeting-worker/bin/hf download Mrbizarro/gemma4-12b-ltx25-q4 --local-dir ~/ai/models/video/ltx25-gemma4-q4     # 6.3 GB text encoder
```

Set `python` to `~/ai/envs/ltx25/bin/python` and `model_dir` and `gemma_dir` to those folders in the `ltx_video` entry.

### MiniMax H3 (h3.c)

[h3.c](https://github.com/antirez/h3.c) (MIT) is a native Metal engine for MiniMax H3. With `--ssd-streaming` it reads the original BF16 transformer from the SSD and keeps two layers in memory, so a clip needs about 11 GiB instead of 60, at the price of speed: 5 s at 864x480 took 200 s as a draft (4 steps) and 16.5 min at standard (20 steps); a 0.9 s clip at 512x512 took 35 s. It makes sound with the video. The app offers the text and first/last-frame modes, which need only the FL2VA checkpoint (134 GB). **The H3 licence excludes the US, EU, UK and South Korea, so use it only where it grants rights, on your own machine.**

```sh
git clone https://github.com/antirez/h3.c ~/ai/tools/h3.c && make -C ~/ai/tools/h3.c -j8
~/ai/envs/meeting-worker/bin/hf download MiniMaxAI/MiniMax-H3 --include "FL2VA/*" --local-dir ~/ai/models/minimax-h3/MiniMax-H3
```

The engine finds its Metal shaders in its own folder, so the worker runs it from there. It uses the `mlx-video` environment's Python only to run the worker.

## 6. Speech

All five speech models run through [mlx-audio](https://github.com/Blaizzy/mlx-audio) (MIT) in one environment, in the worker process, with no server. **Check each model's licence before anyone but you uses it.**

```sh
uv venv ~/ai/envs/mlx-tts --python 3.12
uv pip install --python ~/ai/envs/mlx-tts/bin/python mlx-audio soundfile pillow
HF=~/ai/envs/meeting-worker/bin/hf; T=~/ai/models/tts
for r in Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit Qwen3-TTS-12Hz-1.7B-Base-8bit \
         OmniVoice-bf16 fish-audio-drama-3-3bit fish-audio-s2-pro-8bit Breeze-TTS-2-mlx-8bit; do
  $HF download mlx-community/$r --local-dir $T/$r; done
```

| Model | Licence | Notes |
| --- | --- | --- |
| Qwen3-TTS | Apache-2.0 | Built-in voices, a voice from a description, cloning. About 3 GiB per model; only the tab in use stays loaded. |
| Fish Drama 3 | Fish Audio Community License: free only below USD 500,000 annual revenue (you and your affiliates), so personal use only for a larger company; no hosted service for third parties | Scenes with several speakers, `[cue]` tags. 3-bit peaks near 22.6 GiB; the 4-bit near 26.4 GiB. |
| Fish S2 Pro | Fish Audio Research License: **no commercial use, including a company's internal operations** | `[cue]` tags, cloning. |
| OmniVoice | CC BY-NC (weights), plus a 100,000-user cap on its audio tokenizer | **Non-commercial.** The Mac model has no speed control, so that form field is ignored. |
| Breeze TTS 2 (BreezeBlue's, not MediaTek's) | BreezeBlue research and non-commercial licence | **Non-commercial.** English and Chinese; one reference voice per take. |

### The Speech page and saved voices

All five models share one **Speech** page (in the sidebar). A dropdown lists the running speech models with their licence,. What you type (the words, language, seed, voice description, direction, a clone sample and what it says) is kept by role, so switching the model or the voice tab carries it over; what the new model has no place for is named and kept for the way back. Each model explains how it takes direction: a plain-words field (Qwen3-TTS, Breeze), cues in the text (Fish: `[whisper]`; Breeze: `(laugh)`; OmniVoice: sounds only, such as `[laughter]`) or none. Square-bracket cues sent to a model that has none would be read aloud, so the page warns and offers "Remove cues".

**Record a sample** with the Record tile next to any voice-sample field on a speech model: it uses the browser's microphone (allowed only on https pages or localhost), stops by itself at 30 seconds, and adds a WAV like a chosen file. 5 to 20 seconds works best. Every audio sample on a speech form can be played back, and once one is recorded or chosen the page writes down what it says (the Qwen3-ASR `asr_dir` the model is set up with, run once per sample in the model's environment, about 5 seconds) and fills "What the sample says" unless you typed your own words there. The host route is `POST /api/runtimes/{id}/transcribe` with `{upload_id}`.

**Saved voices** (folded section on the page) are kept on the host under `runtime/voices/`: a name, the sample and the words it says. Save the sample on the form, or choose **Save as voice** on a finished result (a speech recording, or a video clip's soundtrack); **Use** puts a voice on the clone tab of any model that clones. The API: `GET/POST /api/voices`, `PUT/DELETE /api/voices/{id}`, `GET /api/voices/{id}/sample`. Only keep voices you have permission to use.

In the chat, every running speech model is reached through one `speak` tool (text, and optionally a saved voice by name, a voice description, a built-in speaker, a direction, language, speed, seed, and which model). The chat picks a running model that can do what was asked, fills that model's own fields, leaves out what it cannot take (said in the result) and removes cues the model would read aloud. The tool's description and the assistant's model guide are generated from each running model's capabilities.

When you clone a voice without typing what the sample says, the worker writes it down with the Qwen3-ASR folder from the meeting setup (`asr_dir`). The MLX models need those exact words.

## 6a. Decide (decision models)

A decision model reads a situation once and gives a probability for each answer to a multiple-choice, yes/no or scored question, in one pass (about a quarter of a second for a short text). It is the open-weight counterpart of TypeSafe's hosted Jev. All four below are Apache-2.0, so they are work use.

```sh
# Torchcast 4B (v1.3.1, 9.7 GB): the vendor package on the Mac GPU through torch. Stock MLX and llama.cpp give wrong
# answers because the model was trained with non-causal attention in its full-attention layers.
uv venv ~/ai/envs/decide-torchcast --python 3.12
uv pip install --python ~/ai/envs/decide-torchcast/bin/python torch "transformers==5.8.1" accelerate safetensors pillow torchvision numpy
~/ai/envs/meeting-worker/bin/hf download torchcast-ai/torchcast-decision-4b --revision v1.3.1 --local-dir ~/ai/models/decision/torchcast-4b

# Torchcast 31B (v1.0.0, 61 GB bf16) as a 33 GB 8-bit MLX copy. Needs mlx-lm 0.32.x, which the same environment has;
# the conversion peaks near 40 GB, so run it alone. Afterwards delete the folder's `model-*.safetensors` shards (61 GB) but keep the rest: the engine reads its prompt code, tokenizer and `decision_config.json` at run time.
~/ai/envs/meeting-worker/bin/hf download torchcast-ai/torchcast-decision-31b --revision v1.0.0 --local-dir ~/ai/models/decision/torchcast-31b
~/ai/envs/decide-torchcast/bin/python workers/torchcast31_convert.py ~/ai/models/decision/torchcast-31b ~/ai/models/decision/torchcast-31b-mlx-8bit

# pplx-decider 27B (8-bit, 26 GB) and H2O-Lightning 4B (8.7 GB): both read pictures, through mlx-decision
uv venv ~/ai/envs/decide-pplx --python 3.12
uv pip install --python ~/ai/envs/decide-pplx/bin/python mlx-decision pillow
export HF_HOME=~/ai/models/decision/.hf-cache
~/ai/envs/decide-pplx/bin/mlx-decision download h2oai/h2o-lightning-4b --local-dir ~/ai/models/decision/h2o-lightning-4b --yes
~/ai/envs/decide-pplx/bin/mlx-decision download perplexity-ai/pplx-decider-v1.2 --local-dir ~/ai/models/decision/pplx-decider --bits 8 --yes
```

| Model | Memory while running | Latency (warm) | Notes |
| --- | --- | --- | --- |
| Torchcast 4B v1.3.1 (bf16, torch on the Mac GPU) | about 14 GB | 0.15 s short, 1.5 s for 6,000 tokens | Text only. Checked against the vendor's CPU fp32 output: probabilities within 0.006, same answer on every test. Use v1.3.1 (earlier tags are non-commercial). Not 4-bit: one answer flips. |
| Torchcast 31B v1.0 (8-bit MLX, bidirectional global attention) | about 37 GB at peak; run it alone | 0.2-0.5 s short, 9 s for three 2,000-token questions | Text only. Within 0.0084 of the vendor's bf16 run, same answers on every test. Loads in about 14 s, then a warm-up. Do not use stock MLX or llama.cpp builds of it: they get answers wrong. |
| pplx-decider v1.2 27B (8-bit) | about 30 GB at peak | 0.5 s for 300 words, 3.7 s for 3,000 | Reads pictures (cold first call 7 s). Does not fit in bf16 (52 GB). The v1.3 release adds span extraction; not tested here. |
| H2O-Lightning 4B (bf16) | about 10 GB at peak | 0.15 s for 300 words, 1 s for 3,000 | Reads pictures. The 31B is non-commercial; this is the 4B. |

Inputs are capped at 20,000 characters and 255 options. The worker keeps every MLX call on one thread, because MLX streams belong to the thread that made them. Karpo 31B (a community 4-bit MLX port) was tried and removed: Torchcast 31B scores higher and Torchcast 4B and pplx-decider cover the lighter and picture cases. Rankings come from JevBench, the Decision Index and Artificial Analysis; the hosted Jev is the baseline, and a few other open models (two of them personal-use only) are reference bars. The full survey is in `docs/context.md`.

## Files in the chat

The paperclip attaches files from your computer: pictures (up to 12 MB; the model sees them when picture reading is on), PDFs (their text is extracted with pypdf; a scan with no text layer is refused with a hint to attach its pages as pictures) and text or code files (.txt, .md, .csv, .json, .py and similar). Each file's text is cut at 120,000 characters, with a note saying so. Files are kept with the conversation under `<runtime_dir>/chat-files/` and removed when it is deleted. "Add from library" attaches things made here earlier: pictures, videos, sounds, meetings (notes, then transcript) and decisions (their result), which the model reads as text.

## Connecting your own tools to a model

Chat and Decide each have a "Connect a tool" link (left of the model dropdown) that opens a window with the running model's address and the settings of the tool you pick. It shows the running model's own address (this API does not sit in between) and the settings of the tool you pick:

- **Chat models** speak the OpenAI chat API at `http://127.0.0.1:<port>/v1`; no key is needed, so any text works. The picker offers Aider, OpenCode, Open WebUI, curl and the Python OpenAI SDK, filled in with the model's name. Claude Code is not offered: it needs an Anthropic-style endpoint and these servers speak the OpenAI style (not checked beyond that).
- **Decision models** answer TypeSafe's System One API on their own port: `POST http://127.0.0.1:<port>/v1/systemone` with `{"state", "questions", "images"?}`, and `GET /healthz`. The picker offers curl, Python and JavaScript. Pictures go in `images` as data URLs (only pplx-decider and H2O-Lightning read them).
- **Same computer by default.** Each model's server listens on `127.0.0.1`. To reach one from another machine, set `"host": "0.0.0.0"` on its entry in `runtimes.json` and restart it; the page then shows the address under the name this dashboard uses for the host. These servers have no login, so only do that on a network you trust.

## 7. Web search for the chat

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
| Chat says it cannot search the web | No search address is saved. See section 7. |
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
