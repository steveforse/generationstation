"""MiniMax H3 video worker for Apple silicon, through antirez/h3.c (a native Metal engine). The H3 weights are under
the MiniMax H3 Community License, which excludes the US, EU, UK and South Korea: personal use on your own machine only.

Each clip is one `h3` process (run in its own folder, where it finds its Metal shaders) with `--ssd-streaming`, which keeps
two transformer layers in memory and reads the rest from the SSD: about 11 GiB at the peak instead of 60. Nothing is
resident between clips. Text and first/last-frame modes use the FL2VA checkpoint; the reference modes need the Ref2VA
checkpoint, which this worker does not offer.

Config options (from runtimes.json, per preset):
    h3_dir      The h3.c checkout with its built `h3` binary.
    model_dir   The MiniMax-H3 snapshot (with FL2VA/).
    ssd_streaming  true (default): stream the transformer from the SSD.
Inputs: prompt, shape ("landscape 16:9" | "portrait 9:16" | "square 1:1"), resolution ("240p" | "360p" | "480p" | "540p"),
    length ("3" | "5" | "10" seconds), quality ("draft" 4 steps | "standard" 20 steps), seed, first, last (frames mode).
"""
import random
import re
import subprocess
import time
from pathlib import Path

from gs_worker import serve

EDGE = {"240p": 256, "360p": 352, "480p": 480, "540p": 544}  # the short edge, a multiple of 32
RATIO = {"landscape 16:9": (16, 9), "portrait 9:16": (9, 16), "square 1:1": (1, 1)}
STEPS = {"draft": 4, "standard": 20}
LINE = re.compile(r"^(?P<phase>[A-Za-z][A-Za-z0-9 ]*?)\s+(?P<done>\d+)/(?P<total>\d+)")


def canvas(inputs):
    """Width and height: the short edge from the resolution, the long edge from the shape, both multiples of 32."""
    edge = EDGE[inputs.get("resolution") or "480p"]
    w, h = RATIO[inputs.get("shape") or "landscape 16:9"]
    width, height = (edge, edge) if w == h else ((round(edge * w / h / 32) * 32, edge) if w > h else (edge, round(edge * h / w / 32) * 32))
    return width, height


def phase_text(phase, done, total):
    phase = phase.lower()
    if phase in ("tokenizer", "text encoder", "refine text", "precompute adaln"):
        return "Reading the description"
    if phase == "load transformer core":
        return "Loading the video model"
    if phase.startswith("denoise"):
        return f"Filming, step {min(done + 1, total)} of {total}" if phase == "denoise enqueue" else "Filming"
    if "vae" in phase:
        return "Decoding the video and sound"
    if phase == "ffmpeg":
        return "Saving the clip"
    return None


def load(config):
    options = config["options"]
    binary = Path(options["h3_dir"]) / "h3"
    model_dir = Path(options["model_dir"])
    if not binary.is_file():
        raise FileNotFoundError(f"The h3 engine is not built: {binary} (run make in {binary.parent})")
    if not (model_dir / "FL2VA" / "transformer").is_dir():
        raise FileNotFoundError(f"No MiniMax-H3 FL2VA checkpoint in {model_dir}")
    return {"dir": str(binary.parent), "binary": str(binary), "model_dir": str(model_dir),
            "ssd": bool(options.get("ssd_streaming", True))}


def generate(model, inputs, job):
    from PIL import Image

    width, height = canvas(inputs)
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    seconds = inputs.get("length") or "5"
    steps = STEPS[inputs.get("quality") or "draft"]
    out = job.output(f"video-{seed}.mp4", "video/mp4")
    command = [model["binary"], "-d", model["model_dir"], "-p", inputs["prompt"], "--width", str(width), "--height", str(height),
               "--seconds", seconds, "--steps", str(steps), "--layers", "50", "--reuse", "1", "--seed", str(seed), "-o", str(out)]
    if model["ssd"]:
        command.append("--ssd-streaming")
    for key, flag in (("first", "--first-frame"), ("last", "--last-frame")):
        picture = (inputs.get(key) or [None])[0]
        if picture:
            command += [flag, picture["path"]]
    job.report("Starting")
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=model["dir"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    pending, last, tail = b"", None, []
    try:
        while True:
            chunk = process.stdout.read1(4096)
            if not chunk:
                break
            pending += chunk
            *lines, pending = re.split(rb"[\r\n]", pending)
            for raw in lines:
                text = raw.decode(errors="replace").strip()
                if not text:
                    continue
                tail = (tail + [text])[-12:]
                match = LINE.match(text)
                if match:
                    said = phase_text(match["phase"], int(match["done"]), int(match["total"]))
                    if said and said != last:
                        last = said
                        job.report(said)
            if job.cancel_requested:
                break
        if job.cancel_requested:
            job.report("Cancelling")  # raises JobCancelled
        if process.wait() != 0 or not out.exists():
            raise RuntimeError("H3 failed: " + (tail[-1][:300] if tail else "no output"))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    thumb = out.with_suffix(".frame.png")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out), "-frames:v", "1", str(thumb)], check=False)
    if thumb.exists():
        job.thumbnail(Image.open(thumb), size=1024)
        thumb.unlink()
    job.detail(seed=seed, width=width, height=height, seconds_of_video=float(seconds), steps=steps,
               quality=inputs.get("quality") or "draft", mode="frames" if (inputs.get("first") or inputs.get("last")) else "text")
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
