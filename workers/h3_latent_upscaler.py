"""MiniMax H3 latent upscaler (3D): enlarges H3's video latents before they are decoded, so H3 can refine
them at the larger size. Network and loading ported from LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler
(MIT licence, copyright the authors), without its ComfyUI parts; weights from
LBH-123-AI/Minimax_h3_latent_Upscaler (Apache 2.0).

Latent form: ComfyUI's H3 VAE (like Diffusers') already returns latents normalised with the VAE's per-channel
statistics, and the original node normalises them a *second* time before the network, then undoes that second
step afterwards. The network was trained that way, so `upscale` applies the same extra normalisation to
Diffusers' (once-normalised) latents.
"""
import re

import torch
import torch.nn.functional as F
from torch import nn


def _norm(channels):
    return nn.GroupNorm(32, channels)


def _zero(module):
    for p in module.parameters():
        p.detach().zero_()
    return module


class ResBlockEmb3D(nn.Module):
    def __init__(self, channels, emb_channels, dropout=0.0, out_channels=None):
        super().__init__()
        self.out_channels = out_channels or channels
        self.in_layers = nn.Sequential(_norm(channels), nn.SiLU(), nn.Conv3d(channels, self.out_channels, 3, padding=1))
        self.emb_layers = nn.Sequential(nn.SiLU(), nn.Linear(emb_channels, 2 * self.out_channels))
        self.out_norm = _norm(self.out_channels)
        self.out_layers = nn.Sequential(nn.SiLU(), nn.Dropout(p=dropout),
                                        _zero(nn.Conv3d(self.out_channels, self.out_channels, 3, padding=1)))
        self.skip = nn.Conv3d(channels, self.out_channels, 1) if self.out_channels != channels else nn.Identity()

    def forward(self, x, emb):
        h = self.in_layers(x)
        emb_out = self.emb_layers(emb).type(h.dtype)
        while emb_out.dim() < h.dim():
            emb_out = emb_out[..., None]
        scale, shift = torch.chunk(emb_out, 2, dim=1)
        h = self.out_layers(self.out_norm(h) * (1 + scale) + shift)
        return self.skip(x) + h


class TemporalConv(nn.Module):
    def __init__(self, channels, kernel_size=5):
        super().__init__()
        self.norm = _norm(channels)
        self.dwconv = nn.Conv3d(channels, channels, kernel_size=(kernel_size, 1, 1),
                                padding=(kernel_size // 2, 0, 0), groups=channels)
        self.pwconv = nn.Conv3d(channels, channels, kernel_size=1)

    def forward(self, x):
        return x + self.pwconv(self.dwconv(F.silu(self.norm(x))))


class LatentResizer3D(nn.Module):
    def __init__(self, in_channels=24, in_blocks=12, out_blocks=12, channels=512, temporal_every=2, temporal_kernel=5):
        super().__init__()
        self.conv_in = nn.Conv3d(in_channels, channels, 3, padding=1)
        embed_dim = 64
        self.embed = nn.Sequential(nn.Linear(1, embed_dim), nn.SiLU(), nn.Linear(embed_dim, embed_dim))

        def stack(count):
            blocks = nn.ModuleList()
            for b in range(count):
                blocks.append(ResBlockEmb3D(channels, embed_dim))
                if temporal_every > 0 and b % temporal_every == 0:
                    blocks.append(TemporalConv(channels, temporal_kernel))
            return blocks

        self.in_blocks, self.out_blocks = stack(in_blocks), stack(out_blocks)
        self.norm_out = _norm(channels)
        self.conv_out = nn.Conv3d(channels, in_channels, 3, padding=1)

    def forward(self, x, size, scale):
        """x: (B, 24, T, H, W) normalised latents; size: (T, H', W'); scale: the spatial factor."""
        emb = self.embed(torch.tensor([[scale - 1.0]], dtype=x.dtype, device=x.device)).expand(x.shape[0], -1)
        x = self.conv_in(x)
        for block in self.in_blocks:
            x = block(x, emb) if isinstance(block, ResBlockEmb3D) else block(x)
        x = F.interpolate(x, size=size, mode="trilinear", align_corners=False)
        for block in self.out_blocks:
            x = block(x, emb) if isinstance(block, ResBlockEmb3D) else block(x)
        return self.conv_out(F.silu(self.norm_out(x)))


def load(path, device="cuda", dtype=torch.bfloat16):
    from safetensors.torch import load_file

    state = load_file(str(path), device="cpu")
    if any(key.startswith("upscaler.") for key in state):
        state = {key[len("upscaler."):]: value for key, value in state.items() if key.startswith("upscaler.")}
    in_blocks = len({int(m.group(1)) for k in state if (m := re.match(r"in_blocks\.(\d+)\.in_layers\.", k))})
    out_blocks = len({int(m.group(1)) for k in state if (m := re.match(r"out_blocks\.(\d+)\.in_layers\.", k))})
    kernel = next((v.shape[2] for k, v in state.items() if k.endswith("dwconv.weight")), 5)
    model = LatentResizer3D(in_channels=state["conv_in.weight"].shape[1], channels=state["conv_in.weight"].shape[0],
                            in_blocks=in_blocks, out_blocks=out_blocks, temporal_kernel=kernel)
    model.load_state_dict(state, strict=True)
    return model.to(device=device, dtype=dtype).eval().requires_grad_(False)


@torch.inference_mode()
def upscale(model, latents, height, width, mean, std):
    """Enlarge H3 latents (B, 24, T, H, W), in Diffusers' normalised form, to (B, 24, T, height, width) latent
    cells. `mean` and `std` are the H3 video VAE's 24 per-channel statistics (vae.config.latents_mean / _std)."""
    t = latents.shape[2]
    scale = (height / latents.shape[3] + width / latents.shape[4]) / 2
    dtype = next(model.parameters()).dtype
    mean = torch.as_tensor(mean, device=latents.device, dtype=torch.float32).view(1, -1, 1, 1, 1)
    std = torch.as_tensor(std, device=latents.device, dtype=torch.float32).view(1, -1, 1, 1, 1)
    x = ((latents.float() - mean) / std).to(dtype)  # the node's second normalisation
    out = model(x, size=(t, height, width), scale=scale).float() * std + mean
    return out.to(latents.dtype)


__all__ = ["LatentResizer3D", "load", "upscale"]
