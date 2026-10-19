"""Everything the agent talks to, in one frozen bundle (tests swap in fakes)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AgentDeps:
    analyzer: Callable[[str], dict[str, Any]]
    search: Any
    llm: Any | None
    integrations: Any
    ad_clone: Any
    generation: Any
    publisher: Any
    now: Callable[[], datetime] = _utcnow


def default_deps() -> AgentDeps:
    from app.domains.brand_agent import site_analysis
    from app.domains.brand_agent.ports import ad_clone, generation, integrations, llm, publishing, search

    return AgentDeps(
        analyzer=lambda url: site_analysis.analyze_site(url),
        search=search.get_port(),
        llm=llm.get_port(),
        integrations=integrations.get_port(),
        ad_clone=ad_clone.get_port(),
        generation=generation.get_port(),
        publisher=publishing.get_port(),
    )


__all__ = ["AgentDeps", "default_deps"]
