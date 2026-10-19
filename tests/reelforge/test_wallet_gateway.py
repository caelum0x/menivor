"""WalletServiceGateway adapter — binds the real WalletService verbs correctly."""

from __future__ import annotations

from app.services.render.execution import WalletGateway
from app.services.render.wallet_gateway import WalletServiceGateway


class SpyService:
    def __init__(self):
        self.calls = []

    def reserve(self, user_id, *, amount_micros, job_id, correlation_id, workspace_id):
        self.calls.append(("reserve", user_id, amount_micros, job_id, workspace_id))

    def settle(self, user_id, *, reserved_micros, actual_micros, job_id, correlation_id, workspace_id):
        self.calls.append(("settle", user_id, reserved_micros, actual_micros, job_id))

    def release(self, user_id, *, reserved_micros, job_id, correlation_id, workspace_id):
        self.calls.append(("release", user_id, reserved_micros, job_id, workspace_id))


def test_adapter_satisfies_wallet_gateway_protocol():
    gw = WalletServiceGateway(SpyService(), user_id="u1")
    assert isinstance(gw, WalletGateway)  # structural check


def test_adapter_binds_principal_and_verbs():
    svc = SpyService()
    gw = WalletServiceGateway(svc, user_id="u1", workspace_id="ws1", correlation_id="c")
    gw.reserve(100_000, job_id="j1")
    gw.settle(100_000, 80_000, job_id="j1")
    gw.release(50_000, job_id="j2")
    assert svc.calls == [
        ("reserve", "u1", 100_000, "j1", "ws1"),
        ("settle", "u1", 100_000, 80_000, "j1"),
        ("release", "u1", 50_000, "j2", "ws1"),
    ]
