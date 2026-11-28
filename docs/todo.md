# Open work

What is still open, as of 2026-11-28. Finished work is in the git history and the state of the project is in `docs/context.md`.

## Decisions waiting on the owner

- **Meeting notes with Claude.** Use a hosted model as its writing model (deferred on request).
- **Hosted section on the Overview.** The Models page has a Hosted tab; the Overview shows only local models.
- **`ernie-5.5` branch.** One commit (ERNIE 5.5 Flash Preview with a vLLM engine) that the desktop cannot run (it needs two 288 GB GPUs). Merge or leave.

## Hosted chat models

- A full turn through the app with a tool call, a picture sent and thinking shown (streaming and the assistant were checked live).
- OpenCode as a source: revisit on the Windows desktop (OpenCode lists a custom provider's models in its own config; it does not discover them).
- Meeting notes and the connect-a-tool snippets still use local models only.

## Windows desktop

- The Images, Music, Speech, Video, Transcription and Decision pages and their chat tools are built and checked on the Mac; they are untested on the desktop (H3's picture tabs, YuE2's page, no Windows speech-to-text engine yet).
- Quality scores for `runtimes.example.json`, which has none.
- A Windows setup guide, as a separate pull request.
- Running Inkling on the RTX 4080 at SQ-15 once the monitors move to the motherboard's video (see `docs/context.md`).
- Project Maya: its Metal path is experimental and too big for the Mac (73.4 GB), but worth revisiting for the RTX 5090.

## Models and pages

- **Transcription:** Cohere Transcribe (gated repository, waits for approval on the owner's Hugging Face account); a real recording to check speaker detection and long-form quality (everything was measured on synthetic speech); the NVIDIA NVFP4 Nemotron checkpoint (24 to 27 GB, word times and speaker tags; never tried); translation; a live run of the `transcribe` chat tool. Recheck Parakeet's leaderboard figure (5.66 word error here, 6.32 on NVIDIA's card).
- **Video:** LTX extend and retake (need the dev transformer); LongCat continuations still show artifacts at the join on some seeds; a look by eye at each model's clips.
- **Music:** HeartMuLa 3B as a fourth model (Apache-2.0, Llama tokenizer caveat, PyTorch only); a listening check per model.
- **Speech:** a listening check per model on the Mac.
- **Images:** Qwen Image 2.1 full and Qwen-Image 2512 have not been looked at by eye; instruction editing (Qwen-Image-Edit-2511, Apache-2.0, about 34 GB) was skipped.
- **Decision:** a calibration note on the result page, pplx v1.3, an ordering test.
- **Connect a tool** (Chat and Decision): the chat half is tested against the fixture API only, so the served-model name needs a real chat model to confirm. Claude Code and Codex CLI are not offered (other API styles).
- **Meeting notes:** naming speakers in a form the person confirms before the notes; one file per participant.
- **VBench:** run our own subset on the video models (about 100 prompts, 1 to 3 hours each; own numbers, not comparable to published ones). Needs an idle machine.
- An OpenAI-style `/v1/audio/speech` endpoint.

## Tests

- The Playwright suite has tests that fail at random on this machine ("reconnects after a stream outage", "chats with the text model, which starts a song", and one or two others that vary by run). The same tests fail on code from before the recent changes. Re-run on an idle machine.
