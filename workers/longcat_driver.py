"""Low-memory LongCat-Video driver (MLX), run by longcat_mlx_worker.py in the longcat environment.

The upstream port (xocialize/longcat-video-mlx) needs three fixes this driver makes without editing it: the 8-step
cfg_step_lora cannot merge into 4/8-bit weights (longcat_qlora_patch.py dequantizes, adds and requantizes), the image and
continuation pipelines never give the clean reference latents timestep 0 (the output is garbage otherwise), and it keeps
umT5 and the DiT in memory through decoding (peaks of 44-52 GiB). Here: umT5 -> encode -> free; VAE + DiT (+ LoRA) ->
denoise; free DiT -> VAE decode. Prints stage lines, `step i/N` lines and a RESULT json line.

The checkout of the port is named by the LONGCAT_REPO environment variable.
usage: longcat_driver.py {t2v,i2v,cont} --weights DIR --variant q8|q4 --prompt P --frames N --out X.mp4 [...]"""
import argparse, json, pathlib, sys, time, os
_repo = os.environ["LONGCAT_REPO"]
sys.path.insert(0, _repo)
sys.path.insert(0, os.path.join(_repo, "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mlx.core as mx, mlx.nn as nn, numpy as np
from mlx.utils import tree_flatten, tree_unflatten
import _common as C
import longcat_qlora_patch  # quantization-aware LoRA merge (patches longcat_video.lora)

ap = argparse.ArgumentParser()
ap.add_argument("mode", choices=["t2v", "i2v", "cont"])
ap.add_argument("--weights", type=pathlib.Path, required=True)
ap.add_argument("--variant", default="q8")
ap.add_argument("--prompt", required=True)
ap.add_argument("--frames", type=int, default=9)          # t2v/i2v: frames; cont: NEW frames
ap.add_argument("--image", type=pathlib.Path)
ap.add_argument("--prior", type=pathlib.Path)
ap.add_argument("--prior-frames", type=int, default=9)
ap.add_argument("--height", type=int, default=480)
ap.add_argument("--width", type=int, default=832)
ap.add_argument("--steps", type=int, default=None)
ap.add_argument("--no-lora", action="store_true", help="baseline 50 steps + CFG instead of cfg_step_lora 8 steps")
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--limit-gib", type=float, default=0)
ap.add_argument("--no-cond-fix", action="store_true", help="disable the I2V/continuation conditioning fix")
ap.add_argument("--keep-dit-for-decode", action="store_true")
ap.add_argument("--out", type=pathlib.Path, required=True)
a = ap.parse_args()
if a.limit_gib > 0:
    mx.set_memory_limit(int(a.limit_gib * 2**30))
GiB = 2**30
def log(m): print(f"[{time.time()-T0:6.1f}s act {mx.get_active_memory()/GiB:5.1f} peak {mx.get_peak_memory()/GiB:5.1f} GiB] {m}", flush=True)
T0 = time.time()

def free(mod):
    mod.update(tree_unflatten([(k, mx.zeros((1,), dtype=mx.bfloat16)) for k, _ in tree_flatten(mod.parameters())]))
    mx.clear_cache()

vdir = C._resolve_variant(a.weights, a.variant)
# 1. text
from longcat_video.models.umt5 import UMT5EncoderModel
log("stage 1/5 load umT5")
cfgj = json.loads((vdir / "text_encoder/config.json").read_text())
t5 = UMT5EncoderModel.from_config(cfgj)
idx = json.loads((vdir / "text_encoder/model.safetensors.index.json").read_text())
for sh in sorted(set(idx["weight_map"].values())):
    t5.load_weights(str(vdir / "text_encoder" / sh), strict=False)
mx.eval(t5.parameters())
log("stage 2/5 encode prompt")
te, tm, ue, um = C.encode_prompts(t5, a.prompt, "", vdir)
mx.eval(te, tm, ue, um)
free(t5); del t5
log("umT5 freed")
# 2. vae + dit
from longcat_video.models.autoencoder_kl_wan import AutoencoderKLWan
from longcat_video.models.longcat_video_dit import LongCatVideoTransformer3DModel
log("stage 3/5 load VAE + DiT")
vae = AutoencoderKLWan.from_config(json.loads((vdir / "vae/config.json").read_text()))
vae.load_weights(str(vdir / "vae/diffusion_pytorch_model.safetensors"), strict=False)
dcfg = json.loads((vdir / "dit/config.json").read_text())
dit = LongCatVideoTransformer3DModel.from_config(dcfg)
if dcfg.get("quantization"):
    C._apply_quantization_for_load(dit, dcfg["quantization"])
didx = json.loads((vdir / "dit/diffusion_pytorch_model.safetensors.index.json").read_text())
for sh in sorted(set(didx["weight_map"].values())):
    dit.load_weights(str(vdir / "dit" / sh), strict=False)
mx.eval(vae.parameters(), dit.parameters())
log("loaded")
if mx.metal.is_available(): pass
if a.mode == "t2v":
    from longcat_video.pipeline_t2v import LongCatVideoT2VPipeline as P, T2VPipelineConfig as Cfg
elif a.mode == "i2v":
    from longcat_video.pipeline_i2v import LongCatVideoI2VPipeline as P, I2VPipelineConfig as Cfg
else:
    from longcat_video.pipeline_continuation import LongCatVideoContinuationPipeline as P, ContinuationPipelineConfig as Cfg
cfg = Cfg()
pipe = P(vae=vae, text_encoder=None, dit=dit, config=cfg)
if not a.no_lora:
    C.merge_lora(dit, vdir, "cfg_step_lora")
    cfg.cfg_collapse = True; cfg.num_sampling_steps = 8; cfg.text_guidance_scale = 0.0
    mx.clear_cache()
    log("cfg_step_lora merged (8 steps, cfg collapsed)")
if a.steps: cfg.num_sampling_steps = a.steps

# progress per step
import mlx_arsenal.diffusion as D
_o = D.FlowMatchEulerDiscreteScheduler.step
st = {"n": 0, "t": None}
def _step(self, pred, t, lat, *x, **k):
    n = st.get("ncond", 0)
    if n > 0 and not a.no_cond_fix:
        # keep conditioning latents clean; step only the noisy frames
        r = mx.concatenate([lat[:, :, :n], _o(self, pred[:, :, n:], t, lat[:, :, n:], *x, **k)], axis=2)
    else:
        r = _o(self, pred, t, lat, *x, **k)
    mx.eval(r)
    st["n"] += 1; st["t"] = st["t"] or time.time()
    log(f"step {st['n']}/{len(self.timesteps)} ({time.time()-st['t']:.0f}s in loop)")
    return r
D.FlowMatchEulerDiscreteScheduler.step = _step
# free DiT right before VAE decode
if not a.keep_dit_for_decode:
    _dec = vae.decode
    def dec(z, *x, **k):
        mx.eval(z); free(dit); log("DiT freed before VAE decode"); return _dec(z, *x, **k)
    vae.decode = dec

class DitProxy:
    """Upstream sets timestep=0 for conditioning latents; the port forgets. Do it here."""
    def __init__(s, d): s.d = d
    def __call__(s, h, t, *x, num_cond_latents=0, **k):
        st["ncond"] = num_cond_latents
        if num_cond_latents > 0 and not a.no_cond_fix:
            B, N_t = h.shape[0], h.shape[2] // s.d.patch_size[0]
            t = mx.broadcast_to(t.reshape(-1)[:, None], (B, N_t))
            t = mx.concatenate([mx.zeros((B, num_cond_latents), dtype=t.dtype), t[:, num_cond_latents:]], axis=1)
        return s.d(h, t, *x, num_cond_latents=num_cond_latents, **k)
pipe.dit = DitProxy(dit)
log(f"stage 4/5 denoise ({cfg.num_sampling_steps} steps)")
t1 = time.time()
kw = dict(text_embeds=te, text_mask=tm, uncond_embeds=ue, uncond_mask=um, height=a.height, width=a.width, seed=a.seed)
if a.mode == "t2v":
    v = pipe(num_frames=a.frames, **kw)
elif a.mode == "i2v":
    v = pipe(image=C.load_image(a.image, a.height, a.width), num_frames=a.frames, **kw)
else:
    pre = C.load_video(a.prior, a.prior_frames, a.height, a.width)
    v = pipe(prefix_video=pre, num_new_frames=a.frames, return_full_video=True, **kw)
mx.eval(v)
gen_s = time.time() - t1
log(f"stage 5/5 decoded, generate+decode {gen_s:.1f}s")
arr = C.postprocess_video(v)
C.save_video_mp4(arr, a.out, fps=cfg.target_fps)
print("RESULT " + json.dumps(dict(mode=a.mode, variant=a.variant, frames_out=int(arr.shape[0]), steps=cfg.num_sampling_steps,
      lora=not a.no_lora, gen_seconds=round(gen_s, 1), total_seconds=round(time.time()-T0, 1),
      mlx_peak_gib=round(mx.get_peak_memory()/GiB, 2), limit_gib=a.limit_gib, out=str(a.out))), flush=True)
