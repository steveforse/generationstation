# Running TODO

Things asked for or noticed, newest first within each section. Move an item to Done when it is committed and tested. Last updated 2026-11-27.

## In progress

- **LongCat-Video** has three tabs through the app (2026-11-27): a description, a first picture (1.1 s clip in 79 s, clean on seeds 3 and 7 with the cropped picture) and continuing a clip (25 frames, 156 s, followed the prompt). Earlier "garbles half" notes came before the driver fixes and are not reproduced; continuations on some seeds still show artifacts at the join.
- **Wan 2.2 A14B: measured, recommend not adding.** 19 minutes for a 17-frame clip, 33 GiB resident floor, and image-to-video is broken in mlx-video at this commit. Converted weights (80 GB) are kept on disk; delete them if you agree.
- **LLM benchmarks and Claude reference bars: committed** (GPQA Diamond, Terminal-Bench 4.0 and 2.1, plus the earlier rankings; Claude Haiku, Sonnet and Opus 5.5 as references). Fable 5.2 as a fourth reference: decided against (2026-11-27, no open model is near the three already shown); Terminal-Bench 4.0 has no independent score for Qwen3.8 27B and Flash-Next; AIME 2025 is not published for any of the models.

## Waiting for a decision

- **One Speech page and a saved voice library** (plan in `docs/speech-consolidation.md`, agreed and approved 2026-11-27): capabilities on the five models, the shared Speech page and the voice library are built and tested with fixtures; the single `speak` chat tool is built too; left: a listening check per model on the Mac (fixtures and unit tests cover the logic, not the sound).

