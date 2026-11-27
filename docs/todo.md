# Running TODO

Things asked for or noticed, newest first within each section. Move an item to Done when it is committed and tested. Last updated 2026-11-26.

## In progress

- **Chat page: name only running models, and a dropdown when two or more run.** Code and tests are done (frontend 47 tests, switching sends `model_id` with the message and the host moves the conversation to it). Still to do: a backend test for the switch in `backend/tests/test_chat.py`, then commit.
- **LTX-2.5 video (personal use).** Plugin, worker, catalog entries and docs are written and the catalog tests pass. Still to do: one end-to-end clip through the app (queued behind the other agents' generations), then commit.
- **Video engines to add, in this order.** (1) FastMetal-QAD 5B and 14B (Apache-2.0, official MLX runtime), (2) Wan 2.2 A14B through mlx-video, (3) LongCat-Video (MIT, single-developer MLX port), (4) LTX-2.5 (above). Four background agents have installed and measured them; LTX-2.5 reported, the others are pending. Each needs a plugin, worker, catalog entry, quality score, docs, tests and an end-to-end clip.
- **LLM benchmarks: add AIME 2025, GPQA Diamond and LiveCodeBench rankings, plus Claude Haiku, Sonnet and Opus as reference bars.** A research agent is collecting sourced numbers for the four local models and the Claude models. The reference bars need a new idea in the catalog and chart: scores for models that are not run here, drawn in a neutral style and labelled as reference points. Hy4-Flash has no published AIME25/GPQA/LiveCodeBench so far.

## Waiting for a decision

- **Speech-to-text as a standalone tool.** Research is done (see `docs/context.md` once recorded). Proposed first models: Qwen3-ASR 1.7B (already works here) and Nemotron 3.5 Transcribe (mlx-audio has it natively, about 24-27 GB). Then Cohere Transcribe (gated repo, read the card), Parakeet TDT v3 (fast, attribution needed), Whisper large-v3-turbo (99 languages). Optional "who spoke" toggle using the sherpa-onnx turns the meeting pipeline already uses. Not started.
- **Project Maya (Mac).** Answered: it has an experimental Metal path for GLM-5.3-Flash only, untested by its author on the real model, and the smallest Mac-relevant quant is 73.4 GB (it expects 64 GB of RAM plus a 24 GB card), so it does not fit this 64 GB Mac. Hy4-Flash and Inkling 2 Mini run on it only on NVIDIA and AMD. Worth revisiting for the Windows RTX 5090 desktop, not the Mac.

## Later / offered

- Add HeartMuLa 3B as a fourth music model (Apache-2.0, Llama tokenizer file caveat, PyTorch only).
- Quality scores for the Windows template (`runtimes.example.json`), which has none yet.
- The Windows setup guide, as a separate PR.
- Delete the merged branches `meetings` and `docs/readme-and-setup-guides` (offered, not approved).
- Delete large leftovers in `/tmp` (`/tmp/hf`, `/tmp/heart`, `/tmp/mm`, `/tmp/wanvenv_work`, `/tmp/hv15`, agents' clips and logs) once the video work is finished.
- Re-run the full Playwright suite when the machine is idle: while the video agents generate, a few tests time out at random (they pass alone).
- Restart note: the API runs from the latest code since the last restart; restart it again after the chat and LTX changes land. The MiniMax Music 3 worker was stopped to free memory; start it again from its card if wanted.

## Done this session (all on PR #2 unless noted)

- Mac generators: Qwen Image family, Z-Image, Qwen-Image 2512, YuE2, five speech models, Wan 2.2 5B, H3, ACE-Step 1.5, MiniMax Music 3.
- Licence badges, filter, details; Models page grouped by kind with folded quality rankings, a ranking switcher and sorting by name or quality.
- Text rankings: Intelligence Index, LLM Stats, DeepSWE, Arena text Elo, LiveBench coding. Music ranking: SongBench. Video: Artificial Analysis open-weights (added with LTX-2.5, not yet committed).
- Meeting notes: edit summary, action items and decisions with a change history; layout fixes (history beside the licence, action item rows, narrower Time field).
- MiniMax Music 3 marked work use while the app stays internal.
