"""Production ``WalletGateway`` adapter over the real ``WalletService``.

The :class:`~app.services.render.execution.RenderExecutor` depends only on the
tiny ``WalletGateway`` protocol (reserve/settle/release). The real
``app.domains.wallet.service.WalletService`` already implements those verbs, but
bound to a ``user_id`` (+ optional ``workspace_id``) and a correlation id. This
adapter binds those so the executor stays pure while production wires the actual
ledger-backed service.
"""

from __future__ import annotations

from typing import Any


class WalletServiceGateway:
    """Binds a ``WalletService`` + principal into the executor's WalletGateway."""

    def __init__(
        self,
        service: Any,
        *,
        user_id: str,
        workspace_id: str | None = None,
        correlation_id: str = "",
    ) -> None:
        self._svc = service
        self._user_id = user_id
        self._workspace_id = workspace_id
        self._corr = correlation_id

    def reserve(self, amount_micros: int, *, job_id: str) -> None:
        self._svc.reserve(
            self._user_id,
            amount_micros=amount_micros,
            job_id=job_id or None,
            correlation_id=self._corr,
            workspace_id=self._workspace_id,
        )

    def settle(self, reserved_micros: int, actual_micros: int, *, job_id: str) -> None:
        self._svc.settle(
            self._user_id,
            reserved_micros=reserved_micros,
            actual_micros=actual_micros,
            job_id=job_id or None,
            correlation_id=self._corr,
            workspace_id=self._workspace_id,
        )

    def release(self, reserved_micros: int, *, job_id: str) -> None:
        self._svc.release(
            self._user_id,
            reserved_micros=reserved_micros,
            job_id=job_id or None,
            correlation_id=self._corr,
            workspace_id=self._workspace_id,
        )
