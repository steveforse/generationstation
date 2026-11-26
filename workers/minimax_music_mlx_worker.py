"""MiniMax Music 3 song worker for Apple silicon, through mlx-audio (mlx-community/MiniMax-Music3-mxfp8). Runs in the
mlx-audio environment. MiniMax-Music3 Community License: free to use, but a commercial product must display
"MiniMax-Music3" on its interface, and the revenue such products and services generate above US$20 million a year
needs MiniMax's written authorisation.

Config options (from runtimes.json, per preset):
    model_dir   The mlx-community/MiniMax-Music3-mxfp8 folder (about 13 GB).
Inputs: style (the caption), lyrics (empty makes an instrumental), length (seconds, a maximum), seed.
"""
import os
import random
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from gs_worker import serve
from mlx_runtime import MLXThread


def load(config):
    from mlx_audio.music.utils import load_model

    thread = MLXThread()
    started = time.perf_counter()
    model = thread.call(lambda: load_model(config["options"]["model_dir"]))
    print(f"[worker] MiniMax Music 3 ready in {time.perf_counter() - started:.1f} s", flush=True)
    return {"model": model, "thread": thread}


def compose(model, inputs, job, seed):
    import mlx.core as mx
    import numpy as np

    kwargs = {"text": inputs["style"], "seed": seed, "duration": float(inputs.get("length") or 60)}
    # The model refuses an empty lyric; it wants the marker spelled out for a piece without singing.
    kwargs["lyrics"] = (inputs.get("lyrics") or "").strip() or "[instrumental]"
    job.report("Composing the song")
    pieces, rate = [], None
    for part in model["model"].generate(**kwargs):
        pieces.append(np.array(part.audio))
        rate = part.sample_rate
        if job.cancel_requested:
            raise InterruptedError("cancelled")
    mx.clear_cache()
    if not pieces or rate is None:
        raise RuntimeError("The model produced no audio.")
    return np.concatenate(pieces, axis=0), rate


def generate(model, inputs, job):
    import soundfile as sf

    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    started = time.perf_counter()
    audio, rate = model["thread"].call(lambda: compose(model, inputs, job, seed))
    job.report("Saving")
    sf.write(job.output("song.flac", "audio/flac"), audio, rate, subtype="PCM_24")
    seconds = len(audio) / rate
    job.detail(seed=seed, audio_seconds=round(seconds, 1), instrumental=not (inputs.get("lyrics") or "").strip())
    job.report(f"Done: {seconds:.0f} seconds of music in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