- **Decide tool: Karpo 31B, pplx-decider 27B (8-bit) and H2O-Lightning 4B built and tested through the app (pplx read a receipt picture). Torchcast 4B (vendor package on torch MPS) and 31B (8-bit MLX, `workers/torchcast_mlx.py`) added and run through the app. Disk cleaned 2026-11-27 (about 344 GB: Wan A14B conversions, LongCat q4, Qwen-Image 2512 q4, the community Torchcast 4B copies, the Torchcast 31B bf16 shards, duplicate cache copies, /tmp scratch).** Also open: a calibration note on the result page (Karpo's probabilities are near 0 or 1), pplx v1.3, an ordering test.

- **Decision models (like TypeSafe's Jev) as a "Decide" tool.** Research done (see `docs/context.md`): Apache-2.0 shortlist is karpo-decision-31B (community MLX, 16.4 GB), pplx-decider 27B / flash 4B through `mlx-decision`, then H2O-Lightning-4B. Waiting for your go-ahead and which to start with; none measured on this Mac yet.

- **Transcribe page** built (2026-11-27; plan and measurements in `docs/transcribe-plan.md`): Qwen3-ASR, Whisper large-v3-turbo, Parakeet TDT v3 and Nemotron 3.5 Transcribe (4-bit export), who spoke by sherpa turns, one `transcribe` chat tool. Not done: Cohere Transcribe (gated repository, waits for approval on your Hugging Face account), a real recording to check speaker detection and long-form quality (everything was measured on synthetic speech), the NVIDIA NVFP4 Nemotron checkpoint (word times and speaker tags, 24 to 27 GB), translation, the Windows desktop (the page and its models are untested there; no Windows engine exists yet), a listening check of the live chat tool.
- **Project Maya (Mac).** Answered: it has an experimental Metal path for GLM-5.3-Flash only, untested by its author on the real model, and the smallest Mac-relevant quant is 73.4 GB (it expects 64 GB of RAM plus a 24 GB card), so it does not fit this 64 GB Mac. Hy4-Flash and Inkling 2 Mini run on it only on NVIDIA and AMD. Worth revisiting for the Windows RTX 5090 desktop, not the Mac.

## Later / offered

- Picture models stay loaded (2026-11-27), with the text encoder given back after each description and tiled decoding: Z-Image 28 to 14 s, Qwen Turbo 35 to 17 s, peaks 7 to 35 GiB (estimates 9, 14, 18, 38 GiB; nothing held before, now 1.5 to 22 GiB idle). The Windows picture worker is unchanged.

- **Images page** done on the Mac (2026-11-27): checked by eye on Z-Image Turbo and Qwen Image 2.1 Turbo; not looked at by eye: Qwen Image 2.1 full and Qwen-Image 2512. The H3 picture tabs on the Windows desktop are untested. Instruction editing (Qwen Image 2.1 edit mode on the installed weights, personal use only; Qwen-Image-Edit-2511, Apache-2.0, about 34 GB) skipped for now. 
- **Video page** built (2026-11-27; plan and results in `docs/video-consolidation.md`): one entry over Wan, FastMetal, LongCat, LTX-2.5 and H3, LTX last frame, LongCat picture and continue tabs, "Use last frame as first picture" and "Use as source clip", one `make_video` chat tool. Not done: LTX extend and retake (they need the dev transformer, see the plan), H3 on the Windows desktop (the page, its tabs and the picture tabs on Images are untested there), a look by eye at each model's clips through the page.
- **Music page** built and tested with fixtures and the real models (2026-11-27; plan in `docs/music-consolidation.md`): one entry, three models, ACE-Step tempo, cover and repaint, MiniMax steps, one `make_song` chat tool. Left: a listening check per model on the Mac and YuE2's page on the Windows desktop; 

- Run our own VBench subset on the video models (about 100 prompts, 1 to 3 hours each, own numbers not comparable to published ones): after the Decide work, needs an idle machine. VBench-2.0 LongCat and the Wan 2.2 and LTX-2 VBench estimates are in the catalog.

- Frontend tests are flaky on this machine again (2026-11-27 afternoon): the stream reconnect and chat song tests, plus one or two others that vary by run, fail with timeouts, and the suite takes 1 to 1.5 minutes instead of 17 s. The same tests fail on the commit before today's changes, so it is the machine (two decision workers and a virtual machine were running), not the code. They passed at 17 s earlier today.

- Clean re-timing of the video models: done 2026-11-26 (see `docs/context.md`); a few cells are scaled rather than measured.

- Add HeartMuLa 3B as a fourth music model (Apache-2.0, Llama tokenizer file caveat, PyTorch only).
- Quality scores for the Windows template (`runtimes.example.json`), which has none yet.
- The Windows setup guide, as a separate PR.
- Delete the merged branches `meetings` and `docs/readme-and-setup-guides` (offered, not approved).
- Delete large leftovers in `/tmp` (`/tmp/hf`, `/tmp/heart`, `/tmp/mm`, `/tmp/wanvenv_work`, `/tmp/hv15`, agents' clips and logs) once the video work is finished.
- Re-run the full Playwright suite when the machine is idle: while the video agents generate, a few tests time out at random (they pass alone).
- Restart note: the API runs from the latest code since the last restart; restart it again after the chat and LTX changes land. The MiniMax Music 3 worker was stopped to free memory; start it again from its card if wanted.

- Decide: Karpo 31B removed (weights, environment and catalog entry; kept as a reference bar); every decision model now shares one Decide page with a dropdown over those running, like Chat.

- Connect a tool (Chat and Decide): address and per-tool settings built; the chat half is tested against the fixture API only (needs a real chat model run to confirm the served-model name). Not offered: Claude Code and Codex CLI (they need other API styles).

## Done this session (all on PR #2 unless noted)

- Models page: default sort is alphabetical, sidenav and Overview lists are alphabetical, margin under the sort control.
- FastMetal-QAD (5B, 14B) and LTX-2.5 video added and tested through the app (FastMetal 2 s clip in 29 s fast mode, LTX 2 s clip with sound in 31 s).
- Chat page names only running models, with a dropdown to switch between running chat models (the host moves the conversation to the model chosen).
- Reference-model support in the quality charts; quality rankings moved below the cards with the sort control above them.
- Running TODO (this file).
- Mac generators: Qwen Image family, Z-Image, Qwen-Image 2512, YuE2, five speech models, Wan 2.2 5B, H3, ACE-Step 1.5, MiniMax Music 3.
- Licence badges, filter, details; Models page grouped by kind with folded quality rankings, a ranking switcher and sorting by name or quality.
- Text rankings: Intelligence Index, LLM Stats, DeepSWE, Arena text Elo, LiveBench coding. Music ranking: SongBench. Video: Artificial Analysis open-weights (added with LTX-2.5, not yet committed).
- Meeting notes: edit summary, action items and decisions with a change history; layout fixes (history beside the licence, action item rows, narrower Time field).
- MiniMax Music 3 marked work use while the app stays internal.
