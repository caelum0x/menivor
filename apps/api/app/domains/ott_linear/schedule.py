"""FAST schedules (MV15): a loop of a channel's free titles with ad breaks, anchored in time.

Pure logic. A linear channel plays its titles in order, forever, starting at
``anchor``; every ``ad_every`` programs an ad break of ``AD_BREAK_S`` seconds
is inserted (filled from MV14 at play time). Any instant maps to exactly one
item and an offset into it, so the program guide (XMLTV) and the playout
engine agree, and a whole day plays with no gap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

AD_BREAK_S = 30.0
PROGRAM, AD = "program", "ad"


@dataclass(frozen=True)
class Item:
    kind: str
    duration_s: float
    title_id: Optional[str] = None
    name: str = ""
    synopsis: str = ""


@dataclass(frozen=True)
class Slot:
    index: int
    item: Item
    start: datetime
    stop: datetime


def build_cycle(programs: Iterable[Item], ad_every: int = 0, ad_break_s: float = AD_BREAK_S) -> list[Item]:
    cycle: list[Item] = []
    for n, program in enumerate(programs, start=1):
        if program.duration_s <= 0:
            continue
        cycle.append(program)
        if ad_every and n % ad_every == 0:
            cycle.append(Item(kind=AD, duration_s=ad_break_s, name="Ad break"))
    return cycle


def cycle_length(cycle: list[Item]) -> float:
    return sum(item.duration_s for item in cycle)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def at(cycle: list[Item], anchor: datetime, moment: datetime) -> tuple[int, Item, float]:
    """(global item index since the anchor, the item, seconds into it) at ``moment``."""
    if not cycle:
        raise ValueError("an empty schedule plays nothing")
    total = cycle_length(cycle)
    elapsed = max(0.0, (_aware(moment) - _aware(anchor)).total_seconds())
    loops, into = divmod(elapsed, total)
    for position, item in enumerate(cycle):
        if into < item.duration_s:
            return int(loops) * len(cycle) + position, item, into
        into -= item.duration_s
    return (int(loops) + 1) * len(cycle), cycle[0], 0.0


def item(cycle: list[Item], index: int) -> Item:
    return cycle[index % len(cycle)]


def slots(cycle: list[Item], anchor: datetime, start: datetime, hours: float) -> list[Slot]:
    """Every item that overlaps ``[start, start + hours)``, with its exact start and stop."""
    index, current, into = at(cycle, anchor, start)
    begin = _aware(start) - timedelta(seconds=into)
    end = _aware(start) + timedelta(hours=hours)
    out: list[Slot] = []
    while begin < end:
        stop = begin + timedelta(seconds=current.duration_s)
        out.append(Slot(index=index, item=current, start=begin, stop=stop))
        index += 1
        current = item(cycle, index)
        begin = stop
    return out


def _xmltv_time(moment: datetime) -> str:
    return _aware(moment).astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def xmltv(channel_id: str, channel_name: str, guide: list[Slot], *, source: str = "Menivor") -> bytes:
    """An XMLTV guide: one ``channel`` and a ``programme`` per program (ad breaks fold into the next start)."""
    root = ET.Element("tv", {"generator-info-name": source})
    channel = ET.SubElement(root, "channel", id=channel_id)
    ET.SubElement(channel, "display-name").text = channel_name
    programs = [s for s in guide if s.item.kind == PROGRAM]
    for slot in programs:
        node = ET.SubElement(root, "programme", start=_xmltv_time(slot.start), stop=_xmltv_time(slot.stop),
                             channel=channel_id)
        ET.SubElement(node, "title", lang="en").text = slot.item.name or "Program"
        if slot.item.synopsis:
            ET.SubElement(node, "desc", lang="en").text = slot.item.synopsis
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


__all__ = ["AD", "AD_BREAK_S", "Item", "PROGRAM", "Slot", "at", "build_cycle", "cycle_length", "item", "slots",
           "xmltv"]
