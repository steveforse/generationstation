"""One `make_video` chat tool for every running video model.

The model gives a description and, if it wants them, a shape, a length in seconds, a quality, things to avoid, sounds and music, a
seed, earlier pictures to start from or end on, an earlier clip to continue and which model. This module picks the running model
that can do it, picks the tab (a description, pictures, or a clip to continue) and fills that tab's own fields through the model's
`video` capability (`plugins/video.py`), so the chat needs no tool per model and way. What a model cannot take is left out and said
in the result.
"""

WORDS = {"shape": "the shape", "length": "the length", "quality": "the quality", "speed": "the speed", "resolution": "the resolution",
         "negative": "the things to avoid", "sounds": "the sounds", "music": "the music", "seed": "the seed",
         "first": "the first picture", "last": "the last picture", "source": "the clip to continue"}


class VideoTool:
    def __init__(self, fields_of=None):
        # fields_of(plugin, runtime, mode) -> {field key: InputSpec}; the chat gives the runtime's own (narrowed) form.
        self.fields_of = fields_of or (lambda plugin, runtime, mode: plugin.mode_inputs(mode or None, runtime) or {})

    def _spec(self, item, mode, role):
        _, runtime, plugin = item
        key = plugin.video.roles.get(mode, {}).get(role)
        return key, (self.fields_of(plugin, runtime, mode).get(key) if key else None)

    def _has(self, item, role, mode=None):
        return self._spec(item, item[2].video.create if mode is None else mode, role)[1] is not None

    @staticmethod
    def _tab(info, first, last, source):
        """The tab a call needs: a clip to continue, pictures to start from or end on, or a description alone."""
        if source:
            return info.extend
        if first or last:
            return info.picture
        return info.create

    def schema(self, running):
        """The tool for the video models running now (a list of (model_id, runtime, plugin)), or None."""
        if not running:
            return None
        lines = ["Make a video clip with a video model running now. Pass the description in `prompt`; everything else is optional."]
        for item in running:
            model_id, runtime, plugin = item
            info = plugin.video
            _, length = self._spec(item, info.create, "length")
            _, shape = self._spec(item, info.create, "shape")
            parts = []
            if length is not None:
                parts.append("length in seconds: " + ", ".join(f"{info.seconds[option]:g}" for option in length.options if option in info.seconds))
            if shape is not None and shape.options:
                parts.append("shape: " + ", ".join(shape.options))
            parts += [text for role, text in (("quality", "quality"), ("speed", "speed"), ("resolution", "resolution"), ("negative", "things to avoid"),
                                              ("sounds", "sounds and music")) if self._has(item, role)]
            if info.picture is not None:
                parts.append("start from a picture (`first_picture`)" + (" and end on one (`last_picture`)" if self._has(item, "last", info.picture) else ""))
            if info.extend is not None:
                parts.append("continue an earlier clip (`source_clip`)")
            sound = {"none": "silent clips", "automatic": "clips come with sound it makes itself", "prompted": "sound from the sounds and music fields"}[info.sound]
            lines.append(f"- {runtime.name} (id {model_id}): {info.guidance} Makes {sound}. Takes: " + "; ".join(parts) + ".")
        properties = {
            "prompt": {"type": "string", "maxLength": 3000, "description": "What the clip shows and what happens, in order: subject, motion, setting, light, camera."},
            "shape": {"type": "string", "description": "landscape, portrait or square, for models that ask; the closest the model offers is used."},
            "length": {"type": "number", "description": "Seconds of video; the nearest length the model offers is used."},
            "quality": {"type": "string", "description": "A quality choice, for models that have one (such as draft, standard, quick, sharp)."},
            "negative_prompt": {"type": "string", "description": "Things to keep out of the clip, for models that take them."},
            "sounds": {"type": "string", "description": "What should be heard (not the music), for models that take it."},
            "music": {"type": "string", "description": "The music, for models that take it."},
            "seed": {"type": "integer", "description": "A seed, to repeat a clip."},
        }
        if any(item[2].video.picture is not None for item in running):
            properties["first_picture"] = {"type": "string", "description": "Reference (8 characters, such as 1a2b3c4d) of an earlier picture the clip starts from."}
            properties["last_picture"] = {"type": "string", "description": "Reference of an earlier picture the clip ends on, for models that take one."}
        if any(item[2].video.extend is not None for item in running):
            properties["source_clip"] = {"type": "string", "description": "Reference of an earlier clip to continue: the new clip carries on from where it ended, and the prompt says what happens next."}
        if len(running) > 1:
            properties["model"] = {"type": "string", "enum": [model_id for model_id, _, _ in running],
                                   "description": "Which model. Leave out to let the tool choose one that can do what was asked."}
        return {"type": "function", "function": {"name": "make_video", "description": "\n".join(lines)[:4000],
                                                 "parameters": {"type": "object", "properties": properties, "required": ["prompt"]}}}

    def plan(self, arguments, running):
        """(model_id, runtime, plugin, mode, inputs, references, notes) for a call, or ValueError saying what is wrong.
        `references` maps a files field to the result references to copy in."""
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("Give the description in `prompt`.")
        first, last, source = arguments.get("first_picture"), arguments.get("last_picture"), arguments.get("source_clip")
        for name, ref in (("first_picture", first), ("last_picture", last), ("source_clip", source)):
            if ref is not None and not isinstance(ref, str):
                raise ValueError(f"`{name}` takes one result reference.")
        if source and (first or last):
            raise ValueError("Continue a clip or start from pictures, not both.")
        by_id = {item[0]: item for item in running}
        asked = arguments.get("model")
        if asked is not None and asked not in by_id:
            raise ValueError(f"{asked} is not running. Running: {', '.join(by_id)}.")
        chosen = by_id[asked] if asked else next((item for item in running if self._tab(item[2].video, first, last, source) is not None), None)
        what = "continue a clip" if source else "start from pictures"
        if chosen is None or self._tab(chosen[2].video, first, last, source) is None:
            able = [r.name for _, r, p in running if self._tab(p.video, first, last, source) is not None]
            who = f"{chosen[1].name} cannot {what}." if chosen else f"No running model can {what}."
            raise ValueError(who + (f" Use {' or '.join(able)}." if able else ""))
        model_id, runtime, plugin = chosen
        info = plugin.video
        mode = self._tab(info, first, last, source)
        roles = info.roles[mode]
        form = self.fields_of(plugin, runtime, mode)
        values = {"prompt": prompt.strip(), "shape": arguments.get("shape"), "length": arguments.get("length"), "quality": arguments.get("quality"),
                  "negative": arguments.get("negative_prompt"), "sounds": arguments.get("sounds"), "music": arguments.get("music"), "seed": arguments.get("seed")}
        inputs = {"mode": mode} if plugin.modes else {}
        notes = []
        for role, value in values.items():
            if value in (None, ""):
                continue
            field = roles.get(role)
            if field is None or field not in form:
                if role != "prompt":
                    notes.append(f"{WORDS.get(role, role)} (this model has no place for it)")
                continue
            spec = form[field]
            if role == "length" and spec.options:  # the nearest length the model offers
                try:
                    value = min((option for option in spec.options if option in info.seconds), key=lambda option: abs(info.seconds[option] - float(value)))
                except (TypeError, ValueError):
                    notes.append("the length (it was not a number of seconds)")
                    continue
            elif role == "shape" and spec.options:  # the option that starts with the same word
                word = str(value).lower().split()[0]
                value = next((option for option in spec.options if option.lower().startswith(word)), None)
                if value is None:
                    notes.append("the shape (this model has no such shape)")
                    continue
            inputs[field] = value
        references = {}
        for role, ref in (("first", first), ("last", last), ("source", source)):
            if not ref:
                continue
            if role in roles and roles[role] in form:
                references[roles[role]] = [ref]
            else:
                notes.append(f"{WORDS[role]} (this model has no place for it)")
        return model_id, runtime, plugin, mode, inputs, references, notes
