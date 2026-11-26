"""ACE-Step 1.5 song worker for Apple silicon (MIT code and weights), native MLX. Runs in the ace-step environment.

A 1.7B language model plans the song (structure, tempo, key) and a turbo diffusion model with a VAE makes the audio:
about 8 s for 30 s of music on an M5 Max, about 14 GiB resident and 21 GiB MLX peak for two minutes.

Config options (from runtimes.json, per preset):
    repo_dir   The ACE-Step-1.5 checkout; its checkpoints/ folder holds the models.
    dit        The diffusion model folder name inside checkpoints/ (default "acestep-v15-turbo").
    lm         The language model folder name inside checkpoints/ (default "acestep-5Hz-lm-1.7B").
    steps      Diffusion steps (default 8, the turbo schedule).
Inputs: style (the caption), lyrics (empty makes an instrumental), language, length (seconds), seed.
"""
import os
import random
import sys
import time
from pathlib import Path

os.environ["ACESTEP_LM_BACKEND"] = "mlx"
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from gs_worker import JobCancelled, serve
from mlx_runtime import MLXThread


def load(config):
    options = config["options"]
    root = str(Path(options["repo_dir"]))
    sys.path.insert(0, root)
    thread = MLXThread()

    def build():
        from acestep.handler import AceStepHandler
        from acestep.llm_inference import LLMHandler

        dit = AceStepHandler()
        message, ok = dit.initialize_service(project_root=root, config_path=options.get("dit", "acestep-v15-turbo"),
                                             device="auto", offload_to_cpu=False)
        if not ok:
            raise RuntimeError(f"ACE-Step diffusion model failed to load: {message}")
        lm = LLMHandler()
        message, ok = lm.initialize(checkpoint_dir=root + "/checkpoints", lm_model_path=options.get("lm", "acestep-5Hz-lm-1.7B"),
                                    backend="mlx", device="auto", offload_to_cpu=False, dtype=None)
        if not ok:
            raise RuntimeError(f"ACE-Step language model failed to load: {message}")
        return dit, lm

    dit, lm = thread.call(build)
    return {"dit": dit, "lm": lm, "thread": thread, "steps": int(options.get("steps", 8)), "dir": Path(config["output_dir"])}


def compose(model, inputs, job, seed, folder):
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    lyrics = (inputs.get("lyrics") or "").strip()

    def progress(value=None, desc=None, **_):
        if job.cancel_requested:
            raise JobCancelled()
        if desc:
            job.progress = str(desc)[:200]

    params = GenerationParams(task_type="text2music", thinking=True, caption=inputs["style"], lyrics=lyrics or "[Instrumental]",
                              instrumental=not lyrics, duration=float(inputs.get("length") or 60),
                              vocal_language=inputs.get("language") or "en", inference_steps=model["steps"],
                              guidance_scale=1.0, seed=seed)
    result = generate_music(model["dit"], model["lm"], params=params, config=GenerationConfig(batch_size=1, audio_format="wav"),
                            save_dir=str(folder), progress=progress)
    if job.cancel_requested:
        raise JobCancelled()
    if not result.success or not result.audios:
        raise RuntimeError(f"ACE-Step did not make a song: {(result.status_message or '')[:300]}")
    return result.audios[0]["path"]


def generate(model, inputs, job):
    import soundfile as sf

    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    started = time.perf_counter()
    folder = Path(job.dir) / "work"
    folder.mkdir(parents=True, exist_ok=True)
    job.report("Planning the song")
    try:
        path = model["thread"].call(lambda: compose(model, inputs, job, seed, folder))
        audio, rate = sf.read(path)
        sf.write(job.output("song.flac", "audio/flac"), audio, rate, subtype="PCM_24")
    finally:
        for leftover in folder.glob("*"):
            leftover.unlink(missing_ok=True)
        folder.rmdir()
    seconds = len(audio) / rate
    job.detail(seed=seed, audio_seconds=round(seconds, 1), instrumental=not (inputs.get("lyrics") or "").strip(),
               language=inputs.get("language") or "en", steps=model["steps"])
    job.report(f"Done: {seconds:.0f} seconds of music in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
