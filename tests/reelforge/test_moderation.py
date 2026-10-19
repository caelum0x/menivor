"""Prompt moderation gate: every generation prompt is screened before the handler.

Covers text extraction, the provider switch (safeguard default, creem kept),
the safeguard hop chain (Relay -> Groq direct -> OpenRouter -> Claude, with a
per-hop cooldown after a 429) and answer validation, decision handling (allow / flag / deny), fail-closed on outage
(with the MENIVOR_MODERATION_FAIL_OPEN override), the 24h decision cache, and
the real app wiring: a denied prompt is answered with a human 400 BEFORE the
route handler runs, so nothing is debited or enqueued.
"""

from __future__ import annotations

import json
import sys

import httpx
import pytest
from fastapi.routing import APIRoute
from starlette.testclient import TestClient

from app.core import (
    moderation,
    moderation_cache,
    moderation_claude,
    moderation_common,
    moderation_cooldown,
    moderation_creem,
    moderation_safeguard,
)
from app.core.moderation_policy import POLICY_VERSION
from app.models.exception import HttpException

RID = "3f2a9c1e0b7d4e6fa1b2c3d4e5f60718"
RELAY = "https://relay.test"


@pytest.fixture(autouse=True)
def _moderation_env(monkeypatch):
    for name in (
        "MENIVOR_MODERATION_PROVIDER",
        "MENIVOR_MODERATION",
        "MENIVOR_MODERATION_FAIL_OPEN",
        "MENIVOR_MODERATION_MODEL",
        "MENIVOR_MODERATION_RELAY_MODEL",
        "MENIVOR_MODERATION_CACHE",
        "CREEM_MODERATION_URL",
        "RELAY_URL",
        "RELAY_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "MENIVOR_MODERATION_COOLDOWN_S",
        "MENIVOR_MODERATION_OPENROUTER_MODEL",
        "MENIVOR_MODERATION_CLAUDE_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RAILYARD_RELAY_URL", RELAY)
    monkeypatch.setenv("RAILYARD_RELAY_API_KEY", "rk_unit")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_unit")
    monkeypatch.setenv("CREEM_API_KEY", "creem_unit_test_key")
    moderation_cache.set_client(None)  # no Redis unless a test injects one
    moderation_cooldown.reset()
    yield
    moderation_cache.set_client(None)
    moderation_cooldown.reset()


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, bad_json: bool = False, headers=None):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json
        self.headers = headers or {}

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def _completion(decision: str = "allow", categories=(), raw: str | None = None):
    content = raw if raw is not None else json.dumps(
        {"decision": decision, "categories": list(categories), "rationale": "r"}
    )
    return _FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": content}}]})


def _router(calls: list, routes: dict):
    """Fake ``httpx.post``: ``routes`` maps a URL prefix to a response or exception."""

    def _post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        for prefix, outcome in routes.items():
            if url.startswith(prefix):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected url {url}")

    return _post


def _patch(monkeypatch, calls: list, routes: dict):
    fake = _router(calls, routes)
    monkeypatch.setattr(moderation_common.httpx, "post", fake)
    monkeypatch.setattr(moderation_creem.httpx, "post", fake)


class _FakeRedis:
    def __init__(self):
        self.store: dict = {}
        self.ttl: dict = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value
        self.ttl[key] = ex


# --- extraction -----------------------------------------------------------------


def test_extracts_reel_job_text_and_skips_ids_and_urls():
    body = {
        "params": {
            "video_subject": "Our new running shoe",
            "video_script": "Meet the lightest shoe we have ever made.",
            "music_prompt": "upbeat synth",
            "aspect": "9:16",
            "webhook_url": "https://example.test/hook",
        },
        "avatar_id": "av_123",
        "variants": 2,
    }
    text = moderation.extract_prompt_text(body)
    assert "Our new running shoe" in text
    assert "lightest shoe" in text
    assert "upbeat synth" in text
    assert "example.test" not in text
    assert "av_123" not in text


