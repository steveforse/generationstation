"""OmniVoice speech worker for Apple silicon, through mlx-audio (mlx-community/OmniVoice-bf16; the model is
CC BY-NC, so non-commercial use only). Runs in the mlx-audio environment. Same inputs as the NVIDIA worker.

Config options (from runtimes.json, per preset):
    model_dir   The mlx-community/OmniVoice-bf16 folder.
    asr_dir     Optional Qwen3-ASR folder, used to write down a voice sample when no transcript is given.

Inputs: mode ("clone" | "design"), prompt, sample ([{"path"}], clone), sample_text (clone, optional), design traits
    gender / age / pitch / accent and whisper, language, quality, seed. The `speed` input is ignored: the MLX model has no speed control, only a total duration.
"""
import os
import random
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from gs_worker import serve
from mlx_runtime import MLXThread, transcribe, write_wav
from omnivoice_worker import STEPS, voice_description  # the NVIDIA worker's own trait and quality mapping


def load(config, log=print):
    from mlx_audio.tts.utils import load_model

    options = config["options"]
    thread = MLXThread()
    started = time.perf_counter()
    model = thread.call(lambda: load_model(options["model_dir"]))
    log(f"[worker] OmniVoice ready in {time.perf_counter() - started:.1f} s")
    return {"model": model, "thread": thread, "options": options}


def speak(state, inputs, job, seed):
    import mlx.core as mx
    import numpy as np

    mode = inputs.get("mode") or "design"
    kwargs = {"text": inputs["prompt"], "num_steps": STEPS.get(inputs.get("quality") or "standard", 32)}
    language = (inputs.get("language") or "").strip()
    if language:
        kwargs["language"] = language
    if mode == "clone":
        sample = inputs["sample"][0]["path"]
        transcript = (inputs.get("sample_text") or "").strip()
        if not transcript and state["options"].get("asr_dir"):
            job.report("Listening to the voice sample and writing down what it says")
            transcript = transcribe(state["options"]["asr_dir"], sample)
        job.report("Listening to the voice sample")
        kwargs.update(ref_audio=sample, **({"ref_text": transcript} if transcript else {}))
    else:
        voice = voice_description(inputs)
        if voice:
            kwargs["instruct"] = voice
    job.report("Speaking")
    mx.random.seed(seed)
    pieces, rate = [], 24000
    for part in state["model"].generate(**kwargs):
        audio = np.array(part.audio)
        pieces.append(audio)
        rate = part.sample_rate or rate
        if job.cancel_requested:
            raise InterruptedError("cancelled")
    if not pieces:
        raise RuntimeError("The model produced no audio.")
    audio = np.concatenate(pieces)
    return audio, rate, kwargs


def generate(state, inputs, job):
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    audio, rate, kwargs = state["thread"].call(lambda: speak(state, inputs, job, seed))
    write_wav(job.output(f"speech-{seed}.wav", "audio/wav"), audio, rate)
    job.detail(seed=seed, mode=inputs.get("mode") or "design", steps=kwargs["num_steps"],
               audio_seconds=round(len(audio) / rate, 1), language=kwargs.get("language") or "automatic",
               voice=kwargs.get("instruct"))
    job.report(f"Done: {len(audio) / rate:.0f} seconds of speech, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
