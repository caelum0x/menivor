"""M0.3: the public ``/launch/status`` answer carries no env, vendor or internal names.

Anonymous callers get mode, gates, payments and plain-language format lists.
Staff get the operator detail (the readiness checklist and the env NAMES that
unlock each locked format). The public JSON is checked against the vendored
claims denylist (``policy/copy-denylist.json``, surface ``api-public``) with
the matching steps of gtm/policy/CLAIMS-RULES.md section 4.3.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import importlib

from app.core.launch import policy
from app.core.launch.formats import format_catalog

# ``app.core.launch`` re-exports the APIRouter as ``router``; get the module.
launch_router = importlib.import_module("app.core.launch.router")

DENYLIST = json.loads(
    (Path(__file__).resolve().parents[2] / "policy" / "copy-denylist.json").read_text()
)
VENDORED_VERSION = "2026-09-29.3"

#: Machine ids clients need; not copy. (path, rule) pairs.
_MACHINE_IDS = {("payments.provider", "vendor-infra"), ("payments.provider", "vendor-names")}


def _normalize(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def _rule_hits(rule: dict, text: str) -> bool:
    unit = _normalize(text)
    for token in rule.get("exceptTokens", []):
        unit = re.sub(re.escape(token), " ", unit, flags=re.IGNORECASE)
    match = rule["match"]
    if match["type"] == "regex":
        flags = 0 if match.get("caseSensitive", DENYLIST["defaults"].get("caseSensitive")) else re.IGNORECASE
        return re.search(match["value"], unit, flags) is not None
    ranges = [(int(lo, 16), int(hi, 16)) for lo, hi in match["ranges"]]
    return any(lo <= ord(ch) <= hi for ch in unit for lo, hi in ranges)


def _strings(value, path: str = ""):
    """Every string value and every object key, with a dotted path."""
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}" if path else str(key)
            yield here, str(key)
            yield from _strings(item, here)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item, f"{path}[]")
    elif isinstance(value, str):
        yield path, value


def api_public_hits(doc: dict) -> list[str]:
    rules = [
        r for r in DENYLIST["rules"]
        if "menivor" in r["products"] and "api-public" in r["surfaces"]
        and r.get("severity", DENYLIST["defaults"]["severity"]) == "error"
    ]
    hits = []
    for path, text in _strings(doc):
        for rule in rules:
            if (path, rule["id"]) in _MACHINE_IDS:
                continue
            if _rule_hits(rule, text):
                hits.append(f"{rule['id']} at {path}: {text[:60]!r}")
    return hits


def test_vendored_denylist_version():
    assert DENYLIST["version"] == VENDORED_VERSION


_ESCAPE = re.compile(r'copy-source:\s*\S|data-copy-source="[^"]+"')


def test_matcher_self_test_for_menivor_rules():
    for rule in DENYLIST["rules"]:
        if "menivor" not in rule["products"]:
            continue
        escape = rule.get("sourceEscape", DENYLIST["defaults"]["sourceEscape"])
        for example in rule.get("examples", {}).get("hit", []):
            assert _rule_hits(rule, example), (rule["id"], example)
        for example in rule.get("examples", {}).get("miss", []):
            escaped = escape and _ESCAPE.search(example)
            assert escaped or not _rule_hits(rule, example), (rule["id"], example)


def test_format_labels_and_reasons_name_no_vendor():
    catalog = format_catalog({})  # nothing configured: every paid format locked
    assert catalog["locked_formats"], "expected locked formats with an empty env"
    public = {
        "available_formats": [{"id": f["id"], "label": f["label"]} for f in catalog["available_formats"]],
        "locked_formats": [
            {"id": f["id"], "label": f["label"], "reason": f["reason"]} for f in catalog["locked_formats"]
        ],
    }
    assert api_public_hits(public) == []


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("REELFORGE_LAUNCH_MODE", "internal_pilot")
    monkeypatch.delenv("REELFORGE_PILOT_STAFF", raising=False)
    app = FastAPI()
    app.add_middleware(policy.LaunchRequestScopeMiddleware)
    app.include_router(launch_router.router)
    return TestClient(app)


def _path(client) -> str:
    for route in client.app.routes:
        if getattr(route, "path", "").endswith("/launch/status"):
            return route.path
    raise AssertionError("launch status route missing")


def test_anonymous_status_is_clean(client):
    response = client.get(_path(client))
    assert response.status_code == 200
    doc = response.json()["data"]
    raw = json.dumps(doc)
    assert "unlock_env" not in raw
    assert "requirements" not in raw and "warnings" not in raw
    assert not re.search(r"[A-Z][A-Z0-9]*_(?:API_KEY|SECRET|TOKEN|KEY)\b", raw)
    assert api_public_hits(doc) == []
    # What clients rely on is still there.
    assert {"mode", "features", "payments", "available_formats", "locked_formats", "phase", "beta"} <= set(doc)
    for item in doc["readiness"]["free_paths"]:
        assert item["paid_keys"] == []


def test_staff_status_keeps_operator_detail(client, monkeypatch):
    monkeypatch.setattr(launch_router, "_caller_is_staff", lambda request: True)
    doc = client.get(_path(client)).json()["data"]
    assert "requirements" in doc["readiness"]
    if doc["locked_formats"]:
        assert "unlock_env" in doc["locked_formats"][0]


def test_ordinary_signed_in_user_is_not_staff(monkeypatch):
    from app.core import api_docs

    monkeypatch.setattr(policy, "request_is_pilot_staff", lambda: False)
    monkeypatch.setattr(launch_router, "request_is_pilot_staff", lambda: False)
    monkeypatch.setattr(api_docs, "_is_staff", lambda request: False)
    request = SimpleNamespace(headers={"authorization": "Bearer user"})
    assert launch_router._caller_is_staff(request) is False
    anonymous = SimpleNamespace(headers={})
    assert launch_router._caller_is_staff(anonymous) is False
