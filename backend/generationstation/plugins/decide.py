"""Decide: give a decision model a situation and a question, get back how likely each answer is.

A decision model reads the situation once and answers a multiple-choice, yes/no or scored question in a single forward
pass, so the answer comes with a probability for every option and takes a fraction of a second (a chat model would write
a paragraph). It is the open-weight counterpart of TypeSafe's hosted Jev. The worker (workers/decide_worker.py) loads one
of several engines, chosen by the preset's `engine` option.
"""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

MAX_STATE = 20000  # characters
MAX_OPTIONS = 255  # the readout of these models has 255 slots
MAX_LEVELS = 10


class DecidePreset(WorkerPreset):
    pass


class DecideRuntime(WorkerRuntime):
    kind: Literal["decide"]
    presets: dict[str, DecidePreset] = Field(min_length=1)


def split_lines(text: str | None) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def option_names(text: str | None) -> list[str]:
    """The option lines: "name" or "name: what it means". The names must differ."""
    return [line.split(":", 1)[0].strip() for line in split_lines(text)]


READS_PICTURES = {"mlx_decision"}  # the worker engines whose models take pictures with the text (the Torchcast engines do not)


class DecidePlugin(WorkerPlugin):
    kind = "decide"
    title = "Decide"
    description = ("Answers a question about a situation with a probability for each answer, in one pass and well under a "
                   "second for a short text. Choose between options, answer yes or no, or place something on a scale.")
    runtime_model = DecideRuntime
    worker_script = "decide_worker.py"
    max_gpus = 1
    output_kind = "document"
    make_label = "Decide"
    result_noun = "decision"
    inputs: ClassVar[dict[str, InputSpec]] = {
        "state": InputSpec(
            label="Situation", kind="textarea", required=True, max_length=MAX_STATE,
            placeholder="Hi, I was charged twice for my March order and I would like one of the charges refunded.",
            help="What the model should read: a message, a ticket, a document excerpt. Longer text takes longer "
                 "(about a second for 1,000 words)."),
        "pictures": InputSpec(
            label="Pictures", kind="files", accept=("image",), max_count=4,
            help="Optional: a receipt, a screenshot, a photo, read along with the text."),
        "question_type": InputSpec(
            label="Question", kind="choice", required=True, options=("choose", "yesno", "score"), default="choose",
            option_labels={"choose": "Choose between options", "yesno": "Yes or no", "score": "Place on a scale"},
            help="Choose gives a probability for each option, yes or no gives how likely yes is, a scale gives a "
                 "probability for each level and the expected level."),
        "instructions": InputSpec(
            label="Ask", kind="text", required=True, max_length=400, placeholder="Which team should handle this?",
            help="The question, in a few words."),
        "options": InputSpec(
            label="Options", kind="textarea", required=True, max_length=6000, show_when={"question_type": "choose"},
            placeholder="billing: charges and refunds\nshipping: deliveries\ntech support: login and bugs",
            help=f"One option per line, 2 to {MAX_OPTIONS}. After a colon you can say what the option means; the model "
                 "reads it. Names must differ."),
        "levels": InputSpec(
            label="Scale levels", kind="textarea", required=True, max_length=2000, show_when={"question_type": "score"},
            placeholder="calm\nannoyed\nangry\nfurious",
            help=f"One level per line, lowest first, 2 to {MAX_LEVELS}."),
    }
    # Measured on an M5 Max (2026-11-27), one question, a situation of a few hundred words, model already running:
    # Torchcast 4B and H2O-Lightning 4B (bf16) about 0.2 s, Torchcast 31B (mlx8) about 0.5 s, pplx-decider 27B (q8) about 0.5 s.
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        TimingSpec(when={}, preset="bf16", seconds=1, note="for a situation of a few hundred words"),
        TimingSpec(when={}, preset="mlx8", seconds=1, note="for a situation of a few hundred words"),
        TimingSpec(when={}, preset="q8", seconds=1, note="for a situation of a few hundred words"),
    )

    def reads_pictures(self, runtime) -> bool:
        return any(preset.options.get("engine") in READS_PICTURES for preset in runtime.presets.values())

    def mode_inputs(self, mode, runtime=None):
        """The form of a model that cannot read pictures has no picture field (and a request with one is refused)."""
        inputs = super().mode_inputs(mode, runtime)
        if runtime is not None and inputs is not None and not self.reads_pictures(runtime):
            return {key: spec for key, spec in inputs.items() if key != "pictures"}
        return inputs

    def check_inputs(self, mode, values, files):
        problems = []
        kind = values.get("question_type") or "choose"
        if kind == "choose":
            names = option_names(values.get("options"))
            if len(names) < 2:
                problems.append("Give at least two options, one per line.")
            elif len(names) > MAX_OPTIONS:
                problems.append(f"Give at most {MAX_OPTIONS} options.")
            elif len({name.lower() for name in names}) != len(names):
                problems.append("Each option needs a different name.")
            elif any(not name for name in names):
                problems.append("An option line needs a name before the colon.")
        elif kind == "score":
            levels = split_lines(values.get("levels"))
            if not 2 <= len(levels) <= MAX_LEVELS:
                problems.append(f"Give 2 to {MAX_LEVELS} levels, one per line.")
        return problems
