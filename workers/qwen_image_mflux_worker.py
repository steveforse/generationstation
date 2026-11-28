"""Picture worker for Apple silicon, through mflux (MLX). Runs in the mflux environment.

The model is loaded once, when the worker starts, and stays in memory: a picture then costs only its painting time (Z-Image
Turbo at 1344x768: about 12 s, against about 28 s when each picture started its own mflux process). To keep the memory down,
the large text encoder is not kept between pictures: once a picture's description has been encoded the encoder is swapped for
a fresh one whose weights are not read until the next picture needs them (mflux's `--low-ram` frees the same part, but also
reloads the transformer every time), and the picture is decoded in tiles with a small MLX cache. Qwen Image 2.1 Turbo then
holds 7.6 GiB and peaks at 12.6 GiB instead of 15.6 and 28.5. All MLX work runs on one thread, because MLX's GPU stream
belongs to the thread that made it. The commands' own argument parsers and helpers are used, so defaults, validation and each
model family's scheduler are mflux's; a cancel stops the picture at the next step.

Config options (from runtimes.json, per preset):
    model_dir    An mflux model folder (a community conversion, or one made with `mflux-save`).
    command      Which mflux command's model this is: mflux-generate-qwen-2.1 (default), mflux-generate-qwen or
                 mflux-generate-z-image-turbo.
    steps        Denoising steps (default 8, the Turbo schedule).
    guidance     Optional guidance scale; omit for distilled (Turbo) models.
    base_model   Optional `--base-model`: the built-in model a third-party folder is based on.
    negative     true if the model uses a negative prompt (default false; Turbo models ignore it).
Inputs: prompt, size ("square" | "portrait" | "landscape" | "wide" | "custom" with width and height | "match picture" |
    "WxH"), picture ([{"path"}], an init image) with strength (percent, how closely it follows the picture), steps (default
    the preset's), negative_prompt, seed. `quality` is ignored: a preset is one quality.
"""
import copy
import gc
import random
import sys
import time
from pathlib import Path

from gs_worker import serve
from mlx_runtime import MLXThread

SHAPES = {"square": (1024, 1024), "portrait": (768, 1152), "landscape": (1152, 768), "wide": (1344, 768)}
DEFAULT_COMMAND = "mflux-generate-qwen-2.1"
FAMILIES = {"mflux-generate-qwen-2.1": "qwen21", "mflux-generate-qwen": "qwen", "mflux-generate-z-image-turbo": "zimage"}


def _size(text):
    if str(text or "square").lower() in SHAPES:
        return SHAPES[str(text or "square").lower()]
    width, _, height = str(text).lower().partition("x")
    width, height = int(width), int(height)
    if not (256 <= width <= 2048 and 256 <= height <= 2048):
        raise ValueError("Size must be between 256 and 2048 pixels on each side.")
    return width // 16 * 16, height // 16 * 16  # the model works in 16-pixel blocks


class _Painting:
    """An mflux callback: reports each step to the job (which stops the picture when the job was cancelled)."""
    job = None

    def call_in_loop(self, t, seed, prompt, latents, config, time_steps):
        if self.job is not None:
            self.job.report(f"Painting, step {t + 1} of {config.num_inference_steps}")


class _TextEncoderRelease:
    """An mflux callback: once the description has been encoded, the text encoder's memory is given back (the encoder is replaced by
    a fresh one whose weights are read from disk when the next picture's description needs them)."""

    def __init__(self, model, options, fresh):
        self.model, self.options, self.fresh = model, options, fresh

    def call_before_loop(self, **kwargs):
        import mlx.core as mx
        self.model.text_encoder = None
        gc.collect()
        mx.clear_cache()
        self.fresh(self.model, self.options)


def _parse(parser, argv):
    """mflux's parser reads sys.argv, so each picture's arguments are put there for the parse (only the MLX thread calls this)."""
    saved = sys.argv
    sys.argv = ["mflux", *argv]
    try:
        return parser.parse_args()
    finally:
        sys.argv = saved


def _base_args(options):
    """The argv every picture shares: the model folder and what it is based on."""
    argv = ["--model", str(options["model_dir"])]
    if options.get("base_model"):
        argv += ["--base-model", str(options["base_model"])]
    return argv


