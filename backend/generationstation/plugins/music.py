"""What a song model can do, in one shape, so one page can serve every song model.

A song plugin declares a `music` capability next to its fields. The Music page reads it to show only what the chosen model takes
(a length, a tempo, starting from a song), to give that model's guidance for writing a style and lyrics, and to carry what the
person typed from one model to another by *role* instead of by each model's own field names.
"""
from pydantic import BaseModel, ConfigDict

ROLES = ("style", "lyrics", "length", "language", "tempo", "key", "time_signature", "steps", "seed", "source", "strength", "start", "end")


class MusicInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # How to describe a song to this model and how to write its lyrics, in a sentence or two.
    guidance: str
    # The tab that makes a song from a style and lyrics ("" is a plugin with no tabs), and the tabs that start from a song:
    # a new version of it, and a redo of one section of it.
    create: str = ""
    cover: str | None = None
    repaint: str | None = None
    # tab -> role -> the field that holds it there.
    roles: dict[str, dict[str, str]]

    def check(self, plugin) -> list[str]:
        """Problems with this declaration against the plugin's own tabs and fields (a test runs it for each song plugin)."""
        problems = []
        for mode, roles in self.roles.items():
            if plugin.modes and mode not in plugin.modes:
                problems.append(f"roles for the missing mode {mode!r}")
                continue
            fields = plugin.modes[mode].inputs if plugin.modes else plugin.inputs
            for role in ("style",):
                if role not in roles:
                    problems.append(f"{mode!r} has no {role} role")
            for role, key in roles.items():
                if role not in ROLES:
                    problems.append(f"{mode!r}: unknown role {role!r}")
                if key not in fields:
                    problems.append(f"{mode!r}: role {role} names the missing field {key!r}")
        for name, mode in (("create", self.create), ("cover", self.cover), ("repaint", self.repaint)):
            if mode is not None and mode not in self.roles:
                problems.append(f"{name} names the tab {mode!r}, which has no roles")
            if name != "create" and mode is not None and "source" not in self.roles.get(mode, {}):
                problems.append(f"the {name} tab has no source role")
        return problems

    def for_runtime(self, fields_of) -> "MusicInfo":
        """The same capability with the roles whose field this model's form does not have taken out."""
        roles = {mode: {role: key for role, key in mapping.items() if key in (fields_of(mode) or {})} for mode, mapping in self.roles.items()}
        return self.model_copy(update={"roles": roles})
