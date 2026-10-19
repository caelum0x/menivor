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
Single-clip video generation (t2v / i2v) via managed providers.

A thin async route ReelForge's AI B-roll studio calls: given a prompt (and an
optional reference image URL for image->video), it runs ONE managed video client
(Kling / Seedance / Wan) and returns a ``task_id`` to poll at
``GET /api/tasks/{task_id}``. Unlike ``/api/video/generate/*`` (which runs the full
narration + TTS + template pipeline), this produces a single raw motion clip —
the right shape/latency/cost for a ~5s B-roll cutaway.

The heavy narration/ComfyUI/LLM stack is NOT touched: this route only needs the
managed-provider credentials (``KLING_ACCESS_KEY``/``KLING_SECRET_KEY`` for Kling,
``ARK_API_KEY`` for Seedance, ``DASHSCOPE_API_KEY`` for Wan), read by
``VideoClient`` from the ``Config`` facade / environment.
"""

import asyncio
import os
import uuid
from typing import Optional

import requests
from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel, Field

from api.routers.video import path_to_url
from api.schemas.video import VideoGenerateAsyncResponse
from api.tasks import TaskType, task_manager

router = APIRouter(prefix="/clip", tags=["Clip Generation"])

# Clips live in the mounted backend runtime volume. ``path_to_url`` preserves
# the existing compatibility file URL shape by stripping the ``output`` part.
_IMAGE_DOWNLOAD_TIMEOUT_S = 120


class ClipGenerateRequest(BaseModel):
    """Request body for ``POST /api/clip/generate/async``."""

    prompt: str = Field(..., min_length=1, max_length=2000)
    image_url: Optional[str] = Field(
        default=None,
        description="Reference image URL for image->video; omit for text->video.",
    )
    model: str = Field(
        default="kling-v3",
        description="Managed model; VideoClient routes by name (kling* / seedance* / wan*).",
    )
    duration: int = Field(default=5, ge=1, le=15)
    aspect_ratio: str = Field(default="9:16")
    negative_prompt: Optional[str] = None
    seed: Optional[int] = None


def _download_to_temp(url: str, dest_path: str) -> str:
    """Download a reference image URL to a local path (blocking)."""
    resp = requests.get(url, stream=True, timeout=_IMAGE_DOWNLOAD_TIMEOUT_S)
    resp.raise_for_status()
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            if chunk:
                fh.write(chunk)
    return dest_path


@router.post("/generate/async", response_model=VideoGenerateAsyncResponse)
async def generate_clip_async(request_body: ClipGenerateRequest, request: Request):
    """Start ONE managed t2v/i2v clip generation; returns a ``task_id`` to poll.

    ``image_url`` set -> image->video (downloaded to a local first-frame);
    omitted -> text->video. Poll ``GET /api/tasks/{task_id}``; on ``completed`` the
    task ``result`` is ``{video_url, duration, file_size}``.
    """
    task = task_manager.create_task(
        task_type=TaskType.VIDEO_GENERATION,
        request_params=request_body.model_dump(),
    )

    async def execute_clip_generation():
        from app.bootstrap import RUNTIME_ROOT, ensure_runtime_directories

        ensure_runtime_directories()
        output_dir = RUNTIME_ROOT / "output" / "clips"
        output_dir.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex
        save_path = str(output_dir / f"{run_id}.mp4")

        # i2v: fetch the reference image to a local first-frame path.
        image_path: Optional[str] = None
        tmp_image: Optional[str] = None
        if request_body.image_url:
            tmp_image = str(output_dir / f"{run_id}_ref")
            image_path = await asyncio.to_thread(
                _download_to_temp, request_body.image_url, tmp_image
            )

        try:
            # Imported lazily so the module loads even where the managed-provider
            # deps are absent; VideoClient reads creds from Config/env.
            from services.api_services.video_client import VideoClient

            client = VideoClient()
            out_path = await asyncio.to_thread(
                client.generate_video,
                request_body.prompt,
                image_path,
                save_path,
                request_body.model,
                request_body.duration,
                video_ratio=request_body.aspect_ratio,
                negative_prompt=request_body.negative_prompt or None,
                seed=request_body.seed,
            )
        finally:
            if tmp_image and os.path.exists(tmp_image):
                try:
                    os.remove(tmp_image)
                except OSError:
                    pass

        file_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        logger.success(f"clip generated: {out_path} ({file_size} bytes)")
        return {
            "video_url": path_to_url(request, out_path),
            "duration": float(request_body.duration),
            "file_size": file_size,
        }

    await task_manager.execute_task(
        task_id=task.task_id, coro_func=execute_clip_generation
    )
    return VideoGenerateAsyncResponse(task_id=task.task_id)
