"""MiniMax H3: makes a short video clip with sound from a description."""
from typing import ClassVar, Literal

from pydantic import Field

from .base import InputSpec, ModeSpec, SettingSpec, TimingSpec
from .worker import WorkerPlugin, WorkerPreset, WorkerRuntime

PROMPT = InputSpec(
    label="Description", kind="textarea", required=True, max_length=3000,
    placeholder="A red fox trots through a snowy pine forest at dawn, stops, looks at the camera "
                "and bounds away between the trees.",
    help="Describe what is seen and what happens, in order, and how the camera moves. For speech, "
         "write who speaks and put their words in quotes: She says: \"Wait for me by the clock.\"")
FRAMES_PROMPT = InputSpec(
    label="What happens", kind="textarea", required=True, max_length=3000,
    placeholder="She lifts her gaze from the letter toward the window and smiles as the train pulls out.",
    help="Describe the motion from the first frame or toward the last frame: who moves, how, and how the "
         "camera moves. Keep people and objects as they look in the pictures. For speech, put the words in "
         "quotes: He says: \"Here we go.\"")
REFERENCE_PROMPT = InputSpec(
    label="What happens", kind="textarea", required=True, max_length=3000,
    placeholder="The dog from picture 1 runs across the kitchen in picture 2 and jumps onto the sofa. "
                "The woman from picture 3 laughs and says: \"Not again!\"",
    help="Describe what happens and how the camera moves, naming the references by number: picture 1, "
         "video 1, audio 1. For speech, put the words in quotes.")
QUALITY_HELP = ("Low (Fast): 4 steps with the Turbo add-on, about 40 s for 5 s at 540p; good for drafts and trying ideas. "
                "Standard: 20 steps, about 2.5 min; good everyday quality. "
                "High: 30 steps, about 4 min; finer detail and steadier complex motion. "
                "Extreme: 50 steps, MiniMax's own default, about 6 min; for final renders. "
                "Lower resolutions are much faster.")
REFERENCE_QUALITY = InputSpec(
    label="Quality (steps)", kind="choice", options=("extreme", "high", "standard"), default="standard",
    help="Standard: 20 steps, good everyday quality. High: 30 steps, finer detail and steadier complex motion. "
         "Extreme: 50 steps, MiniMax's own default, for final renders. With references each step is slower than "
         "in the other tabs, and the references are read first. (The Turbo add-on is made for the other tabs.)")
SHAPES = ("landscape 16:9", "portrait 9:16", "square 1:1", "portrait 4:5", "classic 4:3")
SHAPE = InputSpec(
    label="Shape", kind="choice", options=SHAPES, default="landscape 16:9",
    help="Landscape for TVs and computers, portrait 9:16 for phones (full screen), portrait 4:5 for feeds, "
         "square, or classic 4:3.")
FRAMES_SHAPE = InputSpec(
    label="Shape", kind="choice", options=("match picture", *SHAPES), default="match picture",
    help="'match picture' keeps the picture's own proportions (the first frame's when there are two). Another "
         "shape crops the picture: choose the framing on the preview.")
RESOLUTION = InputSpec(
    label="Resolution", kind="choice",
    options=("1080p (AI upscale)", "1080p (fast resize)", "720p", "540p", "480p", "360p", "240p", "custom"),
    default="540p",
    help="The height of a landscape clip (the width of a portrait one). At Low (Fast) quality a 5 s clip takes "
         "about 6 s at 240p, 12 s at 360p, 30 s at 480p, 40 s at 540p and 90 s at 720p. 1080p does not fit on the "
         "card, so it is made smaller and enlarged: 'AI upscale' makes 540p and adds real detail with FlashVSR+ "
         "(about 45 s more; finest texture, may shimmer slightly on fast camera moves); 'fast resize' makes 720p "
         "and resizes it (about 4 s more; sharp but no added detail). 'Custom' lets you type a width and height.")
WIDTH = InputSpec(
    label="Custom width", kind="int", minimum=256, maximum=1344, default=960, show_when={"resolution": "custom"},
    ratio_partner="height", ratio_role="width", shape_field="shape",
    help="Pixels. Locked to the shape's proportions (unlock with the padlock): changing the width changes the "
         "height. Rounded to a multiple of 32; at most 1280 x 720 worth of pixels, the most that fits on the card.")
