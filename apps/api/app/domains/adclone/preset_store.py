"""Brand product presets for Ad Clone, made from a product the user already has (migration ``a1c3e5f7b9d2``).

The Brand Agent offers the brand's catalog (Shopify / Medusa / CSV imports in
``store_catalog_products``) and the products in brand memory. "Use this" turns
one into a preset: the shipped episode template (cast, sets, look) with this
product, brand name, domain and closing line. Shipped presets stay read-only
files; these rows are per user and Brand space.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import JSON, DateTime, ForeignKey, String, func, select
from sqlalchemy.orm import Mapped, mapped_column

from app.models.db import models as _core_models  # noqa: F401  (registers users for the FK)
from app.models.db.base import Base

PREFIX = "bp"
TEMPLATE = "oxhan"
_ID = re.compile(r"^bp[0-9a-f]{30}$")
MAX_NAME = 120


class AdClonePreset(Base):
    __tablename__ = "adclone_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    space_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    product_ref: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def is_stored(name: str) -> bool:
    return bool(_ID.match(name or ""))


def _new_id() -> str:
    return PREFIX + uuid.uuid4().hex[:30]


def _clean(text: Any, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def _domain(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def build(template: dict[str, Any], *, product: str, product_line: str, brand_name: str, domain: str,
          preset_id: str) -> dict[str, Any]:
    """A new preset dict: the template's cast/sets/look with this product and closing line."""
    out = copy.deepcopy(template)
    where = domain or brand_name
    out.update({"id": preset_id, "product": _clean(product, MAX_NAME), "brand_name": _clean(brand_name, MAX_NAME),
                "product_line": _clean(product_line or product, 400), "domain": where, "template": template["id"]})
    out["cta"] = {"text": f"{_clean(product, 60)}. Get yours at {where}.",
                  "tts": f"{_clean(product, 60)}. Get yours at {where.replace('.', ' dot ')}.",
                  "speaker": template["cta"]["speaker"], "card": f"Get yours at {where}"}
    return out


def create(session: Any, *, user_id: str, space_id: str | None, product_ref: str, product: str,
           product_line: str, brand_name: str, url: str = "") -> dict[str, Any]:
    from . import presets

    preset_id = _new_id()
    data = build(presets.load(TEMPLATE), product=product, product_line=product_line, brand_name=brand_name,
                 domain=_domain(url), preset_id=preset_id)
    session.add(AdClonePreset(id=preset_id, user_id=user_id, space_id=space_id, product_ref=product_ref[:80],
                              data=data))
    session.flush()
    return data


def for_space(session: Any, user_id: str, space_id: str) -> dict[str, Any] | None:
    row = session.execute(
        select(AdClonePreset).where(AdClonePreset.user_id == user_id, AdClonePreset.space_id == space_id)
        .order_by(AdClonePreset.created_at.desc(), AdClonePreset.id.desc())
    ).scalars().first()
    return dict(row.data) if row else None


def load(name: str, session: Any | None = None) -> dict[str, Any] | None:
    """A stored preset by id (ids are random and unguessable), or None."""
    if not is_stored(name):
        return None
    if session is not None:
        row = session.get(AdClonePreset, name)
        return dict(row.data) if row else None
    from app.models.db.base import get_session

    with get_session() as s:
        row = s.get(AdClonePreset, name)
        return dict(row.data) if row else None


__all__ = ["AdClonePreset", "build", "create", "for_space", "is_stored", "load"]
