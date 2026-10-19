# Copyright (C) 2025 AIDC-AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Pixelle-Video Services

Core services providing atomic capabilities.

Services:
- LLMService: LLM text generation
- TTSService: Text-to-speech
- MediaService: Media generation (image & video)
- VideoService: Video processing
- FrameProcessor: Frame processing orchestrator
- PersistenceService: Task metadata and storyboard persistence
- HistoryManager: History management business logic
- ComfyBaseService: Base class for ComfyUI-based services
"""

from importlib import import_module
from typing import TYPE_CHECKING

# Do not eagerly import GPU/Comfy adapters. Importing any child module first
# executes this package initializer, and eager imports made health-only Pixelle
# deployments require the optional ComfyKit runtime. The actual service is
# resolved only when a caller asks for it.
if TYPE_CHECKING:
    from services.comfy_base_service import ComfyBaseService
    from services.frame_processor import FrameProcessor
    from services.history_manager import HistoryManager
    from services.llm_service import LLMService
    from services.media import MediaService
    from services.persistence import PersistenceService
    from services.tts_service import TTSService
    from services.video import VideoService

_EXPORTS = {
    "ComfyBaseService": ("services.comfy_base_service", "ComfyBaseService"),
    "LLMService": ("services.llm_service", "LLMService"),
    "TTSService": ("services.tts_service", "TTSService"),
    "MediaService": ("services.media", "MediaService"),
    "ImageService": ("services.media", "MediaService"),
    "VideoService": ("services.video", "VideoService"),
    "FrameProcessor": ("services.frame_processor", "FrameProcessor"),
    "PersistenceService": ("services.persistence", "PersistenceService"),
    "HistoryManager": ("services.history_manager", "HistoryManager"),
}


def __getattr__(name: str):
    """Lazily load optional engine services while preserving public imports."""
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value

__all__ = [
    "ComfyBaseService",
    "LLMService",
    "TTSService",
    "MediaService",
    "ImageService",  # Backward compatibility
    "VideoService",
    "FrameProcessor",
    "PersistenceService",
    "HistoryManager",
]