def test_extracts_nested_subtrees_and_dedupes():
    body = {
        "beats": [{"line": "a hero walks in"}, "a hero walks in"],
        "character": {"look": "red jacket"},
        "descriptors": ["tall", "smiling"],
        "overlays": [{"text": "SALE 50%"}],
    }
    text = moderation.extract_prompt_text(body)
    assert text.count("a hero walks in") == 1
    for fragment in ("red jacket", "tall", "smiling", "SALE 50%"):
        assert fragment in text


def test_extraction_is_capped():
    text = moderation.extract_prompt_text({"prompt": "x" * 50_000})
    assert len(text) == moderation.MAX_PROMPT_CHARS


# --- provider switch --------------------------------------------------------------


def test_default_provider_is_safeguard_via_relay(monkeypatch):
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("allow")})
    result = moderation.enforce_moderation("a coffee mug", request_id=RID, surface="t")
    assert result is not None and result.decision == "allow"
    assert result.provider == "safeguard:relay"
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == f"{RELAY}/openai/v1/chat/completions"
    assert call["headers"]["authorization"] == "Bearer rk_unit"
    body = call["json"]
    assert body["model"] == "tensorzero::model_name::groq::openai/gpt-oss-safeguard-20b"
    assert body["temperature"] == 0
    assert body["max_tokens"] <= 1024
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert "a coffee mug" in body["messages"][1]["content"]
    assert "a coffee mug" not in body["messages"][0]["content"]


def test_unknown_provider_falls_back_to_safeguard(monkeypatch):
    monkeypatch.setenv("MENIVOR_MODERATION_PROVIDER", "nonsense")
    assert moderation.provider_name() == "safeguard"


def test_creem_provider_still_available(monkeypatch):
    monkeypatch.setenv("MENIVOR_MODERATION_PROVIDER", "creem")
    calls: list = []
    _patch(
        monkeypatch,
        calls,
        {moderation_creem.LIVE_URL: _FakeResponse(200, {"id": "m1", "decision": "allow"})},
    )
    result = moderation.enforce_moderation("a coffee mug", request_id=RID)
    assert result is not None and result.decision == "allow" and result.provider == "creem"
    assert calls[0]["headers"]["x-api-key"] == "creem_unit_test_key"
    assert calls[0]["json"] == {"prompt": "a coffee mug", "external_id": RID}


def test_creem_sandbox_key_uses_test_endpoint(monkeypatch):
    monkeypatch.setenv("MENIVOR_MODERATION_PROVIDER", "creem")
    monkeypatch.setenv("CREEM_API_KEY", "creem_test_abc")
    calls: list = []
    _patch(
        monkeypatch,
        calls,
        {moderation_creem.SANDBOX_URL: _FakeResponse(200, {"id": "m1", "decision": "allow"})},
    )
    moderation.enforce_moderation("hello there", request_id=RID)
    assert calls[0]["url"] == moderation_creem.SANDBOX_URL


def test_safeguard_does_not_need_creem_key(monkeypatch):
    monkeypatch.delenv("CREEM_API_KEY")
    assert moderation.moderation_enabled()


# --- safeguard transport + validation -------------------------------------------


def test_relay_failure_falls_back_to_groq_direct(monkeypatch):
    calls: list = []
    _patch(
        monkeypatch,
        calls,
        {RELAY: _FakeResponse(503, {"error": "down"}), moderation_safeguard.GROQ_URL: _completion("deny", ["sexual"])},
    )
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("something prohibited", request_id=RID)
    assert info.value.status_code == 400
    assert [c["url"].split("/openai")[0] for c in calls] == [RELAY, "https://api.groq.com"]
    groq_call = calls[1]
    assert groq_call["json"]["model"] == "openai/gpt-oss-safeguard-20b"
    assert groq_call["headers"]["authorization"] == "Bearer gsk_unit"


def test_groq_direct_when_relay_not_configured(monkeypatch):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    calls: list = []
    _patch(monkeypatch, calls, {moderation_safeguard.GROQ_URL: _completion("allow")})
    result = moderation.enforce_moderation("a coffee mug", request_id=RID)
    assert result.provider == "safeguard:groq"
    assert len(calls) == 1


# --- fallthrough chain: OpenRouter + Claude + cooldown ---------------------------

