# One Speech page (plan agreed 2026-11-27; capabilities and the shared page built, library and `speak` tool next)

The speech models (Qwen3-TTS, OmniVoice, Fish Drama 3, Fish S2 Pro, Breeze TTS 2 on the Mac; OmniVoice, Qwen3-TTS and Drama 3 on the Windows template) get one shared page, as Decide does for decision models and Chat does for text models: one sidenav entry under Speech, a dropdown over the running speech models, and a form built from the chosen model. Other generators (pictures, video, music) follow later, once this has settled.

## How the models differ today

| Model | Voice sources | Direction (emotion) |
| --- | --- | --- |
| Qwen3-TTS | built-in names, described, cloned | free-text "How to say it" (not in clone mode) |
| OmniVoice | described (gender, age, pitch, accent, whisper), cloned | none (speed and whisper only) |
| Fish Drama 3 | model's own, cloned; multi-voice scenes | inline cues in the text, `[whispers]` |
| Fish S2 Pro | model's own, cloned | inline cues in the text, `[whisper]` (other spellings than Drama 3) |
| Breeze TTS 2 | described, cloned | the voice description; an advanced "Direction" field when cloning |

## Design

1. **Roles on the existing fields.** Each speech field is tagged with a role (text, language, voice sample, sample transcript, voice description, built-in voice, direction, speed, seed). Workers and the stored job format do not change, so old results and "Use these settings" keep working.
2. **Capabilities per model.** Each plugin declares which voice sources it offers (built-in, described, cloned, model's own; cloning is optional, not assumed), whether it has scenes, its languages, and how it takes direction: `style_field`, `inline_cues` (with its own cue list and examples), `voice_description` or `none`. The page hides what a model lacks.
3. **Voice selector** (Built-in, Describe, Clone, Model's choice) maps to each model's own modes. Scenes show only for a model that has them.
4. **Direction guidance** adapts to the loaded model: a style box with examples, cue chips that insert at the cursor, or a note that the model cannot act emotions and which ones can.
5. **Switching models** carries over text, language, seed and a sample with its transcript; style, cues and OmniVoice's attributes do not. The page says what was dropped. Cues typed for one model are read aloud by a model without cues, so switching warns and offers "Remove cues"; Fish S2 and Drama 3 cue names are mapped.
6. **Voice library** (in scope): saved voices, each with a name, the sample and its transcript, kept by the app on the host (`<runtime_dir>/voices/`). A voice can be picked on the Speech page for any model that clones, saved from a result's sample, and renamed or deleted. The transcript is read from the sample when the ASR model is configured. A note beside the sample field: only clone voices you have permission to use.
7. **Licences.** Each option in the dropdown carries its licence badge (OmniVoice, Fish S2 and Breeze are personal use only, Drama 3 has a revenue cap), and a work-only filter hides the rest.
8. **Chat and assistant.** The dozen per-model speech tools become one `speak` tool whose description carries the loaded model's direction guidance; the assistant guide is generated from the same capabilities.
9. **No redirects.** Old per-model addresses are not kept; in-app links use `modelRoute`.

## Later

- An OpenAI-style `POST /v1/audio/speech` on each speech worker's own port (not a proxy; like `/v1/systemone` for Decide), taking `{input, voice, instructions}`. Needs the voice library readable from the worker.
- Pictures, video and music pages on the same pattern.

## Checks

Fixture tests for the form logic (capabilities, switching, cue handling, library). Audio is checked by listening: five spot checks on the Mac, one per model.
