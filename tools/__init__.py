from tools.registry import registry, register_tool
from tools import system_audio
from tools import system_apps

# Expose the registry and register_tool decorator for convenient import
__all__ = ["registry", "register_tool", "system_audio", "system_apps"]
