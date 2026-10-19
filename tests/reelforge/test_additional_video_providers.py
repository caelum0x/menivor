"""Additional open-weights video fallbacks on the pluggable async-media layer.

Covers the additive Stable Video Diffusion (SVD) / AnimateDiff / Mochi-1 provider
configs (all on the fal.ai queue, sharing ``FAL_API_KEY``) and the reference-only
HunyuanVideo config (non-commercial + EU/UK/KR territorial exclusion). The HTTP
seam is a fake ``request_fn``; adapter logic (submit/poll/state-mapping/usage/
output extraction) is real. Also asserts the license-class gate, the extended
policy fallback order, registry auto-discovery, and the catalog wiring.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.domains.catalog import seed_data
from app.domains.routing import license_class as lic
from app.domains.routing import policy as pol
from app.domains.routing.base import (
    RUN_COMPLETED,
    RUN_QUEUED,
    RUN_RUNNING,
    ProviderRegistry,
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
# SVD / AnimateDiff / Mochi — real submit + poll over fal's UPPERCASE queue
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "provider_key, submit_path, output_url",
    [
        ("svd", "/fal-ai/stable-video-diffusion", "https://fal/svd.mp4"),
        ("animatediff", "/fal-ai/fast-animatediff/text-to-video", "https://fal/ad.mp4"),
        ("mochi", "/fal-ai/mochi-v1", "https://fal/mochi.mp4"),
    ],
)
def test_fal_video_provider_submit_poll_completed(provider_key, submit_path, output_url):
    req = FakeReq([
        {"request_id": "fal-x", "status": "IN_QUEUE"},
        {"status": "IN_PROGRESS"},
        {"status": "COMPLETED", "video": {"url": output_url}, "duration": 6},
    ])
    a = build_async_media_adapter(provider_key, api_key="k", request_fn=req)
    run = a.submit({"prompt": "a river"}, {"model_id": f"{provider_key}/m"}, "corr")
    assert run.run_id == "fal-x" and run.state == RUN_QUEUED
    assert req.calls[0]["method"] == "POST" and req.calls[0]["path"] == submit_path
    assert req.calls[0]["json"]["prompt"] == "a river"

    run = a.poll(run)  # IN_PROGRESS -> running
    assert run.state == RUN_RUNNING
    assert req.calls[1]["path"] == f"{submit_path}/requests/fal-x"
    done = a.poll(run)
    assert done.state == RUN_COMPLETED
    assert done.result_ref == output_url
    assert done.usage and done.usage.quantity_units == 6 and done.usage.unit == "seconds"


def test_svd_carries_image_init_frame():
    req = FakeReq([{"request_id": "svd-1", "status": "IN_QUEUE"}])
    a = build_async_media_adapter("svd", api_key="k", request_fn=req)
    a.submit({"prompt": "clouds", "image_url": "https://img/c.png"}, {"model_id": "svd/x"}, "c")
    body = req.calls[0]["json"]
    assert body["image_url"] == "https://img/c.png"  # i2v init frame passes through


def test_new_fal_providers_share_key_auth_and_fal_env():
    for key in ("svd", "animatediff", "mochi", "hunyuanvideo"):
        cfg = PROVIDER_CONFIGS[key]
        assert cfg.auth_scheme == "Key "        # fal.ai "Authorization: Key <token>"
        assert cfg.auth_env == "FAL_API_KEY"    # shared vendor credential
        assert cfg.capability == "video"
        assert env_var_for(key) == "FAL_API_KEY"


# --------------------------------------------------------------------------- #
# HunyuanVideo — reference-only (NC + EU/UK/KR); config present, protocol works
# --------------------------------------------------------------------------- #
def test_hunyuanvideo_is_reference_only_but_protocol_works():
    assert PROVIDER_CONFIGS["hunyuanvideo"].reference_only is True
    # The other fal fallbacks are true live-routable providers.
    for key in ("svd", "animatediff", "mochi"):
        assert PROVIDER_CONFIGS[key].reference_only is False

    req = FakeReq([
        {"request_id": "hy-1", "status": "IN_QUEUE"},
        {"status": "COMPLETED", "video": {"url": "https://fal/hy.mp4"}, "duration": 5},
    ])
    a = build_async_media_adapter("hunyuanvideo", api_key="k", request_fn=req)
    run = a.submit({"prompt": "a forest"}, {"model_id": "hunyuanvideo/hunyuanvideo"}, "c")
    assert run.run_id == "hy-1" and run.state == RUN_QUEUED
    done = a.poll(run)
    assert done.state == RUN_COMPLETED and done.result_ref == "https://fal/hy.mp4"


# --------------------------------------------------------------------------- #
# License-class gate: SVD/AnimateDiff/Mochi paid-safe; HunyuanVideo blocked
# --------------------------------------------------------------------------- #
def test_license_gate_paid_safety():
    today = date(2026, 9, 23)
    assert lic.is_paid_safe("svd") is True
    assert lic.is_paid_safe("animatediff") is True
    assert lic.is_paid_safe("mochi") is True
    assert lic.is_paid_safe("hunyuanvideo") is False           # NC + territorial
    assert lic.is_route_allowed("mochi", paid=True, on=today) is True
    assert lic.is_route_allowed("hunyuanvideo", paid=True, on=today) is False
    # A free/draft render may still reference it.
    assert lic.is_route_allowed("hunyuanvideo", paid=False, on=today) is True
    with pytest.raises(lic.LicenseError):
        lic.assert_route_allowed("hunyuanvideo", paid=True, on=today)


# --------------------------------------------------------------------------- #
# Registry auto-discovery: FAL_API_KEY -> svd/animatediff/mochi; NOT hunyuanvideo
# --------------------------------------------------------------------------- #
def test_registry_registers_fal_fallbacks_but_skips_reference_only():
    reg = ProviderRegistry()
    registered = register_available_adapters(reg, env={"FAL_API_KEY": "f"})
    for key in ("svd", "animatediff", "mochi", "ltx_fal"):
        assert key in registered and reg.has(key)
    assert "hunyuanvideo" not in registered      # reference-only -> never a route
    assert not reg.has("hunyuanvideo")


def test_registry_reference_flag_opts_hunyuanvideo_in():
    reg = ProviderRegistry()
    registered = register_available_adapters(
        reg,
        env={"FAL_API_KEY": "f", "REELFORGE_ENABLE_HUNYUANVIDEO_REFERENCE": "1"},
    )
    assert "hunyuanvideo" in registered and reg.has("hunyuanvideo")


# --------------------------------------------------------------------------- #
# Policy: fallback order extended to SVD -> AnimateDiff -> Mochi after the OSS trio
# --------------------------------------------------------------------------- #
def test_extended_fallback_order_and_route_selection():
    assert pol.VIDEO_FALLBACK_ORDER == (
        "higgsfield", "wan", "ltx_fal", "cogvideox", "svd", "animatediff", "mochi",
    )
    assert "hunyuanvideo" not in pol.VIDEO_FALLBACK_ORDER

    def cand(model_id, provider_key, cost):
        return pol.Candidate(
            model_id=model_id, provider_key=provider_key, capability="broll", est_cost_micros=cost
        )

    candidates = [
        cand("higgsfield/dop-v1", "higgsfield", 45_000),
        cand("cogvideox/cogvideox-2b", "cogvideox", 3_000),
        cand("svd/stable-video-diffusion", "svd", 15_000),
        cand("animatediff/animatediff-v1", "animatediff", 8_000),
        cand("mochi/mochi-1", "mochi", 25_000),
    ]
    policy = pol.video_fallback_policy(max_cost_micros=100_000)
    route = pol.select_route("higgsfield/dop-v1", candidates, policy)
    # Primary first, then the preferred provider order (cogvideox precedes svd..).
    assert [c.provider_key for c in route] == [
        "higgsfield", "cogvideox", "svd", "animatediff", "mochi",
    ]


# --------------------------------------------------------------------------- #
# Catalog: SVD/AnimateDiff/Mochi promoted; HunyuanVideo stays shadow reference-only
# --------------------------------------------------------------------------- #
def test_catalog_wires_new_providers_and_excludes_reference_only():
    provider_keys = {p["provider_key"] for p in seed_data.PROVIDERS}
    for key in ("svd", "animatediff", "mochi", "hunyuanvideo"):
        assert key in provider_keys

    model_ids = {m["model_id"] for m in seed_data.MODELS}
    assert {
        "svd/stable-video-diffusion",
        "animatediff/animatediff-v1",
        "mochi/mochi-1",
        "hunyuanvideo/hunyuanvideo",
    } <= model_ids

    # Live-promoted fallback chain includes the three new paid-safe providers...
    assert "svd/stable-video-diffusion" in seed_data.VIDEO_FALLBACK_MODELS
    assert "animatediff/animatediff-v1" in seed_data.VIDEO_FALLBACK_MODELS
    assert "mochi/mochi-1" in seed_data.VIDEO_FALLBACK_MODELS
    # ...but never the reference-only HunyuanVideo.
    assert "hunyuanvideo/hunyuanvideo" not in seed_data.VIDEO_FALLBACK_MODELS
