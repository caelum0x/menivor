"""Shared episode-plan contract (mirror of gtm/oxhan-very-turkish-time/work/vtt/plan.py rules).

Menivor validates every Ad Clone plan against the same structural rules the cost-capped
``make_episode.py`` renderer enforces, so a plan that passes here renders there. Checks that need
the cast file or the asset folder (sheets, voices) stay in the renderer.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

SHOT_KINDS = ("talk", "action", "payoff")
FRAMINGS = ("close", "side", "wide")
AMBIENCES = ("sea", "studio", "airport", "court")
DUR_RULES = {"talk": (4, 7), "action": (4, 7), "payoff": (5, 8)}
CAST_KEYS = ("H", "O")
_ID = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def validate(plan: Mapping[str, Any], *, cta_text: str, cta_speaker: str = "H") -> list[str]:
    p: list[str] = []
    ep = plan.get("episode")
    if not isinstance(ep, int) or isinstance(ep, bool) or not 1 <= ep <= 99:
        p.append("episode must be an integer 1..99")
    if not _SLUG.match(str(plan.get("slug") or "")):
        p.append("slug must be lowercase words joined by '-'")
    t = plan.get("target_seconds", 30)
    if not isinstance(t, (int, float)) or not 25 <= t <= 35:
        p.append("target_seconds must be 25..35")
    if plan.get("ambience", "studio") not in AMBIENCES:
        p.append(f"ambience must be one of {AMBIENCES}")
    speakers = set(CAST_KEYS) | set((plan.get("characters") or {}).keys())
    lines = {}
    for ln in plan.get("lines") or []:
        lid = ln.get("id")
        if not lid or not _ID.match(str(lid)) or lid in lines:
            p.append(f"line {lid!r}: bad or duplicate id")
            continue
        if ln.get("speaker") not in speakers:
            p.append(f"line {lid}: unknown speaker {ln.get('speaker')!r}")
        if not str(ln.get("text") or "").strip():
            p.append(f"line {lid}: empty text")
        if not 0.7 <= float(ln.get("speed", 1.0)) <= 1.4:
            p.append(f"line {lid}: speed must be 0.7..1.4")
        lines[lid] = ln
    if not lines:
        p.append("plan has no lines")
    stills, seen = {}, set()
    for s in plan.get("stills") or []:
        sid = s.get("id")
        if not sid or not _ID.match(str(sid)) or sid in seen:
            p.append(f"still {sid!r}: bad or duplicate id")
            continue
        for r in s.get("refs") or []:
            if not (str(r).startswith("@") or "/" in str(r) or r in seen):
                p.append(f"still {sid}: bad ref {r!r} (stills may only reference earlier stills)")
        if len(s.get("refs") or []) > 14:
            p.append(f"still {sid}: more than 14 refs")
        if not str(s.get("prompt") or "").strip():
            p.append(f"still {sid}: empty prompt")
        seen.add(sid)
        stills[sid] = s
    shots, owner = {}, {}
    for s in plan.get("shots") or []:
        sid, kind = s.get("id"), s.get("kind")
        if not sid or not _ID.match(str(sid)) or sid in shots or sid in stills:
            p.append(f"shot {sid!r}: bad or duplicate id")
            continue
        if kind not in SHOT_KINDS:
            p.append(f"shot {sid}: kind must be one of {SHOT_KINDS}")
            continue
        lo, hi = DUR_RULES[kind]
        d = s.get("dur")
        if not isinstance(d, int) or isinstance(d, bool) or not lo <= d <= hi:
            p.append(f"shot {sid}: dur must be an integer {lo}..{hi}")
        if s.get("framing", "close") not in FRAMINGS:
            p.append(f"shot {sid}: framing must be one of {FRAMINGS}")
        refs = list(s.get("refs") or [])
        if kind != "action":
            if not s.get("lines"):
                p.append(f"shot {sid}: needs lines")
            if not any(r in stills for r in refs):
                p.append(f"shot {sid}: needs at least one still in refs")
            if len(refs) > 9:
                p.append(f"shot {sid}: more than 9 refs")
        for lid in s.get("lines") or []:
            if lid not in lines:
                p.append(f"shot {sid}: unknown line {lid!r}")
            elif lid in owner:
                p.append(f"line {lid}: recorded in two shots")
            else:
                owner[lid] = sid
        shots[sid] = s
    used: list[str] = []
    edit = list(plan.get("edit") or [])
    for i, g in enumerate(edit):
        if "shot" in g:
            sh = shots.get(g["shot"])
            if sh is None:
                p.append(f"edit #{i}: unknown shot {g['shot']!r}")
                continue
            gl = list(g.get("lines") or [])
            rec = list(sh.get("lines") or [])
            idx = [rec.index(x) for x in gl if x in rec]
            if sh["kind"] != "action" and (not gl or len(idx) != len(gl) or idx != list(range(idx[0], idx[0] + len(idx)))):
                p.append(f"edit #{i}: lines must be consecutive and in recorded order within {sh['id']}")
            used.extend(gl)
        elif "still" in g:
            for lid in g.get("lines") or []:
                if lid in owner:
                    p.append(f"line {lid}: recorded in shot {owner[lid]} but voiced over still {g['still']}")
                elif lid not in lines:
                    p.append(f"edit #{i}: unknown line {lid!r}")
            used.extend(g.get("lines") or [])
            if g["still"] not in stills:
                p.append(f"edit #{i}: unknown still {g['still']!r}")
            if float(g.get("len", 0) or 0) <= 0:
                p.append(f"edit #{i}: still segment needs len > 0")
        else:
            p.append(f"edit #{i}: segment needs `shot` or `still`")
    for lid in lines:
        if used.count(lid) != 1:
            p.append(f"line {lid}: used {used.count(lid)} times in the edit (must be exactly once)")
    pay = [s for s in shots.values() if s["kind"] == "payoff"]
    if len(pay) != 1:
        p.append(f"plan needs exactly one payoff shot, found {len(pay)}")
    else:
        if not edit or edit[-1].get("shot") != pay[0]["id"]:
            p.append("the last edit segment must be the payoff shot")
        last = lines.get((pay[0].get("lines") or [None])[-1])
        if not last or _norm(last.get("text", "")) != _norm(cta_text):
            p.append(f"payoff must end on the spoken CTA: {cta_text!r}")
        elif last.get("speaker") != cta_speaker:
            p.append(f"the CTA must be spoken by {cta_speaker}")
    return p
