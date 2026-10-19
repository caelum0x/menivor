"""Normalized provider adapters for the routing domain.

Each adapter implements the single :class:`app.domains.routing.base.ProviderAdapter`
contract. There is one source of outbound protocol code per provider; the
routing service resolves adapters through the registry rather than importing an
SDK directly. Web/mobile/desktop never import anything here.
"""

from .elevenlabs import ElevenLabsAdapter
from .heygen import HeyGenAdapter
from .image import ImageAdapter
from .openrouter import OpenRouterAdapter
from .pixelle import PixelleAdapter
from .registry import register_available_adapters
from .sadtalker import SadTalkerAdapter
from .tts import SelfHostTTSAdapter

__all__ = [
    "ElevenLabsAdapter",
    "HeyGenAdapter",
    "ImageAdapter",
    "OpenRouterAdapter",
    "PixelleAdapter",
    "SadTalkerAdapter",
    "SelfHostTTSAdapter",
    "register_available_adapters",
]