def _family(options):
    command = Path(options.get("command") or DEFAULT_COMMAND).name
    if command not in FAMILIES:
        raise ValueError(f"Unknown mflux command {command!r}; use one of {', '.join(FAMILIES)}.")
    return FAMILIES[command]


def _modules(family):
    """(parser module, how to build the model from parsed args, how to paint one picture from them, how to give the model a
    fresh text encoder whose weights are not read yet)."""
    from mflux.cli.parser.parsers import lora_init_kwargs_from_args
    from mflux.models.common.compute_precision import ComputePrecision
    from mflux.utils.dimension_resolver import DimensionResolver
    from mflux.utils.prompt_util import PromptUtil

    if family == "zimage":
        from mflux.models.z_image.cli import z_image_turbo_generate as cli

        from mflux.models.common.weights.loading.weight_applier import WeightApplier
        from mflux.models.z_image.model.z_image_text_encoder.text_encoder import TextEncoder
        from mflux.models.z_image.weights.z_image_weight_definition import ZImageWeightDefinition
        from mflux.models.z_image.z_image_initializer import ZImageInitializer

        def fresh(model, options):
            model.text_encoder = TextEncoder()
            WeightApplier.apply_and_quantize(weights=ZImageInitializer._load_weights(str(options["model_dir"])), quantize_arg=None,
                                             weight_definition=ZImageWeightDefinition, models={"text_encoder": model.text_encoder})

        return cli, cli.ZImageTurboCommand.load, lambda model, args, seed, prompt: cli.ZImageTurboCommand.generate(model, args, seed, prompt), fresh
    if family == "qwen":
        from mflux.models.qwen.cli import qwen_image_generate as cli

        def paint(model, args, seed, prompt):
            run = copy.copy(args)
            run.width, run.height = DimensionResolver.resolve(width=args.width, height=args.height, reference_image_path=args.image_path)
            return cli.QwenImageCommand.generate(model, run, seed, prompt)

        from mflux.models.common.weights.loading.weight_applier import WeightApplier
        from mflux.models.qwen.model.qwen_text_encoder.qwen_text_encoder import QwenTextEncoder
        from mflux.models.qwen.qwen_initializer import QwenImageInitializer
        from mflux.models.qwen.weights.qwen_weight_definition import QwenWeightDefinition

        def fresh(model, options):
            model.text_encoder = QwenTextEncoder()
            WeightApplier.apply_and_quantize(weights=QwenImageInitializer._load_weights(str(options["model_dir"])), quantize_arg=None,
                                             weight_definition=QwenWeightDefinition, models={"text_encoder": model.text_encoder})

        return cli, cli.QwenImageCommand.load, paint, fresh

    from mflux.models.common.resolution.config_resolution import ConfigResolution
    from mflux.models.qwen21.cli import qwen21_generate as cli
    from mflux.models.qwen21.model.qwen21_text_encoder.qwen21_text_encoder import Qwen21TextEncoder
    from mflux.models.qwen21.qwen21_initializer import Qwen21Initializer
    from mflux.models.qwen21.variants.txt2img.qwen_image_21 import QwenImage21
    from mflux.models.qwen21.weights.qwen21_weight_definition import Qwen21WeightDefinition

    class OnlyTextEncoder(Qwen21WeightDefinition):
        @staticmethod
        def get_components():
            return [component for component in Qwen21WeightDefinition.get_components() if component.name == "text_encoder"]

    def fresh(model, options):
        bits = model.bits
        model.text_encoder = Qwen21TextEncoder()
        Qwen21Initializer.load_components(model, Path(options["model_dir"]), OnlyTextEncoder, None)
        model.bits = bits  # load_components resets it

    def load(args):
        config = ConfigResolution.resolve_restricted(args.model, cli.DEFAULT_MODEL, model_path=args.model_path, base_model=args.base_model, extra_keys=cli.FAMILY_MODELS)
        return QwenImage21(quantize=args.quantize, model_path=args.model_path, model_config=config,
                           compute_precision=ComputePrecision.dtype_for(args.compute_precision), small_text_encoder=args.small_text_encoder,
                           **lora_init_kwargs_from_args(args))

    def paint(model, args, seed, prompt):
        width, height = DimensionResolver.resolve(width=args.width, height=args.height, reference_image_path=args.image_path)
        return model.generate_image(seed=seed, prompt=prompt, negative_prompt=PromptUtil.read_negative_prompt(args), width=width, height=height,
                                    guidance=args.guidance if args.guidance is not None else 1.0, scheduler=args.scheduler, image_path=args.image_path,
                                    num_inference_steps=args.steps, image_strength=args.image_strength, step_cache_ratio=args.step_cache_ratio)

    return cli, load, paint, fresh


