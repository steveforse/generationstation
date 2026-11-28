"""FastMetal-QAD video worker for Apple silicon (distilled Wan 2.1/2.2 in INT8, 3 denoise steps), through FastVideo's MLX
scripts. Runs in the fastmetal environment.

Each clip is one FastVideo script process, started from the FastVideo checkout (the scripts import `examples.inference...`
from the repository root), so nothing stays resident between clips. On an M5 Max, 81 frames: 5B at 1280x704 72 s (9.6 GiB
MLX peak), 14B at 832x480 338 s (21.7 GiB). A new description runs the text encoder first (a few seconds, up to 24 GiB
resident for a moment); the encoded prompt is cached, so the same description again skips it.

Config options (from runtimes.json, per preset):
    model_dir    The FastMetal folder (mlx_dit.safetensors, text_encoder/, tokenizer/, vae/).
    repo_dir     The FastVideo checkout (~/ai/src/FastVideo).
    family       "wan22" (the 5B: mlx_wan22_generate.py) or "t2v" (the 1.3B and 14B: mlx_wan_prompt_to_video.py).
    memory_limit_gib   MLX limit for the "t2v" family (default 26).
Inputs: prompt, shape ("landscape" | "portrait"), length ("short" | "medium" | "long"), speed ("full" | "fast"), seed.
"""
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")

from gs_worker import serve

# (width, height, frames per length, fps). Heights and widths are multiples of 16; frames are 4n+1.
FAMILIES = {
    "wan22": {"landscape": (1280, 704), "portrait": (704, 1280), "frames": {"short": 49, "medium": 81, "long": 121}, "fps": 24,
              "script": "examples/inference/basic/mlx_wan22_generate.py"},
    "t2v": {"landscape": (832, 480), "portrait": (480, 832), "frames": {"short": 33, "medium": 49, "long": 81}, "fps": 16,
            "script": "examples/inference/basic/mlx_wan_prompt_to_video.py"},
}
ANSI = re.compile(rb"\x1b\[[0-9;]*m")
STEP = re.compile(rb"denoise step (\d+)/(\d+) complete")
STAGES = ((b"prompt encoded", "Loading the video model"), (b"Prompt encode time", "Painting the clip"), (b"DiT loaded", "Painting the clip"),
          (b"Loading weights", "Reading the description"), (b"decoded via", "Finishing the clip"), (b"[post] RIFE", "Filling in frames"),
          (b"RIFE 2x", "Filling in frames"))


def load(config):
    options = config["options"]
    family = options.get("family", "t2v")
    if family not in FAMILIES:
        raise ValueError(f"Unknown FastMetal family {family!r}")
    model_dir, repo_dir = Path(options["model_dir"]), Path(options["repo_dir"])
    if not (model_dir / "mlx_dit.safetensors").is_file():
        raise FileNotFoundError(f"No FastMetal weights in {model_dir}")
    script = repo_dir / FAMILIES[family]["script"]
    if not script.is_file():
        raise FileNotFoundError(f"No FastVideo script {script}")
    return {"model_dir": str(model_dir), "repo_dir": str(repo_dir), "family": family, "limit": float(options.get("memory_limit_gib", 26))}


def generate(model, inputs, job):
    from PIL import Image

    spec = FAMILIES[model["family"]]
    width, height = spec[inputs.get("shape") or "landscape"]
    frames = spec["frames"][inputs.get("length") or "medium"]
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    out = job.output(f"video-{seed}.mp4", "video/mp4")
    base = [sys.executable, spec["script"], "--height", str(height), "--width", str(width), "--num-frames", str(frames),
            "--prompt", inputs["prompt"], "--seed", str(seed), "--fps", str(spec["fps"]), "--output-path", str(out)]
    if model["family"] == "wan22":
        command = base + ["--mlx-checkpoint", model["model_dir"], "--text-encoder-root", model["model_dir"], "--vae-root", str(Path(model["model_dir"]) / "vae")]
    else:
        command = base + ["--model-root", model["model_dir"], "--mlx-checkpoint", model["model_dir"], "--mlx-memory-limit-gib", str(model["limit"])]
    if inputs.get("speed") == "fast":
        command.append("--fast")
    env = dict(os.environ, PYTHONPATH=model["repo_dir"], HF_HUB_OFFLINE="1", PYTHONUNBUFFERED="1")
    job.report("Starting")
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=model["repo_dir"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail = b""
    try:
        while True:
            chunk = process.stdout.read1(4096)
            if not chunk:
                break
            tail = ANSI.sub(b"", (tail + chunk))[-6000:]
            steps = STEP.findall(tail[-400:])
            if steps:
                done, total = (int(n) for n in steps[-1])
                job.report(f"Painting, step {done} of {total}")
            else:
                for marker, text in STAGES:
                    if marker in chunk:
                        job.report(text)
                        break
            if job.cancel_requested:
                break
        if job.cancel_requested:
            job.report("Cancelling")  # raises JobCancelled
        if process.wait() != 0 or not out.exists():
            lines = tail.decode(errors="replace").strip().splitlines()
            raise RuntimeError("FastMetal failed: " + (lines[-1][:300] if lines else "no output"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    thumb = out.with_suffix(".frame.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-frames:v", "1", str(thumb)], check=False)
    if thumb.exists():
        job.thumbnail(Image.open(thumb), size=1024)
        thumb.unlink()
    job.detail(seed=seed, width=width, height=height, frames=frames, seconds_of_video=round(frames / spec["fps"], 1),
               speed=inputs.get("speed") or "full", model=model["family"])
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
