import importlib.util
import sys
from pathlib import Path

from generationstation.plugins.decide import DecidePlugin

WORKERS = Path(__file__).resolve().parents[2] / "workers"
plugin = DecidePlugin()


def worker(name):
    sys.path.insert(0, str(WORKERS))
    spec = importlib.util.spec_from_file_location(name, WORKERS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def problems(**values):
    return plugin.check_inputs(None, values, {})


def test_choice_needs_two_different_options():
    assert problems(question_type="choose", options="billing") != []
    assert problems(question_type="choose", options="billing\nBilling: again") != []
    assert problems(question_type="choose", options="billing: charges\nshipping") == []
    assert problems(question_type="choose", options="\n".join(f"o{i}" for i in range(256))) != []
    assert problems(question_type="choose", options="\n".join(f"o{i}" for i in range(255))) == []


def test_scale_and_yes_no_rules():
    assert problems(question_type="score", levels="calm") != []
    assert problems(question_type="score", levels="calm\nangry") == []
    assert problems(question_type="yesno", instructions="") != []
    assert problems(question_type="yesno", instructions="Wants a refund?") == []


def test_question_and_answer_shapes():
    decide = worker("decide_worker")
    question, names = decide.question_for({"question_type": "choose", "instructions": "Which team?", "options": "billing: charges\nshipping"})
    assert question["criteria"] == {"billing": "charges", "shipping": "shipping"} and names == ["billing", "shipping"]
    answer = decide.normal({"type": "noul"}, {"noul": 0.9})
    assert answer["confidence"] == 0.8  # chance-corrected, as System One reports it
    scored = decide.normal({"type": "score"}, {"score": 1.6, "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6}})
    assert scored["score"] == 2 and scored["expected_level"] == 1.6


def test_result_page_marks_close_calls():
    render = worker("decide_render")
    question = {"type": "choice", "instructions": "Which team?"}
    close = render.render(question, {"type": "choice", "choice": "a", "confidence": 0.1, "probabilities": {"a": 0.52, "b": 0.48}})
    assert "Close call" in close and "52.0%" in close
    sure = render.render(question, {"type": "choice", "choice": "a", "confidence": 0.9, "probabilities": {"a": 0.95, "b": 0.05}})
    assert "Close call" not in sure
