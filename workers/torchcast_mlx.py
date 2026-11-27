"""Torchcast 31B on MLX (8-bit), for Apple silicon.

The model was trained with no causal mask in its ten global-attention layers (decision_config "hybrid_bidir_global");
its sliding-window layers (1024 tokens) stay causal. Stock MLX, llama.cpp and the transformers fast paths mask every
layer causally and get different answers (differences up to 0.8 in a probability, and a flipped answer). This engine
runs the forward pass itself with no mask on the global layers, and borrows everything else (prompt, option letters,
temperature, the yes/no floor, wide choices, confidence) from the vendor's own `torchcast_decision` package, so the
answers come out in the vendor's format.

Needs, in one environment: mlx, mlx-lm 0.32.x (it uses the gemma4 layer's `layer_type` and the body's `_make_masks`),
transformers, torch (the vendor module imports it), and the vendor package from the model folder. Checked on an M5 Max
against the vendor's own bf16 run: probabilities within 0.0084, same answer on every test.

    model_dir    The vendor folder (torchcast_decision/, decision_config.json, tokenizer).
    weights_dir  The 8-bit MLX conversion (see torchcast31_convert.py).
"""
import json
import sys
import types
from pathlib import Path


class TorchcastMLX31B:
    def __init__(self, model_dir, weights_dir):
        import mlx.core as mx
        import transformers
        from mlx_lm import load
        from mlx_lm.models.base import create_attention_mask

        self.mx = mx
        sys.path.insert(0, str(model_dir))
        from torchcast_decision import model as vendor
        from torchcast_decision import prompt as P

        self.P = P
        config = json.loads((Path(model_dir) / "decision_config.json").read_text(encoding="utf-8"))
        self.tok = transformers.AutoTokenizer.from_pretrained(str(model_dir))
        self.letters = P.check_tokenizer(self.tok)
        if self.letters != config["letter_token_ids"]:
            raise ValueError("tokenizer letter ids differ from decision_config.json")
        self.temperature = {key: float(value) for key, value in config["temperature_by_type"].items()}
        self.noul_floor = float(config.get("noul_floor", 0.0))
        wide = config.get("wide_choice", {})
        self.group, self.keep, self.residual = wide.get("group", 25), wide.get("keep", 3), wide.get("residual", 1e-3)
        self.softcap = config["final_logit_softcapping"]
        window = config["sliding_window"]
        self.model, _ = load(str(weights_dir))
        language = self.model.language_model
        self.body = language.model
        self.rows = language.lm_head.weight[mx.array(self.letters)].astype(mx.float32)  # the output head stays bf16
        mx.eval(self.rows)

        def masks(h, cache):
            sliding = create_attention_mask(h, None, window_size=window)
            return [None if layer.layer_type == "full_attention" else sliding for layer in self.body.layers]  # None: sees every token
        self.body._make_masks = masks
        # The vendor's request handling, answers and many-option rounds, run on this class's probabilities().
        for name in ("decide", "_format", "_many_options"):
            setattr(self, name, types.MethodType(getattr(vendor.TorchcastDecision, name), self))

    def probabilities(self, questions):
        """[Question] -> ([probabilities of each question's options], prompt tokens), one prompt per pass, no padding."""
        mx = self.mx
        out, tokens = [], 0
        for question in questions:
            ids = self.P.render_ids(question, self.tok, max_length=self.P.CUT_LEN)
            tokens += len(ids)
            hidden = self.body(mx.array([ids]))
            z = hidden[0, -1].astype(mx.float32) @ self.rows.T
            z = (self.softcap * mx.tanh(z / self.softcap))[: len(question.options)]
            out.append(mx.softmax(z / self.temperature.get(question.type, 1.0), axis=-1).tolist())
        return out, tokens
