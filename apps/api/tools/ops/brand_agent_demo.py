"""Run the Brand Agent setup flow on a real website and print the brand memory as JSON.

Free and local: an in-memory SQLite database, the real site fetch (SSRF-guarded),
optional DuckDuckGo HTML search (``--search duckduckgo``), no LLM unless Relay is
configured, and the stub Meta / Ad Clone ports. Nothing is generated, charged or
published (no action is ever approved here).

    python apps/api/tools/ops/brand_agent_demo.py https://scribase.com --search duckduckgo \
        --out docs/plans/brand-agent-demo-scribase.json

Corrections are given the same way a user would answer "No, change it":
``--fix positioning="one-liner: ..."`` (repeatable).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

API = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(API))
os.environ.setdefault("REELFORGE_DISABLE_DOTENV", "1")
if "REELFORGE_CONFIG_FILE" not in os.environ:  # never write a config.toml into the repo
    import shutil
    import tempfile

    _cfg = Path(tempfile.mkdtemp(prefix="brand-agent-demo-")) / "config.toml"
    shutil.copyfile(API.parents[1] / "config.example.toml", _cfg)
    os.environ["REELFORGE_CONFIG_FILE"] = str(_cfg)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--search", default="", help="duckduckgo | searxng:https://host | (empty = off)")
    parser.add_argument("--fix", action="append", default=[], help='section="correction text"')
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    if args.search:
        os.environ["BRAND_AGENT_SEARCH"] = args.search

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.domains.brand_agent import agent, copy_rules, memory, sessions, setup_flow, spaces
    from app.domains.brand_agent import models as _models  # noqa: F401
    from app.domains.brand_agent.deps import AgentDeps, default_deps
    from app.models.db.base import Base
    from app.models.db.models import User

    class NoSpend:
        def generate(self, **_kw):
            raise RuntimeError("the demo never generates")

        def publish(self, **_kw):
            raise RuntimeError("the demo never publishes")

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def scope():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    base = default_deps()
    deps = AgentDeps(analyzer=base.analyzer, search=base.search, llm=base.llm, integrations=base.integrations,
                     ad_clone=base.ad_clone, generation=NoSpend(), publisher=NoSpend())
    fixes = {}
    for item in args.fix:
        section, _, text = item.partition("=")
        fixes[section.strip()] = text.strip().strip('"')

    with scope() as s:
        user = User(email="demo@menivor.local", api_key_hash=hashlib.sha256(b"demo").hexdigest(), credits=0)
        s.add(user)
        s.flush()
        uid = user.id
        space = spaces.ensure_default(s, uid)
        sid = sessions.create(s, uid, space.id).id
        space_id = space.id

    def say(text):
        with scope() as s:
            return agent.handle_text(s, deps, uid, sid, text)

    def chip(step, choice):
        with scope() as s:
            return agent.handle_chip(s, deps, uid, sid, step=step, choice=choice)

    say(f"Let's set up my brand from my website: {args.url}")
    for step in setup_flow.SECTION_STEPS:
        if step in fixes:
            chip(step, "no")
            say(fixes[step])
        chip(step, "yes")
    chip(setup_flow.STEP_META, "connect")
    chip(setup_flow.STEP_META, "skip")
    say("Write 5 hooks for TikTok")

    with scope() as s:
        transcript = [{"role": m["role"], "content": m["content"], "card": m["card"], "chips": m["chips"]}
                      for m in sessions.messages(s, uid, sid)]
        current = memory.current(s, space_id)
        versions = memory.history(s, space_id)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "url": args.url,
        "mode": {"llm": "relay" if deps.llm is not None else "off (deterministic, $0)",
                 "search": (os.environ.get("BRAND_AGENT_SEARCH") or "off")
                 + (f" ({deps.search.last_status})" if getattr(deps.search, "last_status", "") else ""),
                 "meta_ads": "stub (not connected on this machine)", "spend": "none; no action approved"},
        "corrections": fixes,
        "brand_memory": current,
        "versions": [{k: v[k] for k in ("version", "section", "source")} for v in versions],
        "copy_check": {"indie_violations": copy_rules.violations(json.dumps([current, transcript]))},
        "transcript": transcript,
    }
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