HEIGHT = InputSpec(
    label="Custom height", kind="int", minimum=256, maximum=1344, default=544, show_when={"resolution": "custom"},
    ratio_partner="width", ratio_role="height", shape_field="shape",
    help="Pixels. Locked to the shape's proportions like the width (unlock with the padlock). Rounded to a "
         "multiple of 32.")
MAX_PIXELS = 1280 * 720
LENGTH = InputSpec(
    label="Length", kind="choice", options=("5", "10", "15"), default="5",
    option_labels={"5": "5 seconds", "10": "10 seconds", "15": "14.4 seconds (longest)"},
    help="Longer clips take more than proportionally longer and need more of the card, so they are limited to "
         "smaller sizes: 10 seconds up to 540p, 15 seconds up to 480p. A 10 s clip takes about 2.5 times as long "
         "as a 5 s one.")
FRAMES = {"5": 124, "10": 243, "15": 345}
# Largest frames x pixels allowed for longer clips (15 s at 480p; 10 s at 540p is smaller), with the decoder and
# transformer taking turns on the RTX 5090.
MAX_FRAME_PIXELS = 345 * 864 * 480
SHORT_EDGES = {"240p": 256, "360p": 352, "480p": 480, "540p": 544, "720p": 704, "1080p (fast resize)": 704,
               "1080p (AI upscale)": 544}


def _render_pixels(values):
    """Approximately the pixels H3 renders per frame (the worker's canvas_size; pictures taken as 16:9)."""
    if values.get("resolution") == "custom":
        return (values.get("width") or 960) * (values.get("height") or 544)
    short = SHORT_EDGES.get(values.get("resolution") or "540p", 544)
    shape = values.get("shape") or "landscape 16:9"
    w, h = (16, 9) if shape == "match picture" else tuple(int(x) for x in shape.split()[-1].split(":"))
    ratio = max(w, h) / min(w, h)
    return short * round(short * ratio / 32) * 32
COMMON = {
    "sounds": InputSpec(
        label="Sounds", kind="text", max_length=500, placeholder="Crunching snow, wind in the pines, distant birds",
        help="The sounds of the scene. Leave empty for natural sounds that match it."),
    "music": InputSpec(
        label="Music", kind="text", max_length=300, placeholder="Soft acoustic guitar",
        help="Background music, if any. Leave empty for none."),
    "quality": InputSpec(
        label="Quality (steps)", kind="choice", options=("extreme", "high", "standard", "turbo"), default="turbo",
        option_labels={"turbo": "Low (Fast)"},
        help=QUALITY_HELP),
    "style": InputSpec(
        label="Look", kind="choice", options=("none", "cinematic", "handheld", "animated"), default="none",
        help="None adds nothing: the description (or the pictures) sets the look. Cinematic, Handheld and "
             "Animated add that look to the description.", advanced=True),
    "seed": InputSpec(
        label="Seed", kind="seed", minimum=0, maximum=2**31 - 1,
        help="Leave empty for a new clip each time. Reuse a seed to get the same clip again.", advanced=True),
}


FRAMES_STYLE = COMMON["style"].model_copy(update={
    "help": "None: the pictures set the look. The others add a look to the description."})


def _fields(prompt, shape, style=COMMON["style"], quality=COMMON["quality"], shape_first=False):
    """A mode's form: its description field, then sounds, music, shape, resolution, quality and the advanced
    fields. With pictures, shape and resolution come first, next to the pictures they frame."""
    size = {"shape": shape, "resolution": RESOLUTION, "width": WIDTH, "height": HEIGHT}
    rest = {"prompt": prompt, "sounds": COMMON["sounds"], "music": COMMON["music"]}
    size = {**size, "length": LENGTH}
    return {**(size if shape_first else {}), **rest, **({} if shape_first else size), "quality": quality,
            "style": style, "seed": COMMON["seed"]}


def _crop(target):
    return InputSpec(label=f"{target.capitalize()} frame framing", kind="crop", target=target, shape_field="shape",
                     help="The part of the picture that is kept when the shape differs from the picture's.")


