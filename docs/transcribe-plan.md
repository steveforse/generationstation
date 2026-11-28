# Speech to text as its own tool (built 2026-11-27)

**Nemotron 3.5 Transcribe was built, measured and removed on 2026-11-27.** The page now serves Qwen3-ASR, Whisper large-v3-turbo and Parakeet TDT v3. Nemotron was within noise of the others on accuracy (3.7 % against 4.0 to 5.1 % on the 56 minute test) and cost 19.8 GiB of memory, 19 GB of disk, gave no times, no speaker labels and no language choice, and was slower. Its measurements below are kept as history and marked removed. The NVIDIA NVFP4 checkpoint (24 to 27 GB, with word times) was never tried.

A Transcribe page that turns a recording into a transcript, without the meeting pipeline (no speaker turns, correction or notes unless asked for). Same shape as Speech, Images, Music and Video: one sidebar entry, a dropdown over the running transcription models with the licence word, capability declarations per model, carry-over by role, and one `transcribe` chat tool.

## Candidates

All load through mlx-audio 0.6.8 (`mlx_audio.stt.load`) in `~/ai/envs/mlx-tts`, which already has the code for each. Sizes are the weights on Hugging Face; licences, languages and accuracy are from the Nemotron and Cohere cards (read 2026-11-27) and the mlx-audio READMEs; cells marked "not looked up" are filled in during the checks.

| | Qwen3-ASR 1.7B (8-bit) | Whisper large-v3-turbo | Parakeet TDT v3 | Nemotron 3.5 Transcribe (4-bit export; removed) | Cohere Transcribe |
| --- | --- | --- | --- | --- | --- |
| Installed | yes (`~/ai/models/asr`, used by Meeting notes) | no, 1.6 GB | no, 2.5 GB | no, 19.3 GB | no, 4.1 GB, repo is gated |
| Licence | Apache-2.0 (work) | MIT (work) | CC-BY-4.0 (work, needs credit to NVIDIA) | OpenMDW-1.1, "ready for commercial or non-commercial use" (work; read the terms before marking) | Apache-2.0 (work) |
| Languages | not looked up yet | 99 | 25 European, detected | 40 | 14 |
| Timestamps | segment (via the forced aligner, separate model) | segment and word | segment and word | none in the early-access export (the NVIDIA checkpoints have word times, 67 GB bf16) | none |
| Extras | context text for names and terms | translate to English | fast (a 0.6B model) | context terms, speaker tags (`<spk:N>`), translation, rich transcription | punctuation on or off |
| English accuracy (Open ASR average word error, from the cards and the earlier meeting research) | about 5.3 % | not looked up | not looked up | 4.7 % | 5.4 % |

Not proposed: Whisper large-v3 (turbo is the same family and faster), Canary, SenseVoice, Moonshine, Voxtral and the rest of the mlx-audio list (no reason to add them before these are measured).

## What the page offers

