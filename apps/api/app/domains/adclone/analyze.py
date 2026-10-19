"""Observations of a source ad -> clone brief (pure; no I/O).

The heuristic brief comes from measured signals only (cuts, face size, frame motion, OCR
caption runs, transcript, audio onsets). An optional LLM pass (Relay / Anthropic credits via
``app.services.llm``) may relabel hook pattern, roles, shot types and setting; its answer is
validated against the schema and anything invalid is ignored.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .schemas import Beat, CaptionStyle, CloneBrief, Hook, Pacing, SourceInfo

MIN_BEAT_S = 0.5
BAND_STEP = 0.05
BAND_TOL = 0.1
SAME_CAPTION = 0.6
MERGE_S = 1.0
HOOK_MAX_S = 3.0
_PRICE = re.compile(r"(\$|€|£|₺|\d+\s?%|\b\d+(\.\d+)?\s?(lira|dollars?|euros?|tl)\b|\bprice|\brent\b|\bcost)", re.I)
_DOMAIN = re.compile(r"\b[\w-]+\.(com|co|net|org|shop|store|io)\b", re.I)
_TURN = re.compile(r"\b(maybe|so|that's why|time to|until|but then|now i)\b", re.I)
_PAYOFF = re.compile(r"time in my life|get yours|link in bio|shop now|order now", re.I)
_BOLD = re.compile(r"\b(nobody|never|best|worst|only|stop)\b", re.I)


@dataclass(frozen=True)
class ShotObs:
    start_s: float
    end_s: float
    face_ratio: float | None = None
    scale: float | None = None
    dx_ratio: float | None = None


@dataclass(frozen=True)
class CaptionObs:
    at_s: float
    text: str
    y_center: float = 0.8
    x_center: float = 0.5


@dataclass(frozen=True)
class SpeechObs:
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class Observations:
    url: str
    platform: str
    source_ref: str
    duration_s: float
    width: int
    height: int
    shots: tuple[ShotObs, ...]
    captions: tuple[CaptionObs, ...] = ()
    speech: tuple[SpeechObs, ...] = ()
    onsets_s: tuple[float, ...] = ()
    language: str = "en"
    avoid_terms: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)
    ocr_available: bool = True


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# A burned-in caption sits in the caption zone, stays put while it is on screen, and is replaced
# within seconds. Text printed on clothing moves with the body; logos, prints and watermarks stay
# for most of the video. Those are kept as "all text" (brand detection) but never become captions.
CAPTION_ZONE = (0.06, 0.93)
MOVE_TOL_Y = 0.04
MOVE_TOL_X = 0.06
MAX_CAPTION_S = 8.0
PERSISTENT_SHARE = 0.6
LANE_STEP = 0.05
LANE_MIN_FRAMES = 3
TRACK_JUMP_Y = 0.15


@dataclass(frozen=True)
class TextTrack:
    text: str
    members: tuple[int, ...]  # indexes into the observations
    times: tuple[float, ...]
    ys: tuple[float, ...]
    xs: tuple[float, ...]

    @property
    def y(self) -> float:
        ys = sorted(self.ys)
        return ys[len(ys) // 2]

    def span(self, step_s: float) -> float:
        return round(max(self.times) - min(self.times) + step_s, 3)

    @property
    def moving(self) -> bool:
        return max(self.ys) - min(self.ys) > MOVE_TOL_Y or max(self.xs) - min(self.xs) > MOVE_TOL_X


def text_tracks(captions: tuple[CaptionObs, ...], step_s: float) -> list[TextTrack]:
    """Follow each piece of on-screen text across consecutive samples (same text, nearby position)."""
    open_: list[dict] = []
    done: list[dict] = []
    times = sorted({round(c.at_s, 3) for c in captions})
    for t in times:
        rows = [(i, c) for i, c in enumerate(captions) if round(c.at_s, 3) == t and c.text.strip()]
        still_open, claimed = [], set()
        for i, c in rows:
            match = next((tr for tr in open_ if id(tr) not in claimed and t - tr["times"][-1] <= step_s * 1.5
                          and abs(tr["ys"][-1] - c.y_center) <= TRACK_JUMP_Y and same_caption(tr["text"], c.text)),
                         None)
            if match is None:
                match = {"text": c.text, "members": [], "times": [], "ys": [], "xs": []}
            elif len(c.text) < len(match["text"]):
                match["text"] = c.text  # the shorter reading carries less OCR noise
            claimed.add(id(match))
            for key, value in (("members", i), ("times", t), ("ys", c.y_center), ("xs", c.x_center)):
                match[key].append(value)
            if match not in still_open:
                still_open.append(match)
        done.extend(tr for tr in open_ if tr not in still_open)
        open_ = still_open
    done.extend(open_)
    return [TextTrack(_norm(tr["text"]), tuple(tr["members"]), tuple(tr["times"]), tuple(tr["ys"]), tuple(tr["xs"]))
            for tr in sorted(done, key=lambda tr: (tr["times"][0], tr["ys"][0]))]


def _shape_ok(track: TextTrack, duration_s: float, step_s: float) -> bool:
    """In the caption zone, not moving with a subject, not on screen for most of the video."""
    if not CAPTION_ZONE[0] <= track.y <= CAPTION_ZONE[1] or track.moving:
        return False
    span = track.span(step_s)
    return span <= MAX_CAPTION_S and not (duration_s >= 4 and span >= PERSISTENT_SHARE * duration_s)


def _lane(y: float) -> float:
    return round(round(y / LANE_STEP) * LANE_STEP, 2)


def caption_lanes(tracks: list[TextTrack], duration_s: float, step_s: float) -> dict[float, int]:
    """Lane (y bucket) -> number of sample times with caption-shaped text in it (a subtitle lane)."""
    lanes: dict[float, set[float]] = {}
    for tr in tracks:
        if _shape_ok(tr, duration_s, step_s):
            lanes.setdefault(_lane(tr.y), set()).update(tr.times)
    return {k: len(v) for k, v in lanes.items()}


def is_caption_track(track: TextTrack, duration_s: float, step_s: float,
                     lanes: dict[float, int] | None = None) -> bool:
    """Caption-like: zone + steady + caption timing, and seen on 2+ frames (or in a busy subtitle lane,
    for fast word-by-word captions)."""
    if not _shape_ok(track, duration_s, step_s):
        return False
    if len(track.times) >= 2:
        return True
    lane = _lane(track.y)
    busy = max((lanes or {}).get(k, 0) for k in (lane, round(lane - LANE_STEP, 2), round(lane + LANE_STEP, 2)))
    return busy >= LANE_MIN_FRAMES


def classify_text(captions: tuple[CaptionObs, ...], step_s: float,
                  duration_s: float) -> tuple[set[int], list[TextTrack]]:
    """(indexes of observations that are captions, the non-caption tracks: prints, logos, watermarks)."""
    tracks = text_tracks(captions, step_s)
    lanes = caption_lanes(tracks, duration_s, step_s)
    keep: set[int] = set()
    other: list[TextTrack] = []
    for tr in tracks:
        if is_caption_track(tr, duration_s, step_s, lanes):
            keep.update(tr.members)
        else:
            other.append(tr)
    return keep, other


def band_captions(captions: tuple[CaptionObs, ...], step_s: float = 0.5,
                  duration_s: float | None = None) -> list[tuple[float, str, float, str]]:
    """Per sample time: (t, subtitle-band text, band y, all text on the frame).

    Only caption-like text (:func:`classify_text`) can be the caption, and only inside the dominant
    band (the y bucket holding the most multi-word caption lines). Everything is kept in
    ``all text`` for brand / card detection.
    """
    dur = duration_s if duration_s is not None else max((c.at_s for c in captions), default=0.0) + step_s
    keep, _ = classify_text(captions, step_s, dur)
    buckets: dict[float, int] = {}
    for i, c in enumerate(captions):
        if i in keep and len(c.text.split()) >= 2:
            key = round(round(c.y_center / BAND_STEP) * BAND_STEP, 2)
            buckets[key] = buckets.get(key, 0) + 1
    band = max(buckets.items(), key=lambda kv: (kv[1], kv[0]))[0] if buckets else 0.8
    by_t: dict[float, list[tuple[int, CaptionObs]]] = {}
    for i, c in enumerate(captions):
        by_t.setdefault(round(c.at_s, 3), []).append((i, c))
    out = []
    for t in sorted(by_t):
        rows = sorted(by_t[t], key=lambda ic: ic[1].y_center)
        inside = [c.text for i, c in rows if c.text and i in keep and abs(c.y_center - band) <= BAND_TOL]
        out.append((t, _norm(" ".join(inside)), band, _norm(" ".join(c.text for _, c in rows if c.text))))
    return out


def same_caption(a: str, b: str) -> bool:
    """OCR jitter tolerant: near-identical text, or one reading contained in the other."""
    x, y = re.sub(r"[^a-z0-9 ]", "", a.lower()).strip(), re.sub(r"[^a-z0-9 ]", "", b.lower()).strip()
    if not x or not y:
        return x == y
    if x in y or y in x:
        return True
    return difflib.SequenceMatcher(None, x, y).ratio() >= SAME_CAPTION


def caption_runs(captions: tuple[CaptionObs, ...], step_s: float, duration_s: float) -> list[tuple]:
    """Consecutive samples with the same caption -> (start, end, text, y, all_text). Empty text = none."""
    runs: list[list] = []
    for t, text, y, all_text in band_captions(captions, step_s, duration_s):
        start = max(round(t - step_s / 2, 3), 0.0)
        end = min(round(t + step_s / 2, 3), duration_s)
        if runs and same_caption(runs[-1][2], text):
            runs[-1][1] = end
            if len(text) < len(runs[-1][2]) and text:
                runs[-1][2] = text  # the shorter reading carries less OCR noise
            runs[-1][4] = runs[-1][4] + " " + all_text
        else:
            if runs:
                runs[-1][1] = start
            runs.append([start, end, text, y, all_text])
    return [tuple(r) for r in runs if r[1] > r[0]]


def beat_edges(shots: tuple[ShotObs, ...], runs: list[tuple], duration_s: float) -> list[float]:
    edges = {0.0, round(duration_s, 3)}
    edges.update(round(s.start_s, 3) for s in shots)
    edges.update(round(r[0], 3) for r in runs)
    out: list[float] = []
    for t in sorted(edges):
        if not out or t - out[-1] >= MIN_BEAT_S:
            out.append(t)
        elif t == round(duration_s, 3):
            out[-1] = t
    if out[-1] != round(duration_s, 3):
        out.append(round(duration_s, 3))
    return out


def _at(items, t: float, start=lambda x: x[0], end=lambda x: x[1]):
    return next((x for x in items if start(x) <= t < end(x)), None)


def _speech_in(speech: tuple[SpeechObs, ...], a: float, b: float) -> str:
    """Words of the transcript overlapping [a, b), split proportionally inside long segments."""
    parts = []
    for s in speech:
        lo, hi = max(a, s.start_s), min(b, s.end_s)
        if hi <= lo:
            continue
        words = s.text.split()
        span = max(s.end_s - s.start_s, 1e-6)
        i0 = int(round((lo - s.start_s) / span * len(words)))
        i1 = int(round((hi - s.start_s) / span * len(words)))
        parts.extend(words[i0:max(i1, i0 + 1)] if words else [])
    return " ".join(parts)


def merge_short(raw: list[tuple]) -> list[tuple]:
    """Fold uncaptioned beats shorter than MERGE_S into a neighbour (the next one when it is the same
    shot, else the previous). Rows are (start, end, shot, caption, said, card); returns new rows."""
    rows = list(raw)
    i = 0
    while i < len(rows) and len(rows) > 1:
        a, b, shot, caption, said, card = rows[i]
        if caption or card or b - a >= MERGE_S:
            i += 1
            continue
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if nxt is not None and (nxt[2] is shot or i == 0):
            rows[i + 1] = (a, nxt[1], nxt[2], nxt[3], _norm(f"{said} {nxt[4]}"), nxt[5])
            del rows[i]
        elif i > 0:
            p = rows[i - 1]
            rows[i - 1] = (p[0], b, p[2], p[3], _norm(f"{p[4]} {said}"), p[5])
            del rows[i]
        else:
            i += 1
    return rows


def hook_pattern(text: str) -> str:
    t = text.strip().lower()
    if _PRICE.search(t):
        return "price_shock"
    if t.startswith("pov"):
        return "pov"
    if t.endswith("?"):
        return "question"
    if _BOLD.search(t):
        return "bold_claim"
    if "," in t and len(t.split(",")) >= 3:
        return "list"
    return "statement"


def _framing(shot: ShotObs | None) -> str:
    from .vision import framing_from_face

    return framing_from_face(shot.face_ratio) if shot else "unknown"


def _move(shot: ShotObs | None) -> str:
    from .vision import camera_move_from_transform

    return camera_move_from_transform(shot.scale, shot.dx_ratio) if shot else "unknown"


def _role(i: int, n: int, text: str, card: bool, cta_index: int | None) -> str:
    if card:
        return "cta"
    if i == 0:
        return "hook"
    if _PAYOFF.search(text):
        return "payoff"
    last_story = (cta_index if cta_index is not None else n) - 1
    if i == last_story:
        return "payoff"
    if _TURN.search(text):
        return "turn"
    return "setup" if i <= max(1, last_story // 3) else "escalation"


def _caption_style(runs: list[tuple], ocr_available: bool) -> CaptionStyle:
    texts = [r[2] for r in runs if not _DOMAIN.search(r[2])]
    if not texts:
        return CaptionStyle(present=False, burned_in=False)
    ys = [r[3] for r in runs]
    y = sum(ys) / len(ys)
    joined = "".join(texts)
    letters = [c for c in joined if c.isalpha()]
    lower = sum(c.islower() for c in letters) / max(len(letters), 1)
    case = "lower" if lower > 0.97 else "upper" if lower < 0.05 else "sentence" if \
        sum(t[:1].isupper() for t in texts) / len(texts) > 0.8 else "mixed"
    return CaptionStyle(present=True, position="top" if y < 0.33 else "middle" if y < 0.6 else "bottom", case=case,
                        words_per_caption=round(sum(len(t.split()) for t in texts) / len(texts), 1),
                        burned_in=ocr_available)


def source_brand_terms(obs: Observations, step_s: float = 0.5) -> list[str]:
    """Names our script may never use: the given ones plus brands found in the handle, OCR and speech."""
    from .brandterms import extract

    _, other = classify_text(obs.captions, step_s, obs.duration_s)
    found = extract(url=obs.url, ocr_texts=[c.text for c in obs.captions if c.text],
                    overlay_texts=[tr.text for tr in other], transcript=" ".join(s.text for s in obs.speech),
                    extra=obs.avoid_terms)
    return sorted({t for t in (*obs.avoid_terms, *found) if t})[:200]


def heuristic_brief(obs: Observations, *, caption_step_s: float = 0.5) -> CloneBrief:
    from .media import bpm_from_onsets

    runs = caption_runs(obs.captions, caption_step_s, obs.duration_s)
    edges = beat_edges(obs.shots, runs, obs.duration_s)
    raw = []
    for a, b in zip(edges, edges[1:]):
        mid = (a + b) / 2
        shot = _at(obs.shots, mid, lambda s: s.start_s, lambda s: s.end_s)
        run = _at(runs, mid)
        caption = run[2] if run else ""
        said = _speech_in(obs.speech, a, b)
        card = bool(run and _DOMAIN.search(run[4]))
        raw.append((a, b, shot, caption, said, card))
    raw = merge_short(raw)
    cta_index = next((i for i, r in enumerate(raw) if r[5]), None)
    beats = []
    for i, (a, b, shot, caption, said, card) in enumerate(raw):
        framing = _framing(shot)
        text = caption or said
        stype = "product_card" if card else ("establishing" if i == 0 and framing == "wide" and not text else
                                             "talking" if (said or caption) and framing in ("close", "medium") else
                                             "insert" if not text else "talking")
        beats.append(Beat(index=i, start_s=a, end_s=b, shot_type=stype, framing=framing, camera_move=_move(shot),
                          speaker="narrator" if said else "none", line=_norm(said)[:300],
                          on_screen_text=caption[:300], role=_role(i, len(raw), text, card, cta_index)))
    hook_text = beats[0].on_screen_text or beats[0].line
    hook_end = min(max(beats[0].end_s, 1.0), HOOK_MAX_S)
    shots_n = max(len(obs.shots), 1)
    pacing = Pacing(shot_count=shots_n, avg_shot_s=round(obs.duration_s / shots_n, 2),
                    cuts_per_10s=round((shots_n - 1) / obs.duration_s * 10, 2), beat_count=len(beats),
                    avg_beat_s=round(obs.duration_s / len(beats), 2), music_bpm=bpm_from_onsets(list(obs.onsets_s)),
                    onsets_s=[round(t, 2) for t in obs.onsets_s[:200]])
    hook = Hook(end_s=round(hook_end, 2), pattern=hook_pattern(hook_text),
                summary=f"{beats[0].framing} shot, caption '{hook_text[:80]}'" if hook_text else
                f"{beats[0].framing} shot, no caption", framing=beats[0].framing)
    return CloneBrief(
        source=SourceInfo(url=obs.url, platform=obs.platform, source_ref=obs.source_ref, duration_s=obs.duration_s,
                          width=obs.width, height=obs.height, language=obs.language,
                          avoid_terms=source_brand_terms(obs, caption_step_s)),
        hook=hook, beats=beats, pacing=pacing, caption_style=_caption_style(runs, obs.ocr_available),
        transcript=" ".join(s.text for s in obs.speech)[:4000], notes=list(obs.notes))


# --------------------------------------------------------------------------- #
# Optional LLM refinement
# --------------------------------------------------------------------------- #
LLM_FIELDS = ("hook_pattern", "hook_summary", "setting", "beats")


def llm_prompt(brief: CloneBrief) -> str:
    rows = [{"i": b.index, "t": [b.start_s, b.end_s], "framing": b.framing, "move": b.camera_move,
             "caption": b.on_screen_text, "said": b.line, "type": b.shot_type, "role": b.role} for b in brief.beats]
    return ("You analyse the STRUCTURE of a short vertical ad so it can be re-made with a different product and "
            "different, original characters. Do not describe the people's appearance, names or brands.\n"
            f"Beats (measured): {json.dumps(rows)}\nTranscript: {brief.transcript[:1500]!r}\n"
            "Reply with JSON only: {\"hook_pattern\": one of price_shock|question|pov|bold_claim|list|statement, "
            "\"hook_summary\": <=20 words about the hook device, \"setting\": <=12 words generic location class "
            "(e.g. 'apartment balcony, daytime'), \"beats\": [{\"i\": int, \"role\": hook|setup|escalation|turn|"
            "payoff|cta, \"type\": talking|reaction|insert|establishing|product_card|text_card}]}")


def refine_with_llm(brief: CloneBrief, llm: Callable[[str], str]) -> CloneBrief:
    try:
        text = llm(llm_prompt(brief))
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as exc:  # noqa: BLE001 - LLM is optional; keep the measured brief
        return brief.model_copy(update={"notes": [*brief.notes, f"llm refinement skipped: {type(exc).__name__}"]})
    beats = list(brief.beats)
    for row in data.get("beats") or []:
        i = row.get("i")
        if isinstance(i, int) and 0 <= i < len(beats):
            upd = {}
            if row.get("role") in ("hook", "setup", "escalation", "turn", "payoff", "cta"):
                upd["role"] = row["role"]
            if row.get("type") in ("talking", "reaction", "insert", "establishing", "product_card", "text_card"):
                upd["shot_type"] = row["type"]
            beats[i] = beats[i].model_copy(update=upd)
    hook = brief.hook
    if data.get("hook_pattern") in ("price_shock", "question", "pov", "bold_claim", "list", "statement"):
        hook = hook.model_copy(update={"pattern": data["hook_pattern"]})
    if isinstance(data.get("hook_summary"), str):
        hook = hook.model_copy(update={"summary": data["hook_summary"][:300]})
    setting = data.get("setting") if isinstance(data.get("setting"), str) else brief.setting
    return CloneBrief.model_validate({**brief.model_dump(), "beats": [b.model_dump() for b in beats],
                                      "hook": hook.model_dump(), "setting": setting[:200], "analysis": "llm"})