OPENROUTER = moderation_safeguard.OPENROUTER_URL
CLAUDE = moderation_claude.URL
GROQ = moderation_safeguard.GROQ_URL
RATE_LIMITED = _FakeResponse(429, {"error": "rate limit"})


def _claude_answer(decision: str = "allow", categories=(), text: str | None = None):
    body = text if text is not None else json.dumps(
        {"decision": decision, "categories": list(categories), "rationale": "r"}
    )
    return _FakeResponse(200, {"content": [{"type": "text", "text": body}]})


def _hosts(calls: list) -> list[str]:
    return [c["url"] for c in calls]


@pytest.fixture
def full_chain(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_unit")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant_unit")


def test_groq_429_falls_through_to_openrouter(monkeypatch, full_chain):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    calls: list = []
    _patch(monkeypatch, calls, {GROQ: RATE_LIMITED, OPENROUTER: _completion("deny", ["illegal"])})
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("something prohibited", request_id=RID)
    assert info.value.status_code == 400
    assert _hosts(calls) == [GROQ, OPENROUTER]
    body = calls[1]["json"]
    assert calls[1]["headers"]["authorization"] == "Bearer or_unit"
    assert body["model"] == "openai/gpt-oss-safeguard-20b"
    assert body["models"] == ["openai/gpt-oss-safeguard-20b", "openai/gpt-oss-120b"]
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["content"] == moderation_safeguard.POLICY_TEXT
    assert "something prohibited" in body["messages"][1]["content"]


def test_openrouter_fallback_models_can_be_disabled(monkeypatch):
    monkeypatch.setenv("MENIVOR_MODERATION_OPENROUTER_FALLBACKS", "off")
    assert "models" not in moderation_safeguard.build_openrouter_body("x")


def test_openrouter_200_error_body_falls_through(monkeypatch, full_chain):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    monkeypatch.delenv("GROQ_API_KEY")
    calls: list = []
    upstream_502 = _FakeResponse(200, {"error": {"code": 502, "message": "upstream"}})
    _patch(monkeypatch, calls, {OPENROUTER: upstream_502, CLAUDE: _claude_answer("allow")})
    assert moderation.check_prompt("first prompt").provider == "safeguard:claude"
    moderation.check_prompt("second prompt")
    assert _hosts(calls) == [OPENROUTER, CLAUDE, OPENROUTER, CLAUDE], "a 502 is not a cooldown"


def test_openrouter_200_error_429_starts_cooldown(monkeypatch, full_chain):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    monkeypatch.delenv("GROQ_API_KEY")
    calls: list = []
    upstream_429 = _FakeResponse(200, {"error": {"code": 429, "message": "rate"}})
    _patch(monkeypatch, calls, {OPENROUTER: upstream_429, CLAUDE: _claude_answer("allow")})
    moderation.check_prompt("first prompt")
    moderation.check_prompt("second prompt")
    assert _hosts(calls) == [OPENROUTER, CLAUDE, CLAUDE]


def test_openrouter_answer_records_provider(monkeypatch, full_chain):
    calls: list = []
    _patch(
        monkeypatch,
        calls,
        {RELAY: _FakeResponse(503), GROQ: RATE_LIMITED, OPENROUTER: _completion("allow")},
    )
    result = moderation.check_prompt("a coffee mug")
    assert result.provider == "safeguard:openrouter"
    assert _hosts(calls) == [f"{RELAY}/openai/v1/chat/completions", GROQ, OPENROUTER]


def test_groq_and_openrouter_fail_then_claude_answers(monkeypatch, full_chain):
    calls: list = []
    _patch(
        monkeypatch,
        calls,
        {
            RELAY: httpx.ConnectError("down"),
            GROQ: RATE_LIMITED,
            OPENROUTER: _FakeResponse(502),
            CLAUDE: _claude_answer("flag", ["violence"]),
        },
    )
    result = moderation.enforce_moderation("edgy but ok", request_id=RID)
    assert result.decision == "flag" and result.categories == ("violence",)
    assert result.provider == "safeguard:claude"
    claude_call = calls[-1]
    assert claude_call["url"] == CLAUDE
    assert claude_call["headers"]["x-api-key"] == "ant_unit"
    assert claude_call["headers"]["anthropic-version"] == moderation_claude.API_VERSION
    body = claude_call["json"]
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["temperature"] == 0
    assert body["system"] == moderation_safeguard.POLICY_TEXT
    assert "edgy but ok" in body["messages"][0]["content"]


