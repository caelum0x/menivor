"""Small shared HTTP helper for the wave-2 routers: auth + one DB session + domain-error mapping."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.controllers import base
from app.core.api_dependencies import get_session as _default_session
from app.core.api_dependencies import require_database, resolve_principal
from app.models.exception import HttpException
from app.services.ratelimit import enforce_rate_limit

WINDOW_S = 3600


class Call:
    """``with Call(request, errors, "key", get_session) as (session, user_id): ...``

    Domain errors (anything in ``errors`` with ``message`` + ``status_code``) roll the
    session back and become an ``HttpException`` with a safe message.
    """

    def __init__(self, request: Request, errors: tuple[type[Exception], ...], limit_key: str = "",
                 session_factory: Any = None, limit: int = 600) -> None:
        self.request = request
        self.request_id = base.get_task_id(request)
        self.errors = errors
        self.limit_key = limit_key
        self.limit = limit
        self.factory = session_factory or _default_session
        self._cm: Any = None

    def __enter__(self) -> tuple[Any, str]:
        require_database(self.request_id)
        self._cm = self.factory()
        session = self._cm.__enter__()
        try:
            user_id = str(resolve_principal(self.request, session, self.request_id).id)
            if self.limit_key:
                enforce_rate_limit(self.request, f"{self.limit_key}:{user_id}", limit=self.limit, window_s=WINDOW_S)
        except BaseException as exc:
            self._cm.__exit__(type(exc), exc, exc.__traceback__)
            raise
        return session, user_id

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        try:
            handled = self._cm.__exit__(exc_type, exc, tb)
        except self.errors as err:
            raise self.fail(err) from err
        if exc is not None and isinstance(exc, self.errors):
            raise self.fail(exc) from exc
        return bool(handled)

    def fail(self, err: Any) -> HttpException:
        status = int(getattr(err, "status_code", 400) or 400)
        message = getattr(err, "message", "") or str(err)
        return HttpException(task_id=self.request_id, status_code=status, message=f"{self.request_id}: {message}")


__all__ = ["Call"]
