"""LongCat-Video worker for Apple silicon (8-bit, 8-step fast path), through the xocialize MLX port. Runs in the longcat
environment.

Each clip is one `longcat_driver.py` process (see its notes for the fixes it makes), so nothing stays resident between
clips. On an M5 Max, 832x480 at 15 fps, 8-bit: 9 frames 65 s (18.5 GiB MLX peak), 17 frames 115 s (26 GiB), 33 frames
243 s (28 GiB), 61 frames 549 s (37 GiB). 4-bit is no faster.

Config options (from runtimes.json, per preset):
    weights_dir    The folder holding LongCat-Video-q8/ (and -q4/): the downloads, or a folder of symlinks to them.
    variant        "q8" (default) or "q4".
    repo_dir       The checkout of xocialize/longcat-video-mlx.
    memory_limit_gib   MLX memory limit for the process (default 40; a soft limit).
Tabs (the mode input): text (prompt, length, seed), image (a first picture, cropped to 832x480) and continue (an earlier clip: the
last 5 frames are the prior, and the result is that end plus the new frames; 5 prior frames joined more cleanly than 9).
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

HEIGHT, WIDTH, FPS = 480, 832, 15
PRIOR_FRAMES = 5
FRAMES = {"very short": 9, "short": 17, "medium": 33, "long": 61}  # 4n+1
ANSI = re.compile(rb"\x1b\[[0-9;]*m")
STEP = re.compile(rb"step (\d+)/(\d+)")
STAGES = ((b"stage 1/5", "Reading the description"), (b"umT5 freed", "Loading the video model"), (b"cfg_step_lora merged", "Getting ready"),
          (b"stage 4/5", "Painting the clip"), (b"DiT freed before VAE", "Decoding the video"))
RESULT = re.compile(rb"RESULT (\{.*\})")


def load(config):
    options = config["options"]
    weights, repo = Path(options["weights_dir"]), Path(options["repo_dir"])
    variant = options.get("variant", "q8")
    if not (weights / f"LongCat-Video-{variant}").is_dir():
        raise FileNotFoundError(f"No LongCat-Video-{variant} folder in {weights}")
    if not (repo / "scripts" / "_common.py").is_file():
        raise FileNotFoundError(f"No longcat-video-mlx checkout in {repo}")
    driver = Path(__file__).with_name("longcat_driver.py")
    return {"weights": str(weights), "variant": variant, "repo": str(repo), "driver": str(driver), "limit": float(options.get("memory_limit_gib", 40))}


def generate(model, inputs, job):
    from PIL import Image

    frames = FRAMES[inputs.get("length") or "short"]
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    out = job.output(f"video-{seed}.mp4", "video/mp4")
    mode = inputs.get("mode") or "text"
    picture = (inputs.get("image") or [None])[0] if mode == "image" else None
    prior = (inputs.get("source") or [None])[0] if mode == "continue" else None
    if mode == "image" and not picture or mode == "continue" and not prior:
        raise ValueError("Add the " + ("picture" if mode == "image" else "clip to continue") + " first.")
    command = [sys.executable, "-u", "-I", model["driver"], {"text": "t2v", "image": "i2v", "continue": "cont"}[mode], "--weights", model["weights"],
               "--variant", model["variant"], "--prompt", inputs["prompt"], "--frames", str(frames), "--height", str(HEIGHT), "--width", str(WIDTH),
               "--seed", str(seed), "--limit-gib", str(model["limit"]), "--out", str(out)]
    if picture:
        command += ["--image", picture["path"]]
    if prior:
        command += ["--prior", prior["path"], "--prior-frames", str(PRIOR_FRAMES)]
    env = dict(os.environ, LONGCAT_REPO=model["repo"], HF_HUB_OFFLINE="1", PYTHONUNBUFFERED="1")
    job.report("Starting")
    started = time.perf_counter()
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail = b""
    try:
        while True:
            chunk = process.stdout.read1(4096)
            if not chunk:
                break
            tail = ANSI.sub(b"", (tail + chunk))[-6000:]
            steps = STEP.findall(tail[-300:])
            if steps and b"step" in chunk:
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
            raise RuntimeError("LongCat failed: " + (lines[-1][:300] if lines else "no output"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    found = RESULT.findall(tail)
    frames_out = None
    if found:
        import json

        frames_out = json.loads(found[-1]).get("frames_out")
    thumb = out.with_suffix(".frame.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-frames:v", "1", str(thumb)], check=False)
    if thumb.exists():
        job.thumbnail(Image.open(thumb), size=1024)
        thumb.unlink()
    job.detail(seed=seed, width=WIDTH, height=HEIGHT, frames=frames_out or frames, seconds_of_video=round((frames_out or frames) / FPS, 1),
               mode=mode, model=model["variant"])
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
