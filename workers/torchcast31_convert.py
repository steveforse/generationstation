"""Makes the 8-bit MLX copy of Torchcast 31B that torchcast_mlx.py runs (about 33 GB; the bf16 original is 61 GB).

    python workers/torchcast31_convert.py ~/ai/models/decision/torchcast-31b ~/ai/models/decision/torchcast-31b-mlx-8bit

Two things stock mlx-lm does not do for this checkpoint: its config lists the global layers' shapes under
`per_layer_config`, which mlx-lm does not read (it wants `global_head_dim` and `num_global_key_value_heads`), and the
output head is stored untied from the embeddings, which mlx-lm's gemma4 `sanitize` drops. This script works from a
folder of links with a patched config, renames the head so `sanitize` keeps it, and leaves the head in bf16 (its rows
are the answers' letter logits). Needs mlx-lm 0.32.x. Run it alone: it peaks near 40 GB.
"""
import json
import os
import sys
from pathlib import Path


def main(source, target, bits=8):
    from mlx_lm import convert
    from mlx_lm.models import gemma4

    source, target = Path(source), Path(target)
    untied = target.with_name(target.name + "-input")
    untied.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        link = untied / item.name
        if item.name != "config.json" and not link.exists():
            os.symlink(item, link)
    config = json.loads((source / "config.json").read_text(encoding="utf-8"))
    text = config["text_config"]
    layers = text.pop("per_layer_config")
    first = next(iter(layers.values()))
    text["global_head_dim"], text["num_global_key_value_heads"] = first["head_dim"], first["num_key_value_heads"]
    text["tie_word_embeddings"] = False
    (untied / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    original = gemma4.Model.sanitize

    def sanitize(self, weights):
        weights = {("language_model.lm_head.weight" if key == "lm_head.weight" else key): value for key, value in weights.items()}
        return original(self, weights)
    gemma4.Model.sanitize = sanitize
    convert(str(untied), mlx_path=str(target), quantize=True, q_bits=int(bits), q_group_size=64,
            quant_predicate=lambda path, module: "lm_head" not in path)


if __name__ == "__main__":
    main(*sys.argv[1:4])