def test_claude_minors_always_denies(monkeypatch, full_chain):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    monkeypatch.delenv("GROQ_API_KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY")
    _patch(monkeypatch, [], {CLAUDE: _claude_answer("allow", ["minors"])})
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("something prohibited", request_id=RID)
    assert info.value.status_code == 400


@pytest.mark.parametrize(
    "claude_outcome",
    [
        _claude_answer(text="I cannot help with that."),
        _FakeResponse(200, {"content": "nope"}),
        RATE_LIMITED,
        _FakeResponse(529),
    ],
)
def test_all_hops_fail_is_503(monkeypatch, full_chain, claude_outcome):
    calls: list = []
    _patch(
        monkeypatch,
        calls,
        {
            RELAY: _FakeResponse(500),
            GROQ: RATE_LIMITED,
            OPENROUTER: RATE_LIMITED,
            CLAUDE: claude_outcome,
        },
    )
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("anything", request_id=RID)
    assert info.value.status_code == 503
    assert len(calls) == 4


def test_rate_limited_hop_is_skipped_during_cooldown(monkeypatch, full_chain):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    calls: list = []
    _patch(monkeypatch, calls, {GROQ: RATE_LIMITED, OPENROUTER: _completion("allow")})
    moderation.check_prompt("first prompt")
    moderation.check_prompt("second prompt")
    assert _hosts(calls) == [GROQ, OPENROUTER, OPENROUTER], "Groq must not be retried while cooling down"


def test_cooldown_expires(monkeypatch, full_chain):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    clock = [1000.0]
    monkeypatch.setattr(moderation_cooldown, "_now", lambda: clock[0])
    calls: list = []
    _patch(monkeypatch, calls, {GROQ: RATE_LIMITED, OPENROUTER: _completion("allow")})
    moderation.check_prompt("first prompt")
    clock[0] += moderation_cooldown.DEFAULT_COOLDOWN_S - 1
    moderation.check_prompt("second prompt")
    clock[0] += 2
    moderation.check_prompt("third prompt")
    assert _hosts(calls) == [GROQ, OPENROUTER, OPENROUTER, GROQ, OPENROUTER]


