"""What a video model can do, in one shape, so one page can serve every video model.

A video plugin declares a `video` capability next to its fields. The Video page reads it to show only what the chosen model takes
(a last picture, sound prompts, a clip to continue), to give that model's guidance for describing a clip, to turn a length such as
"short" into seconds so a length carries from one model to another, and to carry what the person typed by *role* instead of by each
model's own field names.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict

ROLES = ("prompt", "shape", "resolution", "length", "quality", "speed", "negative", "sounds", "music", "seed", "first", "last",
         "source", "references", "videos", "audio", "notes")


class VideoInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # How to describe a clip to this model, in a sentence or two.
    guidance: str
    # Whether the clip comes with sound: none, made by the model on its own, or made from the sound and music prompts.
    sound: Literal["none", "automatic", "prompted"] = "none"
    # The tab that makes a clip from a description ("" is a plugin with no tabs); the tab that starts from a first picture
    # (a last one too where the model takes it); the tab that starts from references; the tab that continues a clip.
    create: str = ""
    picture: str | None = None
    references: str | None = None
    extend: str | None = None
    # Each length choice in seconds, for carrying a length from one model to another.
    seconds: dict[str, float]
    # tab -> role -> the field that holds it there. Only these tabs belong to the Video page.
    roles: dict[str, dict[str, str]]

    def check(self, plugin) -> list[str]:
        """Problems with this declaration against the plugin's own tabs and fields (a test runs it for each video plugin)."""
        problems = []
        for mode, roles in self.roles.items():
            if plugin.modes and mode not in plugin.modes:
                problems.append(f"roles for the missing mode {mode!r}")
                continue
            fields = plugin.modes[mode].inputs if plugin.modes else plugin.inputs
            if "prompt" not in roles:
                problems.append(f"{mode!r} has no prompt role")
            for role, key in roles.items():
                if role not in ROLES:
                    problems.append(f"{mode!r}: unknown role {role!r}")
                if key not in fields:
                    problems.append(f"{mode!r}: role {role} names the missing field {key!r}")
            if "length" in roles:
                options = fields[roles["length"]].options if roles["length"] in fields else ()
                for option in options:
                    if option not in self.seconds:
                        problems.append(f"{mode!r}: the length {option!r} has no seconds")
        for name, mode in (("create", self.create), ("picture", self.picture), ("references", self.references), ("extend", self.extend)):
            if mode is not None and mode not in self.roles:
                problems.append(f"{name} names the tab {mode!r}, which has no roles")
        if self.picture is not None and "first" not in self.roles.get(self.picture, {}):
            problems.append("the picture tab has no first role")
        if self.extend is not None and "source" not in self.roles.get(self.extend, {}):
            problems.append("the extend tab has no source role")
        return problems

    def for_runtime(self, fields_of) -> "VideoInfo":
        """The same capability with the roles whose field this model's form does not have taken out."""
        roles = {mode: {role: key for role, key in mapping.items() if key in (fields_of(mode) or {})} for mode, mapping in self.roles.items()}
        return self.model_copy(update={"roles": roles})
