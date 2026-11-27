"""One `make_image` chat tool for every running picture model.

The model gives a description and, if it wants them, a shape, a size, a quality, things to avoid, a seed, results to start from
(which edits them) and which model. This module picks the running model that can do it, picks the tab (a picture from words, or an
edit of pictures) and fills that tab's own fields through the model's `image` capability (`plugins/images.py`), so the chat needs no
tool per model. What a model cannot take is left out and said in the result.
"""

PARAMETERS = {
    "shape": "The shape of the picture.",
    "size": "How big the picture is, for models that ask.",
    "quality": "Quality, for models that have the choice.",
    "negative": "Things to keep out of the picture, for models that take them.",
}


class ImageTool:
    def __init__(self, fields_of=None):
        # fields_of(plugin, runtime, mode) -> {field key: InputSpec}; the chat gives the runtime's own (narrowed) form.
        self.fields_of = fields_of or (lambda plugin, runtime, mode: plugin.mode_inputs(mode or None, runtime) or {})

    def _spec(self, item, mode, role):
        _, runtime, plugin = item
        key = plugin.image.roles.get(mode, {}).get(role)
        return key, (self.fields_of(plugin, runtime, mode).get(key) if key else None)

    def _has(self, item, role):
        """Whether the model's form has a field for the role, on its tab that makes a picture from words."""
        return self._spec(item, item[2].image.create or "", role)[1] is not None

    def _options(self, item, role):
        """The values a model takes for a choice role on its tab that makes a picture from words."""
        _, spec = self._spec(item, item[2].image.create or "", role)
        return list(spec.options) if spec is not None and getattr(spec, "options", None) else []

    def schema(self, running):
        """The tool for the picture models running now (a list of (model_id, runtime, plugin)), or None."""
        if not running:
            return None
        lines = ["Make a picture with a picture model running now. Pass the description in `prompt`; everything else is optional."]
        for item in running:
            model_id, runtime, plugin = item
            info = plugin.image
            parts = [f"shape: {', '.join(self._options(item, 'shape'))}" if self._options(item, "shape") else None,
                     f"size: {', '.join(self._options(item, 'size'))}" if self._options(item, "size") else None,
                     "quality choice" if self._has(item, "quality") else None, "negative prompt" if self._has(item, "negative") else None,
                     "custom size" if self._has(item, "width") else None, "start from a picture (`start_picture`)" if self._has(item, "start") else None,
                     "can edit the pictures given in `pictures`" if info.edit is not None else None]
            lines.append(f"- {runtime.name} (id {model_id}): {info.guidance}" + (" Takes: " + "; ".join(p for p in parts if p) + "." if any(parts) else ""))
        properties = {
            "prompt": {"type": "string", "maxLength": 3000, "description": "What the picture shows: subject, setting, light, style."},
            "shape": {"type": "string", "description": PARAMETERS["shape"]},
            "size": {"type": "string", "description": PARAMETERS["size"]},
            "quality": {"type": "string", "description": PARAMETERS["quality"]},
            "negative_prompt": {"type": "string", "description": PARAMETERS["negative"]},
            "seed": {"type": "integer", "description": "A seed, to repeat a picture."},
            "width": {"type": "integer", "description": "Custom width in pixels (256 to 2048), with `height`, for models that take a custom size."},
            "height": {"type": "integer", "description": "Custom height in pixels (256 to 2048), with `width`."},
            "steps": {"type": "integer", "description": "Painting steps, for models that take them; leave out for the model's own."},
        }
        if any(self._has(item, "start") for item in running):
            properties["start_picture"] = {"type": "string", "description": "Reference (8 characters, such as 1a2b3c4d) of an earlier picture to begin from, for models that can; the new picture is a variation of it, so describe the whole picture."}
            properties["strength"] = {"type": "integer", "description": "With start_picture: percent (5 to 95), how closely the result follows it. Default 40."}
        if any(item[2].image.edit is not None for item in running):
            properties["pictures"] = {"type": "array", "items": {"type": "string"}, "maxItems": 4,
                                      "description": "References (8 characters, such as 1a2b3c4d) of earlier pictures to start from; the prompt then says what to make with them."}
        if len(running) > 1:
            properties["model"] = {"type": "string", "enum": [model_id for model_id, _, _ in running],
                                   "description": "Which model. Leave out to let the tool choose one that can do what was asked."}
        return {"type": "function", "function": {"name": "make_image", "description": "\n".join(lines)[:4000],
                                                 "parameters": {"type": "object", "properties": properties, "required": ["prompt"]}}}

    def plan(self, arguments, running):
        """(model_id, runtime, plugin, mode, inputs, references, notes) for a call, or ValueError saying what is wrong.
        `references` maps a files field to the result references to copy in."""
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Give the description in `prompt`.")
        pictures = arguments.get("pictures") or []
        if not isinstance(pictures, list) or not all(isinstance(ref, str) for ref in pictures):
            raise ValueError("`pictures` takes a list of result references.")
        by_id = {item[0]: item for item in running}
        asked = arguments.get("model")
        if asked is not None and asked not in by_id:
            raise ValueError(f"{asked} is not running. Running: {', '.join(by_id)}.")
        if asked:
            chosen = by_id[asked]
        else:
            chosen = next((item for item in running if pictures and item[2].image.edit is not None), running[0])
        model_id, runtime, plugin = chosen
        info = plugin.image
        if pictures and info.edit is None:
            able = [r.name for _, r, p in running if p.image.edit is not None]
            raise ValueError(f"{runtime.name} cannot start from pictures." + (f" Use {' or '.join(able)}." if able else " No running model can."))
        mode = info.edit if pictures else info.create
        roles = info.roles[mode]
        form = self.fields_of(plugin, runtime, mode)
        start = arguments.get("start_picture")
        width, height = arguments.get("width"), arguments.get("height")
        shape = arguments.get("shape") or ("custom" if width and height and "width" in roles else None)
        values = {"prompt": prompt.strip(), "shape": shape, "size": arguments.get("size"), "quality": arguments.get("quality"),
                  "negative": arguments.get("negative_prompt"), "seed": arguments.get("seed"), "width": width, "height": height,
                  "steps": arguments.get("steps"), "strength": arguments.get("strength") if start else None}
        inputs = {"mode": mode} if plugin.modes else {}
        notes = []
        for role, value in values.items():
            if value in (None, ""):
                continue
            if role in roles and roles[role] in form:
                inputs[roles[role]] = value
            elif role != "prompt":
                notes.append(f"the {'things to avoid' if role == 'negative' else role} (this model has no place for it)")
        references = {roles["pictures"]: pictures} if pictures else {}
        if start:
            if not isinstance(start, str):
                raise ValueError("`start_picture` takes one result reference.")
            if "start" in roles and roles["start"] in form:
                references[roles["start"]] = [start]
            else:
                notes.append("the starting picture (this model cannot begin from one)")
        return model_id, runtime, plugin, mode, inputs, references, notes
