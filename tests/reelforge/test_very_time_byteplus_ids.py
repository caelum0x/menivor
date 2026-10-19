"""Seedream / Seedance engine clients default to BytePlus international model ids (item 8)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2] / "apps" / "api" / "engine" / "services" / "api_services"


def _load(name: str):
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    return importlib.import_module(name)


def test_seedream_defaults_are_byteplus(monkeypatch):
    monkeypatch.delenv("SEEDREAM_ARK_MODEL", raising=False)
    monkeypatch.delenv("ARK_BASE_URL", raising=False)
    mod = _load("image_seedream")
    assert mod.default_model() == "seedream-4-5-251128"
    assert mod.ark_base_url() == "https://ark.ap-southeast.bytepluses.com/api/v3"
    assert mod.normalize_model_name("") == "seedream-4-5-251128"
    assert mod.normalize_model_name("doubao-seedream-4-5-251128") == "seedream-4-5-251128"
    assert not any(v.startswith("doubao-") for v in mod.MODEL_NAME_MAP.values())
    assert mod.SeedreamClient(api_key="k").base_url == "https://ark.ap-southeast.bytepluses.com/api/v3"


def test_seedream_env_overrides(monkeypatch):
    mod = _load("image_seedream")
    monkeypatch.setenv("SEEDREAM_ARK_MODEL", "seedream-5-0-260128")
    assert mod.normalize_model_name("") == "seedream-5-0-260128"
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    assert mod.normalize_model_name("doubao-seedream-4-5-251128") == "doubao-seedream-4-5-251128"


def test_seedance_defaults_are_byteplus(monkeypatch):
    monkeypatch.delenv("SEEDANCE_ARK_MODEL", raising=False)
    monkeypatch.delenv("ARK_BASE_URL", raising=False)
    mod = _load("video_seedance")
    assert mod.default_model() == "dreamina-seedance-2-0-260128"
    assert mod.normalize_model_name("") == "dreamina-seedance-2-0-260128"
    assert mod.normalize_model_name("doubao-seedance-2-0-fast-260128") == "dreamina-seedance-2-0-fast-260128"
    monkeypatch.setenv("SEEDANCE_ARK_MODEL", "dreamina-seedance-2-5-260628")
    assert mod.normalize_model_name("") == "dreamina-seedance-2-5-260628"
    monkeypatch.setenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    assert mod.normalize_model_name("doubao-seedance-2-0-260128") == "doubao-seedance-2-0-260128"


def test_seedance_submit_uses_the_normalised_id(monkeypatch):
    monkeypatch.delenv("ARK_BASE_URL", raising=False)
    monkeypatch.delenv("SEEDANCE_ARK_MODEL", raising=False)
    mod = _load("video_seedance")
    seen = {}
    client = mod.SeedanceVideoClient(api_key="k")
    monkeypatch.setattr(client, "_submit_task", lambda prompt, image, model, duration, **kw: seen.setdefault("m", model) and "t1")
    monkeypatch.setattr(client, "_poll_until_done", lambda task_id: "https://x/v.mp4")
    monkeypatch.setattr(client, "_download_video", lambda url, path: None)
    client.generate_video("p", None, "/tmp/out.mp4")
    assert seen["m"] == "dreamina-seedance-2-0-260128"
