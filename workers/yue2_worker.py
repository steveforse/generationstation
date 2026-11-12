"""YuE2 song worker. Runs in its own environment with the official `yue2_infer` package.

Config options (from runtimes.json): model_dir, vae_dir. Start settings: memory_budget_gib, quantization.
Inputs: style, lyrics, mode ("full", "melody", "off"), seed, cfg_scale.
"""
import random

from gs_worker import serve


def _flash_attention_works():
    """Windows PyTorch wheels ship the FlashAttention op without its kernels; try it once."""
    import warnings

    import torch
    from torch.nn.attention import SDPBackend, sdpa_kernel
    try:
        q = torch.zeros(1, 1, 1, 64, device="cuda", dtype=torch.bfloat16)
        with warnings.catch_warnings(), sdpa_kernel(SDPBackend.FLASH_ATTENTION):
            warnings.simplefilter("ignore")
            torch.nn.functional.scaled_dot_product_attention(q, q, q)
        return True
    except RuntimeError:
        return False


def _use_cudnn_attention_when_flash_is_missing(log=print):
    """YuE2 picks FlashAttention when the op exists, even if this build cannot run it.

    Its cuDNN attention path is a supported alternative; make it the choice for "auto".
    """
    if _flash_attention_works():
        return
    from yue2 import cuda_graph

    original = cuda_graph.GraphAR.__init__
    if getattr(original, "_gs_patched", False):
        return

    def init(self, *args, attention_backend="auto", **kwargs):
        original(self, *args, attention_backend="cudnn" if attention_backend == "auto" else attention_backend,
                 **kwargs)

    init._gs_patched = True
    cuda_graph.GraphAR.__init__ = init
    log("[worker] FlashAttention is not in this PyTorch build; using cuDNN attention")


def load(config):
    from yue2 import YuE2Pipeline

    _use_cudnn_attention_when_flash_is_missing()

    options, settings = config["options"], config["settings"]
    pipe = YuE2Pipeline(options["model_dir"], options["vae_dir"], device="cuda",
                        memory_budget_gib=settings.get("memory_budget_gib", 24),
                        quantization=settings.get("quantization", "none"), progress=False)
    # Load the weights now, so "loaded" means ready to sing rather than loading on the first song.
    pipe._load_model()
    return pipe


def generate(pipe, inputs, job):
    from yue2.protocol import SongRequest

    seed = inputs.get("seed")
    request = SongRequest(style=inputs["style"], lyrics=inputs["lyrics"], cot=inputs.get("mode") or "full",
                          seed=seed if isinstance(seed, int) else random.randrange(1, 2**31),
                          cfg_scale=inputs.get("cfg_scale"), id="song")
    job.report("Writing the melody")
    plan = pipe.plan(request=request)
    job.report("Composing the song")
    semantic = pipe.generate_semantic(plan)
    job.report("Rendering the instruments and voice")
    latents = pipe.synthesize(semantic)
    job.report("Mixing the audio")
    audio = pipe.decode(latents)

    import soundfile as sf
    sf.write(job.output("song.flac", "audio/flac"), audio, 48000, subtype="PCM_24")
    if plan.abc:
        job.output("melody.abc", "text/plain").write_text(plan.abc, encoding="utf-8")
    job.report(f"Done: {len(audio) / 48000:.0f} seconds, seed {request.seed}")


if __name__ == "__main__":
    serve(load, generate)
