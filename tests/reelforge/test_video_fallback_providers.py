"""Higgsfield + OSS video fallbacks on the pluggable async-media routing layer.

Covers the additive Higgsfield / LTX-Video (fal.ai) / CogVideoX provider configs,
their env auto-discovery in the registry, and the Higgsfield -> Wan2.2 -> LTX
fallback ordering in the routing policy. The HTTP seam is a fake ``request_fn``;
adapter logic (submit/poll/state-mapping/usage/output extraction) is real.
"""

from __future__ import annotations

import pytest

from app.domains.routing import policy as pol
from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_QUEUED,
    RUN_RUNNING,
    ProviderRegistry,
    ProviderRun,
)
from app.domains.routing.providers.async_media import (
    PROVIDER_CONFIGS,
    build_async_media_adapter,
    env_var_for,
)
from app.domains.routing.providers.registry import register_available_adapters


class FakeReq:
    """Fake request_fn recording calls and replaying scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __call__(self, method, path, *, json=None):
        self.calls.append({"method": method, "path": path, "json": json})
        return self._responses.pop(0)


# --------------------------------------------------------------------------- #
# Higgsfield — submit body (prompt + camera/motion preset + i2v image) + poll
# --------------------------------------------------------------------------- #
def test_higgsfield_i2v_submit_body_and_poll_completed():
    req = FakeReq([
        {"id": "hf-1", "status": "queued"},
        {"status": "generating"},
        {"status": "completed", "results": [{"url": "https://cdn/hf.mp4"}], "duration": 6},
    ])
    a = build_async_media_adapter("higgsfield", api_key="k", request_fn=req)
    run = a.submit(
        {"prompt": "a neon city", "seconds": 6, "motion": "dolly-in", "image_url": "https://img/f.png"},
        {"model_id": "higgsfield/dop-v1"},
        "corr",
    )
    assert run.run_id == "hf-1" and run.state == RUN_QUEUED
    body = req.calls[0]["json"]
    assert req.calls[0]["method"] == "POST" and req.calls[0]["path"] == "/v1/generations"
    assert body["prompt"] == "a neon city"
    assert body["duration"] == 6
    assert body["motion"] == "dolly-in"           # camera/motion preset carried
    assert body["image_url"] == "https://img/f.png"  # i2v init frame carried
    assert body["model"] == "dop-v1"

    run = a.poll(run)  # "generating" -> running
    assert run.state == RUN_RUNNING
    done = a.poll(run)
    assert done.state == RUN_COMPLETED
    assert done.result_ref == "https://cdn/hf.mp4"
    assert done.usage and done.usage.quantity_units == 6 and done.usage.unit == "seconds"


def test_higgsfield_t2v_omits_image_and_reads_preset_aliases():
    req = FakeReq([{"id": "hf-2", "status": "queued"}])
    a = build_async_media_adapter("higgsfield", api_key="k", request_fn=req)
    a.submit({"prompt": "sunset", "camera": "crane-up"}, {"model_id": "higgsfield/dop-v1"}, "c")
    body = req.calls[0]["json"]
    assert "image_url" not in body          # text-to-video: no init frame
    assert body["motion"] == "crane-up"      # "camera" alias also maps to the preset


# --------------------------------------------------------------------------- #
# LTX-Video via fal.ai — fal's UPPERCASE queue states + "Key " auth + video.url
# --------------------------------------------------------------------------- #
def test_ltx_fal_submit_poll_completed_via_fal_state_map():
    req = FakeReq([
        {"request_id": "fal-1", "status": "IN_QUEUE"},
        {"status": "IN_PROGRESS"},
        {"status": "COMPLETED", "video": {"url": "https://fal/out.mp4"}, "duration": 5},
    ])
    a = build_async_media_adapter("ltx_fal", api_key="k", request_fn=req)
    run = a.submit({"prompt": "waves", "image_url": "https://img/w.png"}, {"model_id": "ltx_fal/ltx-video"}, "c")
    assert run.run_id == "fal-1" and run.state == RUN_QUEUED
    assert req.calls[0]["path"] == "/fal-ai/ltx-video"
    assert req.calls[0]["json"]["prompt"] == "waves"
    assert req.calls[0]["json"]["image_url"] == "https://img/w.png"

    run = a.poll(run)
    assert run.state == RUN_RUNNING
    assert req.calls[1]["path"] == "/fal-ai/ltx-video/requests/fal-1"
    done = a.poll(run)
    assert done.state == RUN_COMPLETED
    assert done.result_ref == "https://fal/out.mp4"
    assert done.usage and done.usage.quantity_units == 5


def test_ltx_fal_uses_key_auth_scheme_and_shared_fal_env():
    cfg = PROVIDER_CONFIGS["ltx_fal"]
    assert cfg.auth_scheme == "Key "       # fal.ai uses "Authorization: Key <token>"
    assert cfg.auth_env == "FAL_API_KEY"   # shared vendor credential, not LTX_FAL_API_KEY
    assert cfg.capability == "video"


def test_higgsfield_and_cogvideox_use_default_env_var():
    assert PROVIDER_CONFIGS["higgsfield"].auth_env == ""
    assert env_var_for("higgsfield") == "HIGGSFIELD_API_KEY"
    assert env_var_for("cogvideox") == "COGVIDEOX_API_KEY"


# --------------------------------------------------------------------------- #
# Registry auto-discovery: keys present -> routable; absent -> never a route
# --------------------------------------------------------------------------- #
def test_registry_registers_video_providers_by_env_key():
    reg = ProviderRegistry()
    registered = register_available_adapters(
        reg,
        env={
            "HIGGSFIELD_API_KEY": "h",
            "FAL_API_KEY": "f",           # picks up ltx_fal via explicit auth_env
            "REPLICATE_API_TOKEN": "r",   # picks up Wan 2.2 fallback candidate
        },
    )
    assert "higgsfield" in registered
    assert "ltx_fal" in registered
    assert "wan" in registered            # Wan2.2 present as a fallback candidate
    assert "cogvideox" not in registered  # no COGVIDEOX_API_KEY -> not a live route
    assert reg.has("higgsfield") and reg.has("ltx_fal") and reg.has("wan")


# --------------------------------------------------------------------------- #
# Policy: Higgsfield -> Wan2.2 -> LTX -> CogVideoX fallback ordering
# --------------------------------------------------------------------------- #
def test_video_fallback_policy_orders_higgsfield_then_wan_then_ltx():
    assert pol.VIDEO_FALLBACK_ORDER == (
        "higgsfield", "wan", "ltx_fal", "cogvideox", "svd", "animatediff", "mochi",
    )
    assert pol.equivalent_order("video") == pol.VIDEO_FALLBACK_ORDER
    assert pol.equivalent_order("broll") == pol.VIDEO_FALLBACK_ORDER

    def cand(model_id, provider_key, cost):
        return pol.Candidate(
            model_id=model_id, provider_key=provider_key, capability="broll", est_cost_micros=cost
        )

    candidates = [
        cand("higgsfield/dop-v1", "higgsfield", 45_000),
        cand("wan/wan-2.2-t2v", "wan", 60_000),
        cand("ltx_fal/ltx-video", "ltx_fal", 20_000),
        cand("cogvideox/cogvideox-2b", "cogvideox", 3_000),
    ]
    policy = pol.video_fallback_policy(max_cost_micros=100_000)
    route = pol.select_route("higgsfield/dop-v1", candidates, policy)
    assert [c.provider_key for c in route] == ["higgsfield", "wan", "ltx_fal", "cogvideox"]


def test_video_fallback_policy_respects_cost_cap():
    def cand(model_id, provider_key, cost):
        return pol.Candidate(
            model_id=model_id, provider_key=provider_key, capability="broll", est_cost_micros=cost
        )

    candidates = [
        cand("higgsfield/dop-v1", "higgsfield", 45_000),
        cand("wan/wan-2.2-t2v", "wan", 60_000),
        cand("ltx_fal/ltx-video", "ltx_fal", 20_000),
    ]
    # Cap below Wan's cost drops it from the fallback set (no silent overspend).
    policy = pol.video_fallback_policy(max_cost_micros=50_000)
    route = pol.select_route("higgsfield/dop-v1", candidates, policy)
    assert [c.provider_key for c in route] == ["higgsfield", "ltx_fal"]
