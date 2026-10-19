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
FastAPI Dependencies

Provides dependency injection for PixelleVideoCore and other services.
"""

from typing import Annotated, Any
from fastapi import Depends, HTTPException
from loguru import logger

# Global Pixelle-Video instance
_pixelle_video_instance: Any = None


async def get_pixelle_video() -> Any:
    """
    Get Pixelle-Video core instance (dependency injection)
    
    Returns:
        PixelleVideoCore instance
    """
    global _pixelle_video_instance
    
    if _pixelle_video_instance is None:
        # Keep health/readiness independent from optional GPU adapters. This
        # makes the sidecar deployable on a control-plane node; generation
        # requests correctly report unavailable until its licensed runtime
        # dependencies are installed.
        try:
            from service import PixelleVideoCore
        except ModuleNotFoundError as exc:
            logger.warning(f"Pixelle runtime unavailable: {exc}")
            raise HTTPException(
                status_code=503,
                detail="Pixelle generation runtime is not installed",
            ) from exc
        _pixelle_video_instance = PixelleVideoCore()
        await _pixelle_video_instance.initialize()
        logger.info("✅ Pixelle-Video initialized for API")
    
    return _pixelle_video_instance


async def shutdown_pixelle_video():
    """Shutdown Pixelle-Video instance and cleanup resources"""
    global _pixelle_video_instance
    if _pixelle_video_instance:
        logger.info("Shutting down Pixelle-Video...")
        await _pixelle_video_instance.cleanup()
        _pixelle_video_instance = None
    
    try:
        from services.frame_html import HTMLFrameGenerator
        await HTMLFrameGenerator.close_browser()
    except ModuleNotFoundError:
        # The optional browser/GPU stack was never initialized.
        pass


# Type alias for dependency injection
PixelleVideoDep = Annotated[Any, Depends(get_pixelle_video)]
