"""Picture worker for Apple silicon, through mflux (MLX). Runs in the mflux environment.

Each picture is one mflux process with `--low-ram`, so nothing stays in memory between pictures (Qwen Image 2.1 Turbo:
about 8.5 GiB at the peak for a 1024x1024 picture, 8 steps, about 20 s on an M5 Max). The worker holds no model.

Config options (from runtimes.json, per preset):
    model_dir    An mflux model folder (a community conversion, or one made with `mflux-save`).
    command      The mflux command, a name beside this Python or a path (default mflux-generate-qwen-2.1).
    steps        Denoising steps (default 8, the Turbo schedule).
    guidance     Optional guidance scale; omit for distilled (Turbo) models.
    base_model   Optional `--base-model`: the built-in model a third-party folder is based on.
    negative     true if the model uses a negative prompt (default false; Turbo models ignore it).
Inputs: prompt, size ("square" | "portrait" | "landscape" | "wide" | "custom" with width and height | "match picture" |
    "WxH"), picture ([{"path"}], an init image) with strength (percent, how closely it follows the picture), steps (default
    the preset's), negative_prompt, seed. `quality` is ignored: a preset is one quality.
"""
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from gs_worker import serve

SHAPES = {"square": (1024, 1024), "portrait": (768, 1152), "landscape": (1152, 768), "wide": (1344, 768)}
STEP = re.compile(rb"(\d+)/(\d+) \[")
PEAK = re.compile(rb"Peak MLX memory: ([\d.]+) GB")


def _size(text):
    if str(text or "square").lower() in SHAPES:
        return SHAPES[str(text or "square").lower()]
    width, _, height = str(text).lower().partition("x")
    width, height = int(width), int(height)
    if not (256 <= width <= 2048 and 256 <= height <= 2048):
        raise ValueError("Size must be between 256 and 2048 pixels on each side.")
    return width // 16 * 16, height // 16 * 16  # the model works in 16-pixel blocks


def _command(options):
    path = Path(options.get("command") or "mflux-generate-qwen-2.1")
    path = path if path.is_absolute() else Path(sys.executable).parent / path
    if not path.exists():
        raise FileNotFoundError(f"mflux command not found: {path}")
    return str(path)


def load(config):
    options = config["options"]
    model_dir = Path(options["model_dir"])
    if not (model_dir / "transformer").is_dir():
        raise FileNotFoundError(f"No mflux model in {model_dir} (expected a transformer/ folder)")
    return {"command": _command(options), "model_dir": str(model_dir), "steps": int(options.get("steps", 8)),
            "guidance": options.get("guidance"), "base_model": options.get("base_model"),
            "negative": bool(options.get("negative"))}


def generate(model, inputs, job):
    from PIL import Image

    picture = (inputs.get("picture") or [{}])[0].get("path")
    size = str(inputs.get("size") or "square").lower()
    # "match picture" leaves the size to the starting picture; "custom" takes the width and height fields.
    width, height = (None, None) if size == "match picture" else _size(f"{inputs.get('width') or 1024}x{inputs.get('height') or 1024}" if size == "custom" else size)
    step_count = int(inputs.get("steps") or model["steps"])
    seed = inputs.get("seed")
    seed = seed if isinstance(seed, int) else random.randrange(1, 2**31)
    out = job.output(f"picture-{seed}.png", "image/png")
    job.report("Reading the description")
    started = time.perf_counter()
    command = [model["command"], "--model", model["model_dir"], "--prompt", inputs["prompt"], "--seed", str(seed),
               "--steps", str(step_count), "--low-ram", "--no-metadata", "--output", str(out)]
    if width:
        command += ["--width", str(width), "--height", str(height)]
    if picture:
        command += ["--image", str(picture), str(int(inputs.get("strength") or 40) / 100)]
    if model["base_model"]:
        command += ["--base-model", model["base_model"]]
    if model["guidance"] is not None:
        command += ["--guidance", str(model["guidance"])]
    if model["negative"] and inputs.get("negative_prompt"):
        command += ["--negative-prompt", inputs["negative_prompt"]]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    tail, peak = b"", None
    try:
        while True:
            chunk = process.stdout.read1(4096)  # tqdm redraws one line with carriage returns, so read raw bytes
            if not chunk:
                break
            tail = (tail + chunk)[-4000:]
            steps = STEP.findall(tail)
            if steps:
                done, total = (int(n) for n in steps[-1])
                job.report(f"Painting, step {done} of {total}")
            found = PEAK.search(tail)
            if found:
                peak = float(found.group(1))
            if job.cancel_requested:
                break
        if job.cancel_requested:
            job.report("Cancelling")  # raises JobCancelled
        if process.wait() != 0 or not out.exists():
            raise RuntimeError("mflux failed: " + tail.decode(errors="replace").strip().splitlines()[-1][:300])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    image = Image.open(out)
    job.detail(seed=seed, steps=step_count, width=image.width, height=image.height, **({"start_strength": int(inputs.get("strength") or 40)} if picture else {}),
               **({"peak_gib": round(peak, 1)} if peak else {}))
    job.thumbnail(image, size=1024)
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
