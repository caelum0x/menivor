"""Pure brief builders: what each weekly Megaphone video says and links to.

No network, no DB: inputs are plain data (Bidstage's weekly tender counts,
the run date), outputs are :class:`Brief` values the pipeline renders. Every
claim in a script comes from the input data or from facts that are true on
the live product (checked 2026-10-08), so nothing here invents numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlencode, urlsplit, urlunsplit

MENIVOR_GALLERY_URL = "https://menivor.com/made-with-menivor"

COUNTRY_NAMES: dict[str, str] = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CA": "Canada", "CH": "Switzerland",
    "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia",
    "ES": "Spain", "FI": "Finland", "FR": "France", "GB": "the United Kingdom", "GR": "Greece",
    "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IS": "Iceland", "IT": "Italy",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta", "NL": "the Netherlands",
    "NO": "Norway", "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SE": "Sweden",
    "SI": "Slovenia", "SK": "Slovakia", "US": "the United States",
}

_SPACES = re.compile(r"\s+")
_UNSAFE_ID = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class Brief:
    """One video to render."""

    id: str
    product: str
    title: str
    description: str
    script: str
    landing_url: str
    page_path: str = "/"
    capture_url: str = ""
    footage_keys: tuple[str, ...] = ()
    footage_builder: str = ""  # "codeclip": render footage locally, upload via the API
    background_id: str = "block-runner"
    language: str = "en"
    dub_to: str = ""
    dub_voice: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


def week_id(day: date) -> str:
    """ISO week label, e.g. ``2026w41``."""
    year, week, _ = day.isocalendar()
    return f"{year}w{week:02d}"


def slug(text: str) -> str:
    return _UNSAFE_ID.sub("-", text.lower()).strip("-")[:60]


def with_utm(url: str, *, campaign: str, content: str) -> str:
    """Append Megaphone UTM tags (keeps any existing query)."""
    parts = urlsplit(url)
    query = urlencode(
        {"utm_source": "menivor", "utm_medium": "video", "utm_campaign": campaign, "utm_content": content}
    )
    joined = f"{parts.query}&{query}" if parts.query else query
    return urlunsplit((parts.scheme, parts.netloc, parts.path, joined, parts.fragment))


def _clean(text: str, limit: int) -> str:
    return _SPACES.sub(" ", str(text or "")).strip()[:limit]


def _short_buyer(name: str) -> str:
    """A buyer name short enough to read aloud (department tails dropped), else ""."""
    text = _clean(name, 200)
    for sep in (" – ", " - ", " (", ","):
        if sep in text:
            text = text.split(sep, 1)[0]
    text = text.strip()
    return text if 3 <= len(text) <= 40 else ""


SHORT_LABEL = 40


def category_name(label: str) -> str:
    """Bidstage's ``categoryName`` rule: long CPV labels are cut at a colon or comma."""
    text = _clean(label, 200).rstrip(".")
    if len(text) <= SHORT_LABEL:
        return text
    head = re.split(r"[:;(]", text)[0].strip()
    if len(head) <= SHORT_LABEL:
        return head
    parts = [p.strip() for p in head.split(",") if p.strip()]
    short = parts[0] if (" " in parts[0] or len(parts) < 2) else f"{parts[0]} and {parts[1]}"
    return short[:SHORT_LABEL].rsplit(" ", 1)[0] if len(short) > SHORT_LABEL else short


def _label(text: str) -> str:
    label = category_name(text)
    return label[:1].lower() + label[1:] if label and not label[:2].isupper() else label


