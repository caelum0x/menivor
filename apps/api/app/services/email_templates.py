"""Branded Menivor transactional email templates.

Dependency-free renderer for every email Menivor sends: table layout, inline
CSS, 600px max width, one primary button, a plain-text alternative, and the
Menivor logo served as a PNG from ``https://menivor.com/email/`` (email clients
do not render SVG and Gmail strips data URIs).

Design: warm paper background, white card, dark ink button, gold only as a
thin accent rule. No emoji. The footer carries the company name and support
address; an unsubscribe link appears only when the caller passes
``unsubscribe_url`` (marketing / newsletter mail).

Usage::

    rendered = sign_in_link_email(url="https://menivor.com/auth/confirm?t=...")
    send(to, rendered.subject, rendered.text, rendered.html)
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from html import escape
from urllib.parse import urlsplit

BRAND_NAME = "Menivor"
SUPPORT_EMAIL = "hello@menivor.com"
LOGO_URL = "https://menivor.com/email/logo%402x.png"
LOGO_SIZE = 40

INK = "#16161A"
BODY = "#4B4B55"
MUTED = "#7A7A85"
PAPER = "#FAF8F3"
CARD = "#FFFFFF"
BORDER = "#ECE6DA"
GOLD = "#F0B843"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


class EmailTemplateError(ValueError):
    """Raised when email content is invalid (for example a non-http(s) URL)."""


@dataclass(frozen=True)
class EmailAction:
    label: str
    url: str


@dataclass(frozen=True)
class EmailContent:
    subject: str
    title: str
    paragraphs: tuple[str, ...] = ()
    preheader: str = ""
    action: EmailAction | None = None
    code: str | None = None
    code_hint: str = "Or enter this code:"
    note: str = ""
    reason: str = ""
    unsubscribe_url: str | None = None


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
    headers: dict[str, str] = field(default_factory=dict)


def _safe_url(url: str) -> str:
    value = (url or "").strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise EmailTemplateError("email links must be absolute http(s) URLs")
    if any(ch.isspace() or ord(ch) < 32 for ch in value):
        raise EmailTemplateError("email links must not contain whitespace")
    return value


def _require(value: str, name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise EmailTemplateError(f"{name} is required")
    return cleaned


def _header() -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="padding:0 12px 0 0;vertical-align:middle">'
        f'<img src="{LOGO_URL}" width="{LOGO_SIZE}" height="{LOGO_SIZE}" alt="{BRAND_NAME}" '
        f'style="display:block;border:0;outline:none;width:{LOGO_SIZE}px;height:{LOGO_SIZE}px;'
        f'border-radius:9px"></td>'
        f'<td style="vertical-align:middle;font-family:{FONT};font-size:20px;font-weight:600;'
        f'letter-spacing:-0.01em;color:{INK}">{BRAND_NAME}</td>'
        "</tr></table>"
    )


def _button(action: EmailAction) -> str:
    href = escape(action.url, quote=True)
    label = escape(action.label)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:28px 0 0 0"><tr>'
        f'<td align="center" bgcolor="{INK}" style="border-radius:10px;background:{INK}">'
        f'<a href="{href}" target="_blank" style="display:inline-block;padding:14px 24px;'
        f'font-family:{FONT};font-size:15px;font-weight:600;line-height:1;color:#FFFFFF;'
        f'text-decoration:none;border-radius:10px">{label}</a></td></tr></table>'
        f'<p style="margin:20px 0 0 0;font-family:{FONT};font-size:12px;line-height:1.6;'
        f'color:{MUTED};word-break:break-all">Or paste this link into your browser:<br>'
        f'<a href="{href}" style="color:{MUTED};text-decoration:underline">{escape(action.url)}</a></p>'
    )


def _code_block(code: str, hint: str) -> str:
    return (
        f'<p style="margin:24px 0 8px 0;font-family:{FONT};font-size:13px;color:{MUTED}">'
        f"{escape(hint)}</p>"
        f'<p style="margin:0;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:26px;'
        f'font-weight:600;letter-spacing:6px;color:{INK}">{escape(code)}</p>'
    )


def _footer(content: EmailContent) -> str:
    lines = [
        f'{BRAND_NAME} &middot; <a href="mailto:{SUPPORT_EMAIL}" '
        f'style="color:{MUTED};text-decoration:underline">{SUPPORT_EMAIL}</a>'
    ]
    if content.reason:
        lines.append(escape(content.reason))
    if content.unsubscribe_url:
        href = escape(content.unsubscribe_url, quote=True)
        lines.append(
            f'<a href="{href}" style="color:{MUTED};text-decoration:underline">Unsubscribe</a>'
        )
    body = "<br>".join(lines)
    return (
        f'<p style="margin:0;font-family:{FONT};font-size:12px;line-height:1.7;color:{MUTED};'
        f'text-align:center">{body}</p>'
    )


def _html(content: EmailContent) -> str:
    paragraphs = "".join(
        f'<p style="margin:0 0 14px 0;font-family:{FONT};font-size:15px;line-height:1.6;'
        f'color:{BODY}">{escape(p)}</p>'
        for p in content.paragraphs
    )
    code = _code_block(content.code, content.code_hint) if content.code else ""
    button = _button(content.action) if content.action else ""
    note = (
        f'<p style="margin:24px 0 0 0;font-family:{FONT};font-size:13px;line-height:1.6;'
        f'color:{MUTED}">{escape(content.note)}</p>'
        if content.note
        else ""
    )
    preheader = escape(content.preheader or content.title)
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta name="supported-color-schemes" content="light">'
        f"<title>{escape(content.subject)}</title></head>"
        f'<body style="margin:0;padding:0;background:{PAPER}" bgcolor="{PAPER}">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{PAPER}">'
        f"{preheader}</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'bgcolor="{PAPER}" style="background:{PAPER}"><tr><td align="center" '
        'style="padding:40px 16px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="max-width:600px">'
        f'<tr><td bgcolor="{CARD}" style="background:{CARD};border:1px solid {BORDER};'
        'border-radius:16px;padding:32px">'
        f"{_header()}"
        f'<div style="margin:32px 0 16px 0;width:24px;height:3px;background:{GOLD};'
        'border-radius:2px;font-size:0;line-height:0">&nbsp;</div>'
        f'<h1 style="margin:0 0 16px 0;font-family:{FONT};font-size:22px;line-height:1.3;'
        f'font-weight:600;color:{INK}">{escape(content.title)}</h1>'
        f"{paragraphs}{button}{code}{note}"
        "</td></tr>"
        f'<tr><td style="padding:24px 16px 0 16px">{_footer(content)}</td></tr>'
        "</table></td></tr></table></body></html>"
    )


def _text(content: EmailContent) -> str:
    parts = [content.title, *content.paragraphs]
    if content.code:
        parts.append(f"{content.code_hint} {content.code}")
    if content.action:
        parts.append(f"{content.action.label}: {content.action.url}")
    if content.note:
        parts.append(content.note)
    footer = [f"{BRAND_NAME} - {SUPPORT_EMAIL}"]
    if content.reason:
        footer.append(content.reason)
    if content.unsubscribe_url:
        footer.append(f"Unsubscribe: {content.unsubscribe_url}")
    parts.append("--\n" + "\n".join(footer))
    return "\n\n".join(parts) + "\n"


def render_email(content: EmailContent) -> RenderedEmail:
    """Render ``content`` to a branded HTML email plus its plain-text alternative."""
    subject = _require(content.subject, "subject")
    if any(ch in subject for ch in "\r\n"):
        raise EmailTemplateError("subject must be a single line")
    _require(content.title, "title")
    if content.action is not None:
        _require(content.action.label, "action label")
        action = EmailAction(label=content.action.label.strip(), url=_safe_url(content.action.url))
        content = replace(content, action=action)
    headers: dict[str, str] = {}
    if content.unsubscribe_url:
        unsubscribe = _safe_url(content.unsubscribe_url)
        headers = {
            "List-Unsubscribe": f"<{unsubscribe}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    return RenderedEmail(subject=subject, html=_html(content), text=_text(content), headers=headers)


# --- Presets ---------------------------------------------------------------


def sign_in_link_email(*, url: str, code: str | None = None, minutes: int = 15) -> RenderedEmail:
    """One-time sign-in link (optionally with a code for another device)."""
    return render_email(
        EmailContent(
            subject="Your Menivor sign-in link",
            preheader=f"Sign in to Menivor. The link expires in {minutes} minutes.",
            title="Sign in to Menivor",
            paragraphs=("Use the button below to sign in. It works once.",),
            action=EmailAction(label="Sign in", url=url),
            code=code,
            code_hint="On another device? Enter this code:",
            note=(
                f"The link expires in {minutes} minutes. If you did not ask for this, "
                "ignore this email; nothing changes."
            ),
            reason="You received this because someone asked to sign in with this address.",
        )
    )


def video_ready_email(*, title: str, url: str, batch_size: int = 1) -> RenderedEmail:
    """A render finished and the video is ready to review.

    ``batch_size`` > 1: the first reel of a run is ready and the rest finish on
    the same results page (one email per run, not per reel).
    """
    name = _require(title, "video title")
    if batch_size > 1:
        others = batch_size - 1
        rest = "The other one is" if others == 1 else f"The other {others} are"
        return render_email(
            EmailContent(
                subject="Your reels are ready",
                preheader=f"{name} finished rendering.",
                title="Your reels are ready",
                paragraphs=(
                    f"{name} finished rendering. {rest} finishing on the same page.",
                    "Pick the one you like best, then download or post it.",
                ),
                action=EmailAction(label="Watch my reels", url=url),
                reason="You received this because reels you created on Menivor finished.",
            )
        )
    return render_email(
        EmailContent(
            subject="Your video is ready",
            preheader=f"{name} finished rendering.",
            title="Your video is ready",
            paragraphs=(f"{name} finished rendering. Watch it, then publish or tweak it.",),
            action=EmailAction(label="Watch video", url=url),
            reason="You received this because a video you created on Menivor finished.",
        )
    )


def reel_stopped_email(*, url: str) -> RenderedEmail:
    """A reel stopped making progress; it was stopped and its credit returned."""
    return render_email(
        EmailContent(
            subject="One of your reels could not be finished",
            preheader="We stopped it and returned your credit.",
            title="We stopped a reel and returned your credit",
            paragraphs=(
                "One of your reels stopped making progress, so we tried it again and then "
                "stopped it. The credit it used is back in your balance.",
                "Open your results to see the reels that finished, or try this one again.",
            ),
            action=EmailAction(label="Open my reels", url=url),
            reason="You received this because a reel you started on Menivor could not be finished.",
        )
    )


def credits_low_email(*, credits_left: int, url: str) -> RenderedEmail:
    """Credit balance is running low."""
    if credits_left < 0:
        raise EmailTemplateError("credits_left must not be negative")
    unit = "credit" if credits_left == 1 else "credits"
    return render_email(
        EmailContent(
            subject="Your Menivor credits are running low",
            preheader=f"{credits_left} {unit} left.",
            title=f"{credits_left} {unit} left",
            paragraphs=(
                "Top up to keep your videos rendering without a pause.",
            ),
            action=EmailAction(label="Add credits", url=url),
            reason="You received this because your Menivor credit balance is low.",
        )
    )
