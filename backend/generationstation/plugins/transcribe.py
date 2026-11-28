"""What a speech-to-text model can do, in one shape, so one page can serve every transcription model.

A transcription plugin declares a `transcribe` capability next to its fields. The Transcribe page reads it to show only what the chosen
model takes (a language, words to expect, who spoke), to say what the model gives back (times on each line, speaker labels of its own),
and to carry what the person chose from one model to another by *role* instead of by each model's own field names.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict

ROLES = ("recording", "language", "terms", "speakers")


class TranscribeInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # What this model is good at and what to expect from it, in a sentence or two.
    guidance: str
    # Whether each line of the result has times (and so captions can be written).
    times: Literal["none", "lines"] = "none"
    # Who spoke: "turns" when the speaker turns of the meeting notes are laid over the model's text, "none" when that is not set up
    # on this computer or does not fit the model.
    speakers: Literal["none", "turns"] = "none"
    # The longest recording it was checked on, in minutes (a longer file is tried, with a warning on the page).
    checked_minutes: int
    # tab -> role -> the field that holds it there. These plugins have one form, under "".
    roles: dict[str, dict[str, str]]

    def check(self, plugin) -> list[str]:
        """Problems with this declaration against the plugin's own fields (a test runs it for each transcription plugin)."""
        problems = []
        for mode, roles in self.roles.items():
            if plugin.modes and mode not in plugin.modes:
                problems.append(f"roles for the missing mode {mode!r}")
                continue
            fields = plugin.modes[mode].inputs if plugin.modes else plugin.inputs
            if "recording" not in roles:
                problems.append(f"{mode!r} has no recording role")
            for role, key in roles.items():
                if role not in ROLES:
                    problems.append(f"{mode!r}: unknown role {role!r}")
                if key not in fields:
                    problems.append(f"{mode!r}: role {role} names the missing field {key!r}")
        return problems

    def for_runtime(self, fields_of) -> "TranscribeInfo":
        """The same capability with the roles whose field this model's form does not have taken out (and who spoke set to what
        this computer can do)."""
        roles = {mode: {role: key for role, key in mapping.items() if key in (fields_of(mode) or {})} for mode, mapping in self.roles.items()}
        speakers = self.speakers if any("speakers" in mapping for mapping in roles.values()) else "none"
        return self.model_copy(update={"roles": roles, "speakers": speakers})
