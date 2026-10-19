"""SEO (Menivor Growth): connect OpenSEO, site audit, keyword research, rank
tracking. Every OpenSEO call runs through a recording fake MCP transport;
only the network is faked (the DB, encryption and scope checks are real).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.domains.integrations.errors import IntegrationError
from app.domains.integrations.scope import resolve
from app.domains.seo import openseo_client as oseo
from app.domains.seo import service
from app.domains.seo.errors import SeoError
from app.domains.seo.models import SeoAuditRun, SeoConnection, SeoKeywordResearch, SeoRankKeyword, SeoRankSnapshot
from app.services import crypto_tokens
from tests.reelforge._integrations_fakes import FakeTransport, Resp, add_user, add_workspace

MCP = "https://app.openseo.so/mcp"


def _rpc_result(result) -> dict:
    return {"jsonrpc": "2.0", "id": "call-1", "result": {"structuredContent": result}}


def _init_resp() -> Resp:
    return Resp(200, {"jsonrpc": "2.0", "id": "init", "result": {}}, headers={"Mcp-Session-Id": "sess-1"})


def _make_db():
    from app.models.db.base import Base
    import app.domains.seo.models  # noqa: F401  (registers tables)
    import app.domains.integrations.models  # noqa: F401  (Scope touches WorkspaceMember/UserPreset)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)

    @contextmanager
    def scope():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    factory.scope = scope
    return factory


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setenv("SOCIAL_TOKEN_KEY", "unit-test-seo-key")
    return _make_db()


@pytest.fixture()
def team(db):
    owner = add_user(db, "owner@example.com")
    member = add_user(db, "member@example.com")
    ws = add_workspace(db, owner, members=[(member, "member")])
    return {"owner": owner, "member": member, "ws": ws}


def _scope(db, user_id, ws=None):
    with db.scope() as s:
        return resolve(s, user_id, workspace_id=ws)


def _connect(db, team, *, domain="shop.example.com"):
    sc = _scope(db, team["owner"], team["ws"])
    t = FakeTransport().add("POST", MCP, _init_resp(),
                            Resp(200, _rpc_result([{"id": "proj_1", "domain": domain}])))
    with db.scope() as s:
        out = service.connect(s, sc, "oseo_live_key_12345", domain=domain, transport=t)
    return out, t


# --------------------------------------------------------------------------- client
def test_openseo_client_initializes_a_session_then_calls_the_tool():
    t = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, _rpc_result({"ok": True})))
    out = oseo.call_tool(t, "oseo_key", "list_projects", {})
    assert out == {"ok": True}
    init_call, tool_call = t.calls
    assert init_call["json"]["method"] == "initialize" and "Mcp-Session-Id" not in init_call["headers"]
    assert tool_call["json"]["method"] == "tools/call" and tool_call["headers"]["Mcp-Session-Id"] == "sess-1"
    assert tool_call["json"]["params"] == {"name": "list_projects", "arguments": {}}
    assert init_call["headers"]["Authorization"] == "Bearer oseo_key"


def test_openseo_client_text_block_result_is_json_decoded():
    t = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, {"jsonrpc": "2.0", "id": "call-1", "result": {
        "content": [{"type": "text", "text": '{"audits": 1}'}]}}))
    assert oseo.call_tool(t, "k", "run_site_audit", {}) == {"audits": 1}


def test_openseo_client_maps_401_to_auth_error():
    t = FakeTransport().add("POST", MCP, Resp(401, {"error": "unauthorized"}))
    with pytest.raises(oseo.OpenSeoError) as err:
        oseo.call_tool(t, "bad-key", "list_projects", {})
    assert err.value.status_code == 401


def test_openseo_client_tool_error_raises():
    t = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, {"jsonrpc": "2.0", "id": "call-1", "result": {
        "isError": True, "content": [{"type": "text", "text": "rate limited"}]}}))
    with pytest.raises(oseo.OpenSeoError, match="rate limited"):
        oseo.call_tool(t, "k", "run_site_audit", {})


def test_openseo_client_requires_a_key():
    with pytest.raises(oseo.OpenSeoError):
        oseo.call_tool(FakeTransport(), "", "list_projects", {})


def test_openseo_client_reads_an_sse_frame():
    sse = Resp(200, text='event: message\ndata: {"jsonrpc": "2.0", "id": "call-1", "result": {"ok": true}}\n',
              headers={"Content-Type": "text/event-stream"})
    t = FakeTransport().add("POST", MCP, _init_resp(), sse)
    assert oseo.call_tool(t, "k", "list_projects", {}) == {"ok": True}


def test_openseo_client_sse_with_no_data_line_errors():
    sse = Resp(200, text="event: ping\n", headers={"Content-Type": "text/event-stream"})
    t = FakeTransport().add("POST", MCP, _init_resp(), sse)
    with pytest.raises(oseo.OpenSeoError, match="empty response"):
        oseo.call_tool(t, "k", "list_projects", {})


def test_openseo_client_sse_with_malformed_json_errors():
    sse = Resp(200, text="data: not-json\n", headers={"Content-Type": "text/event-stream"})
    t = FakeTransport().add("POST", MCP, _init_resp(), sse)
    with pytest.raises(oseo.OpenSeoError, match="could not read"):
        oseo.call_tool(t, "k", "list_projects", {})


def test_openseo_client_non_json_body_errors():
    t = FakeTransport().add("POST", MCP, Resp(200, text="<html>not json</html>"))
    with pytest.raises(oseo.OpenSeoError, match="could not read"):
        oseo.call_tool(t, "k", "list_projects", {})


def test_openseo_client_network_failure_is_wrapped():
    class _Boom:
        def request(self, *a, **k):
            raise ConnectionError("down")
    with pytest.raises(oseo.OpenSeoError, match="unreachable"):
        oseo.call_tool(_Boom(), "k", "list_projects", {})


def test_openseo_client_server_http_error_maps_to_502():
    t = FakeTransport().add("POST", MCP, Resp(500, {"error": "boom"}))
    with pytest.raises(oseo.OpenSeoError) as err:
        oseo.call_tool(t, "k", "list_projects", {})
    assert err.value.status_code == 502


def test_openseo_client_top_level_jsonrpc_error_maps_to_400():
    t = FakeTransport().add("POST", MCP, Resp(200, {"jsonrpc": "2.0", "id": "call-1",
                                                    "error": {"message": "unknown tool"}}))
    with pytest.raises(oseo.OpenSeoError, match="unknown tool") as err:
        oseo.call_tool(t, "k", "no_such_tool", {})
    assert err.value.status_code == 400


def test_openseo_client_text_block_that_is_not_json_is_returned_as_is():
    t = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, {"jsonrpc": "2.0", "id": "call-1", "result": {
        "content": [{"type": "text", "text": "plain text answer"}]}}))
    assert oseo.call_tool(t, "k", "list_projects", {}) == "plain text answer"


def test_openseo_client_custom_mcp_url_is_honored():
    custom = "https://self-hosted.example.com/mcp"
    t = FakeTransport().add("POST", custom, _init_resp(), Resp(200, _rpc_result({"ok": True})))
    assert oseo.call_tool(t, "k", "list_projects", {}, url=custom) == {"ok": True}


# --------------------------------------------------------------------------- connect
def test_connect_validates_the_key_with_a_free_call_and_picks_the_project(db, team):
    out, t = _connect(db, team)
    assert out["connected"] is True and out["project_id"] == "proj_1" and out["domain"] == "shop.example.com"
    assert len(t.calls) == 2  # initialize + tools/call; no audit/research call made
    with db.scope() as s:
        conn = s.execute(select(SeoConnection)).scalar_one()
        assert crypto_tokens.decrypt(conn.api_key_enc) == "oseo_live_key_12345"
        assert "oseo_live_key_12345" not in str(out)


def test_connect_rejects_a_short_key(db, team):
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s, pytest.raises(SeoError) as err:
        service.connect(s, sc, "short", domain="x.com", transport=FakeTransport())
    assert err.value.status_code == 422


def test_connect_requires_manage_role(db, team):
    sc = _scope(db, team["member"], team["ws"])
    with db.scope() as s, pytest.raises(IntegrationError) as err:
        service.connect(s, sc, "oseo_live_key_12345", domain="x.com", transport=FakeTransport())
    assert err.value.status_code == 403


def test_overview_before_connect_is_not_connected(db, team):
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        out = service.overview(s, sc)
    assert out == {"connected": False, "can_manage": True}


def test_disconnect_removes_everything(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s:
        assert service.disconnect(s, sc) is True
    with db.scope() as s:
        assert s.execute(select(SeoConnection)).scalars().all() == []
    with db.scope() as s:
        assert service.disconnect(s, sc) is False  # already gone


# --------------------------------------------------------------------------- audit
def test_run_audit_then_refresh_reads_score_and_issues(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    t = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, _rpc_result({"auditId": "aud_1"})))
    with db.scope() as s:
        started = service.run_audit(s, sc, transport=t)
    assert started["status"] == "running"
    t2 = FakeTransport()
    t2.add("POST", MCP, _init_resp(), Resp(200, _rpc_result({"status": "completed", "score": 82})))
    with db.scope() as s:
        mid = service.refresh_audit(s, sc, started["id"], transport=t2)
    assert mid["status"] == "completed" and mid["score"] == 82
    # a completed status triggers a second (free) issues read
    assert len(t2.calls) == 4  # init+call for status, init+call for issues


def test_run_audit_without_a_project_is_rejected(db, team, monkeypatch):
    sc = _scope(db, team["owner"], team["ws"])
    # connect with no domain -> no project resolved
    t = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, _rpc_result([])))
    with db.scope() as s:
        service.connect(s, sc, "oseo_live_key_12345", domain="", transport=t)
    with db.scope() as s, pytest.raises(SeoError) as err:
        service.run_audit(s, sc, transport=FakeTransport())
    assert err.value.status_code == 422


def test_refresh_audit_unknown_id_404s(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s, pytest.raises(SeoError) as err:
        service.refresh_audit(s, sc, "0" * 32, transport=FakeTransport())
    assert err.value.status_code == 404


def test_auth_error_marks_needs_reauth(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    t = FakeTransport().add("POST", MCP, Resp(401, {"error": "unauthorized"}))
    with db.scope() as s, pytest.raises(SeoError) as err:
        service.run_audit(s, sc, transport=t)
    assert err.value.status_code == 401
    with db.scope() as s:
        assert s.execute(select(SeoConnection)).scalar_one().status == "needs_reauth"
    # a later call against the now-reauth connection is refused before any network call
    with db.scope() as s, pytest.raises(SeoError) as err2:
        service.run_audit(s, sc, transport=FakeTransport())
    assert err2.value.status_code == 409


# --------------------------------------------------------------------------- keyword research
def test_research_keywords_caps_seeds_and_caches_rows(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    t = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, _rpc_result([
        {"keyword": "project management software", "volume": 12000, "difficulty": 55, "cpc": 4.2,
         "intent": "commercial"},
        {"keyword": "free project tracker", "volume": 3000, "difficulty": 20, "cpc": 1.1},
    ])))
    with db.scope() as s:
        out = service.research_keywords(s, sc, ["project management"] * 3 + [f"seed{i}" for i in range(20)],
                                        transport=t)
    assert len(out) == 2 and out[0]["volume"] == 12000 and out[0]["cpc_minor"] == 420
    call = t.calls[1]["json"]["params"]["arguments"]
    assert len(call["keywords"]) == service.MAX_RESEARCH_SEEDS  # deduped + capped before the network call
    with db.scope() as s:
        assert len(service.list_research(s, sc)) == 2


def test_research_keywords_requires_at_least_one_seed(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    with db.scope() as s, pytest.raises(SeoError) as err:
        service.research_keywords(s, sc, ["   ", ""], transport=FakeTransport())
    assert err.value.status_code == 422


# --------------------------------------------------------------------------- rank tracker
def test_add_rank_keywords_enforces_the_handful_limit(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    t = FakeTransport()
    t.add("POST", MCP, *([_init_resp(), Resp(200, _rpc_result({}))] * 2))
    with db.scope() as s:
        out = service.add_rank_keywords(s, sc, [f"kw{i}" for i in range(service.MAX_TRACKED_KEYWORDS)],
                                        transport=t)
    assert len(out) == service.MAX_TRACKED_KEYWORDS
    with db.scope() as s, pytest.raises(SeoError) as err:
        service.add_rank_keywords(s, sc, ["one more"], transport=FakeTransport())
    assert err.value.status_code == 422


def test_add_rank_keywords_dedupes_against_existing(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    t1 = FakeTransport().add("POST", MCP, *([_init_resp(), Resp(200, _rpc_result({}))] * 2))
    with db.scope() as s:
        service.add_rank_keywords(s, sc, ["alpha"], transport=t1)
    t2 = FakeTransport().add("POST", MCP, *([_init_resp(), Resp(200, _rpc_result({}))] * 2))
    with db.scope() as s:
        out = service.add_rank_keywords(s, sc, ["alpha", "beta"], transport=t2)
    assert sorted(k["keyword"] for k in out) == ["alpha", "beta"]


def test_remove_rank_keyword(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    t = FakeTransport().add("POST", MCP, *([_init_resp(), Resp(200, _rpc_result({}))] * 2))
    with db.scope() as s:
        [row] = service.add_rank_keywords(s, sc, ["alpha"], transport=t)
    with db.scope() as s:
        assert service.remove_rank_keyword(s, sc, row["id"]) is True
    with db.scope() as s:
        assert s.execute(select(SeoRankKeyword)).scalars().all() == []
    with db.scope() as s, pytest.raises(SeoError) as err:
        service.remove_rank_keyword(s, sc, row["id"])
    assert err.value.status_code == 404


def test_refresh_rank_tracker_records_rank_history_and_change(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    setup = FakeTransport().add("POST", MCP, _init_resp(), Resp(200, _rpc_result({})))
    with db.scope() as s:
        service.add_rank_keywords(s, sc, ["alpha"], transport=setup)
    t1 = FakeTransport()
    t1.add("POST", MCP, _init_resp(), Resp(200, _rpc_result({})), _init_resp(),
          Resp(200, _rpc_result([{"keyword": "alpha", "rank": 8}])))
    with db.scope() as s:
        out1 = service.refresh_rank_tracker(s, sc, transport=t1, today="2026-10-10")
    assert out1[0]["current_rank"] == 8 and out1[0]["change_7d"] is None
    t2 = FakeTransport()
    t2.add("POST", MCP, _init_resp(), Resp(200, _rpc_result({})), _init_resp(),
          Resp(200, _rpc_result([{"keyword": "alpha", "rank": 5}])))
    with db.scope() as s:
        out2 = service.refresh_rank_tracker(s, sc, transport=t2, today="2026-10-11")
    assert out2[0]["current_rank"] == 5 and out2[0]["change_7d"] == 3  # 8 -> 5, improved by 3
    with db.scope() as s:
        snaps = s.execute(select(SeoRankSnapshot)).scalars().all()
        assert sorted(sn.day for sn in snaps) == ["2026-10-10", "2026-10-11"]


def test_refresh_rank_tracker_with_no_keywords_is_a_no_op(db, team):
    _connect(db, team)
    sc = _scope(db, team["owner"], team["ws"])
    out = None
    with db.scope() as s:
        out = service.refresh_rank_tracker(s, sc, transport=FakeTransport())
    assert out == []
