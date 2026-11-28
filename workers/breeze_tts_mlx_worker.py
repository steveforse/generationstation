"""Breeze TTS 2 (BreezeBlue) speech worker for Apple silicon, through mlx-audio (mlx-community/Breeze-TTS-2-mlx-8bit).
Runs in the mlx-audio environment. BreezeBlue Research and Non-Commercial License: research and personal use only,
no use for a company's operations.

Config options (from runtimes.json, per preset):
    model_dir   The mlx-community/Breeze-TTS-2-mlx-8bit folder.
    asr_dir     Optional Qwen3-ASR folder, to write down a voice sample (the clone needs its exact words).
Inputs: mode ("design" | "clone"), prompt, voice (design: the description; clone: an optional direction),
    sample ([{"path"}], clone), sample_text (clone, optional), seed.
"""
import os
import random
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from gs_worker import serve
from mlx_runtime import MLXThread, transcribe, write_wav

CFG_SCALE = 4


def load(config, log=print):
    from mlx_audio.tts.utils import load_model

    options = config["options"]
    thread = MLXThread()
    started = time.perf_counter()
    model = thread.call(lambda: load_model(options["model_dir"]))
    log(f"[worker] Breeze TTS 2 ready in {time.perf_counter() - started:.1f} s")
    return {"model": model, "thread": thread, "options": options}


def speak(state, inputs, job, seed):
    import numpy as np

    model = state["model"]
    mode = inputs.get("mode") or "design"
    kwargs = {"text": inputs["prompt"], "seed": seed, "cfg_scale": CFG_SCALE}
    voice = (inputs.get("voice") or "").strip()
    if voice:
        kwargs["instruct"] = voice
    if mode == "clone":
        sample = inputs["sample"][0]["path"]
        transcript = (inputs.get("sample_text") or "").strip()
        if not transcript:
            if not state["options"].get("asr_dir"):
                raise ValueError("Type what is said in the voice sample (no transcriber is set up).")
            job.report("Listening to the voice sample and writing down what it says")
            transcript = transcribe(state["options"]["asr_dir"], sample)
        kwargs.update(ref_audio=sample, ref_text=transcript)
    job.report("Speaking")
    pieces = []
    for part in model.generate(**kwargs):
        pieces.append(np.array(part.audio))
        if job.cancel_requested:
            raise InterruptedError("cancelled")
    if not pieces:
        raise RuntimeError("The model produced no audio.")
    return np.concatenate(pieces), model.sample_rate


def generate(state, inputs, job):
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    audio, rate = state["thread"].call(lambda: speak(state, inputs, job, seed))
    write_wav(job.output(f"speech-{seed}.wav", "audio/wav"), audio, rate)
    job.detail(seed=seed, mode=inputs.get("mode") or "design", audio_seconds=round(len(audio) / rate, 1),
               voice=(inputs.get("voice") or "").strip() or None)
    job.report(f"Done: {len(audio) / rate:.0f} seconds of speech, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
