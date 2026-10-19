"""Wave P PM1.5: Relay, Rago and Mint in production for Menivor (contract 5.3, 5.4).

* Every LLM call goes through Relay: provider SDKs are imported only by the
  Relay boundary, and with ``RAILYARD_LIVE=1`` a direct LLM client is refused
  and the free-provider fallback chain is off (deterministic fallbacks stay).
* Rago events in the contract shape with ``<product>:<meter>:<source id>``
  transaction ids, kept in an outbox and sent only when live; a repeated id is
  a no-op.
* A Scribase add-on ``grant`` claim funds one launch reel per org per month;
  a second draw is refused with a plain message and an upgrade path.
* Mint mirrors Dodo credit and pack events as ledger entries and never mints
  or pays out.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.domains.funnel_readout.models  # noqa: F401 - registers funnel_attribution for create_all
import app.models.db.base as db_base
from app.integrations.railyard import contract, grants, meters, provider_clients
from app.models.db.base import Base
from app.models.db.models import Job, User

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "apps" / "api" / "app"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "railyard-consumer-contract.json").read_text())
PROVIDER_SDKS = ("openai", "anthropic", "groq", "google.genai", "google.generativeai", "mistralai", "cohere",
                 "litellm", "dashscope")
RELAY_BOUNDARY = ("integrations/railyard/provider_clients.py", "domains/railyard/")
LIVE = {"RAILYARD_LIVE": "1", "RAGO_URL": "http://rago.test", "RAGO_API_KEY": "rk", "RELAY_URL": "http://relay.test"}


@pytest.fixture()
def maker(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
                           future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def _session():
        s = factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    monkeypatch.setattr(db_base, "get_session", _session)
    with factory() as s:
        s.add(User(email="u@example.com", api_key_hash=hashlib.sha256(b"k").hexdigest()))
        s.commit()
    for name in FIXTURE["env"]:
        monkeypatch.delenv(name, raising=False)
    return factory


def _uid(maker):
    with maker() as s:
        return s.query(User).one().id


# --------------------------------------------------------------------------- #
# Relay: no direct provider client outside the Relay boundary
# --------------------------------------------------------------------------- #
def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
            found += [f"{node.module}.{alias.name}" for alias in node.names]
    return found


def test_no_provider_sdk_is_imported_outside_the_relay_boundary():
    offenders = []
    for path in APP.rglob("*.py"):
        rel = str(path.relative_to(APP))
        if "tests" in path.parts or any(rel.startswith(b) or rel == b for b in RELAY_BOUNDARY):
            continue
        for name in _imports(path):
            if any(name == sdk or name.startswith(sdk + ".") for sdk in PROVIDER_SDKS):
                offenders.append(f"{rel}: {name}")
    assert offenders == []


def test_live_mode_refuses_direct_llm_clients_but_allows_relay_and_speech(monkeypatch):
    monkeypatch.setenv("RAILYARD_LIVE", "1")
    monkeypatch.setenv("RELAY_URL", "http://relay.test/")
    with pytest.raises(provider_clients.DirectProviderBlocked):
        provider_clients.OpenAI(api_key="sk", base_url="https://api.openai.com/v1")
    with pytest.raises(provider_clients.DirectProviderBlocked):
        provider_clients.AzureOpenAI(api_key="k", api_version="2024-01-01", azure_endpoint="https://x.azure.com")
    with pytest.raises(provider_clients.DirectProviderBlocked):
        provider_clients.litellm_module()
    assert provider_clients.OpenAI(api_key="relay", base_url="http://relay.test/openai/v1") is not None
    assert provider_clients.OpenAI(api_key="k", base_url="https://api.openai.com/v1",
                                   purpose=provider_clients.SPEECH) is not None
    monkeypatch.setenv("RAILYARD_LIVE", "0")
    assert provider_clients.OpenAI(api_key="k", base_url="https://api.openai.com/v1") is not None


def test_live_mode_turns_off_the_free_provider_chain(monkeypatch):
    from app.services import llm_fallback

    runtime = {"ollama_base_url": "http://localhost:11434", "pollinations_api_key": "", "groq_api_key": "g"}
    monkeypatch.delenv("RAILYARD_LIVE", raising=False)
    before = list(llm_fallback.fallback_chain("openai", runtime))
    monkeypatch.setenv("RAILYARD_LIVE", "1")
    assert list(llm_fallback.fallback_chain("openai", runtime)) == []
    monkeypatch.setenv("RAILYARD_LIVE", "0")
    assert list(llm_fallback.fallback_chain("openai", runtime)) == before  # unchanged when not live


def test_live_llm_call_without_relay_never_reaches_a_provider(monkeypatch):
    import openai

    from app.services import llm

    monkeypatch.setenv("RAILYARD_LIVE", "1")
    monkeypatch.delenv("RELAY_URL", raising=False)
    monkeypatch.delenv("RAILYARD_RELAY_URL", raising=False)
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: pytest.fail("direct provider client was built"))
    runtime = {"llm_provider": "openai", "openai_api_key": "sk-test", "openai_model_name": "gpt-4o-mini"}
    text = llm._generate_response_uncounted("hello", runtime)
    assert text.startswith("Error: ") and "relay" in text.lower()


def test_relay_key_is_accepted_under_the_contract_name():
    from app.integrations.railyard.relay import relay_env

    env = relay_env({"RELAY_URL": "http://relay.test", "RELAY_KEY": "rk"})
    assert env["RELAY_API_KEY"] == "rk"


# --------------------------------------------------------------------------- #
# Rago: contract events through the outbox
# --------------------------------------------------------------------------- #
def test_contract_matches_the_fixture():
    assert list(contract.MENIVOR_METERS) == FIXTURE["meters"]["menivor"]
    example = FIXTURE["event_example"]
    assert contract.transaction_id(example["code"], "job_123") == example["transaction_id"]
    event = contract.rago_event(code=example["code"], source_id="job_123", customer="user_1",
                                timestamp=example["timestamp"], properties=example["properties"])
    assert event == example
    assert contract.grant_transaction_id("org_1", "2026-10", 1) == FIXTURE["grant"]["transaction_id_example"]
    with pytest.raises(ValueError):
        contract.transaction_id("rally.email.sent", "x")


def test_events_are_idempotent_and_sent_only_when_live(maker, monkeypatch):
    sent = []

    def post(url, body, headers):
        sent.append((url, body, headers))
        return 200

    with maker() as s:
        assert meters.record(s, code="menivor.reel.rendered", source_id="j1", customer="u1") is True
        assert meters.record(s, code="menivor.reel.rendered", source_id="j1", customer="u1") is False
        s.commit()
    with maker() as s:
        assert meters.flush(s, post=post, env={}) == 0
        assert sent == []
        assert meters.flush(s, post=post, env=LIVE) == 1
        s.commit()
    url, body, headers = sent[0]
    assert url == "http://rago.test" + FIXTURE["rago_events_path"]
    assert body == {"event": {"transaction_id": "menivor:reel.rendered:j1", "external_customer_id": "u1",
                              "code": "menivor.reel.rendered", "timestamp": body["event"]["timestamp"],
                              "properties": {}}}
    assert headers["Authorization"] == "Bearer rk"
    with maker() as s:
        assert meters.flush(s, post=post, env=LIVE) == 0  # nothing left to send


def test_failed_sends_are_retried_with_attempts_recorded(maker):
    calls = {"n": 0}

    def flaky(url, body, headers):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("rago down")
        return 200

    with maker() as s:
        meters.record(s, code="menivor.preset.render", source_id="j2", customer="u1")
        s.commit()
    with maker() as s:
        assert meters.flush(s, post=flaky, env=LIVE) == 0
        s.commit()
    with maker() as s:
        row = s.query(meters.MeterOutbox).one()
        assert row.attempts == 1 and "rago down" in row.last_error and row.sent_at is None
        assert meters.flush(s, post=flaky, env=LIVE) == 1
        s.commit()


def test_a_settled_render_records_reel_and_preset_meters(maker):
    uid = _uid(maker)
    with maker() as s:
        job = Job(user_id=uid, kind="avatar_reel", state=1,
                  params={"preset_run": {"preset_id": "crash-zoom", "opened_at": "2026-09-30T10:00:00+00:00"}})
        s.add(job)
        s.commit()
        job_id = job.id
    meters.on_render_settled(job_id=job_id, owner_key=uid, job_kind="avatar_reel")
    with maker() as s:
        ids = sorted(r.transaction_id for r in s.query(meters.MeterOutbox).all())
    assert ids == [f"menivor:preset.render:{job_id}", f"menivor:reel.rendered:{job_id}"]


def test_meter_render_feeds_the_contract_outbox_even_without_legacy_rago(maker):
    from app.integrations.railyard import meter_render

    uid = _uid(maker)
    with maker() as s:
        job = Job(user_id=uid, kind="avatar_reel", state=1, params={})
        s.add(job)
        s.commit()
        job_id = job.id
    assert meter_render(job_id=job_id, owner_key=uid, credits_micros=10, env={}) is False
    with maker() as s:
        assert [r.transaction_id for r in s.query(meters.MeterOutbox).all()] == [f"menivor:reel.rendered:{job_id}"]


def test_lora_training_records_its_meter(maker):
    with maker() as s:
        meters.lora_train(s, job_id="lora1", customer="u1", credits=300)
        s.commit()
    with maker() as s:
        row = s.query(meters.MeterOutbox).one()
    assert row.transaction_id == "menivor:lora.train:lora1" and row.payload["properties"]["ai_video_credits"] == 300


# --------------------------------------------------------------------------- #
# Grants: the Scribase add-on's monthly launch reel
# --------------------------------------------------------------------------- #
def _claims(org="org_1", grant="addon-monthly-reel", period=None):
    from app.domains.partners.scribase_tokens import PartnerClaims

    period = period or datetime.now(timezone.utc).strftime("%Y-%m")
    return PartnerClaims(issuer="https://api.scribase.com", audience="menivor", capability="launch-video",
                         project_id="p", org_id=org, jti="j", issued_at=0, expires_at=1, grant=grant,
                         grant_period=period)


def _second_user(maker) -> str:
    with maker() as s:
        u = User(email="two@example.com", api_key_hash=hashlib.sha256(b"k2").hexdigest())
        s.add(u)
        s.commit()
        return u.id


def test_grant_funds_one_reel_per_org_per_month(maker):
    from app.models.db.repositories import CreditRepository

    uid = _uid(maker)
    with maker() as s:
        before = CreditRepository(s).balance(uid)
        result = grants.redeem(s, _claims(), user_id=uid)
        s.commit()
    assert result["reels"] == 1 and result["period"] == datetime.now(timezone.utc).strftime("%Y-%m")
    with maker() as s:
        assert CreditRepository(s).balance(uid) == before + 1
        again = grants.redeem(s, _claims(), user_id=uid)  # same user: no second credit
        s.commit()
    assert again["reels"] == 1 and again["duplicate"] is True
    with maker() as s:
        assert CreditRepository(s).balance(uid) == before + 1
        ids = [r.transaction_id for r in s.query(meters.MeterOutbox).all()]
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    assert ids == [f"menivor:grant:org_1:{period}:1"]
    other = _second_user(maker)
    with maker() as s, pytest.raises(grants.GrantExhausted) as exc:
        grants.redeem(s, _claims(), user_id=other)
    assert "pricing" in exc.value.upgrade_url and "included reel" in exc.value.message


def test_grants_refuse_other_claims_and_other_months(maker):
    uid = _uid(maker)
    with maker() as s:
        assert grants.redeem(s, _claims(grant=""), user_id=uid) is None
        with pytest.raises(grants.GrantInvalid):
            grants.redeem(s, _claims(grant="addon-mail"), user_id=uid)
        with pytest.raises(grants.GrantInvalid):
            grants.redeem(s, _claims(period="2020-01"), user_id=uid)


def test_partner_token_carries_the_grant_claims():
    from app.domains.partners import scribase_tokens as st

    claims = st.PartnerClaims(issuer="i", audience="menivor", capability="launch-video", project_id="p",
                              org_id="o", jti="j", issued_at=0, expires_at=1)
    assert claims.grant == "" and claims.grant_period == ""


# --------------------------------------------------------------------------- #
# Mint mirror of Dodo events: ledger entries only
# --------------------------------------------------------------------------- #
def test_dodo_pack_and_refund_are_mirrored_once_and_never_minted(maker, monkeypatch):
    from app.domains.wallet import mint_client

    monkeypatch.setattr(mint_client.MintClient, "mint_deposit",
                        lambda *a, **k: pytest.fail("the mirror must never mint"))
    view = {"payment_id": "pay_123", "total_amount": 900, "currency": "USD", "metadata": {"user_id": "u1"}}
    result = {"plan_key": "pack_10", "credits": 10}
    with maker() as s:
        assert meters.mirror_dodo_payment(s, view, result) is True
        assert meters.mirror_dodo_payment(s, view, result) is False
        assert meters.mirror_dodo_refund(s, "pay_123", {"debited": 10, "user_id": "u1"}) is True
        s.commit()
    with maker() as s:
        rows = {r.transaction_id: r for r in s.query(meters.MeterOutbox).filter_by(channel="mint").all()}
    assert set(rows) == {"menivor:dodo:pay_123", "menivor:dodo:pay_123:refund"}
    entry = rows["menivor:dodo:pay_123"].payload
    assert entry == {"entry_id": "menivor:dodo:pay_123", "type": "payment.succeeded", "external_customer_id": "u1",
                     "amount_cents": 900, "currency": "USD", "credits": 10, "product": "pack_10", "source": "dodo"}


def test_mint_entries_wait_for_the_mirror_endpoint(maker):
    sent = []
    with maker() as s:
        meters.mirror_dodo_payment(s, {"payment_id": "p", "total_amount": 1, "currency": "USD",
                                       "metadata": {"user_id": "u"}}, {"plan_key": "k", "credits": 1})
        s.commit()
    env = {**LIVE, "MINT_URL": "http://mint.test", "MINT_API_KEY": "mk"}
    with maker() as s:
        assert meters.flush(s, post=lambda *a: sent.append(a) or 200, env=env, channel="mint") == 0
        env["MINT_MIRROR_PATH"] = "/v1/ledger/mirror"
        assert meters.flush(s, post=lambda *a: sent.append(a) or 200, env=env, channel="mint") == 1
    assert sent[0][0] == "http://mint.test/v1/ledger/mirror"


# --------------------------------------------------------------------------- #
# Migration
# --------------------------------------------------------------------------- #
def test_migration_is_idempotent_on_a_scratch_database():
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    path = REPO / "migrations" / "versions" / "20260930_1100_a4c6e8f0b2d3_railyard_meter_outbox.py"
    spec = importlib.util.spec_from_file_location("outbox_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.revision, module.down_revision) == ("a4c6e8f0b2d3", "f3b5d7e9a1c2")
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            module.upgrade()
            module.upgrade()
        assert {"railyard_meter_outbox", "railyard_grant_redemptions"} <= set(inspect(conn).get_table_names())
        with Operations.context(ctx):
            module.downgrade()
        assert "railyard_meter_outbox" not in set(inspect(conn).get_table_names())


def test_launch_video_brief_says_the_reel_is_included_then_used(maker):
    from app.domains.partners import launch_video as lv

    class Verifier:
        def verify(self, token, audience, capability):
            return _claims()

    uid = _uid(maker)
    with maker() as s:
        brief = lv.start_launch_video(s, user_id=uid, token="t" * 20, app_url="https://app.example",
                                      app_name="App", verifier=Verifier())
        s.commit()
    assert brief.as_dict()["grant"]["reels"] == 1
    other = _second_user(maker)
    with maker() as s:
        second = lv.start_launch_video(s, user_id=other, token="t" * 20, app_url="https://app.example",
                                       app_name="App", verifier=Verifier())
    assert second.as_dict()["grant"]["reels"] == 0
    assert second.as_dict()["grant"]["upgrade_url"] == "/pricing"
    assert "grant" not in lv.draft_brief("https://a.example", "A", "scribase").as_dict()


def test_live_moderation_uses_the_relay_hop_only_and_fails_closed(monkeypatch):
    from app.core import moderation_safeguard as ms
    from app.core.moderation_types import ModerationUnavailable

    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("RELAY_URL", raising=False)
    monkeypatch.delenv("RAILYARD_RELAY_URL", raising=False)
    monkeypatch.setenv("RAILYARD_LIVE", "1")
    monkeypatch.setitem(ms._CALL, "groq", lambda p, t: pytest.fail("direct groq hop in production"))
    monkeypatch.setitem(ms._CALL, "claude", lambda p, t: pytest.fail("direct Anthropic hop in production"))
    assert [hop for hop in ms.HOPS if ms._ENABLED[hop]()] == []
    with pytest.raises(ModerationUnavailable):
        ms.check("hello", timeout_s=1.0)
    monkeypatch.setenv("RAILYARD_LIVE", "0")
    assert ms._ENABLED["groq"]() and ms._ENABLED["claude"]()


def test_live_openrouter_llm_has_no_direct_fallback(monkeypatch):
    from app.domains.routing.base import ProviderError
    from app.domains.routing.providers import openrouter

    monkeypatch.setenv("RAILYARD_LIVE", "1")
    provider = openrouter.OpenRouterAdapter.__new__(openrouter.OpenRouterAdapter)
    monkeypatch.setattr(provider, "_railyard_payload", lambda body, cid: None, raising=False)
    monkeypatch.setattr(provider, "_request", lambda *a, **k: pytest.fail("direct OpenRouter call"), raising=False)
    monkeypatch.setattr(provider, "_raw_model_id", lambda snapshot: "m", raising=False)
    with pytest.raises(ProviderError):
        provider.submit({"messages": [{"role": "user", "content": "hi"}]}, None, correlation_id="c1")


def test_metering_never_fails_the_action_when_the_outbox_is_missing():
    engine = create_engine("sqlite://")
    with sessionmaker(bind=engine)() as s:
        assert meters.record(s, code="menivor.lora.train", source_id="j", customer="u") is False
