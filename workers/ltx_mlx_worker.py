"""LTX-2.5 video worker for Apple silicon (4-bit distilled pack), through the ltx-2-mlx fork. Runs in the ltx25 environment.

Each clip is one `ltx-2-mlx generate --distilled` process with an MLX memory limit, so nothing stays resident between
clips. On an M5 Max a 4 second 704x448 clip took about 53 s (13.8 GiB at the peak), a 4 second 1280x704 clip about
147 s (same peak), and 1920x1088 at 5 seconds 595 s (29.8 GiB). The clip has a sound track.

Config options (from runtimes.json, per preset):
    model_dir          The LTX-2.5 distilled pack folder (the transformer, VAEs, vocoder and upscalers).
    gemma_dir          The Gemma-4 text encoder folder the pack needs.
    memory_limit_gib   MLX memory limit for the process (default 26; a soft limit).
Inputs: prompt, image ([{"path"}], optional: the first frame), last ([{"path"}], optional: the last frame, with the first), shape ("landscape" | "portrait" | "square"),
    quality ("quick" | "sharp"), length ("2 seconds" | "4 seconds" | "5 seconds"), seed.
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

# Sizes are multiples of 64; the width and height are the finished clip's.
SIZES = {
    "quick": {"landscape": (704, 448), "portrait": (448, 704), "square": (576, 576)},
    "sharp": {"landscape": (1280, 704), "portrait": (704, 1280), "square": (768, 768)},
}
FRAMES = {"2 seconds": 49, "4 seconds": 97, "5 seconds": 121}  # 8n+1; 24 frames per second
FPS = 24
ANSI = re.compile(rb"\x1b\[[0-9;]*m")
STEP = re.compile(rb"Denoising:[^\n\r]*?(\d+)/(\d+)")
STAGES = ((b"Loading text encoder", "Reading the description"), (b"Loading transformer", "Loading the video model"),
          (b"Decoding video", "Decoding the video and sound"))
LAUNCH = ("import sys, mlx.core as mx; mx.set_memory_limit(int(float(sys.argv[1]) * 2**30)); "
          "mx.set_cache_limit(2 * 2**30); sys.argv = ['ltx-2-mlx'] + sys.argv[2:]; "
          "from ltx_pipelines_mlx.cli import main; main()")


def load(config):
    options = config["options"]
    model_dir, gemma_dir = Path(options["model_dir"]), Path(options["gemma_dir"])
    if not (model_dir / "transformer-distilled.safetensors").is_file():
        raise FileNotFoundError(f"No LTX-2.5 distilled pack in {model_dir}")
    if not gemma_dir.is_dir():
        raise FileNotFoundError(f"No Gemma-4 text encoder in {gemma_dir}")
    return {"model_dir": str(model_dir), "gemma_dir": str(gemma_dir), "limit": float(options.get("memory_limit_gib", 26))}


def generate(model, inputs, job):
    from PIL import Image

    width, height = SIZES[inputs.get("quality") or "quick"][inputs.get("shape") or "landscape"]
    frames = FRAMES[inputs.get("length") or "4 seconds"]
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    out = job.output(f"video-{seed}.mp4", "video/mp4")
    command = [sys.executable, "-c", LAUNCH, str(model["limit"]), "generate", "--distilled",
               "-m", model["model_dir"], "--gemma", model["gemma_dir"], "-p", inputs["prompt"],
               "-H", str(height), "-W", str(width), "-f", str(frames), "--frame-rate", str(FPS), "-s", str(seed),
               "-o", str(out)]
    image = (inputs.get("image") or [None])[0]
    if image:
        command += ["--image", image["path"], "0", "1.0"]
    last = (inputs.get("last") or [None])[0]
    if last:  # the clip ends on this picture: the last frame is anchored the same way as the first
        command += ["--image", last["path"], str(frames - 1), "1.0"]
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
                # The first bar (8 steps) paints the clip small; the second (2 steps) sharpens it.
                job.report(f"{'Painting' if total > 4 else 'Sharpening'}, step {done} of {total}")
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
            raise RuntimeError("LTX failed: " + (lines[-1][:300] if lines else "no output"))
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
               quality=inputs.get("quality") or "quick", mode="image" if image else "text", **({"last_frame": True} if last else {}))
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
