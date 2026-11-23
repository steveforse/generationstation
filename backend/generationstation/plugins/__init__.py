"""Model plugin registry. Add a plugin by writing a module here and listing it below."""
from .basalt import BasaltPlugin
from .base import RuntimePlugin
from .llm import LLMPlugin
from .minimax_h3 import MiniMaxH3Plugin
from .omnivoice import OmniVoicePlugin
from .qwen3_tts import Qwen3TTSPlugin
from .qwen_image import QwenImagePlugin
from .yue2 import YuE2Plugin

_PLUGINS: dict[str, RuntimePlugin] = {plugin.kind: plugin for plugin in (
    BasaltPlugin(),
    LLMPlugin(),
    YuE2Plugin(),
    QwenImagePlugin(),
    MiniMaxH3Plugin(),
    OmniVoicePlugin(),
    Qwen3TTSPlugin(),
)}


def get_plugin(kind: str) -> RuntimePlugin | None:
    return _PLUGINS.get(kind)


def plugin_kinds() -> list[str]:
    return sorted(_PLUGINS)