def test_retry_after_extends_cooldown_but_is_capped(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(moderation_cooldown, "_now", lambda: clock[0])
    assert moderation_cooldown.trip("groq", 5) == moderation_cooldown.DEFAULT_COOLDOWN_S
    assert moderation_cooldown.trip("openrouter", 120) == 120
    assert moderation_cooldown.trip("claude", 10_000) == moderation_cooldown.MAX_COOLDOWN_S
    clock[0] = 100
    assert not moderation_cooldown.active("groq")
    assert moderation_cooldown.active("openrouter")


def test_non_429_errors_do_not_start_a_cooldown(monkeypatch, full_chain):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    calls: list = []
    _patch(monkeypatch, calls, {GROQ: _FakeResponse(500), OPENROUTER: _completion("allow")})
    moderation.check_prompt("first prompt")
    moderation.check_prompt("second prompt")
    assert _hosts(calls) == [GROQ, OPENROUTER, GROQ, OPENROUTER]


def test_every_hop_cooling_down_fails_closed(monkeypatch, full_chain):
    for hop in moderation_safeguard.HOPS:
        moderation_cooldown.trip(hop)
    calls: list = []
    _patch(monkeypatch, calls, {})
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("anything", request_id=RID)
    assert info.value.status_code == 503
    assert calls == []


def test_hop_outcomes_are_counted_without_text(monkeypatch, full_chain):
    from app.telemetry.metrics import REGISTRY

    monkeypatch.delenv("RAILYARD_RELAY_URL")
    _patch(monkeypatch, [], {GROQ: RATE_LIMITED, OPENROUTER: _completion("allow")})
    moderation.check_prompt("secret product launch")
    exposition = REGISTRY.render()
    assert 'moderation_hop_total{hop="groq",outcome="rate_limited"}' in exposition
    assert 'moderation_hop_total{hop="openrouter",outcome="allow"}' in exposition
    assert "secret product launch" not in exposition


def test_openrouter_only_or_claude_only_enables_moderation(monkeypatch):
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    monkeypatch.delenv("GROQ_API_KEY")
    assert not moderation.moderation_enabled()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant_unit")
    assert moderation.moderation_enabled()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or_unit")
    assert moderation.moderation_enabled()


def test_flag_is_allowed(monkeypatch):
    _patch(monkeypatch, [], {RELAY: _completion("flag", ["violence"])})
    result = moderation.enforce_moderation("edgy but ok", request_id=RID)
    assert result is not None and result.decision == "flag"
    assert result.categories == ("violence",)


def test_deny_raises_human_400(monkeypatch):
    _patch(monkeypatch, [], {RELAY: _completion("deny", ["illegal"])})
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("something prohibited", request_id=RID)
    assert info.value.status_code == 400
    assert "Acceptable Use Policy" in info.value.message
    assert "not charged" in info.value.message


def test_minors_category_always_denies(monkeypatch):
    _patch(monkeypatch, [], {RELAY: _completion("flag", ["minors"])})
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("something prohibited", request_id=RID)
    assert info.value.status_code == 400


def test_answer_with_surrounding_text_and_unknown_categories():
    raw = 'Sure:\n{"decision": "DENY", "categories": ["sexual", "made_up"], "rationale": "x"}'
    decision, categories = moderation_safeguard.parse_decision(raw)
    assert decision == "deny"
    assert categories == ("sexual",)


@pytest.mark.parametrize(
    "raw",
    ["", "not json at all", '{"decision": "maybe"}', '["allow"]', '{"decision": "allow", "categories": 5}'],
)
def test_invalid_answers_are_outages(raw):
    with pytest.raises(moderation.ModerationUnavailable):
        moderation_safeguard.parse_decision(raw)


# --- outages ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        httpx.ConnectTimeout("timeout"),
        _FakeResponse(500, {"error": "boom"}),
        _FakeResponse(200, bad_json=True),
        _FakeResponse(200, {"choices": []}),
        _completion(raw='{"decision": "maybe"}'),
    ],
)
def test_outage_fails_closed(monkeypatch, outcome):
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: outcome, moderation_safeguard.GROQ_URL: outcome})
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("anything", request_id=RID)
    assert info.value.status_code == 503
    assert "not charged" in info.value.message
    assert len(calls) == 2, "both Relay and Groq direct must be tried"


def test_outage_fail_open_override(monkeypatch):
    monkeypatch.setenv("MENIVOR_MODERATION_FAIL_OPEN", "1")
    down = httpx.ConnectError("down")
    _patch(monkeypatch, [], {RELAY: down, moderation_safeguard.GROQ_URL: down})
    assert moderation.enforce_moderation("anything", request_id=RID) is None


def test_legacy_creem_fail_open_name_is_ignored(monkeypatch):
    monkeypatch.setenv("CREEM_MODERATION_FAIL_OPEN", "1")
    down = httpx.ConnectError("down")
    _patch(monkeypatch, [], {RELAY: down, moderation_safeguard.GROQ_URL: down})
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("anything", request_id=RID)
    assert info.value.status_code == 503


def test_disabled_when_unconfigured_or_off(monkeypatch):
    calls: list = []
    _patch(monkeypatch, calls, {})
    monkeypatch.setenv("MENIVOR_MODERATION", "off")
    assert moderation.enforce_moderation("x y", request_id=RID) is None
    monkeypatch.setenv("MENIVOR_MODERATION", "auto")
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    monkeypatch.delenv("GROQ_API_KEY")
    assert moderation.enforce_moderation("x y", request_id=RID) is None
    assert calls == []


def test_required_mode_without_transport_fails_closed(monkeypatch):
    monkeypatch.setenv("MENIVOR_MODERATION", "on")
    monkeypatch.delenv("RAILYARD_RELAY_URL")
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(HttpException) as info:
        moderation.enforce_moderation("x y", request_id=RID)
    assert info.value.status_code == 503


