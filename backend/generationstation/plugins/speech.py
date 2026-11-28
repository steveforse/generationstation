"""What a speech model can do, in one shape, so one page can serve every speech model.

Each speech plugin declares a `speech` capability next to its modes. The page reads it to show only the voice sources a
model has, to explain how that model takes direction (emotion), and to carry what the person typed from one model to
another by *role* (text, language, voice sample, ...) instead of by each model's own field names.
"""
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

ROLES = ("text", "language", "seed", "speed", "direction", "builtin_voice", "voice_description", "sample", "sample_text")
SOURCES = ("builtin", "design", "clone", "own")


class Cues(BaseModel):
    """Cues written into the text, such as [whispers] or (laugh)."""
    model_config = ConfigDict(extra="forbid")
    open: str
    close: str
    # "emotion": the delivery from that point on; "sounds": a sound at that point (a laugh, a sigh).
    kind: Literal["emotion", "sounds"]
    # True when any short description works ([whispers], [super happy]); False when only the listed ones do.
    open_vocabulary: bool
    examples: list[str] = Field(min_length=1)
    text: str


class Direction(BaseModel):
    """How a model takes direction: a field of plain words, cues in the text, both, or neither."""
    model_config = ConfigDict(extra="forbid")
    text: str                                                       # what this model does with direction, in a sentence or two
    examples: list[str] = Field(default_factory=list)               # examples for the plain-words field
    style_fields: dict[str, str] = Field(default_factory=dict)      # mode -> the field that takes the plain words
    cues: Cues | None = None

    @property
    def acts_emotion(self) -> bool:
        return bool(self.style_fields) or (self.cues is not None and self.cues.kind == "emotion")


class SpeechInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Voice source -> the mode that serves it. "own" is the model's own voice (no sample, no description).
    voices: dict[str, str]
    scene: str | None = None                                        # the mode for several voices in one scene
    direction: Direction
    # mode -> role -> the field that holds it in that mode. A field with no role is model-specific (OmniVoice's traits).
    roles: dict[str, dict[str, str]]

    def check(self, plugin) -> list[str]:
        """Problems with this declaration against the plugin's own modes and fields (a test runs it for each plugin)."""
        problems = []
        modes = plugin.modes
        for source, mode in self.voices.items():
            if source not in SOURCES:
                problems.append(f"unknown voice source {source!r}")
            if mode not in modes:
                problems.append(f"voice source {source} names the missing mode {mode!r}")
        if self.scene is not None and self.scene not in modes:
            problems.append(f"scene names the missing mode {self.scene!r}")
        for mode, roles in self.roles.items():
            if mode not in modes:
                problems.append(f"roles for the missing mode {mode!r}")
                continue
            for role, key in roles.items():
                if role not in ROLES:
                    problems.append(f"{mode}: unknown role {role!r}")
                if key not in modes[mode].inputs:
                    problems.append(f"{mode}: role {role} names the missing field {key!r}")
        for mode, key in self.direction.style_fields.items():
            if key not in modes.get(mode, ModeLess).inputs:
                problems.append(f"direction style field {key!r} is not in mode {mode!r}")
        for mode in modes:
            if mode not in self.roles:
                problems.append(f"mode {mode!r} has no roles")
        return problems


class ModeLess:
    inputs: ClassVar[dict] = {}
