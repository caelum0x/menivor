"""Wave P PM3.3: MV8 Menivor TV app and MV9 TV apps (server side and app checks).

The watch app (apps/watch) is tested with its own vitest suite (logic, remote
navigation, licence check, copy). Here: the TV sign-in code flow the TV app
and the phone page use, and the rules that the app tree keeps.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.domains.ott_viewers import auth, router as viewers_router, session as viewer_session, tv_codes

from tests.reelforge import _wp_p3_ott as h

REPO = Path(__file__).resolve().parents[2]
WATCH = REPO / "apps" / "watch"


@pytest.fixture()
def env(monkeypatch):
    factory = h.make_factory()
    h.patch_sessions(monkeypatch, factory, (viewers_router,))
    h.enable(monkeypatch, "viewers", "tv")
    monkeypatch.setenv(auth.SECRET_ENV, h.AUTH_SECRET)
    monkeypatch.setenv(viewer_session.SECRET_ENV, h.VIEWER_SECRET)
    monkeypatch.setattr(viewers_router, "enforce_rate_limit", lambda *a, **k: None)
    tv_codes.set_store(tv_codes.MemoryStore())
    owner = h.owner(factory)
    h.channel(factory, owner, "maya")
    other = h.owner(factory, "o@example.com", "o-key")
    h.channel(factory, other, "zed")
    client = h.app_client(viewers_router.router)
    phone = client.post("/api/v1/ott/viewers/maya/session",
                        json={"access_token": h.auth_token("sub-a", "a@example.com"), "device": "ios"}).json()["data"]
    yield {"client": client, "phone": phone}
    tv_codes.set_store(None)


def test_tv_signs_in_with_a_code_approved_on_the_phone(env):
    client = env["client"]
    code = client.post("/api/v1/ott/viewers/maya/tv-codes").json()["data"]
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{3}-[A-HJ-NP-Z2-9]{3}", code["user_code"])
    assert code["expires_in"] == 600 and code["interval"] == 5
    waiting = client.post("/api/v1/ott/viewers/maya/tv-codes/poll", json={"device_token": code["device_token"]})
    assert waiting.status_code == 428 and waiting.json()["message"] == "Waiting for your phone."
    approved = client.post("/api/v1/ott/viewers/maya/tv-codes/approve",
                           json={"user_code": code["user_code"].lower()},
                           headers={"x-ott-viewer": env["phone"]["session"]})
    assert approved.json()["data"] == {"approved": True}
    tv = client.post("/api/v1/ott/viewers/maya/tv-codes/poll", json={"device_token": code["device_token"]})
    assert tv.status_code == 200 and tv.json()["data"]["viewer"]["id"] == env["phone"]["viewer"]["id"]
    me = client.get("/api/v1/ott/viewers/maya/me", headers={"x-ott-viewer": tv.json()["data"]["session"]})
    assert me.status_code == 200
    again = client.post("/api/v1/ott/viewers/maya/tv-codes/poll", json={"device_token": code["device_token"]})
    assert again.status_code == 410  # the session is handed out once


def test_codes_stay_on_their_channel(env):
    client = env["client"]
    code = client.post("/api/v1/ott/viewers/zed/tv-codes").json()["data"]
    refused = client.post("/api/v1/ott/viewers/maya/tv-codes/approve", json={"user_code": code["user_code"]},
                          headers={"x-ott-viewer": env["phone"]["session"]})
    assert refused.status_code == 404 and "did not work" in refused.json()["message"]
    wrong_channel = client.post("/api/v1/ott/viewers/maya/tv-codes/poll", json={"device_token": code["device_token"]})
    assert wrong_channel.status_code == 410
    unsigned = client.post("/api/v1/ott/viewers/maya/tv-codes/approve", json={"user_code": "AAAAAA"})
    assert unsigned.status_code == 401


def test_tv_routes_404_until_the_flag(env, monkeypatch):
    monkeypatch.delenv("OTT_TV_LIVE")
    assert env["client"].post("/api/v1/ott/viewers/maya/tv-codes").status_code == 404


def test_watch_app_declares_tv_targets_and_no_gpl_dependency():
    pkg = json.loads((WATCH / "package.json").read_text())
    assert pkg["dependencies"]["react-native"].startswith("npm:react-native-tvos@")
    assert "@react-native-tvos/config-tv" in pkg["devDependencies"]
    assert "expo-video" in pkg["dependencies"] and "react-native-google-cast" in pkg["dependencies"]
    config = (WATCH / "app.config.ts").read_text()
    assert "EXPO_TV" in config and "@react-native-tvos/config-tv" in config
    assert (WATCH / "scripts" / "licence-check.mjs").exists()


def test_watch_app_calls_only_routes_the_api_serves():
    from app.router import build_full_router
    from fastapi.routing import APIRoute

    served = {re.sub(r"\{[^}]+\}", "{}", r.path.replace("/api/v1", "")) for r in build_full_router().routes
              if isinstance(r, APIRoute)}
    source = (WATCH / "src" / "api" / "ott.ts").read_text()
    used = {re.sub(r"\$\{[^}]+\}", "{}", m) for m in re.findall(r"`(/ott/[^`]+)`", source)}
    assert used and used <= served, used - served
