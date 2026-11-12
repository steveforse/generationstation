"""Model plugin registry. Add a plugin by writing a module here and listing it below."""
from .basalt import BasaltPlugin
from .base import RuntimePlugin

_PLUGINS: dict[str, RuntimePlugin] = {plugin.kind: plugin for plugin in (
    BasaltPlugin(),
)}


def get_plugin(kind: str) -> RuntimePlugin | None:
    return _PLUGINS.get(kind)


def plugin_kinds() -> list[str]:
    return sorted(_PLUGINS)
