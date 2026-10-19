"""ReelForge TTS adapters.

This package hosts ReelForge-specific text-to-speech adapters that layer on top
of MoneyPrinterTurbo's existing ``app.services.voice`` plumbing. The flagship
adapter is the ElevenLabs ``/with-timestamps`` client, which is the single
timing authority for the ReelForge pipeline (see
``docs/reelforge/INTEGRATION_CONTRACT.md`` §8/§9).
"""

from app.services.tts.elevenlabs_timestamps import (
    WordTiming,
    elevenlabs_tts_with_timestamps,
)

__all__ = [
    "WordTiming",
    "elevenlabs_tts_with_timestamps",
]
