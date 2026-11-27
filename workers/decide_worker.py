"""Decision-model worker: one situation and one question in, a probability for each answer out.

The model stays resident, so a request takes the model's forward pass only (0.25 s for a short situation on an M5 Max).
Config options (from runtimes.json, per preset):
    engine     "karpo": the Karpo 31B MLX port (serve_karpo_31b_mlx.py lives in the model folder; text only).
               "mlx_decision": pplx-decider, H2O-Lightning and the other models the mlx-decision package loads; they
               also read pictures.
               "torchcast": the vendor's torchcast_decision package on the Mac GPU (torch MPS, bf16); it keeps the
               vendor's non-causal attention, which stock MLX and llama.cpp get wrong. Text only.
               "torchcast_mlx31": Torchcast 31B on MLX, 8-bit (torchcast_mlx.py; needs weights_dir, made by
               torchcast31_convert.py). Text only.
    reading    mlx_decision only: "two-way" (default) or "one-way" (H2O: questions share one pass over the situation).
    model_dir  The model folder.
Inputs: state, question_type ("choose" | "yesno" | "score"), instructions, options (one per line, "name: meaning"),
levels (one per line, lowest first), pictures (uploaded images, for engines that read them).
Writes decision.json (the answer in TypeSafe's System One shape) and result.md (what the page shows).
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from decide_render import render
from gs_worker import serve

MAX_OPTIONS = 255


def lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def load(config):
    """MLX keeps its streams per thread, and the worker loads the model in one thread and runs jobs in another, so the
    model is built, and every question answered, on one thread of its own."""
    options = config["options"]
    engine = options.get("engine", "karpo")
    model_dir = Path(options["model_dir"])
    if engine not in ("karpo", "mlx_decision", "torchcast", "torchcast_mlx31"):
        raise ValueError(f"Unknown decision engine {engine!r}")
    thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decide")
    if engine == "karpo":
        if not (model_dir / "serve_karpo_31b_mlx.py").is_file():
            raise FileNotFoundError(f"No Karpo MLX port in {model_dir}")

        def build():
            sys.path.insert(0, str(model_dir))
            from serve_karpo_31b_mlx import Karpo31BMLX

            engine_object = Karpo31BMLX(model_dir)

            def decide(state, questions, images):
                if images:
                    raise ValueError("This model reads text only. Start pplx-decider or H2O-Lightning to use a picture.")
                answers, tokens, _encode_ms, forward_ms = engine_object.decide(state, questions)
                return answers, tokens, forward_ms
            return decide
        name = options.get("model_name", "Karpo 31B")
    elif engine == "torchcast_mlx31":
        weights_dir = Path(options["weights_dir"])
        if not (weights_dir / "config.json").is_file() or not (model_dir / "torchcast_decision").is_dir():
            raise FileNotFoundError(f"Torchcast 31B needs the vendor folder {model_dir} and the 8-bit MLX copy {weights_dir}")

        def build():
            from torchcast_mlx import TorchcastMLX31B

            engine_object = TorchcastMLX31B(model_dir, weights_dir)
            engine_object.decide("Warm-up.", {"q": {"type": "noul", "instructions": "Is this a test?"}})  # MLX reads the weights on first use

            def decide(state, questions, images):
                if images:
                    raise ValueError("This model reads text only. Start pplx-decider or H2O-Lightning to use a picture.")
                started = time.perf_counter()
                answers, usage = engine_object.decide(state, questions)
                return answers, usage.get("input_tokens"), (time.perf_counter() - started) * 1000
            return decide
        name = options.get("model_name", "Torchcast 31B")
    elif engine == "torchcast":
        if not (model_dir / "torchcast_decision").is_dir():
            raise FileNotFoundError(f"No torchcast_decision package in {model_dir}")

        def build():
            import os

            os.environ.setdefault("TC_ALLOW_SLOW", "1")  # no flash-linear-attention on a Mac: the plain torch path is used
            sys.path.insert(0, str(model_dir))
            from torchcast_decision.model import TorchcastDecision

            engine_object = TorchcastDecision(str(model_dir), device="mps", images=False, graphs=False)

            def decide(state, questions, images):
                if images:
                    raise ValueError("This model reads text only. Start pplx-decider or H2O-Lightning to use a picture.")
                started = time.perf_counter()
                answers, usage = engine_object.decide(state, questions)
                return answers, usage.get("input_tokens"), (time.perf_counter() - started) * 1000
            return decide
        name = options.get("model_name", "Torchcast")
    else:
        def build():
            import mlx_decision

            kwargs = {"reading": options["reading"]} if options.get("reading") else {}
            engine_object = mlx_decision.load(str(model_dir), **kwargs)

            def decide(state, questions, images):
                started = time.perf_counter()
                result = engine_object.decide(state, questions, images=images or None)
                wire = result.to_wire()
                return wire["answers"], wire["usage"]["input_tokens"], (time.perf_counter() - started) * 1000
            return decide
        name = options.get("model_name", "Decision model")
    decide = thread.submit(build).result()
    return {"engine": engine, "name": name, "decide": lambda state, questions, images: thread.submit(decide, state, questions, images).result()}


def question_for(inputs):
    """The question as System One takes it, and the names the page shows for options or levels."""
    kind = inputs.get("question_type") or "choose"
    instructions = (inputs.get("instructions") or "").strip()
    if kind == "yesno":
        return {"type": "noul", "instructions": instructions}, []
    if kind == "score":
        levels = lines(inputs.get("levels"))
        return {"type": "score", "instructions": instructions, "criteria": levels}, levels
    criteria = {}
    for line in lines(inputs.get("options")):
        name, _, meaning = line.partition(":")
        criteria[name.strip()] = meaning.strip() or name.strip()
    if len(criteria) > MAX_OPTIONS or len(criteria) < 2:
        raise ValueError(f"A choice needs 2 to {MAX_OPTIONS} different options.")
    return {"type": "choice", "instructions": instructions, "criteria": criteria}, list(criteria)


def normal(question, answer):
    """The model's answer in one shape for every engine: noul with a confidence, score with an integer level and the
    expected level, choice as given."""
    kind = question["type"]
    if kind == "noul":
        yes = float(answer["noul"])
        return {"type": "noul", "noul": yes, "confidence": answer.get("confidence", abs(2 * yes - 1))}
    probabilities = {str(key): float(value) for key, value in (answer.get("probabilities") or {}).items()}
    if kind == "score":
        top = max(probabilities, key=probabilities.get)
        expected = answer.get("score")
        expected = sum(int(key) * value for key, value in probabilities.items()) if not isinstance(expected, (int, float)) else float(expected)
        return {"type": "score", "score": int(top), "expected_level": expected, "probabilities": probabilities,
                "confidence": answer.get("confidence")}
    return {"type": "choice", "choice": answer.get("choice") or max(probabilities, key=probabilities.get),
            "probabilities": probabilities, "confidence": answer.get("confidence")}


def generate(model, inputs, job):
    question, _ = question_for(inputs)
    state = inputs["state"].strip()
    job.report("Reading the situation")
    started = time.perf_counter()
    images = [picture["path"] for picture in inputs.get("pictures") or []]
    answers, tokens, forward_ms = model["decide"](state, {"q": question}, images)
    seconds = time.perf_counter() - started
    answer = normal(question, answers["q"])
    job.detail(engine=model["engine"], model=model["name"], input_tokens=tokens, forward_ms=round(forward_ms), pictures=len(images), question=question)
    job.output("decision.json", "application/json").write_text(
        json.dumps({"question": question, "answer": answer, "model": model["name"], "input_tokens": tokens}, indent=1), encoding="utf-8")
    job.output("result.md", "text/markdown").write_text(render(question, answer, model=model["name"], seconds=seconds), encoding="utf-8")
    job.report("Done")


if __name__ == "__main__":
    serve(load, generate)
