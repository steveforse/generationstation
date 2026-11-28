"""Model plugin registry. Add a plugin by writing a module here and listing it below."""
from .ace_step import AceStepPlugin
from .basalt import BasaltPlugin
from .base import RuntimePlugin
from .breeze_tts import BreezeTTSPlugin
from .decide import DecidePlugin
from .fastmetal_video import FastMetalVideoPlugin
from .fish_drama3 import FishDrama3Plugin
from .fish_s2 import FishS2Plugin
from .h3_video import H3VideoPlugin
from .llm import LLMPlugin
from .longcat_video import LongCatVideoPlugin
from .ltx_video import LtxVideoPlugin
from .meeting_notes import MeetingNotesPlugin
from .minimax_h3 import MiniMaxH3Plugin
from .minimax_music import MiniMaxMusicPlugin
from .omnivoice import OmniVoicePlugin
from .qwen3_tts import Qwen3TTSPlugin
from .qwen_image import QwenImagePlugin
from .speech_to_text import NemotronPlugin, ParakeetPlugin, Qwen3AsrPlugin, WhisperPlugin
from .wan_video import WanVideoPlugin
from .yue2 import YuE2Plugin

_PLUGINS: dict[str, RuntimePlugin] = {plugin.kind: plugin for plugin in (
    BasaltPlugin(),
    LLMPlugin(),
    YuE2Plugin(),
    AceStepPlugin(),
    MiniMaxMusicPlugin(),
    QwenImagePlugin(),
    MiniMaxH3Plugin(),
    H3VideoPlugin(),
    OmniVoicePlugin(),
    Qwen3TTSPlugin(),
    FishDrama3Plugin(),
    FishS2Plugin(),
    BreezeTTSPlugin(),
    WanVideoPlugin(),
    LtxVideoPlugin(),
    DecidePlugin(),
    FastMetalVideoPlugin(),
    LongCatVideoPlugin(),
    MeetingNotesPlugin(),
    Qwen3AsrPlugin(),
    WhisperPlugin(),
    ParakeetPlugin(),
    NemotronPlugin(),
)}


def get_plugin(kind: str) -> RuntimePlugin | None:
    return _PLUGINS.get(kind)


def plugin_kinds() -> list[str]:
    return sorted(_PLUGINS)