def load(config):
    options = config["options"]
    model_dir = Path(options["model_dir"])
    if not (model_dir / "transformer").is_dir():
        raise FileNotFoundError(f"No mflux model in {model_dir} (expected a transformer/ folder)")
    family = _family(options)
    thread = MLXThread()
    painting = _Painting()

    def build():
        cli, load_model, paint, fresh = _modules(family)
        parser = cli.build_parser()
        first = _parse(parser, [*_base_args(options), "--prompt", "warm up", "--seed", "1", "--steps", "2", "--width", "256", "--height", "256", "--output", "/dev/null"])
        model = load_model(first)
        model.callbacks.register(painting)
        model.callbacks.register(_TextEncoderRelease(model, options, fresh))
        # Decode pictures in tiles and keep MLX's buffer cache small: the largest part of a picture's peak after the weights.
        from mflux.models.common.vae.tiling_config import TilingConfig
        import mlx.core as mx
        model.tiling_config = model.tiling_config or TilingConfig()
        mx.set_cache_limit(1000**3)
        # Weights load lazily; one tiny picture now brings them into memory, so "ready" means loaded and the first real picture is not slow.
        try:
            paint(model, first, 1, "warm up")
        except Exception as exc:  # noqa: BLE001 - the model still works; the first picture will load what is missing
            print(f"[worker] warm-up failed: {exc}", flush=True)
        import mlx.core as mx
        mx.clear_cache()
        return {"cli": cli, "parser": parser, "model": model, "paint": paint}

    state = thread.call(build)
    return {**state, "thread": thread, "painting": painting, "options": options, "steps": int(options.get("steps", 8)),
            "guidance": options.get("guidance"), "negative": bool(options.get("negative"))}


def generate(model, inputs, job):
    from PIL import Image

    options = model["options"]
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
    argv = [*_base_args(options), "--prompt", inputs["prompt"], "--seed", str(seed), "--steps", str(step_count), "--output", str(out)]
    if width:
        argv += ["--width", str(width), "--height", str(height)]
    if picture:
        argv += ["--image", str(picture), str(int(inputs.get("strength") or 40) / 100)]
    if model["guidance"] is not None:
        argv += ["--guidance", str(model["guidance"])]
    if model["negative"] and inputs.get("negative_prompt"):
        argv += ["--negative-prompt", inputs["negative_prompt"]]
    peak = {}

    def paint():
        import mlx.core as mx
        from mflux.utils.exceptions import StopImageGenerationException

        args = _parse(model["parser"], argv)
        mx.reset_peak_memory()
        model["painting"].job = job
        try:
            image = model["paint"](model["model"], args, seed, inputs["prompt"])
            image.save(path=str(out), export_json_metadata=False)
        except StopImageGenerationException as exc:
            raise RuntimeError(str(exc)) from exc
        finally:
            model["painting"].job = None
            peak["gib"] = mx.get_peak_memory() / 2**30
            mx.clear_cache()

    model["thread"].call(paint)
    image = Image.open(out)
    job.detail(seed=seed, steps=step_count, width=image.width, height=image.height, **({"start_strength": int(inputs.get("strength") or 40)} if picture else {}),
               **({"peak_gib": round(peak["gib"], 1)} if peak else {}))
    job.thumbnail(image, size=1024)
    job.report(f"Done in {time.perf_counter() - started:.0f} s, seed {seed}")


if __name__ == "__main__":
    serve(load, generate)
