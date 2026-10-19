"""Railyard RELAY LLM-metering wiring tests.

Covers the OPT-IN, env-gated hop that routes Menivor/ReelForge's OpenAI-compatible
LLM calls through the Railyard RELAY gateway (TensorZero) and, optionally, the
ABACUS per-key spend cap in front of it — so all AI spend is metered/capped.

Surfaces exercised (all mirror ``vcglass/lib/railyard/{relay,abacus,gtm-llm}.ts``):

* ``app.domains.railyard.relay.to_tensorzero_model_name`` — model-id mapping.
* ``app.domains.railyard.config`` — RELAY_URL / ABACUS_* env gates.
* ``app.domains.railyard.llm_gateway.run_chat_text`` — transport selection
  (Abacus → Relay → direct), model mapping, cap-breach handling, fall-through.
* ``app.services.llm._generate_response`` — the real script-generator call site
  routes through Relay when RELAY_URL is set, and falls straight through to the
  direct provider when it is unset.

No network and no real SDK calls: the OpenAI client factory and the Abacus HTTP
transport are both injected fakes.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping, Tuple

import pytest

from app.domains.railyard import (
    RailyardError,
    get_abacus_config,
    get_relay_config,
    is_abacus_enabled,
    is_relay_enabled,
    railyard_llm_enabled,
    resolve_relay_model,
    run_chat_text,
    to_tensorzero_model_name,
)


# =========================================================================== #
# Fakes
# =========================================================================== #
class _FakeCompletions:
    def __init__(self, recorder: dict, content: str) -> None:
        self._recorder = recorder
        self._content = content

    def create(self, **kwargs: Any) -> Any:
        self._recorder["create_kwargs"] = kwargs
        message = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _FakeOpenAI:
    """Minimal OpenAI SDK stand-in that records how it was constructed/called."""

    def __init__(self, recorder: dict, content: str = "relay-said-hello") -> None:
        self._recorder = recorder
        self.chat = SimpleNamespace(completions=_FakeCompletions(recorder, content))


def _fake_factory(recorder: dict, content: str = "relay-said-hello"):
    def factory(api_key: str, base_url: str | None):
        recorder["api_key"] = api_key
        recorder["base_url"] = base_url
        return _FakeOpenAI(recorder, content)

    return factory


def _abacus_ok_transport(recorder: dict, content: str = "abacus-said-hello"):
    def transport(url: str, headers: Mapping[str, str], body: dict, timeout_s: float) -> Tuple[int, dict]:
        recorder["url"] = url
        recorder["headers"] = dict(headers)
        recorder["body"] = body
        return 200, {
            "success": True,
            "data": {"choices": [{"message": {"role": "assistant", "content": content}}]},
        }

    return transport


def _abacus_capped_transport(url, headers, body, timeout_s) -> Tuple[int, dict]:  # noqa: ARG001
    return 402, {"error": "monthly cap spent"}


# =========================================================================== #
# to_tensorzero_model_name
# =========================================================================== #
def test_tensorzero_maps_openai_and_anthropic_and_passthrough():
    assert to_tensorzero_model_name("gpt-4o-mini") == "tensorzero::model_name::openai::gpt-4o-mini"
    assert (
        to_tensorzero_model_name("claude-3-5-sonnet")
        == "tensorzero::model_name::anthropic::claude-3-5-sonnet"
    )
    # already-TensorZero names pass through untouched
    already = "tensorzero::model_name::openai::gpt-4o"
    assert to_tensorzero_model_name(already) == already
    # function routing
    assert to_tensorzero_model_name("gpt-4o", function_name="chat") == "tensorzero::function_name::chat"
    # explicit provider override
    assert to_tensorzero_model_name("my-model", provider="anthropic") == (
        "tensorzero::model_name::anthropic::my-model"
    )


# =========================================================================== #
# config gates
# =========================================================================== #
def test_relay_gate_off_by_default_and_on_with_url():
    assert is_relay_enabled({}) is False
    assert get_relay_config({}).openai_base_url is None

    cfg = get_relay_config({"RELAY_URL": "https://relay.example/"})
    assert cfg.configured is True
    # trailing slash normalized; OpenAI surface appended
    assert cfg.openai_base_url == "https://relay.example/openai/v1"


def test_abacus_gate_requires_url_and_key():
    assert is_abacus_enabled({"ABACUS_URL": "https://abacus.example"}) is False  # no key
    cfg = get_abacus_config({"ABACUS_URL": "https://abacus.example/", "ABACUS_API_KEY": "k"})
    assert cfg.configured is True
    assert cfg.base_url == "https://abacus.example"


def test_railyard_llm_enabled_and_model_resolution():
    assert railyard_llm_enabled({}) is False
    assert railyard_llm_enabled({"RELAY_URL": "https://r"}) is True
    assert railyard_llm_enabled({"ABACUS_URL": "https://a", "ABACUS_API_KEY": "k"}) is True

    # model is only rewritten to a TensorZero name when RELAY is on
    assert resolve_relay_model("gpt-4o-mini", {}) == "gpt-4o-mini"
    assert resolve_relay_model("gpt-4o-mini", {"RELAY_URL": "https://r"}) == (
        "tensorzero::model_name::openai::gpt-4o-mini"
    )


# =========================================================================== #
# run_chat_text — Relay transport
# =========================================================================== #
def test_run_chat_text_routes_through_relay():
    recorder: dict = {}
    text = run_chat_text(
        prompt="hi",
        model="gpt-4o-mini",
        provider_api_key="sk-direct",
        provider_base_url="https://api.openai.com/v1",
        env={"RELAY_URL": "https://relay.example"},
        openai_factory=_fake_factory(recorder),
    )
    assert text == "relay-said-hello"
    # SDK pointed at the Relay OpenAI surface, model rewritten to TensorZero name
    assert recorder["base_url"] == "https://relay.example/openai/v1"
    assert recorder["create_kwargs"]["model"] == "tensorzero::model_name::openai::gpt-4o-mini"


def test_run_chat_text_direct_when_relay_unset_but_abacus_without_agent():
    # Abacus on but no agent id → gate is skipped → falls through to DIRECT, so
    # the model stays plain and the base_url is the caller's own.
    recorder: dict = {}
    text = run_chat_text(
        prompt="hi",
        model="gpt-4o-mini",
        provider_api_key="sk-direct",
        provider_base_url="https://api.openai.com/v1",
        env={"ABACUS_URL": "https://abacus.example", "ABACUS_API_KEY": "k"},  # no ABACUS_AGENT_ID
        openai_factory=_fake_factory(recorder),
    )
    assert text == "relay-said-hello"
    assert recorder["base_url"] == "https://api.openai.com/v1"
    assert recorder["create_kwargs"]["model"] == "gpt-4o-mini"


# =========================================================================== #
# run_chat_text — Abacus transport (per-key cap in front of Relay)
# =========================================================================== #
def test_run_chat_text_routes_through_abacus_and_maps_model():
    recorder: dict = {}
    env = {
        "RELAY_URL": "https://relay.example",
        "ABACUS_URL": "https://abacus.example",
        "ABACUS_API_KEY": "abx",
        "ABACUS_AGENT_ID": "menivor",
    }
    text = run_chat_text(
        prompt="hi",
        model="gpt-4o-mini",
        provider_api_key="sk-direct",
        env=env,
        abacus_request_fn=_abacus_ok_transport(recorder),
    )
    assert text == "abacus-said-hello"
    # cap enforced at the Abacus proxy endpoint, agent header normalized
    assert recorder["url"] == "https://abacus.example/v1/proxy"
    assert recorder["headers"]["X-Abacus-Agent"] == "agent_menivor"
    assert recorder["headers"]["Authorization"] == "Bearer sk-direct"
    # Abacus fronts Relay → the model still uses the TensorZero name
    assert recorder["body"]["model"] == "tensorzero::model_name::openai::gpt-4o-mini"


def test_run_chat_text_cap_breach_raises_and_does_not_fall_through():
    env = {
        "RELAY_URL": "https://relay.example",
        "ABACUS_URL": "https://abacus.example",
        "ABACUS_API_KEY": "abx",
        "ABACUS_AGENT_ID": "menivor",
    }
    with pytest.raises(RailyardError) as exc:
        run_chat_text(
            prompt="hi",
            model="gpt-4o-mini",
            provider_api_key="sk-direct",
            env=env,
            abacus_request_fn=_abacus_capped_transport,
            # a fake factory that must NOT be reached after a cap breach
            openai_factory=_fake_factory({}),
        )
    assert exc.value.code == "cap_exceeded"
    assert exc.value.status == 402


# =========================================================================== #
# Wiring: the real script-generator call site honors Relay
# =========================================================================== #
def _patch_openai_ctor(monkeypatch, recorder: dict, content: str) -> None:
    """Patch the OpenAI ctor everywhere it is resolved: `openai.OpenAI` (the
    gateway's `from openai import OpenAI`) and the already-bound
    `app.services.llm.OpenAI` (the direct-provider path)."""
    import openai as openai_module

    from app.services import llm as llm_service

    def _ctor(**kwargs: Any) -> _FakeOpenAI:
        recorder["api_key"] = kwargs.get("api_key")
        recorder["base_url"] = kwargs.get("base_url")
        return _FakeOpenAI(recorder, content=content)

    monkeypatch.setattr(openai_module, "OpenAI", _ctor)
    monkeypatch.setattr(llm_service, "OpenAI", _ctor)


def test_generate_response_routes_through_relay(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="wired-relay-script")

    monkeypatch.setenv("RELAY_URL", "https://relay.example")
    monkeypatch.delenv("ABACUS_URL", raising=False)

    app_config = {
        "llm_provider": "openai",
        "openai_api_key": "sk-direct",
        "openai_model_name": "gpt-4o-mini",
        "openai_base_url": "https://api.openai.com/v1",
    }

    out = llm_service._generate_response(prompt="write a script", app_config=app_config)

    assert out == "wired-relay-script"
    # routed to the Relay OpenAI surface with the TensorZero model name
    assert recorder["base_url"] == "https://relay.example/openai/v1"
    assert recorder["create_kwargs"]["model"] == "tensorzero::model_name::openai::gpt-4o-mini"


def test_generate_response_direct_when_relay_unset(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="direct-script")
    monkeypatch.delenv("RELAY_URL", raising=False)
    monkeypatch.delenv("ABACUS_URL", raising=False)

    app_config = {
        "llm_provider": "openai",
        "openai_api_key": "sk-direct",
        "openai_model_name": "gpt-4o-mini",
        "openai_base_url": "https://api.openai.com/v1",
    }
    llm_service._generate_response(prompt="write a script", app_config=app_config)
    # No relay hop: the client is built for the caller's own base_url and the
    # plain (un-mapped) model id — the recorder captures the create() call the
    # direct provider path made before response validation.
    assert recorder["base_url"] == "https://api.openai.com/v1"
    assert recorder["create_kwargs"]["model"] == "gpt-4o-mini"


# =========================================================================== #
# Non-OpenAI adapters (Cloudflare, Azure, ...) also route via Relay when set
# =========================================================================== #
_CLOUDFLARE = {
    "llm_provider": "cloudflare",
    "cloudflare_api_key": "cf-direct",
    "cloudflare_model_name": "openai/gpt-4.1-mini",
    "cloudflare_account_id": "acct",
    "cloudflare_gateway_id": "default",
}
_AZURE = {
    "llm_provider": "azure",
    "azure_api_key": "az-direct",
    "azure_model_name": "gpt-4o-mini",
    "azure_base_url": "https://acme.openai.azure.com",
}


def _no_railyard_env(monkeypatch) -> None:
    for name in ("RELAY_URL", "RAILYARD_RELAY_URL", "ABACUS_URL", "RELAY_API_KEY", "RAILYARD_RELAY_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_cloudflare_adapter_routes_through_railyard_relay_alias(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="cf-via-relay")
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("RAILYARD_RELAY_URL", "https://relay.example/")

    out = llm_service._generate_response(prompt="write a script", app_config=dict(_CLOUDFLARE))

    assert out == "cf-via-relay"
    assert recorder["base_url"] == "https://relay.example/openai/v1"
    # The Cloudflare key is never forwarded to Relay.
    assert recorder["api_key"] != "cf-direct"


def test_azure_adapter_routes_through_relay_and_skips_azure_client(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="azure-via-relay")

    def _azure(**_kwargs):
        raise AssertionError("AzureOpenAI must not be built when Relay is set")

    monkeypatch.setattr(llm_service, "AzureOpenAI", _azure)
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("RELAY_URL", "https://relay.example")

    out = llm_service._generate_response(prompt="write a script", app_config=dict(_AZURE))

    assert out == "azure-via-relay"
    assert recorder["base_url"] == "https://relay.example/openai/v1"
    assert recorder["api_key"] != "az-direct"


def test_azure_adapter_direct_when_relay_unset(monkeypatch):
    from app.services import llm as llm_service

    built: dict = {}

    def _azure(**kwargs):
        built.update(kwargs)
        raise RuntimeError("stop after construction")

    monkeypatch.setattr(llm_service, "AzureOpenAI", _azure)
    _no_railyard_env(monkeypatch)
    try:
        llm_service._generate_response(prompt="write a script", app_config=dict(_AZURE))
    except Exception:  # noqa: BLE001 - the direct client is what we assert on
        pass
    assert built["azure_endpoint"] == "https://acme.openai.azure.com" and built["api_key"] == "az-direct"


def test_non_openai_adapter_ignores_abacus_only_config(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="cf-direct-script")
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("ABACUS_URL", "https://abacus.example")
    monkeypatch.setenv("ABACUS_API_KEY", "k")

    llm_service._generate_response(prompt="write a script", app_config=dict(_CLOUDFLARE))

    # Abacus alone fronts an OpenAI-compatible base URL; Cloudflare stays direct.
    assert recorder["base_url"] == "https://api.cloudflare.com/client/v4/accounts/acct/ai/v1"


# =========================================================================== #
# Real upstream provider on the wire (groq::, openrouter::, ...)
# =========================================================================== #
def test_relay_provider_for_known_providers_hosts_and_unknown():
    from app.domains.railyard import relay_provider_for

    assert relay_provider_for("groq") == "groq"
    assert relay_provider_for("OpenRouter") == "openrouter"
    assert relay_provider_for("anthropic") == "anthropic"
    assert relay_provider_for("openai") == "openai"
    # generic provider id, known upstream host
    assert relay_provider_for("oneapi", "https://api.groq.com/openai/v1") == "groq"
    assert relay_provider_for("litellm", "https://openrouter.ai/api/v1") == "openrouter"
    # unknown → None (caller keeps legacy inference)
    assert relay_provider_for("moonshot", "https://api.moonshot.cn/v1") is None
    assert relay_provider_for(None) is None


def test_tensorzero_name_uses_real_provider_and_legacy_fallback():
    assert to_tensorzero_model_name("llama-3.3-70b-versatile", provider="groq") == (
        "tensorzero::model_name::groq::llama-3.3-70b-versatile"
    )
    assert resolve_relay_model(
        "meta-llama/llama-3.3-70b-instruct", {"RELAY_URL": "https://r"}, relay_provider="openrouter"
    ) == "tensorzero::model_name::openrouter::meta-llama/llama-3.3-70b-instruct"
    # unknown provider → old behaviour
    assert resolve_relay_model("kimi-k2", {"RELAY_URL": "https://r"}) == (
        "tensorzero::model_name::openai::kimi-k2"
    )


_GROQ = {
    "llm_provider": "groq",
    "groq_api_key": "gsk-direct",
    "groq_model_name": "llama-3.3-70b-versatile",
}


def test_generate_response_sends_groq_provider_through_relay(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="groq-via-relay")
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("RELAY_URL", "https://relay.example")

    out = llm_service._generate_response(prompt="write a script", app_config=dict(_GROQ))

    assert out == "groq-via-relay"
    assert recorder["base_url"] == "https://relay.example/openai/v1"
    assert recorder["create_kwargs"]["model"] == (
        "tensorzero::model_name::groq::llama-3.3-70b-versatile"
    )


def test_generate_response_unknown_provider_keeps_legacy_openai_label(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="moonshot-via-relay")
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("RELAY_URL", "https://relay.example")

    llm_service._generate_response(
        prompt="write a script",
        app_config={"llm_provider": "moonshot", "moonshot_api_key": "k", "moonshot_model_name": "kimi-k2"},
    )
    assert recorder["create_kwargs"]["model"].startswith("tensorzero::model_name::openai::")


# =========================================================================== #
# Relay HTTP failures: 503 falls back to direct, 402/429 do not
# =========================================================================== #
def _relay_status_error(status: int, code: str):
    import httpx
    import openai

    request = httpx.Request("POST", "https://relay.example/openai/v1/chat/completions")
    response = httpx.Response(status, request=request)
    body = {"error": {"message": "refused", "code": code}}
    return openai.APIStatusError("refused", response=response, body=body)


def _patch_relay_failing_ctor(monkeypatch, calls: list, status: int, code: str) -> None:
    """Relay-bound clients raise ``status``; direct clients answer normally."""
    import openai as openai_module

    from app.services import llm as llm_service

    class _Failing:
        def create(self, **_kwargs: Any) -> Any:
            raise _relay_status_error(status, code)

    def _ctor(**kwargs: Any) -> Any:
        base_url = kwargs.get("base_url") or ""
        calls.append(base_url)
        if base_url.startswith("https://relay.example"):
            return SimpleNamespace(chat=SimpleNamespace(completions=_Failing()))
        return _FakeOpenAI({}, content="direct-after-relay")

    monkeypatch.setattr(openai_module, "OpenAI", _ctor)
    monkeypatch.setattr(llm_service, "OpenAI", _ctor)
    monkeypatch.setattr(
        llm_service, "_extract_chat_completion_text", lambda response, _p: response.choices[0].message.content
    )
    monkeypatch.setattr(llm_service, "ChatCompletion", SimpleNamespace)


def test_run_chat_text_maps_relay_statuses_to_railyard_codes():
    for status, relay_code, expected in (
        (503, "provider_not_configured", "provider_not_configured"),
        (402, "budget", "cap_exceeded"),
        (429, "rate_limited", "rate_limited"),
    ):
        def factory(api_key, base_url, _status=status, _code=relay_code):
            class _Failing:
                def create(self, **_kwargs):
                    raise _relay_status_error(_status, _code)

            return SimpleNamespace(chat=SimpleNamespace(completions=_Failing()))

        with pytest.raises(RailyardError) as exc:
            run_chat_text(
                prompt="hi",
                model="llama-3.3-70b-versatile",
                relay_provider="groq",
                env={"RELAY_URL": "https://relay.example"},
                openai_factory=factory,
            )
        assert exc.value.code == expected and exc.value.status == status


def test_generate_response_falls_back_to_direct_on_relay_503(monkeypatch):
    from app.services import llm as llm_service

    calls: list = []
    _patch_relay_failing_ctor(monkeypatch, calls, 503, "provider_not_configured")
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("RELAY_URL", "https://relay.example")

    out = llm_service._generate_response(prompt="write a script", app_config=dict(_GROQ))

    assert out == "direct-after-relay"
    assert calls == ["https://relay.example/openai/v1", "https://api.groq.com/openai/v1"]


@pytest.mark.parametrize("status,code", [(402, "insufficient_balance"), (429, "rate_limited")])
def test_generate_response_does_not_fall_back_on_relay_402_429(monkeypatch, status, code):
    from app.services import llm as llm_service

    calls: list = []
    _patch_relay_failing_ctor(monkeypatch, calls, status, code)
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("RELAY_URL", "https://relay.example")

    out = llm_service._generate_response(prompt="write a script", app_config=dict(_GROQ))

    assert out.startswith("Error:")
    # Only the Relay client was built; the direct provider was never called.
    assert calls == ["https://relay.example/openai/v1"]


# =========================================================================== #
# LiteLLM routes carry the upstream in the model id ("groq/openai/gpt-oss-120b")
# =========================================================================== #
def test_split_litellm_model_known_and_unknown_prefixes():
    from app.domains.railyard import split_litellm_model

    assert split_litellm_model("groq/openai/gpt-oss-120b") == ("groq", "openai/gpt-oss-120b")
    assert split_litellm_model("OpenRouter/meta-llama/llama-3.1-8b") == (
        "openrouter",
        "meta-llama/llama-3.1-8b",
    )
    assert split_litellm_model("anthropic/claude-3-5-haiku") == ("anthropic", "claude-3-5-haiku")
    assert split_litellm_model("gpt-4o-mini") == (None, "gpt-4o-mini")
    assert split_litellm_model("moonshot/kimi-k2") == (None, "moonshot/kimi-k2")
    assert split_litellm_model("groq/") == (None, "groq/")


def test_generate_response_litellm_groq_route_goes_to_relay_groq(monkeypatch):
    from app.services import llm as llm_service

    recorder: dict = {}
    _patch_openai_ctor(monkeypatch, recorder, content="litellm-via-relay")
    _no_railyard_env(monkeypatch)
    monkeypatch.setenv("RELAY_URL", "https://relay.example")

    out = llm_service._generate_response(
        prompt="write a script",
        app_config={
            "llm_provider": "litellm",
            "litellm_api_key": "k",
            "litellm_model_name": "groq/openai/gpt-oss-120b",
        },
    )

    assert out == "litellm-via-relay"
    assert recorder["base_url"] == "https://relay.example/openai/v1"
    assert recorder["create_kwargs"]["model"] == (
        "tensorzero::model_name::groq::openai/gpt-oss-120b"
    )
