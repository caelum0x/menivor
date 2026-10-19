"""Contract coverage — the committed OpenAPI artifact must expose the full media
gateway surface under ``/media`` (and never collide with MPT's legacy routes).

This guards the ``packages/api-contract`` source of truth: if a gateway endpoint
is added/moved without regenerating the artifact, this fails in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_ARTIFACT = (
    Path(__file__).resolve().parents[2]
    / "packages" / "api-contract" / "openapi" / "reelforge-v1.json"
)

_GATEWAY_PATHS = [
    "/api/v1/media/models",
    "/api/v1/media/images",
    "/api/v1/media/videos",
    "/api/v1/media/videos/{job_id}",
    "/api/v1/media/audio",
    "/api/v1/media/audio/{job_id}",
    "/api/v1/media/credits",
    "/api/v1/media/usage",
    "/api/v1/media/generation/{job_id}",
    "/api/v1/media/generation/{job_id}/provenance",
    "/api/v1/media/generation/{job_id}/evidence",
    "/api/v1/media/identities",
]


@pytest.fixture(scope="module")
def openapi_paths() -> set[str]:
    if not _ARTIFACT.exists():
        pytest.skip("api-contract OpenAPI artifact not present")
    return set(json.loads(_ARTIFACT.read_text()).get("paths", {}))


@pytest.mark.parametrize("path", _GATEWAY_PATHS)
def test_gateway_path_in_openapi(openapi_paths, path):
    assert path in openapi_paths, f"{path} missing from the committed OpenAPI contract"


def test_gateway_namespaced_no_legacy_collision(openapi_paths):
    # The gateway lives under /media/*; it must NOT shadow MPT's legacy POST /videos.
    assert "/api/v1/media/videos" in openapi_paths
    assert "/api/v1/media/audio" in openapi_paths
    # MPT's legacy video surface stays reachable (not overwritten by the gateway).
    assert "/api/v1/videos" in openapi_paths