def test_prompt_text_is_never_logged(monkeypatch):
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        _patch(monkeypatch, [], {RELAY: _completion("deny", ["sexual"])})
        with pytest.raises(HttpException):
            moderation.enforce_moderation("SECRET-PROMPT-TEXT", request_id=RID)
        down = httpx.ConnectError("down")
        _patch(monkeypatch, [], {RELAY: down, moderation_safeguard.GROQ_URL: down})
        with pytest.raises(HttpException):
            moderation.enforce_moderation("SECRET-PROMPT-TEXT-2", request_id=RID)
    finally:
        logger.remove(sink)
    assert lines, "expected moderation log lines"
    assert not any("SECRET-PROMPT-TEXT" in line for line in lines)


# --- cache ------------------------------------------------------------------------


def test_decision_is_cached_by_text_hash_for_24h(monkeypatch):
    fake = _FakeRedis()
    moderation_cache.set_client(fake)
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("flag", ["violence"])})
    first = moderation.enforce_moderation("a dramatic chase", request_id=RID)
    second = moderation.enforce_moderation("a dramatic chase", request_id=RID)
    assert len(calls) == 1
    assert first.cached is False and second.cached is True
    assert second.decision == "flag" and second.categories == ("violence",)
    (key,) = fake.store
    assert key.startswith(f"menivor:moderation:safeguard:{POLICY_VERSION}:")
    assert "dramatic" not in key and "dramatic" not in fake.store[key]
    assert fake.ttl[key] == 24 * 60 * 60


def test_cached_deny_still_blocks_without_a_call(monkeypatch):
    fake = _FakeRedis()
    moderation_cache.set_client(fake)
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("deny", ["illegal"])})
    for _ in range(2):
        with pytest.raises(HttpException) as info:
            moderation.enforce_moderation("prohibited thing", request_id=RID)
        assert info.value.status_code == 400
    assert len(calls) == 1


def test_outages_are_not_cached(monkeypatch):
    fake = _FakeRedis()
    moderation_cache.set_client(fake)
    down = httpx.ConnectError("down")
    _patch(monkeypatch, [], {RELAY: down, moderation_safeguard.GROQ_URL: down})
    with pytest.raises(HttpException):
        moderation.enforce_moderation("anything", request_id=RID)
    assert fake.store == {}


def test_cache_is_keyed_per_provider(monkeypatch):
    fake = _FakeRedis()
    moderation_cache.set_client(fake)
    _patch(
        monkeypatch,
        [],
        {RELAY: _completion("allow"), moderation_creem.LIVE_URL: _FakeResponse(200, {"id": "c", "decision": "allow"})},
    )
    moderation.enforce_moderation("same text", request_id=RID)
    monkeypatch.setenv("MENIVOR_MODERATION_PROVIDER", "creem")
    moderation.enforce_moderation("same text", request_id=RID)
    assert len(fake.store) == 2


def test_broken_redis_degrades_to_live_calls(monkeypatch):
    class _Broken:
        def get(self, key):
            raise ConnectionError("redis down")

        def set(self, key, value, ex=None):
            raise ConnectionError("redis down")

    moderation_cache.set_client(_Broken())
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("allow")})
    assert moderation.enforce_moderation("a coffee mug", request_id=RID).decision == "allow"
    assert len(calls) == 1


def test_cache_can_be_disabled(monkeypatch):
    fake = _FakeRedis()
    moderation_cache.set_client(fake)
    monkeypatch.setenv("MENIVOR_MODERATION_CACHE", "off")
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("allow")})
    moderation.enforce_moderation("a coffee mug", request_id=RID)
    moderation.enforce_moderation("a coffee mug", request_id=RID)
    assert len(calls) == 2 and fake.store == {}


# --- app wiring -----------------------------------------------------------------


@pytest.fixture()
def client():
    from app.asgi import app

    return TestClient(app, raise_server_exceptions=False)


def test_every_moderated_route_exists_in_the_app():
    from app.asgi import app

    routes = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    missing = moderation.MODERATED_ROUTES - routes
    assert not missing, f"moderated routes not mounted: {sorted(missing)}"


