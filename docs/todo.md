# Running TODO

Things asked for or noticed, newest first within each section. Move an item to Done when it is committed and tested. Last updated 2026-11-26.

## In progress

- **LongCat-Video: plugin, driver, worker, docs written; text-to-video tested through the app (66 s for 0.6 s). Image-to-video produced garbage for a mismatched first picture; the worker now crops it to 832x480 and a re-test is queued (the direct driver run with an exact-size picture was fine). Commit after that passes.**
- **Wan 2.2 A14B: measured, recommend not adding.** 19 minutes for a 17-frame clip, 33 GiB resident floor, and image-to-video is broken in mlx-video at this commit. Converted weights (80 GB) are kept on disk; delete them if you agree.
- **LLM benchmarks and Claude reference bars: committed** (GPQA Diamond, Terminal-Bench 4.0 and 2.1, plus the earlier rankings; Claude Haiku, Sonnet and Opus 5.5 as references). Open: Fable 5.2 as a fourth reference (offered); Terminal-Bench 4.0 has no independent score for Qwen3.8 27B and Flash-Next; AIME 2025 is not published for any of the models.

## Waiting for a decision

- **Decision models (like TypeSafe's Jev) as a "Decide" tool.** Research done (see `docs/context.md`): Apache-2.0 shortlist is karpo-decision-31B (community MLX, 16.4 GB), pplx-decider 27B / flash 4B through `mlx-decision`, then H2O-Lightning-4B. Waiting for your go-ahead and which to start with; none measured on this Mac yet.

- **Speech-to-text as a standalone tool.** Research is done (see `docs/context.md` once recorded). Proposed first models: Qwen3-ASR 1.7B (already works here) and Nemotron 3.5 Transcribe (mlx-audio has it natively, about 24-27 GB). Then Cohere Transcribe (gated repo, read the card), Parakeet TDT v3 (fast, attribution needed), Whisper large-v3-turbo (99 languages). Optional "who spoke" toggle using the sherpa-onnx turns the meeting pipeline already uses. Not started.
- **Project Maya (Mac).** Answered: it has an experimental Metal path for GLM-5.3-Flash only, untested by its author on the real model, and the smallest Mac-relevant quant is 73.4 GB (it expects 64 GB of RAM plus a 24 GB card), so it does not fit this 64 GB Mac. Hy4-Flash and Inkling 2 Mini run on it only on NVIDIA and AMD. Worth revisiting for the Windows RTX 5090 desktop, not the Mac.

## Later / offered

- **Two frontend tests fail since this evening, on old commits too, so not caused by recent changes:** "reconnects after a stream outage..." (second stream does not open within 20 s) and "chats with the text model..." (the song card does not finish within 20 s). Both wait on real timers (stream reconnect backoff, 3 s job polls). They passed all day until about 21:30 MST 2026-11-26 (a few hours after the UTC date rolled to Nov 27). Not the real API, not display sleep, not background-timer throttling (all tried). Next step: run them again tomorrow and, if they still fail, trace one (`npx playwright show-trace`).

- Clean re-timing of the video models: done 2026-11-26 (see `docs/context.md`); a few cells are scaled rather than measured.

- Add HeartMuLa 3B as a fourth music model (Apache-2.0, Llama tokenizer file caveat, PyTorch only).
- Quality scores for the Windows template (`runtimes.example.json`), which has none yet.
- The Windows setup guide, as a separate PR.
- Delete the merged branches `meetings` and `docs/readme-and-setup-guides` (offered, not approved).
- Delete large leftovers in `/tmp` (`/tmp/hf`, `/tmp/heart`, `/tmp/mm`, `/tmp/wanvenv_work`, `/tmp/hv15`, agents' clips and logs) once the video work is finished.
- Re-run the full Playwright suite when the machine is idle: while the video agents generate, a few tests time out at random (they pass alone).
- Restart note: the API runs from the latest code since the last restart; restart it again after the chat and LTX changes land. The MiniMax Music 3 worker was stopped to free memory; start it again from its card if wanted.

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
