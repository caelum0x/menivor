"""Brand Agent adapter: the agent's Ad Clone port over :mod:`app.domains.adclone.service`.

Looked up at ``app.domains.adclone.agent_port:PORT`` (see
``app.domains.brand_agent.ports.ad_clone``). After the user approves a "Clone ad"
action the agent calls :meth:`AdCloneAgentPort.clone_from_link`, which runs the
same $0 steps as the Ad Clone page: the link -> clone brief (local analysis, LLM
only through Relay) -> clone plans priced per engine. It never starts a paid
render: that stays on the Ad Clone page, where the exact AI-video credit price is
shown and approved with an Idempotency-Key (``POST /ad-clone/render/approve``).

The product preset is the one whose brand name or domain appears in the agent's
brand memory, or ``BRAND_AGENT_ADCLONE_PRESET``; without a match the agent says so.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from app.domains.brand_agent.ports.base import PortUnavailable

from . import preset_store, presets, service
from .linkresolve import LinkError
from .rewrite import CloneOptions

PRESET_ENV = "BRAND_AGENT_ADCLONE_PRESET"
MAX_OPTIONS = 50  # the chat shows 6 and searches the rest
VARIATIONS_ENV = "BRAND_AGENT_ADCLONE_VARIATIONS"
STATUS_PLANNED = "planned"
NEXT_STEP = "Open Ad Clone to check the price and approve the render."
OFF = "Ad Clone is switched off on this server. The link is saved in Inspirations."
NO_PRESET = ("Ad Clone has no product preset for this brand yet (it has: {products}). "
             "The link is saved in Inspirations.")
FAILED = "Ad Clone could not read that ad. Check the link and approve again."


def _brand_text(brand: dict[str, Any]) -> str:
    try:
        return json.dumps(brand or {}, ensure_ascii=False, default=str).lower()
    except (TypeError, ValueError):
        return ""


def pick_preset(brand: dict[str, Any], env: dict[str, str] | None = None) -> str | None:
    """The preset for this brand: env override, else a brand name / domain match in brand memory."""
    env = os.environ if env is None else env
    forced = str(env.get(PRESET_ENV) or "").strip()
    if forced:
        return forced if forced in presets.PRESETS else None
    text = _brand_text(brand)
    for name in presets.PRESETS:
        try:
            data = presets.load(name)
        except presets.PresetError:
            continue
        marks = [str(data.get("domain") or "").lower(), str(data.get("brand_name") or "").lower()]
        if any(m and m in text for m in marks):
            return name
    return None


def _product_names() -> str:
    names = []
    for name in presets.PRESETS:
        try:
            names.append(str(presets.load(name).get("brand_name") or name))
        except presets.PresetError:
            continue
    return ", ".join(names) or "none"


def _variations(env: dict[str, str]) -> int:
    try:
        return max(1, min(int(env.get(VARIATIONS_ENV) or 1), 3))
    except ValueError:
        return 1


def _summary(result: dict[str, Any], preset: str, url: str) -> dict[str, Any]:
    variations = result.get("variations") or []
    plans = [v["plan"] for v in variations]
    first = plans[0] if plans else {}
    return {
        "status": STATUS_PLANNED,
        "job_id": f"plan:{first.get('slug', '')}" if first else "",
        "preset": preset,
        "source_url": url,
        "hook": ((result.get("brief") or {}).get("hook") or {}).get("pattern", ""),
        "variations": [{"slug": v["plan"].get("slug", ""), "engine": v["engine"].get("engine"),
                        "engine_label": v["engine"].get("label"), "usd": v["engine"].get("usd"),
                        "ai_video_credits": v.get("ai_video_credits")} for v in variations],
        "plans": plans,
        "paid_render": bool(result.get("paid_render")),
        "next": NEXT_STEP,
    }


class AdCloneAgentPort:
    """``analyze`` / ``plan`` / ``llm`` default to the Ad Clone service (tests pass fakes)."""

    def __init__(self, *, analyze: Callable[..., Any] | None = None, plan: Callable[..., Any] | None = None,
                 llm: Callable[[], Any] | None = None, env: dict[str, str] | None = None) -> None:
        self._analyze = analyze or service.analyze_link
        self._plan = plan or service.clone
        self._llm = llm or service.default_llm
        self._env = env

    @property
    def enabled(self) -> bool:
        """Whether Ad Clone is switched on (``ADCLONE_ENABLED``); the Connectors panel reads it."""
        env = os.environ if self._env is None else self._env
        return service._truthy(env.get(service.ENABLED_ENV))

    # ------------------------------------------------------------------ preflight (before Approve)
    def resolve_preset(self, session: Any, user_id: str, *, brand: dict[str, Any], space_id: str) -> str | None:
        """This Brand space's own product preset, else a shipped preset the brand matches."""
        stored = preset_store.for_space(session, user_id, space_id)
        if stored:
            return str(stored["id"])
        return pick_preset(brand, dict(os.environ if self._env is None else self._env))

    def product_options(self, session: Any, user_id: str, *, brand: dict[str, Any]) -> list[dict[str, str]]:
        """What the user can pick: imported catalog products first, then brand-memory products."""
        from sqlalchemy import select

        from app.domains.adstudio.catalog_models import StoreCatalogProduct

        out: list[dict[str, str]] = []
        rows = session.execute(
            select(StoreCatalogProduct).where(StoreCatalogProduct.user_id == user_id)
            .order_by(StoreCatalogProduct.created_at.desc(), StoreCatalogProduct.id).limit(MAX_OPTIONS)
        ).scalars().all()
        for row in rows:
            if (row.title or "").strip():
                thumb = next((u for u in (row.image_urls or []) if str(u).startswith("https://")), "")
                out.append({"id": f"catalog:{row.id}", "name": row.title.strip()[:120], "source": "catalog",
                            "detail": (row.description or "").strip()[:160], "thumbnail_url": str(thumb)[:500]})
        products = ((brand or {}).get("product") or {}).get("products") or []
        for i, p in enumerate(products):
            if isinstance(p, dict) and str(p.get("name") or "").strip() and len(out) < MAX_OPTIONS:
                out.append({"id": f"memory:{i}", "name": str(p["name"]).strip()[:120], "source": "brand_memory",
                            "detail": str(p.get("what_it_is") or "")[:160], "thumbnail_url": ""})
        return out

    def preflight(self, session: Any, user_id: str, *, brand: dict[str, Any], space_id: str) -> dict[str, Any] | None:
        """None when a clone can run now; else the one missing thing, with what fixes it."""
        if not self.enabled:
            return {"id": "adclone_off", "title": "Ad Clone is switched off on this server.",
                    "detail": "Ask the owner to turn on ADCLONE_ENABLED. Your link is saved in Inspirations.",
                    "options": []}
        if self.resolve_preset(session, user_id, brand=brand, space_id=space_id):
            return None
        options = self.product_options(session, user_id, brand=brand)
        detail = ("Pick the product this ad is for. I'll set it up in Ad Clone." if options else
                  "Import your products in Settings > Integrations (Shopify, Medusa or CSV), then press Check again.")
        return {"id": "product", "title": "Which product is this ad for?", "detail": detail, "options": options}

    def use_product(self, session: Any, user_id: str, *, space_id: str, product_id: str, brand: dict[str, Any],
                    brand_name: str = "", website: str = "") -> dict[str, Any]:
        """Make this space's Ad Clone preset from a picked product. Raises PortUnavailable."""
        option = next((o for o in self.product_options(session, user_id, brand=brand) if o["id"] == product_id), None)
        if option is None:
            raise PortUnavailable("That product is not in your catalog any more. Pick another one.")
        url = website
        line = option["detail"]
        if option["source"] == "catalog":
            from app.domains.adstudio.catalog_models import StoreCatalogProduct

            row = session.get(StoreCatalogProduct, product_id.split(":", 1)[1])
            url = (row.url if row is not None and row.url else "") or website
        name = brand_name or str(((brand or {}).get("positioning") or {}).get("name") or "") or option["name"]
        data = preset_store.create(session, user_id=user_id, space_id=space_id, product_ref=product_id,
                                   product=option["name"], product_line=line, brand_name=name, url=url)
        return {"preset": data["id"], "product": data["product"], "brand_name": data["brand_name"]}

    def clone_from_link(self, user_id: str, url: str, *, brand: dict[str, Any], space_id: str,
                        preset: str | None = None) -> dict[str, Any]:
        env = dict(os.environ if self._env is None else self._env)
        if not self.enabled:
            raise PortUnavailable(OFF)
        preset = preset or pick_preset(brand, env)
        if preset is None:
            raise PortUnavailable(NO_PRESET.format(products=_product_names()))
        llm = self._llm()
        try:
            brief = self._analyze(url, llm=llm)
            result = self._plan(brief, preset_name=preset, options=CloneOptions(variations=_variations(env)),
                                llm=llm, env=env)
        except (LinkError, service.AdCloneError, presets.PresetError) as exc:
            raise PortUnavailable(getattr(exc, "message", "") or FAILED) from exc
        except ValueError as exc:
            raise PortUnavailable(FAILED) from exc
        return _summary(result, preset, url)


PORT = AdCloneAgentPort()

__all__ = ["AdCloneAgentPort", "PORT", "pick_preset"]
