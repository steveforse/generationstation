"""Qwen3-TTS speech worker for Apple silicon, through mlx-audio (MLX conversions of QwenLM/Qwen3-TTS, Apache 2.0).
Runs in the mlx-audio environment. Same inputs as the NVIDIA worker.

Config options (from runtimes.json, per preset):
    custom_voice_dir  mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit folder (the 9 built-in voices).
    voice_design_dir  mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-8bit folder.
    base_dir          mlx-community/Qwen3-TTS-12Hz-1.7B-Base-8bit folder (cloning).
    asr_dir           Optional Qwen3-ASR folder, used to write down a voice sample when no transcript is given
                      (the MLX model needs the words spoken in the sample).

Each tab uses its own model (about 3 GiB); only the one in use is kept.
Inputs: mode ("builtin" | "design" | "clone"), prompt, language ("auto" or one of the 10), builtin: speaker, style;
    design: voice, style; clone: sample ([{"path"}]), sample_text (optional); seed.
"""
import os
import random
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from gs_worker import serve
from mlx_runtime import MLXThread, transcribe, write_wav

MODEL_OF = {"builtin": "custom_voice_dir", "design": "voice_design_dir", "clone": "base_dir"}


def load(config, log=print):
    return {"options": config["options"], "thread": MLXThread(), "model": None, "key": None, "log": log}


def _activate(state, mode):
    from mlx_audio.tts.utils import load_model

    import mlx.core as mx

    key = MODEL_OF[mode]
    if state["key"] != key:
        state["model"] = None
        mx.clear_cache()
        started = time.perf_counter()
        state["model"], state["key"] = load_model(state["options"][key]), key
        state["log"](f"[worker] {key} loaded in {time.perf_counter() - started:.1f} s")
    return state["model"]


def speak(state, inputs, job, seed):
    import mlx.core as mx
    import numpy as np

    mode = inputs.get("mode") or "builtin"
    language = (inputs.get("language") or "auto").lower()
    style = (inputs.get("style") or "").strip()
    job.report("Getting the voice ready")
    model = _activate(state, mode)
    mx.random.seed(seed)
    if mode == "builtin":
        parts = model.generate_custom_voice(text=inputs["prompt"], speaker=inputs.get("speaker") or "Ryan",
                                            language=language, instruct=style or None)
    elif mode == "design":
        description = inputs["voice"].strip() + (f" {style}" if style else "")
        parts = model.generate_voice_design(text=inputs["prompt"], instruct=description, language=language)
    else:
        sample = inputs["sample"][0]["path"]
        transcript = (inputs.get("sample_text") or "").strip()
        if not transcript:
            if not state["options"].get("asr_dir"):
                raise ValueError("Type what is said in the voice sample (no transcriber is set up).")
            job.report("Listening to the voice sample and writing down what it says")
            transcript = transcribe(state["options"]["asr_dir"], sample)
            model = _activate(state, mode)  # transcribing loaded another model
        parts = model.generate(text=inputs["prompt"], ref_audio=sample, ref_text=transcript, lang_code=language)
    job.report("Speaking")
    pieces, rate = [], None
    for part in parts:
        pieces.append(np.array(part.audio))
        rate = part.sample_rate
        if job.cancel_requested:
            raise InterruptedError("cancelled")
    if not pieces:
        raise RuntimeError("The model produced no audio.")
    return np.concatenate(pieces), rate


def generate(state, inputs, job):
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    audio, rate = state["thread"].call(lambda: speak(state, inputs, job, seed))
    mode = inputs.get("mode") or "builtin"
    write_wav(job.output(f"speech-{seed}.wav", "audio/wav"), audio, rate)
    job.detail(seed=seed, mode=mode, language=(inputs.get("language") or "auto"), audio_seconds=round(len(audio) / rate, 1),
               speaker=inputs.get("speaker") if mode == "builtin" else None, style=(inputs.get("style") or "").strip() or None)
    job.report(f"Done: {len(audio) / rate:.0f} seconds of speech, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
