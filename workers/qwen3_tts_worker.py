"""Qwen3-TTS speech worker (QwenLM/Qwen3-TTS, Apache 2.0): built-in voices directed by instructions, voices
designed from a description, and voice cloning from a short sample. Runs in its own environment (the `qwen-tts`
package pins transformers 4.57.3).

Config options (from runtimes.json, per preset):
    custom_voice_dir  Qwen3-TTS-12Hz-1.7B-CustomVoice folder (the 9 built-in voices).
    voice_design_dir  Qwen3-TTS-12Hz-1.7B-VoiceDesign folder.
    base_dir          Qwen3-TTS-12Hz-1.7B-Base folder (cloning).

Each tab uses its own model; only the one in use is kept on the card (the others wait in system RAM).
Inputs: mode ("builtin" | "design" | "clone"), prompt (the text to speak), language ("auto" or one of the 10),
    builtin: speaker, style (optional instruction); design: voice (description), style (optional);
    clone: sample ([{"path", ...}]), sample_text (optional); seed.
"""
import os
import random
import time

from gs_worker import serve

os.environ.setdefault("HF_HUB_OFFLINE", "1")

MODEL_OF = {"builtin": "custom_voice_dir", "design": "voice_design_dir", "clone": "base_dir"}


def _activate(state, mode, log=print):
    """Put the mode's model on the card, moving the previous one to system RAM (loading it the first time)."""
    torch = state["torch"]
    key = MODEL_OF[mode]
    if state["active"] == key:
        return state["models"][key]
    if state["active"] is not None:
        state["models"][state["active"]].model.to("cpu")
        torch.cuda.empty_cache()
    started = time.perf_counter()
    if key not in state["models"]:
        from qwen_tts import Qwen3TTSModel
        state["models"][key] = Qwen3TTSModel.from_pretrained(state["options"][key], device_map="cuda:0",
                                                             dtype=torch.bfloat16)
    else:
        state["models"][key].model.to("cuda:0")
    state["active"] = key
    log(f"[worker] {key} on the card in {time.perf_counter() - started:.1f} s, "
        f"{torch.cuda.memory_allocated() / 2**30:.1f} GiB in use")
    return state["models"][key]


def load(config, log=print):
    import torch

    state = {"torch": torch, "options": config["options"], "models": {}, "active": None}
    _activate(state, "builtin", log)  # the default tab; the others load the first time they are used
    return state


def generate(state, inputs, job):
    import soundfile as sf

    torch = state["torch"]
    mode = inputs.get("mode") or "builtin"
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    language = inputs.get("language") or "auto"
    language = "Auto" if language == "auto" else language.capitalize()
    style = (inputs.get("style") or "").strip()
    job.report("Getting the voice ready")
    model = _activate(state, mode)
    job.report("Speaking")
    torch.manual_seed(seed)
    try:
        if mode == "builtin":
            wavs, rate = model.generate_custom_voice(text=inputs["prompt"], language=language,
                                                     speaker=inputs.get("speaker") or "Ryan", instruct=style or None)
        elif mode == "design":
            description = inputs["voice"].strip() + (f" {style}" if style else "")
            wavs, rate = model.generate_voice_design(text=inputs["prompt"], language=language, instruct=description)
        else:
            transcript = (inputs.get("sample_text") or "").strip()
            prompt = model.create_voice_clone_prompt(ref_audio=inputs["sample"][0]["path"], ref_text=transcript or None,
                                                     x_vector_only_mode=not transcript)
            wavs, rate = model.generate_voice_clone(text=inputs["prompt"], language=language, voice_clone_prompt=prompt)
    finally:
        torch.cuda.empty_cache()
    audio = wavs[0]
    path = job.output(f"speech-{seed}.wav", "audio/wav")
    sf.write(str(path), audio, rate)
    job.detail(seed=seed, mode=mode, language=language, audio_seconds=round(len(audio) / rate, 1),
               speaker=inputs.get("speaker") if mode == "builtin" else None, style=style or None,
               cloned_without_transcript=(mode == "clone" and not (inputs.get("sample_text") or "").strip()))
    job.report(f"Done: {len(audio) / rate:.0f} seconds of speech, seed {seed}")


def cleanup(state):
    state["torch"].cuda.empty_cache()


if __name__ == "__main__":
    serve(load, generate, cleanup=cleanup)