@pytest.fixture()
def verified(monkeypatch):
    """Treat the request's credentials as a verified principal ``user-1``."""
    monkeypatch.setattr(moderation, "_verified_user_id", lambda _request, _rid: "user-1")


def test_denied_prompt_blocked_before_handler(monkeypatch, client, verified):
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("deny", ["illegal"])})
    reached: list = []
    monkeypatch.setattr(
        sys.modules["app.domains.reels.router"], "_require_db", lambda rid: reached.append(rid)
    )
    res = client.post(
        "/api/v1/jobs",
        json={"params": {"video_subject": "prohibited thing"}},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert res.status_code == 400
    assert "Acceptable Use Policy" in res.json()["message"]
    assert res.json().get("request_id")
    assert reached == [], "route handler must not run for a denied prompt"
    assert calls and "prohibited thing" in calls[0]["json"]["messages"][1]["content"]


def test_outage_returns_503_before_handler(monkeypatch, client, verified):
    slow = httpx.ReadTimeout("slow")
    _patch(monkeypatch, [], {RELAY: slow, moderation_safeguard.GROQ_URL: slow})
    res = client.post(
        "/api/v1/broll/generate",
        json={"prompt": "a calm beach at sunset"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert res.status_code == 503
    assert "safety check" in res.json()["message"]


def test_forged_bearer_with_large_prompt_is_401_with_zero_llm_calls(monkeypatch, client):
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("allow")})
    reached: list = []
    monkeypatch.setattr(
        sys.modules["app.domains.reels.router"], "_require_db", lambda rid: reached.append(rid)
    )
    res = client.post(
        "/api/v1/jobs",
        json={"params": {"video_subject": "word " * 5000}},
        headers={"Authorization": "Bearer x"},
    )
    assert res.status_code == 401
    assert calls == []
    assert reached == []


def test_identity_lookup_failure_fails_closed_without_llm_calls(monkeypatch, client):
    import app.models.db.base as db_base

    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("allow")})

    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(db_base, "get_session", broken)
    res = client.post(
        "/api/v1/broll/generate",
        json={"prompt": "a calm beach at sunset"},
        headers={"x-api-key": "rk_anything"},
    )
    assert res.status_code == 503
    assert calls == []


def test_daily_budget_caps_provider_calls_per_user(monkeypatch):
    from app.services import ratelimit

    ratelimit.reset_local_buckets()
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    monkeypatch.setenv("MENIVOR_MODERATION_DAILY_BUDGET", "2")
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("allow")})
    for n in range(2):
        moderation.enforce_moderation(f"prompt {n}", request_id=RID, user_id="budget-user")
    with pytest.raises(HttpException) as exc:
        moderation.enforce_moderation("prompt 3", request_id=RID, user_id="budget-user")
    assert exc.value.status_code == 429
    assert len(calls) == 2
    # Another user has their own budget.
    moderation.enforce_moderation("prompt 3", request_id=RID, user_id="other-user")
    assert len(calls) == 3


def test_cache_hits_do_not_spend_the_budget(monkeypatch):
    from app.services import ratelimit

    ratelimit.reset_local_buckets()
    monkeypatch.setattr(ratelimit, "_get_client", lambda: None)
    moderation_cache.set_client(_FakeRedis())
    monkeypatch.setenv("MENIVOR_MODERATION_DAILY_BUDGET", "1")
    calls: list = []
    _patch(monkeypatch, calls, {RELAY: _completion("allow")})
    for _ in range(3):
        moderation.enforce_moderation("same prompt", request_id=RID, user_id="cache-user")
    assert len(calls) == 1


def test_unauthenticated_request_is_not_moderated(monkeypatch, client):
    calls: list = []
    _patch(monkeypatch, calls, {})
    client.post("/api/v1/broll/generate", json={"prompt": "a calm beach"})
    assert calls == []


def test_non_generation_route_is_not_moderated(monkeypatch, client):
    calls: list = []
    _patch(monkeypatch, calls, {})
    client.post(
        "/api/v1/workspaces",
        json={"name": "anything"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert calls == []
