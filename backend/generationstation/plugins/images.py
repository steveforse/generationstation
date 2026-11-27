"""What a picture model can do, in one shape, so one page can serve every picture model.

An image plugin (or the picture modes of a video plugin) declares an `image` capability next to its fields. The Images page reads
it to show only what the chosen model takes (a negative prompt, a quality control, starting from pictures), to give that model's
guidance for describing a picture, and to carry what the person typed from one model to another by *role* instead of by each
model's own field names.
"""
from pydantic import BaseModel, ConfigDict

ROLES = ("prompt", "shape", "size", "quality", "negative", "seed", "pictures", "notes")


class ImageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # How to describe a picture to this model, in a sentence or two.
    guidance: str
    # The tab that makes a picture from a description, and the tab that starts from pictures (editing); "" is a plugin with no tabs.
    create: str | None = None
    edit: str | None = None
    # tab -> role -> the field that holds it there. Only these tabs belong to the Images page.
    roles: dict[str, dict[str, str]]

    def check(self, plugin) -> list[str]:
        """Problems with this declaration against the plugin's own tabs and fields (a test runs it for each image plugin)."""
        problems = []
        for mode, roles in self.roles.items():
            fields = plugin.modes[mode].inputs if plugin.modes else plugin.inputs
            if plugin.modes and mode not in plugin.modes:
                problems.append(f"roles for the missing mode {mode!r}")
                continue
            if "prompt" not in roles:
                problems.append(f"{mode!r} has no prompt role")
            for role, key in roles.items():
                if role not in ROLES:
                    problems.append(f"{mode!r}: unknown role {role!r}")
                if key not in fields:
                    problems.append(f"{mode!r}: role {role} names the missing field {key!r}")
        for name, mode in (("create", self.create), ("edit", self.edit)):
            if mode is not None and mode not in self.roles:
                problems.append(f"{name} names the tab {mode!r}, which has no roles")
        if self.edit is not None and "pictures" not in self.roles.get(self.edit, {}):
            problems.append("the edit tab has no pictures role")
        return problems

    def for_runtime(self, fields_of) -> "ImageInfo":
        """The same capability with the roles whose field this model's form does not have taken out (`fields_of(mode)` is the
        form's fields). A model that takes no negative prompt then has no negative role."""
        roles = {mode: {role: key for role, key in mapping.items() if key in (fields_of(mode) or {})} for mode, mapping in self.roles.items()}
        return self.model_copy(update={"roles": roles})
