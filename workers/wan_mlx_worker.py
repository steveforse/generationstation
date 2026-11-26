"""Wan 2.2 TI2V 5B video worker for Apple silicon, through Blaizzy/mlx-video (MLX). Runs in the mlx-video environment.

Each clip is one `mlx_video.models.wan_2.generate` process with an MLX memory limit, so nothing stays resident between
clips. On an M5 Max a 33-frame (1.4 s) 832x480 clip took about 100 s at a 29 GiB peak. Longer clips need much more
memory (81 frames peaked at 61 GiB) and are not offered.

Config options (from runtimes.json, per preset):
    model_dir          mlx-video's converted Wan2.2-TI2V-5B folder (`convert --quantize --bits 8`).
    memory_limit_gib   MLX memory limit for the process (default 26).
    steps              Denoising steps (default 20).
    tiling             VAE tiling: "none" (default, fastest) | "auto" | "aggressive".
Inputs: prompt, image ([{"path"}], optional: the first frame), shape ("landscape" | "portrait" | "square"),
    length ("short" | "very short"), negative_prompt, seed.
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

SHAPES = {"landscape": (832, 480), "portrait": (480, 832), "square": (640, 640)}
FRAMES = {"short": 33, "very short": 17}  # 4n+1; 24 frames per second
FPS = 24
ANSI = re.compile(rb"\x1b\[[0-9;]*m")
STEP = re.compile(rb"Diffusion:[^\n\r]*?(\d+)/(\d+)")
STAGES = ((b"Loading T5", "Reading the description"), (b"Encoding input image", "Preparing the first frame"),
          (b"Loading transformer", "Loading the video model"), (b"Decoding with VAE", "Decoding the video"))
LAUNCH = ("import sys, mlx.core as mx; mx.set_memory_limit(int(float(sys.argv[1]) * 2**30)); "
          "mx.set_cache_limit(2 * 2**30); sys.argv = sys.argv[1:]; sys.argv[0] = 'wan'; "
          "from mlx_video.models.wan_2.generate import main; main()")


def load(config):
    options = config["options"]
    model_dir = Path(options["model_dir"])
    if not (model_dir / "config.json").is_file():
        raise FileNotFoundError(f"No converted Wan model in {model_dir}")
    return {"model_dir": str(model_dir), "limit": float(options.get("memory_limit_gib", 26)),
            "steps": int(options.get("steps", 20)), "tiling": options.get("tiling", "none")}


def generate(model, inputs, job):
    from PIL import Image

    width, height = SHAPES[inputs.get("shape") or "landscape"]
    frames = FRAMES[inputs.get("length") or "short"]
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    out = job.output(f"video-{seed}.mp4", "video/mp4")
    command = [sys.executable, "-c", LAUNCH, str(model["limit"]), "--model-dir", model["model_dir"],
               "--prompt", inputs["prompt"], "--width", str(width), "--height", str(height),
               "--num-frames", str(frames), "--steps", str(model["steps"]), "--seed", str(seed),
               "--tiling", model["tiling"], "--output-path", str(out)]
    negative = (inputs.get("negative_prompt") or "").strip()
    if negative:
        command += ["--negative-prompt", negative]
    image = (inputs.get("image") or [None])[0]
    if image:
        command += ["--image", image["path"]]
    job.report("Starting")
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
            if job.cancel_requested:
                break
        if job.cancel_requested:
            job.report("Cancelling")  # raises JobCancelled
        if process.wait() != 0 or not out.exists():
            lines = tail.decode(errors="replace").strip().splitlines()
            raise RuntimeError("Wan failed: " + (lines[-1][:300] if lines else "no output"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    thumb = out.with_suffix(".frame.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-frames:v", "1", str(thumb)], check=False)
    if thumb.exists():
        job.thumbnail(Image.open(thumb), size=1024)
        thumb.unlink()
    job.detail(seed=seed, width=width, height=height, frames=frames, seconds_of_video=round(frames / FPS, 1),
               steps=model["steps"], mode="image" if image else "text")
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
