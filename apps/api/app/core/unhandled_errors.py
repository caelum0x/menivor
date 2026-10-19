"""Turn unhandled exceptions into a JSON 500 INSIDE the CORS middleware.

Starlette's ``ServerErrorMiddleware`` sits outside every user middleware, so a
bare 500 from an unexpected exception (e.g. a ``ResponseValidationError``) goes
out without ``Access-Control-Allow-Origin``. Browsers then report a network
failure (``status 0``: "couldn't reach the server") instead of a server error.
Registered as an http middleware before ``CORSMiddleware`` is added, this
catches those exceptions so the 500 passes back through CORS.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.responses import Response

INTERNAL_ERROR_MESSAGE = "Something went wrong on our side. Please try again."


async def unhandled_error_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001 - last-resort JSON 500 with CORS
        request_id = request.headers.get("x-correlation-id", "")
        logger.exception(
            f"unhandled error on {request.method} {request.url.path}: {type(exc).__name__}"
        )
        return JSONResponse(
            status_code=500,
            content={"status": 500, "message": INTERNAL_ERROR_MESSAGE, "request_id": request_id},
        )


__all__ = ["INTERNAL_ERROR_MESSAGE", "unhandled_error_middleware"]