# --------------------------------------------------------------------------- #
# Bidstage: "new tenders in <category> in <country>" every week
# --------------------------------------------------------------------------- #
def bidstage_candidates(
    rows: Iterable[Mapping[str, Any]],
    published_paths: set[str],
    recent_ids: set[str],
    day: date,
) -> list[dict[str, Any]]:
    """Weekly (country, CPV division) rows that have a live page, newest-first by count.

    ``rows`` come from the box query in ``deploy/megaphone/run-weekly.sh``:
    ``{country, div, n, label, buyers}`` for tenders PUBLISHED in the last 7
    days and still open. Only pairs whose ``/tenders/<cc>/cpv-<div>000000``
    page is in Bidstage's sitemap are kept (the page the video links to must
    exist), and pairs used in recent weeks are skipped so the feed rotates.
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        country = str(row.get("country") or "").upper()
        div = str(row.get("div") or "")
        if len(country) != 2 or not re.fullmatch(r"\d{2}", div) or country not in COUNTRY_NAMES:
            continue
        path = f"/tenders/{country.lower()}/cpv-{div}000000"
        pair_id = f"bidstage-{country.lower()}-cpv{div}"
        if path not in published_paths or pair_id in recent_ids:
            continue
        try:
            count = int(row.get("n") or 0)
        except (TypeError, ValueError):
            continue
        label = _label(str(row.get("label") or ""))
        if count < 5 or not label:
            continue
        buyers = [b for b in (_short_buyer(x) for x in (row.get("buyers") or [])) if b]
        out.append({"country": country, "div": div, "n": count, "label": label, "buyers": buyers[:2],
                    "path": path, "pair_id": pair_id})
    out.sort(key=lambda r: (-r["n"], r["pair_id"]))
    return out


def bidstage_brief(candidate: Mapping[str, Any], day: date) -> Brief:
    country = COUNTRY_NAMES[candidate["country"]]
    label = candidate["label"]
    n = int(candidate["n"])
    week = week_id(day)
    buyers = candidate.get("buyers") or []
    buyer_line = ""
    if len(buyers) >= 2:
        buyer_line = f" Buyers this week include {buyers[0]} and {buyers[1]}."
    elif buyers:
        buyer_line = f" Buyers this week include {buyers[0]}."
    script = (
        f"{n} new public tenders for {label} were published in {country} this week."
        f"{buyer_line}"
        " Most suppliers never see them, because they are spread across official portals."
        " Bidstage collects open government tenders from official EU, UK, US and Canadian feeds"
        " and lists them by country and category, with deadlines and buyer names."
        f" See this week's {label} tenders in {country} free at bidstage dot app."
    )
    vid = f"{candidate['pair_id']}-{week}"
    landing = with_utm(f"https://bidstage.app{candidate['path']}", campaign=f"megaphone-{week}", content=vid)
    title = f"{n} new {label} tenders in {country} this week"
    description = (
        f"New public tenders for {label} published in {country} in the week {week}, "
        "from official procurement feeds. Made with Menivor."
    )
    return Brief(
        id=vid, product="bidstage", title=_clean(title, 110), description=_clean(description, 300),
        script=_clean(script, 900), landing_url=landing, page_path=candidate["path"],
        capture_url=f"https://bidstage.app{candidate['path']}", tags=("tenders", candidate["country"].lower()),
    )


# --------------------------------------------------------------------------- #
# Scribase Mail Studio: "switch from Resend in one line"
# --------------------------------------------------------------------------- #
MAIL_SCRIPTS: tuple[tuple[str, str], ...] = (
    (
        "Switch from Resend in one line",
        "Already sending email with the Resend SDK? Keep your code. Set one environment variable,"
        " RESEND base URL, to mail-api dot scribase dot com, and the same SDK sends through Scribase Mail."
        " Domains, webhooks, inbound email, broadcasts and templates work the same way."
        " Scribase Mail Studio is open source, with a free plan. Start at mail dot scribase dot com.",
    ),
    (
        "Keep the Resend SDK, change the base URL",
        "Moving off Resend usually means rewriting your email code. Not here."
        " Scribase Mail speaks the Resend API, so the official Node, Python and Go SDKs work as they are."
        " Point the base URL at mail-api dot scribase dot com and send."
        " Open source, with a free plan. Try it at mail dot scribase dot com.",
    ),
)


def mail_brief(day: date) -> Brief:
    week = week_id(day)
    title, script = MAIL_SCRIPTS[day.isocalendar()[1] % len(MAIL_SCRIPTS)]
    vid = f"mail-{slug(title)}-{week}"
    return Brief(
        id=vid, product="mail", title=title,
        description="Scribase Mail Studio is a Resend-compatible email API: keep the Resend SDK and change one line. Made with Menivor.",
        script=script, landing_url=with_utm("https://scribase.com/mail", campaign=f"megaphone-{week}", content=vid),
        page_path="/mail", footage_builder="codeclip", tags=("email", "resend"),
    )


# --------------------------------------------------------------------------- #
# Oxhan Atelier: brand teaser from existing footage
# --------------------------------------------------------------------------- #
OXHAN_SCRIPTS: tuple[tuple[str, str], ...] = (
    (
        "Oxhan Atelier Drop 01: forty numbered sweatshirts",
        "You met me at a very Turkish time in my life. Oxhan Atelier Drop 01 is forty numbered"
        " sweatshirts across five designs, each with its own serial on the label. When they are gone,"
        " they are gone. Join the waitlist at oxhan atelier dot com.",
    ),
    (
        "Made in a very Turkish time",
        "Kolonya on the console. Tea on the tray. And a piece with its own serial number."
        " Oxhan Atelier Drop 01: five designs, forty pieces in total, numbered one to forty."
        " Get on the list at oxhan atelier dot com.",
    ),
)


def oxhan_brief(day: date, footage_keys: Sequence[str]) -> Brief:
    """Script and footage rotate together: footage[i] was cut for OXHAN_SCRIPTS[i]."""
    week = week_id(day)
    index = day.isocalendar()[1] % len(OXHAN_SCRIPTS)
    title, script = OXHAN_SCRIPTS[index]
    keys = tuple(footage_keys)
    chosen = (keys[index % len(keys)],) if keys else ()
    vid = f"oxhan-{slug(title)}-{week}"
    return Brief(
        id=vid, product="oxhan", title=title,
        description="Oxhan Atelier Drop 01: forty numbered pieces in five designs. Made with Menivor.",
        script=script, landing_url=with_utm("https://oxhanatelier.com/", campaign=f"megaphone-{week}", content=vid),
        page_path="/", footage_keys=chosen, tags=("fashion", "drop01"),
    )


# --------------------------------------------------------------------------- #
# Menivor itself (+ a Spanish dub to show the dub format)
# --------------------------------------------------------------------------- #
MENIVOR_SCRIPTS: tuple[tuple[str, str], ...] = (
    (
        "This video was made with Menivor",
        "This whole video was made with Menivor. It recorded the page, wrote the captions,"
        " voiced the script with a free voice and cut it to nine by sixteen."
        " Paste a link or a topic and get a reel in minutes, then dub it into another language in one click."
        " Make yours at menivor dot com.",
    ),
    (
        "One link in, a reel out",
        "Paste a link to your site, app or product page. Menivor records it, writes the script,"
        " adds a voice and word by word captions, and gives you a vertical reel ready to post."
        " Every product video on this page was made this way. Try it at menivor dot com.",
    ),
)


def menivor_brief(day: date) -> Brief:
    week = week_id(day)
    title, script = MENIVOR_SCRIPTS[day.isocalendar()[1] % len(MENIVOR_SCRIPTS)]
    vid = f"menivor-{slug(title)}-{week}"
    return Brief(
        id=vid, product="menivor", title=title,
        description="A reel made end to end with Menivor: page capture, script, free voice, captions. Made with Menivor.",
        script=script, landing_url=with_utm("https://menivor.com/", campaign=f"megaphone-{week}", content=vid),
        page_path="/", capture_url="https://menivor.com", dub_to="es", dub_voice="es-ES-ElviraNeural",
        tags=("ai-video",),
    )
