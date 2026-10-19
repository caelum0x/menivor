"""Wave E M-1 (hand-off H4): per-model fal ``duration`` mapping.

Veo takes "8s", Hailuo 02 standard "6" or "10", Pika/LTX-2 integers, frame
models no duration at all. A length a model cannot render is refused before
any reservation or provider call.
"""

from __future__ import annotations

import pytest

from app.domains.gateway import fal_duration as fd
from app.domains.gateway import media_catalog as mc


@pytest.mark.parametrize(
    ("model_ref", "seconds", "expected"),
    [
        ("fal-ai/veo3", 8, {"duration": "8s"}),
        ("fal-ai/veo3.1/fast", 8, {"duration": "8s"}),
        ("fal-ai/veo3.1/fast", 4, {"duration": "4s"}),
        ("fal-ai/minimax/hailuo-02/standard/text-to-video", 6, {"duration": "6"}),
        ("fal-ai/minimax/hailuo-02/standard/text-to-video", 10, {"duration": "10"}),
        ("fal-ai/minimax/hailuo-02/pro/text-to-video", 6, {}),
        ("kling-t2v", 5, {"duration": "5"}),
        ("fal-ai/kling-video/v2.5-turbo/pro/text-to-video", 10, {"duration": "10"}),
        ("fal-ai/kling-video/v3/pro/text-to-video", 7, {"duration": "7"}),
        ("fal-ai/ltx-2/text-to-video", 8, {"duration": 8}),
        ("fal-ai/pika/v2.2/text-to-video", 5, {"duration": 5}),
        ("fal-ai/luma-dream-machine/ray-2", 9, {"duration": "9s"}),
        ("bytedance/seedance-2.0/text-to-video", 12, {"duration": "12"}),
        ("fal-ai/wan-25-preview/text-to-video", 10, {"duration": "10"}),
        ("fal-ai/hunyuan-video", 5, {}),
        ("fal-ai/wan/v2.2-a14b/text-to-video", 5, {}),
    ],
)
def test_duration_table(model_ref, seconds, expected):
    assert fd.duration_extra(model_ref, seconds) == expected


@pytest.mark.parametrize(
    ("model_ref", "seconds"),
    [
        ("fal-ai/veo3.1/fast", 5),
        ("fal-ai/veo3", 10),
        ("fal-ai/minimax/hailuo-02/standard/text-to-video", 5),
        ("fal-ai/minimax/hailuo-02/pro/text-to-video", 10),
        ("fal-ai/kling-video/v2.1/master/text-to-video", 7),
        ("fal-ai/ltx-2/text-to-video", 5),
    ],
)
def test_unsupported_length_is_refused_with_422(model_ref, seconds):
    with pytest.raises(fd.DurationUnsupported) as exc:
        fd.duration_extra(model_ref, seconds)
    assert exc.value.status_code == 422


def test_every_fal_catalog_row_has_a_duration_row():
    missing = [
        m.model_ref for m in mc._VIDEO
        if m.provider == "kling-fal" and fd.spec_for(m.model_ref) is None
    ]
    assert missing == []


def test_every_catalog_max_is_renderable_or_clamped_to_an_allowed_length():
    """A catalog row's own max length must be a length its endpoint renders,
    except rows whose max is above a fixed-length endpoint (refused, not sent)."""
    for m in mc._VIDEO:
        if m.provider != "kling-fal":
            continue
        spec = fd.spec_for(m.model_ref)
        if spec.form in (fd.FRAMES,):
            continue
        assert spec.allowed, m.id
        assert min(spec.allowed) <= m.max_seconds, m.id


class _Boom:
    def __init__(self, *a, **k):
        raise AssertionError("provider adapter must not be built for an unsupported length")


def test_executor_refuses_before_any_provider_call(monkeypatch):
    from app.domains.gateway import provider_execution as pe
    from app.domains.routing.providers.kling_fal import KlingError

    monkeypatch.setattr(pe, "KlingFalAdapter", _Boom)
    executor = pe.MediaProviderExecutor(api_key="k")
    request = pe.ProviderRequestV1(
        **{
            **_request_kwargs(pe),
            "provider_key": "kling-fal",
            "model_ref": "fal-ai/veo3.1/fast",
            "duration_seconds": 5,
        }
    )
    with pytest.raises(KlingError) as exc:
        executor._submit_video(request)
    assert "4s, 6s, 8s" in str(exc.value)


def test_executor_sends_the_mapped_duration(monkeypatch):
    from app.domains.gateway import provider_execution as pe

    seen = {}

    class _Fake:
        def __init__(self, *a, **k):
            pass

        def submit(self, **kwargs):
            seen.update(kwargs)
            from app.domains.routing.providers.kling_fal import KlingJob

            return KlingJob(
                request_id="r1",
                status_url="https://queue.fal.run/x/requests/r1/status",
                response_url="https://queue.fal.run/x/requests/r1",
            )

    monkeypatch.setattr(pe, "KlingFalAdapter", _Fake)
    executor = pe.MediaProviderExecutor(api_key="k")
    request = pe.ProviderRequestV1(
        **{
            **_request_kwargs(pe),
            "provider_key": "kling-fal",
            "model_ref": "fal-ai/veo3.1/fast",
            "duration_seconds": 8,
        }
    )
    executor._submit_video(request)
    assert seen["extra"] == {"duration": "8s"}


def test_gateway_create_video_refuses_before_reserving(monkeypatch):
    from app.domains.gateway import media_gateway as gw

    monkeypatch.setattr(gw, "_reserve_job", _Boom)
    with pytest.raises(gw.GatewayError) as exc:
        gw.create_video(
            object(), user_id="u1", model="google/veo-3.1-fast-fal", prompt="a cat", duration=5
        )
    assert exc.value.status_code == 422


def _request_kwargs(pe) -> dict:
    import dataclasses
    import inspect

    cls = pe.ProviderRequestV1
    if dataclasses.is_dataclass(cls):
        fields = {f.name: f for f in dataclasses.fields(cls)}
    else:  # pydantic or similar
        fields = dict(inspect.signature(cls).parameters)
    base = {
        "provider_key": "kling-fal",
        "model_ref": "kling-t2v",
        "modality": "video",
        "prompt": "a cat",
        "correlation_id": "c1",
        "duration_seconds": 5,
        "aspect_ratio": "9:16",
        "input_refs": (),
        "parameters": {},
    }
    return {k: v for k, v in base.items() if k in fields}