- **Recording**: an audio or video file (the browser uploads it; the worker reads the audio track with ffmpeg and resamples to 16 kHz mono). The same file kinds Meeting notes accepts, up to an hour.
- **Language**: automatic, or one the model lists (each model's own list; a language one model lacks is left out when you switch, as on Speech).
- **Words to expect**: names and terms, for the models that take context (Qwen3-ASR and Whisper). Not shown for Parakeet.
- **Timestamps**: line by line (the models that give them), shown in the result and written to the subtitle files.
- **Who spoke**: speaker labels. No model makes them itself (Nemotron's own tags were not usable); the speaker turns the meeting pipeline already finds (sherpa-onnx, CPU, about 1 s per 10 s of audio on this Mac) are laid over the transcript. Optional; off by default.
- **Result**: the transcript as text with times and speakers when asked for, a copy button, and downloads `transcript.txt`, `.srt`, `.vtt` and `.json` (the model, language, durations and the word list used). A result is a "document" like Meeting notes.
- **Result actions**: "Use as notes source" is not built (Meeting notes keeps its own form); "Use these settings" works as on the other pages.

Capabilities per model (`transcription` on the plugin, as `speech` and `music` are): which of language, terms, timestamps and who-spoke the model takes, its language list, whether it translates, and a long-form note. Roles carry from one model to the next: recording, language, terms, timestamps, speakers.

## Chat

One `transcribe` tool over the running models: a reference to a recording or a result (a clip's soundtrack, a song, an uploaded file) and optionally the language and terms. The job is made as for the other tools; when it finishes, the transcript text goes back to the chat model (cut at a length the model can read, with the file named) so it can answer questions about the recording. The assistant guide gets one line.

## Built and measured (2026-11-27, Apple M5 Max 64 GB)

Decisions taken: Qwen3-ASR, Whisper large-v3-turbo, Parakeet TDT v3 and Nemotron 3.5 Transcribe (4-bit export; Nemotron was removed afterwards, see the top); "Who spoke" for the models that do not label speakers themselves; the sidebar entry is **Transcribe**; the Models page group is "Speech to text".

Test audio: two macOS voices reading 10 lines of a made-up meeting with invented product and people names (so a model cannot know them), 20 and 66 different meetings joined into 17 minutes and 56 minutes (a repeated meeting is not a fair test: models that predict text loop on it). Word error is against the script with numbers left out (models write "42" or "forty two"). A real Zoom recording was not on hand.

| | Qwen3-ASR (30 s parts) | Whisper turbo | Parakeet v3 (60 s parts) | Nemotron (2 min parts; removed) |
| --- | --- | --- | --- | --- |
| 17 minutes: time, word error | 21 s, 4.3 % | 8 s, 4.2 % | 4 s, 4.3 % | 34 s through the app (3.1 % when the 17 minutes went in one piece, in 37 s) |
| 56 minutes: time, word error | 80 s, 4.4 % | 31 s, 4.0 % | 12 s, 5.1 % | 152 s, 3.7 % (in one piece 209 s, 35 %) |
| Memory at the peak | 3.9 GiB | 3.8 GiB | 3.9 GiB | 19.8 GiB |
| Times | about 30 s parts | lines of a few seconds | sentences | none |

- **Long recordings need parts.** Qwen3-ASR on 18 minutes in one go looped (word error 96 %, on a meeting repeated 20 times); in 30 s parts 3.3 % on that repetition and 4.3 to 4.4 % on the varied recordings, in 60 s parts 10.5 %. Parakeet in one go took 32 GiB; at 60 s parts 3.9 GiB. Nemotron on 56 minutes in one go repeats and skips (35 %); parts of 20 minutes 16 %, 10 minutes 9 % (106 s), 5 minutes 5 % (126 s), 2 minutes 3.7 % (152 s): shorter parts read better and cost a little more time. Whisper cuts its own 30 s windows.
- **Words to expect** fixed the invented names (Zephyrine, Quillon) on Qwen3-ASR, Whisper (as its prompt) and Nemotron (removed). Parakeet takes none.
- **Language:** all four (Nemotron included) detected a French sentence by themselves. Qwen3-ASR and Whisper also take a named language.
- **Who spoke:** Nemotron's own speaker tags (`<spk:N>` through a prompt; the `saa` task returned only quote marks) were not usable in this 4-bit export: junk before the first word, text skipped, and on 17 minutes it did not stop at the end of the audio and wrote 5 times the text (250 s). It was therefore not offered; the NVIDIA NVFP4 checkpoint (24 to 27 GB, with word times) may behave differently and has not been tried. The three models that remain use the speaker turns of the meeting notes (sherpa-onnx, 5 s for a minute of audio): Qwen3-ASR listens to each turn (as the meeting notes do), Whisper and Parakeet lines are given the speaker whose turn overlaps them most, and neighbours of one speaker are joined. At the meeting notes' setting (0.9, tuned on a real Zoom call) the two TTS voices came out as one speaker; at "More" (0.7) the 10 lines were attributed correctly, so the form has an advanced "How many speakers" choice (fewer, usual, more).
- **Through the app:** 17 minutes in 21 s (Qwen3-ASR), 7 s (Whisper), 5 s (Parakeet) and 34 s (Nemotron, removed), models loaded; an MP4 works as a recording (the sound is extracted with ffmpeg); each model loads in 1 to 4 s.
- **Chat:** one `transcribe` tool takes the reference of an earlier result (a clip, a song, a recording) and the finished transcript goes to the chat model as text. Not run against a live text model; covered by tests.

## Not in this pass

- Windows: the desktop would run Whisper and Qwen3-ASR through transformers and qwen-asr (the meeting pipeline already does); the plugin keeps an engine field so that can follow.
- Live or streaming transcription from the microphone (the voice sample recorder stays on Speech).
- Translation (Whisper can; a "translate to English" choice can be added when the first pass is checked).
- Replacing the engine Meeting notes uses.
- Nemotron's NVIDIA checkpoints (67 GB bf16, 24 to 27 GB FP8 or NVFP4 with word times). The early-access export was built and then removed; these were never tried.
- Cohere Transcribe until the gated repository is approved on your Hugging Face account, and then only if it adds something (no timestamps, no speakers, 14 languages).

## Checks that were planned (before a feature goes in the form; written before Nemotron was removed)

1. One test set: the 57-second synthetic meeting (known text), a 10-minute stretch of the real Zoom recording (speaker changes, jargon) and a 3-minute clip in another language. For each model: time (the first run and a warm one), peak memory, and the errors against the known text, written down per model.
2. Long recordings: a 60-minute file through each model (chunking, memory growth, a repeated-text failure). Models that cannot do an hour get a note on the page and a length warning, not a silent cut.
3. Words to expect: a recording with five invented product names, with and without the list, on Qwen3-ASR and Nemotron.
4. Timestamps: segment times within a second of the audio on Whisper, Parakeet and Qwen3-ASR (the last needs the forced aligner; if it is too slow or large, Qwen3-ASR has no timestamps here and says so).
5. Who spoke: Nemotron's tags against the sherpa turns on the same two-speaker recording.
6. The chat tool: attach a clip, ask what is said, and a long recording to see the cut.
7. Fixture tests for the page and backend tests for the declarations and the `transcribe` tool, as for the other pages.

## Decisions that were needed

1. Which models in the first pass. Recommended (Nemotron was later removed): Qwen3-ASR (installed), Whisper large-v3-turbo, Parakeet TDT v3 and Nemotron 3.5 Transcribe 4-bit (20 GB of downloads in all). Cohere waits for the gated approval.
2. Whether "Who spoke" is in this pass for the models that do not make it themselves (the sherpa turns laid over the text). Recommended: yes, if check 5 looks reasonable; it is the feature people ask for after the words.
3. The sidebar name: **Transcribe** (recommended) or **Speech to text**. The Models page group would be "Speech to text".
