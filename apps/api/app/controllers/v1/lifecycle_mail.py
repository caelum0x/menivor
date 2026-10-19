"""One-click unsubscribe from Menivor lifecycle mail (MG5, RFC 8058).

* ``POST /mail/unsubscribe?u=<user>&t=<token>`` - the ``List-Unsubscribe-Post``
  target (mail clients send ``List-Unsubscribe=One-Click``). Records the
  opt-out and returns 200.
* ``GET /mail/unsubscribe?u=&t=`` - the visible footer link. Shows one button
  that posts the form, so a link scanner opening the URL never unsubscribes.

Transactional mail (receipts, refunds, sign-in, delete confirmation) is not
affected. The token is an HMAC of the user id (see ``lifecycle_mail``).

Registration (hand-off): add ``lifecycle_mail.router`` to the adapter tuple in
``app/domains/billing/router.py``.
"""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from fastapi import Query, Request
from fastapi.responses import HTMLResponse
from loguru import logger

from app.controllers.v1.base import new_router

router = new_router()

_PAGE = (
    '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    "<title>Menivor email settings</title></head>"
    '<body style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#FAF8F3;'
    'color:#16161A;display:flex;justify-content:center;padding:48px 16px">'
    '<main style="max-width:420px;background:#fff;border:1px solid #ECE6DA;border-radius:16px;padding:32px">'
    "{body}</main></body></html>"
)


def _page(body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(_PAGE.format(body=body), status_code=status)


def _valid(u: str, t: str) -> bool:
    from app.services.billing import lifecycle_mail

    return lifecycle_mail.verify_unsubscribe(u, t)


@router.get("/mail/unsubscribe", summary="Confirm unsubscribing from billing reminders")
def unsubscribe_page(u: str = Query("", max_length=64), t: str = Query("", max_length=64)):
    if not _valid(u, t):
        return _page("<h1>Link not valid</h1><p>Email hello@menivor.com and we will stop these emails.</p>", 400)
    action = f"?u={quote(u, safe='')}&t={escape(t, quote=True)}"
    return _page(
        "<h1 style=\"font-size:20px\">Stop billing reminders?</h1>"
        "<p>You will stop getting payment-failed, low-credit and Autopilot-paused emails. "
        "Receipts and sign-in emails still arrive. The same notices stay in the app.</p>"
        f'<form method="post" action="{action}">'
        '<button type="submit" style="background:#16161A;color:#fff;border:0;border-radius:8px;'
        'padding:10px 16px;font-size:15px">Unsubscribe</button></form>'
    )


@router.post("/mail/unsubscribe", summary="One-click unsubscribe from billing reminders")
async def unsubscribe_post(request: Request, u: str = Query("", max_length=64), t: str = Query("", max_length=64)):
    if not _valid(u, t):
        return _page("<h1>Link not valid</h1><p>Email hello@menivor.com and we will stop these emails.</p>", 400)
    try:
        from app.models.db.base import get_session
        from app.models.db.models import User
        from app.services.billing import lifecycle_mail

        with get_session() as session:
            if session.get(User, u) is not None and not lifecycle_mail.opted_out(session, u):
                lifecycle_mail.unsubscribe(session, u)
    except Exception as exc:  # noqa: BLE001 - tell the user to write in
        logger.error(f"lifecycle unsubscribe failed for {u}: {exc}")
        return _page("<h1>Something went wrong</h1><p>Email hello@menivor.com and we will stop these emails.</p>", 502)
    return _page("<h1 style=\"font-size:20px\">Unsubscribed</h1><p>You will not get billing reminders by email. "
                 "Receipts and sign-in emails still arrive.</p>")


__all__ = ["router"]
