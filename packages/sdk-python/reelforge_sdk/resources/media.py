"""Unified media gateway — OpenRouter-style ``/images`` + ``/videos``.

One API key + one wallet balance → any image or video model. Images return
synchronously; videos submit a job you poll to a terminal status. Credits and
usage mirror OpenRouter's cost-visibility surface.
"""

import time
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

from ._base import RequestClient

_TERMINAL = {"completed", "failed"}


def is_terminal_status(status: str) -> bool:
    """Is a video job in a terminal state?"""
    return status in _TERMINAL


def format_usd_micros(micros: int) -> str:
    """Integer-microdollar → ``"$0.084"`` (1 USD = 1_000_000 micros)."""
    usd = (micros or 0) / 1_000_000
    digits = 3 if usd != 0 and abs(usd) < 0.1 else 2
    return f"${usd:.{digits}f}"


class MediaResource:
    """Unified image + video generation over one key + one balance."""

    def __init__(self, client: RequestClient) -> None:
        self._client = client

    def list_models(self, modality: Optional[str] = None) -> Dict[str, Any]:
        """List image + video models (optionally filtered by modality)."""
        query = {"modality": modality} if modality is not None else None
        return self._client._request("GET", "/media/models", query=query)

    def create_image(self, *, model: str, prompt: str) -> Dict[str, Any]:
        """Generate an image synchronously → ``{"url": ...}``."""
        return self._client._request("POST", "/media/images", body={"model": model, "prompt": prompt})

    def create_video(
        self,
        *,
        model: str,
        prompt: str = "",
        duration: int = 5,
        aspect_ratio: str = "9:16",
        image_url: str = "",
    ) -> Dict[str, Any]:
        """Submit a video job (poll with :meth:`get_video` / :meth:`wait_for_video`)."""
        body = {
            "model": model,
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "image_url": image_url,
        }
        return self._client._request("POST", "/media/videos", body=body)

    def get_video(self, job_id: str) -> Dict[str, Any]:
        """Poll a video job once."""
        return self._client._request("GET", f"/media/videos/{quote(job_id, safe='')}")

    def create_audio(self, *, model: str, prompt: str, instrumental: bool = False) -> Dict[str, Any]:
        """Submit a music/audio job (poll with :meth:`get_audio`)."""
        return self._client._request(
            "POST", "/media/audio", body={"model": model, "prompt": prompt, "instrumental": instrumental})

    def get_audio(self, job_id: str) -> Dict[str, Any]:
        """Poll an audio job once."""
        return self._client._request("GET", f"/media/audio/{quote(job_id, safe='')}")

    def wait_for_video(
        self,
        *,
        model: str,
        prompt: str = "",
        duration: int = 5,
        aspect_ratio: str = "9:16",
        image_url: str = "",
        interval_s: float = 3.0,
        max_attempts: int = 200,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Dict[str, Any]:
        """Submit a video and poll until it reaches a terminal status."""
        job = self.create_video(
            model=model, prompt=prompt, duration=duration,
            aspect_ratio=aspect_ratio, image_url=image_url,
        )
        attempts = 0
        while not is_terminal_status(str(job.get("status", ""))):
            attempts += 1
            if attempts > max_attempts:
                raise TimeoutError(
                    f"wait_for_video: job {job.get('id')} did not finish in {max_attempts} polls"
                )
            sleep(interval_s)
            job = self.get_video(str(job["id"]))
        return job

    def credits(self) -> Dict[str, Any]:
        """Spendable credits + lifetime gateway spend."""
        return self._client._request("GET", "/media/credits")

    def usage(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Gateway spend + job counts grouped by model."""
        query = {"limit": limit} if limit is not None else None
        return self._client._request("GET", "/media/usage", query=query)

    def generation(self, job_id: str) -> Dict[str, Any]:
        """Per-generation cost/status detail (OpenRouter ``/generation?id=``)."""
        return self._client._request("GET", f"/media/generation/{quote(job_id, safe='')}")
