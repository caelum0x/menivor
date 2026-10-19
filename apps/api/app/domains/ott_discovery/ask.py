"""Ask this video (MV19): answers only from the title's own transcript, with a timestamp, or "I do not know".

The transcript (MV16) is cut into windows of about 30 s; the question picks
the closest windows by embedding; the model (through Relay) must answer from
those excerpts and cite ``[mm:ss]``. The answer is kept only if every cited
time falls inside an excerpt it was shown; otherwise the reply is the plain
"I do not know from this video." Nothing is answered from general knowledge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.ott.models import OttTitle

from .embeddings import Embedder, default_embedder

WINDOW_S = 30.0
TOP_WINDOWS = 4
DONT_KNOW = "I do not know from this video."
_STAMP = re.compile(r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]")


class AskError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


@dataclass(frozen=True)
class Window:
    start: float
    end: float
    text: str


def _stamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}" if total >= 3600 else \
        f"{total // 60:02d}:{total % 60:02d}"


def windows(cues: list[tuple[float, float, str]], size_s: float = WINDOW_S) -> list[Window]:
    out: list[Window] = []
    bucket: list[tuple[float, float, str]] = []
    for cue in cues:
        if bucket and cue[1] - bucket[0][0] > size_s:
            out.append(Window(bucket[0][0], bucket[-1][1], " ".join(c[2] for c in bucket)))
            bucket = []
        bucket.append(cue)
    if bucket:
        out.append(Window(bucket[0][0], bucket[-1][1], " ".join(c[2] for c in bucket)))
    return out


def _cited_seconds(answer: str) -> list[int]:
    found = []
    for match in _STAMP.finditer(answer):
        a, b, c = match.group(1), match.group(2), match.group(3)
        found.append(int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b))
    return found


def _default_llm(prompt: str) -> str:
    from app.services import llm

    return llm._generate_response(prompt)


def ask(session: Session, title: OttTitle, question: str, *, embedder: Optional[Embedder] = None,
        llm: Optional[Callable[[str], str]] = None) -> dict[str, Any]:
    from app.domains.ott_ai.models import DONE, OttAiOutput

    text = " ".join(str(question or "").split())[:300]
    if len(text) < 3:
        raise AskError(400, "question", "Type a question.")
    row = session.execute(select(OttAiOutput).where(OttAiOutput.title_id == title.id,
                                                    OttAiOutput.kind == "transcript",
                                                    OttAiOutput.status == DONE)).scalars().first()
    cues = [(float(s), float(e), str(t)) for s, e, t in (row.data or {}).get("cues", [])] if row else []
    if not cues:
        return {"answer": DONT_KNOW, "citations": [], "reason": "no transcript yet"}
    parts = windows(cues)
    model = embedder or default_embedder()
    vectors = model.embed([p.text for p in parts])
    scores = vectors @ model.embed([text])[0]
    chosen = sorted((parts[int(i)] for i in np.argsort(-scores)[:TOP_WINDOWS]), key=lambda w: w.start)
    excerpts = "\n".join(f"[{_stamp(w.start)}-{_stamp(w.end)}] {w.text}" for w in chosen)
    prompt = ("Answer the viewer's question using only these excerpts from the video. Cite the start time of the "
              "excerpt you used as [mm:ss]. If the excerpts do not answer it, reply exactly: "
              f"{DONT_KNOW}\nExcerpts:\n{excerpts}\nQuestion: {text}")
    answer = " ".join(str((llm or _default_llm)(prompt) or "").split())[:800]
    cited = _cited_seconds(answer)
    inside = [s for s in cited if any(w.start - 1 <= s <= w.end + 1 for w in chosen)]
    if not answer or DONT_KNOW.lower() in answer.lower() or not cited or len(inside) != len(cited):
        return {"answer": DONT_KNOW, "citations": []}
    citations = [{"start_s": s, "text": next(w.text for w in chosen if w.start - 1 <= s <= w.end + 1)[:200]}
                 for s in dict.fromkeys(inside)]
    return {"answer": answer, "citations": citations}


__all__ = ["AskError", "DONT_KNOW", "ask", "windows"]
