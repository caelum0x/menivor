"""Launch readiness: names-only public checklist + keyless generation paths."""

from __future__ import annotations

from app.core.launch.readiness import free_paths, readiness_document
from app.core.launch_preflight import (
    enforce_startup_preflight,
    missing_public_requirements,
    public_launch_requirements,
)

SECRETISH = "sk-live-DO-NOT-LEAK-123"


def test_empty_env_lists_every_requirement_missing():
    missing = missing_public_requirements({})
    for expected in ("REELFORGE_PUBLIC_LAUNCH_APPROVED", "SENTRY_DSN", "ANTHROPIC_API_KEY",
                     "ELEVENLABS_API_KEY", "HEYGEN_API_KEY", "COMFYUI_API_KEY", "database_url"):
        assert expected in missing


def test_values_never_appear_in_the_document():
    env = {"SENTRY_DSN": SECRETISH, "ANTHROPIC_API_KEY": SECRETISH}
    doc = readiness_document(env)
    assert SECRETISH not in repr(doc)
    met = {item["id"]: item["met"] for item in doc["requirements"]}
    assert met["SENTRY_DSN"] is True and met["ANTHROPIC_API_KEY"] is True
    assert doc["public_launch_ready"] is False


def test_pixelle_drops_comfyui_requirements():
    ids = {item["id"] for item in public_launch_requirements({"BROLL_GEN_PROVIDER": "pixelle"})}
    assert "COMFYUI_API_KEY" not in ids and "BROLL_GEN_PROVIDER" in ids


def test_strict_preflight_message_lists_the_same_items():
    env = {"REELFORGE_LAUNCH_MODE": "public", "REELFORGE_PUBLIC_LAUNCH_APPROVED": "true"}
    try:
        enforce_startup_preflight(lambda _m: None, env=env)
    except RuntimeError as exc:
        message = str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected strict preflight to fail")
    for item in missing_public_requirements(env):
        assert item in message


def test_free_paths_mark_keyless_formats():
    env = {"R2_ACCOUNT_ID": "a", "R2_ACCESS_KEY_ID": "b", "R2_SECRET_ACCESS_KEY": "c", "R2_BUCKET": "d"}
    paths = {p["id"]: p for p in free_paths(env)}
    assert paths["captions_only_byov"]["paid_keys"] == []
    assert paths["faceless_tts_free_voice"]["paid_keys"] == []
    assert paths["faceless_tts_free_voice"]["requires"]["free_tts"] is True  # edge_tts installed
    assert paths["avatar_ugc"]["available"] is False
    assert paths["avatar_ugc"]["paid_keys"] == ["HEYGEN_API_KEY"]


def test_free_paths_unavailable_without_storage():
    paths = {p["id"]: p for p in free_paths({})}
    assert paths["captions_only_byov"]["available"] is False
