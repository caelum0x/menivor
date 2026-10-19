"""Search across published titles (MV19): semantic similarity plus an exact-words boost.

Index text is the title, synopsis, genres and the first part of the
transcript (MV16). Vectors are kept per title; a search builds (and caches for
60 s) one matrix per channel scope and ranks with a single matrix product,
which stays far under the 300 ms p95 target on 5,000 titles.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.ott import catalog_public
from app.domains.ott.models import STATUS_PUBLISHED, OttChannel, OttTitle

from .embeddings import Embedder, by_name, default_embedder
from .models import OttTitleEmbedding

TRANSCRIPT_CHARS = 1500
KEYWORD_BOOST = 0.15
CACHE_S = 60.0
MIN_SCORE = 0.05
_WORD = re.compile(r"[\w']+", re.UNICODE)
_cache: dict[tuple, tuple[float, list[str], np.ndarray]] = {}


def index_text(session: Session, title: OttTitle) -> str:
    from app.domains.ott_ai.models import DONE, OttAiOutput

    row = session.execute(select(OttAiOutput).where(OttAiOutput.title_id == title.id,
                                                    OttAiOutput.kind == "transcript",
                                                    OttAiOutput.status == DONE)).scalars().first()
    spoken = " ".join(str(c[2]) for c in (row.data or {}).get("cues", [])) if row else ""
    return " ".join(x for x in (title.title, title.synopsis or "", " ".join(title.genres or []),
                                spoken[:TRANSCRIPT_CHARS]) if x)


def reindex(session: Session, *, embedder: Optional[Embedder] = None, limit: int = 500) -> int:
    """(Re)embed published titles whose text changed; returns how many were embedded."""
    model = embedder or default_embedder()
    titles = session.execute(select(OttTitle).where(OttTitle.status == STATUS_PUBLISHED)).scalars().all()
    stale: list[tuple[OttTitle, str, str]] = []
    for title in titles:
        text = index_text(session, title)
        digest = hashlib.sha256(f"{model.name}|{text}".encode()).hexdigest()
        row = session.get(OttTitleEmbedding, title.id)
        if row is None or row.text_hash != digest:
            stale.append((title, text, digest))
        if len(stale) >= limit:
            break
    if not stale:
        return 0
    vectors = model.embed([text for _t, text, _d in stale])
    for (title, _text, digest), vector in zip(stale, vectors):
        row = session.get(OttTitleEmbedding, title.id)
        if row is None:
            row = OttTitleEmbedding(title_id=title.id, channel_id=title.channel_id, model=model.name, dim=model.dim,
                                    vector=[], text_hash=digest)
            session.add(row)
        row.model, row.dim, row.vector, row.text_hash = model.name, model.dim, [round(float(x), 6) for x in vector], \
            digest
    session.flush()
    _cache.clear()
    return len(stale)


def _matrix(session: Session, model: str, channel_id: Optional[str]) -> tuple[list[str], np.ndarray]:
    key = (model, channel_id)
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1], hit[2]
    query = select(OttTitleEmbedding.title_id, OttTitleEmbedding.vector).where(OttTitleEmbedding.model == model)
    if channel_id:
        query = query.where(OttTitleEmbedding.channel_id == channel_id)
    rows = session.execute(query).all()
    ids = [r[0] for r in rows]
    matrix = np.array([r[1] for r in rows], dtype=np.float32) if rows else np.zeros((0, 1), dtype=np.float32)
    _cache[key] = (time.monotonic(), ids, matrix)
    return ids, matrix


def search(session: Session, q: str, *, channel_id: Optional[str] = None, limit: int = 20,
           embedder: Optional[Embedder] = None, country: str = "XX") -> dict[str, Any]:
    started = time.perf_counter()
    text = " ".join(str(q or "").split())[:200]
    if len(text) < 2:
        return {"query": text, "results": [], "took_ms": 0}
    model = embedder or default_embedder()
    ids, matrix = _matrix(session, model.name, channel_id)
    if not ids and embedder is None:
        # The index was written by another model (for example hashing before fastembed loaded): use it if we can.
        stored = session.execute(select(OttTitleEmbedding.model).limit(1)).scalar_one_or_none()
        other = by_name(stored) if stored and stored != model.name else None
        if other is not None:
            model = other
            ids, matrix = _matrix(session, model.name, channel_id)
    results: list[dict[str, Any]] = []
    if ids:
        scores = matrix @ model.embed([text])[0]
        words = {w.lower() for w in _WORD.findall(text)}
        ranked = {ids[int(i)]: float(scores[int(i)]) for i in np.argsort(-scores)[: limit * 3]}
        for title, channel in _watchable(list(ranked), session):
            name_words = {w.lower() for w in _WORD.findall(title.title)}
            score = ranked[title.id] + (KEYWORD_BOOST if words and words <= name_words else 0.0)
            if score < MIN_SCORE:
                continue
            results.append({**catalog_public.title_card(title, country), "channel": channel.handle,
                            "score": round(score, 4)})
        results.sort(key=lambda r: -r["score"])
    return {"query": text, "results": results[:limit], "took_ms": round((time.perf_counter() - started) * 1000, 1)}


RELATED_LIMIT = 12


class NotFound(Exception):
    pass


def _related_ids(session: Session, title: OttTitle, embedder: Optional[Embedder], want: int) -> list[str]:
    """Nearest titles of the same channel by stored vector (no model call when the title is indexed)."""
    row = session.get(OttTitleEmbedding, title.id)
    if row is not None and row.vector:
        model_name, vector = row.model, np.asarray(row.vector, dtype=np.float32)
    else:
        model = embedder or default_embedder()
        model_name, vector = model.name, model.embed([index_text(session, title)])[0].astype(np.float32)
    ids, matrix = _matrix(session, model_name, title.channel_id)
    if not ids or matrix.shape[1] != vector.shape[0]:
        return []
    scores = matrix @ vector
    order = np.argsort(-scores)[: want + 1]
    return [ids[int(i)] for i in order if ids[int(i)] != title.id and float(scores[int(i)]) > 0][:want]


def related(session: Session, title_id: str, *, limit: int = RELATED_LIMIT, country: str = "XX",
            embedder: Optional[Embedder] = None) -> dict[str, Any]:
    """Titles like this one on the same channel; newest titles fill the row when few are similar."""
    started = time.perf_counter()
    title = session.get(OttTitle, title_id)
    if not catalog_public.watchable(session, title):
        raise NotFound(title_id)
    limit = max(1, min(int(limit), 24))
    ranked = _related_ids(session, title, embedder, limit * 3)
    picked = [t for t, _c in _watchable(ranked, session)][:limit]
    source = "similar"
    if len(picked) < limit:
        newest = session.execute(select(OttTitle.id).where(
            OttTitle.channel_id == title.channel_id, OttTitle.status == STATUS_PUBLISHED, OttTitle.id != title.id)
            .order_by(OttTitle.published_at.desc()).limit(limit * 3)).scalars().all()
        have = {t.id for t in picked}
        extra = [t for t, _c in _watchable([i for i in newest if i not in have], session)]
        picked += extra[: limit - len(picked)]
        source = "similar+newest" if ranked else "newest"
    return {"title_id": title.id, "source": source,
            "results": [catalog_public.title_card(t, country) for t in picked],
            "took_ms": round((time.perf_counter() - started) * 1000, 1)}


def _watchable(candidate_ids: list[str], session: Session) -> list[tuple[OttTitle, OttChannel]]:
    """The candidates a viewer may play, loaded in three queries (not three per title), in rank order."""
    from app.domains.compliance.takedown import STATUS_BLOCKED, TakedownReport

    if not candidate_ids:
        return []
    titles = {t.id: t for t in session.execute(select(OttTitle).where(OttTitle.id.in_(candidate_ids))).scalars()}
    channels = {c.id: c for c in session.execute(select(OttChannel).where(
        OttChannel.id.in_({t.channel_id for t in titles.values()}))).scalars()}
    # A block names the source job, or the title id itself for uploads (catalog_public.watchable does both).
    media_ids = {t.source_job_id for t in titles.values() if t.source_job_id} | set(titles)
    blocked = set(session.execute(select(TakedownReport.job_id).where(
        TakedownReport.job_id.in_(media_ids), TakedownReport.status == STATUS_BLOCKED)).scalars())
    out = []
    for title_id in candidate_ids:
        title = titles.get(title_id)
        channel = channels.get(title.channel_id) if title else None
        if (title is None or channel is None or title.status != STATUS_PUBLISHED
                or title.package_status != catalog_public.READY or channel.status != STATUS_PUBLISHED
                or not catalog_public.in_window(title) or title.id in blocked
                or (title.source_job_id and title.source_job_id in blocked)):
            continue
        out.append((title, channel))
    return out


def reset_cache() -> None:
    _cache.clear()


__all__ = ["NotFound", "RELATED_LIMIT", "index_text", "reindex", "related", "reset_cache", "search"]
