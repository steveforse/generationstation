"""Fish Audio S2 Pro speech worker for Apple silicon, through mlx-audio (mlx-community/fish-audio-s2-pro-8bit).
Runs in the mlx-audio environment. Fish Audio Research License: research, personal and evaluation use only; a
company's own use needs a separate licence from Fish Audio.

Config options (from runtimes.json, per preset):
    model_dir   The mlx-community/fish-audio-s2-pro-8bit folder.
    asr_dir     Optional Qwen3-ASR folder, to write down a voice sample when no transcript is given.
Inputs: prompt (with [cue] tags), sample ([{"path"}], optional), sample_text (optional), seed.
"""
import os
import random
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from gs_worker import serve
from mlx_runtime import MLXThread, transcribe, write_wav


def load(config, log=print):
    from mlx_audio.tts.utils import load_model

    options = config["options"]
    thread = MLXThread()
    started = time.perf_counter()
    model = thread.call(lambda: load_model(options["model_dir"]))
    log(f"[worker] S2 Pro ready in {time.perf_counter() - started:.1f} s")
    return {"model": model, "thread": thread, "options": options}


def speak(state, inputs, job, seed):
    import mlx.core as mx
    import numpy as np
    from mlx_audio.utils import load_audio

    model = state["model"]
    kwargs = {"text": inputs["prompt"], "verbose": False}
    sample = (inputs.get("sample") or [None])[0]
    if sample:
        transcript = (inputs.get("sample_text") or "").strip()
        if not transcript:
            if not state["options"].get("asr_dir"):
                raise ValueError("Type what is said in the voice sample (no transcriber is set up).")
            job.report("Listening to the voice sample and writing down what it says")
            transcript = transcribe(state["options"]["asr_dir"], sample["path"])
        kwargs.update(ref_audio=load_audio(sample["path"], sample_rate=model.sample_rate), ref_text=transcript)
    job.report("Speaking")
    mx.random.seed(seed)
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
    job.detail(seed=seed, mode="speak", audio_seconds=round(len(audio) / rate, 1),
               voice="cloned from the sample" if inputs.get("sample") else "chosen by the model")
    job.report(f"Done: {len(audio) / rate:.0f} seconds of speech, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