# Pictures: H3 makes one frame instead of a clip (no sound), at several megapixels.
PICTURE_SIZE = InputSpec(
    label="Size", kind="choice", options=("1 MP", "2 MP", "4 MP", "8 MP"), default="4 MP",
    option_labels={"1 MP": "1 megapixel (about 1344 x 768)", "2 MP": "2 megapixels (about 1888 x 1056)",
                   "4 MP": "4 megapixels (about 2656 x 1504)", "8 MP": "8 megapixels (about 3776 x 2112)"},
    help="How many pixels the picture has (sizes shown for landscape 16:9). At High quality about 21 s at 2 MP, "
         "1 min at 4 MP and 2 min at 8 MP. Below 2 MP pictures are noticeably weaker.")
EDIT_SIZE = PICTURE_SIZE.model_copy(update={"options": ("1 MP", "2 MP", "4 MP"), "default": "2 MP",
                                           "help": "How many pixels the result has. 2 MP takes about 1.5 min at High quality."})
PICTURE_QUALITY = InputSpec(
    label="Quality (steps)", kind="choice", options=("extreme", "high", "standard"), default="high",
    help="Standard: 20 steps, about 35 s at 4 MP. High: 30 steps, about 1 min at 4 MP; finer detail. Extreme: 50 "
         "steps, for final pictures. (The Turbo add-on is made for clips and smears pictures.)")
PICTURE_PROMPT = InputSpec(
    label="Description", kind="textarea", required=True, max_length=3000,
    placeholder="A weathered fisherman in a yellow raincoat mends a net on a wooden pier at golden hour, gulls "
                "overhead, sharp detail on his hands, photographic, shallow depth of field.",
    help="Describe the picture: the subject, the setting, the light, the style and the framing.")
EDIT_PROMPT = InputSpec(
    label="What to make", kind="textarea", required=True, max_length=3000,
    placeholder="The bicycle from picture 1, painted bright blue, leans on a boardwalk railing at a sunny beach.",
    help="Say what to keep from the pictures and what changes, naming them \"picture 1\", \"picture 2\". H3 draws a "
         "new picture with them; it keeps their look but not every exact detail.")
PICTURE_SEED = COMMON["seed"].model_copy(update={
    "help": "Leave empty for a new picture each time. Reuse a seed to get the same picture again."})


class MiniMaxH3Preset(WorkerPreset):
    pass


class MiniMaxH3Runtime(WorkerRuntime):
    kind: Literal["minimax_h3"]
    presets: dict[str, MiniMaxH3Preset] = Field(min_length=1)


