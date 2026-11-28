"""YuE2 song worker for Apple silicon, through the MLX port (mlx-Yue, the `lyra` package). Runs in its environment.

Config options (from runtimes.json, per preset): model_dir (the converted MLX model folder), vae_dir (the decoder),
    precision ("8bit" by default: the language model in 8 bits and the audio model in bf16; or "bf16", "4bit").
    memory_budget_gib (default 16): the port stops a song that would exceed it.
Inputs: style, lyrics, mode ("full", "melody", "off"), seed, and optionally source (a song: [{"path"}]). With a source the song is a
new version of it: the melody and structure are read from the recording by SheetSage2 and MERT2 (about 2.8 GB, the `transcription`
extras of mlx-Yue) and sung again with the new style and lyrics; "off" has no score to follow, so it is not allowed then.
"""
import gc
import os
import random
import shutil
import time

os.environ.setdefault("MLX_ENABLE_TF32", "0")  # the port's documented setting; keeps results repeatable

from gs_worker import serve
from mlx_runtime import MLXThread

TOKENS_PER_SECOND = 25  # one semantic token per 40 ms of audio


# Blank lyrics do not make an instrumental (the model then invents words and sings them). Sections that name no singing do.
INSTRUMENTAL = "[Intro: Instrumental]\n\n[Instrumental Break]\n\n[Outro: Instrumental]"

def load(config):
    from lyra.pipeline import YuE2Pipeline

    options = config["options"]
    thread = MLXThread()

    def build():
        pipe = YuE2Pipeline.from_pretrained(
            options["model_dir"], vae=options["vae_dir"], precision=options.get("precision", "8bit"),
            local_files_only=True, memory_budget_gib=options.get("memory_budget_gib", 16), progress=False)
        pipe._load_model()  # "loaded" should mean ready to sing, not loading on the first song
        return pipe

    return {"pipe": thread.call(build), "thread": thread}


def generate(model, inputs, job):
    model["thread"].call(lambda: sing(model["pipe"], inputs, job))


def read_score(source, planning, job, cancelled):
    """The melody and structure of a recording as ABC notation, ready to be sung again (a new version of the song)."""
    import mlx.core as mx
    from lyra.transcription.pipeline import transcribe

    folder = job.dir / "work"
    try:
        job.report("Reading the melody of the song")
        result = transcribe(source, folder / "transcription", offline=True, task="full" if planning == "full" else "melody-full", cancelled=cancelled)
        if result["status"] != "complete" or result["truncated"]:
            raise RuntimeError("The melody of that song could not be read completely. Try a shorter or cleaner recording.")
        return (folder / "transcription" / "score.abc").read_bytes().decode("utf-8")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        gc.collect()
        mx.clear_cache()  # the transcription models are not kept: the song model keeps the memory


def sing(pipe, inputs, job):
    import numpy as np
    from yue2.protocol import SongRequest

    seed = inputs.get("seed")
    cancelled = lambda: job.cancel_requested  # noqa: E731 - the library raises InterruptedError; serve() reports it as a cancel
    planning = inputs.get("mode") or "full"
    source = (inputs.get("source") or [{}])[0].get("path")
    score = read_score(source, planning, job, cancelled) if source else None
    request = SongRequest(style=inputs["style"], lyrics=inputs.get("lyrics") or INSTRUMENTAL, cot=planning,
                          seed=seed if isinstance(seed, int) else random.randrange(1, 2**31),
                          cfg_scale=inputs.get("cfg_scale"), abc=score, id="song")
    started = time.perf_counter()
    counts = {"abc": 0, "semantic": 0}

    def token(phase, _token):
        counts[phase] += 1
        if counts[phase] % 25 == 0:
            if phase == "abc":
                job.report("Writing the melody")
            else:
                job.report(f"Composing the song, {counts[phase] / TOKENS_PER_SECOND:.0f} s so far")

    job.report("Writing the melody")
    plan = pipe.plan(request=request, cancelled=cancelled, on_token=token)
    job.report("Composing the song")
    semantic = pipe.generate_semantic(plan, cancelled=cancelled, on_token=token)
    job.report("Rendering the instruments and voice")
    latents = pipe.synthesize(semantic, cancelled=cancelled)
    job.report("Mixing the audio")
    audio = np.asarray(pipe.decode(latents, cancelled=cancelled))
    job.report("Saving")

    import soundfile as sf
    sf.write(job.output("song.flac", "audio/flac"), audio, 48000, subtype="PCM_24")
    if plan.abc:
        job.output("melody.abc", "text/plain").write_text(plan.abc, encoding="utf-8")
    seconds = len(audio) / 48000
    job.detail(seed=request.seed, mode=request.cot, audio_seconds=round(seconds, 1), **({"from_song": True} if source else {}))
    job.report(f"Done: {seconds:.0f} seconds of music in {time.perf_counter() - started:.0f} s, seed {request.seed}")


if __name__ == "__main__":
    serve(load, generate)