class MiniMaxH3Plugin(WorkerPlugin):
    kind = "minimax_h3"
    title = "MiniMax H3"
    description = ("Makes short video clips with matching sound, including spoken lines, from a written description; "
                   "also paints still pictures (up to 8 megapixels) and edits pictures.")
    runtime_model = MiniMaxH3Runtime
    worker_script = "minimax_h3_worker.py"
    max_gpus = 1
    output_kind = "video"
    # RTX 5090, Speed-up on: 5 s clips from the 2026-11-16 comparison, the 2026-11-21 API runs and direct worker
    # runs (resolutions, references).
    timings: ClassVar[tuple[TimingSpec, ...]] = (
        # Longer clips, 2026-11-22 through the app (decoder and transformer taking turns on the card); each was the
        # first clip of its length after a start.
        TimingSpec(when={"length": "10", "mode": "text", "quality": "turbo", "resolution": "480p"}, gpu=0, seconds=96),
        TimingSpec(when={"length": "10", "mode": "text", "quality": "turbo", "resolution": "540p"}, gpu=0, seconds=130),
        TimingSpec(when={"length": "15", "mode": "text", "quality": "turbo", "resolution": "480p"}, gpu=0, seconds=162),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "turbo", "resolution": "240p"}, gpu=0, seconds=6),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "turbo", "resolution": "360p"}, gpu=0, seconds=12),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "turbo", "resolution": "480p"}, gpu=0, seconds=29),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "turbo", "resolution": "540p"}, gpu=0, seconds=39, first_seconds=92),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "turbo", "resolution": "720p"}, gpu=0, seconds=89),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "turbo", "resolution": "1080p (fast resize)"}, gpu=0, seconds=100),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "turbo", "resolution": "1080p (AI upscale)"}, gpu=0, seconds=85,
                   note="about 45 s of it upscaling"),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "standard", "resolution": "540p"}, gpu=0, seconds=145, first_seconds=165),
        TimingSpec(when={"length": "5", "mode": "text", "quality": "standard", "resolution": "720p"}, gpu=0, seconds=372),
        TimingSpec(when={"length": "5", "mode": "frames", "quality": "turbo", "resolution": "540p"}, gpu=0, seconds=60),
        TimingSpec(when={"length": "5", "mode": "reference", "quality": "standard", "resolution": "540p"}, gpu=0, seconds=250,
                   note="with one picture at standard detail; each more picture adds about 45 s"),
        # Pictures (one frame), 2026-11-22 direct worker runs on the RTX 5090 without the speed-up.
        TimingSpec(when={"mode": "picture", "quality": "high", "size": "2 MP"}, gpu=0, seconds=21),
        TimingSpec(when={"mode": "picture", "quality": "standard", "size": "4 MP"}, gpu=0, seconds=38),
        TimingSpec(when={"mode": "picture", "quality": "high", "size": "4 MP"}, gpu=0, seconds=63),
        TimingSpec(when={"mode": "picture", "quality": "high", "size": "8 MP"}, gpu=0, seconds=120),
        TimingSpec(when={"mode": "edit", "quality": "high", "size": "2 MP"}, gpu=0, seconds=88,
                   note="one picture at standard detail, including the switch to the reference model"),
    )
    settings: ClassVar[dict[str, SettingSpec]] = {
        "compile": SettingSpec(
            label="Speed-up", target="compile", kind="bool",
            help="Makes each clip faster and lighter on the card. The first clip at each quality and shape "
                 "after a start is slower (about a minute) while it prepares."),
    }
    modes: ClassVar[dict[str, ModeSpec]] = {
        "text": ModeSpec(label="From a description", help="Write what happens and H3 films it, with sound.",
                         inputs=_fields(PROMPT, SHAPE)),
        "frames": ModeSpec(
            label="From pictures",
            help="Start from a picture, end on one, or both: H3 makes the motion in between.",
            inputs={
                "first": InputSpec(
                    label="First frame", kind="files", accept=("image",), max_count=1,
                    help="The picture the clip starts from. Leave empty to only end on the last frame."),
                "last": InputSpec(
                    label="Last frame", kind="files", accept=("image",), max_count=1,
                    help="The picture the clip ends on. Leave empty to only start from the first frame."),
                **_fields(FRAMES_PROMPT, FRAMES_SHAPE, FRAMES_STYLE, shape_first=True),
                "first_crop": _crop("first"), "last_crop": _crop("last"),
            }),
        "reference": ModeSpec(
            label="From references",
            help="Give up to 9 pictures, 3 videos and 3 audio clips (12 in all) of people, places, objects, a "
                 "style, a camera move or a voice, and say what happens.",
            inputs={
                "images": InputSpec(
                    label="Pictures", kind="files", accept=("image",), max_count=9,
                    help="People, animals, objects, places or a style to keep. They are numbered in the order "
                         "added: write \"picture 1\", \"picture 2\" in the description."),
                "videos": InputSpec(
                    label="Videos", kind="files", accept=("video",), max_count=3,
                    help="Videos to take people or things from, copy the camera movement of, continue, or "
                         "edit (choose below). Write \"video 1\" in the description. Their own sound is not used; "
                         "add it as audio if wanted."),
                "audio": InputSpec(
                    label="Audio", kind="files", accept=("audio",), max_count=3,
                    help="A voice to imitate, a soundtrack to keep, or a music style (choose below). Needs at "
                         "least one picture or video. Write \"audio 1\" in the description."),
                "prompt": REFERENCE_PROMPT,
                "notes": InputSpec(
                    label="What's in the references", kind="textarea", max_length=1500,
                    placeholder="Picture 1: my white Samoyed, Max\nPicture 2: our kitchen with the green tiles",
                    help="Optional, one line each: what a picture or video shows, so H3 knows what to keep. "
                         "Start each line with its name, such as \"Picture 1:\" or \"Video 1:\"."),
                "video_use": InputSpec(
                    label="Videos are used to", kind="choice", default="show what's in them",
                    options=("show what's in them", "copy camera and motion", "continue them", "edit them"),
                    help="'show what's in them' takes the people or things in them. 'copy camera and motion' "
                         "follows their camera movement and pacing. 'continue them' picks up where video 1 "
                         "ends. 'edit them' changes video 1 as described."),
                "audio_use": InputSpec(
                    label="Audio is used as", kind="choice", default="voice to imitate",
                    options=("voice to imitate", "soundtrack to keep", "music style"),
                    help="'voice to imitate': whoever speaks sounds like it (audio 1 is the first speaker). "
                         "'soundtrack to keep': the clip's sound is this audio. 'music style': the background "
                         "music follows its style."),
                **{key: value for key, value in _fields(REFERENCE_PROMPT, FRAMES_SHAPE, FRAMES_STYLE,
                                                        REFERENCE_QUALITY).items() if key != "prompt"},
                "detail": InputSpec(
                    label="Reference detail", kind="choice", options=("fast", "standard", "high"), default="standard",
                    help="How closely H3 studies the references. Each picture adds about 25 s (fast), 45 s "
                         "(standard) or several minutes (high, MiniMax's own size) of reading before filming, and "
                         "videos far more. 'high' keeps the most detail of faces and lettering.", advanced=True),
            }),
        "picture": ModeSpec(
            label="A picture", output_kind="image",
            help="H3 paints one still picture instead of a clip, with no sound, at up to 8 megapixels.",
            inputs={"prompt": PICTURE_PROMPT, "shape": SHAPE, "size": PICTURE_SIZE, "quality": PICTURE_QUALITY,
                    "seed": PICTURE_SEED}),
        "edit": ModeSpec(
            label="Edit pictures", output_kind="image",
            help="Give up to 4 pictures and say what to make with them: change a colour, the place, the light, or "
                 "combine them. The result is a new picture that keeps their look.",
            inputs={
                "images": InputSpec(
                    label="Pictures", kind="files", accept=("image",), max_count=4, required=True,
                    help="The pictures to use, numbered in the order added: write \"picture 1\", \"picture 2\"."),
                "prompt": EDIT_PROMPT,
                "notes": InputSpec(
                    label="What's in the pictures", kind="textarea", max_length=1000,
                    placeholder="Picture 1: my red bicycle",
                    help="Optional, one line each, starting \"Picture 1:\": what a picture shows, so H3 knows what to keep."),
                "shape": FRAMES_SHAPE.model_copy(update={"help": "'match picture' keeps picture 1's proportions."}),
                "size": EDIT_SIZE, "quality": PICTURE_QUALITY,
                "detail": InputSpec(
                    label="Picture detail", kind="choice", options=("fast", "standard", "high"), default="standard",
                    help="How closely H3 studies the pictures. 'high' keeps the most detail of faces and lettering "
                         "but reads each picture for minutes.", advanced=True),
                "seed": PICTURE_SEED,
            }),
    }

    def check_inputs(self, mode, values, files):
        if mode == "frames" and not (files.get("first") or files.get("last")):
            return ["Add a first frame, a last frame, or both."]
        frames = FRAMES.get(values.get("length") or "5", 124)
        if frames > 124 and frames * _render_pixels(values) > MAX_FRAME_PIXELS:
            return [(f"{values['length']}-second clips are limited to smaller sizes: choose a lower resolution "
                     "(10 seconds up to 540p, 15 seconds up to 480p) or 5 seconds.")]
        if values.get("resolution") == "custom":
            width, height = values.get("width"), values.get("height")
            if not width or not height:
                return ["Enter a custom width and height."]
            if round(width / 32) * 32 * round(height / 32) * 32 > MAX_PIXELS:
                return ["The custom size is too large: at most 1280 x 720 worth of pixels."]
        if mode == "edit" and not files.get("images"):
            return ["Add at least one picture to edit."]
        if mode == "reference":
            counts = {key: len(files.get(key, [])) for key in ("images", "videos", "audio")}
            if not counts["images"] and not counts["videos"]:
                return ["Add at least one picture or video. Audio can only go with them."]
            if sum(counts.values()) > 12:
                return ["Use at most 12 references in all."]
        return []
