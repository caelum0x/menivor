"""Coverage for the in-process run harness (``ops/smoke.py``).

The smoke harness boots the real ``app.asgi:app`` behind a Starlette
``TestClient`` and exercises a handful of existing endpoints. This test makes the
harness itself part of the suite so a regression that breaks the operator's
one-command smoke check is caught by CI, not just at run time.

It is fully hermetic: ``ops.smoke`` fills a self-contained test environment
(in-memory SQLite + placeholder ``R2_*`` / ``SOCIAL_TOKEN_KEY``) via
``setdefault``, so these tests need no external services. We still set the same
values defensively so the test is order-independent within the suite.
"""

from __future__ import annotations

import os

import pytest

# Ensure the hermetic env exists before ``ops.smoke`` imports the app (harmless
# if the harness or a sibling test already set them — ``setdefault`` semantics).
for _key, _value in {
    "NEON_DATABASE_URL": "sqlite:///:memory:",
    "R2_ACCOUNT_ID": "test",
    "R2_BUCKET": "test",
    "R2_ACCESS_KEY_ID": "test",
    "R2_SECRET_ACCESS_KEY": "test",
    "SOCIAL_TOKEN_KEY": "test",
}.items():
    os.environ.setdefault(_key, _value)

from apps.api.tools.ops import smoke  # noqa: E402 - imported after env is prepared


@pytest.fixture(scope="module")
def results() -> list[smoke.Result]:
    """Run the smoke checks once and share the results across assertions."""
    return smoke.run_checks()


def test_all_checks_pass(results: list[smoke.Result]) -> None:
    """Every in-process smoke check must pass under the hermetic test env."""
    failed = [r for r in results if not r.ok]
    assert not failed, "failed smoke checks: " + ", ".join(
        f"{r.name} ({r.detail})" for r in failed
    )


def test_expected_checks_present(results: list[smoke.Result]) -> None:
    """The harness must run the full, named set of checks (no silent drops)."""
    names = {r.name for r in results}
    assert names == {"openapi", "docs", "envelope", "auth", "authed"}


def test_auth_gate_is_exercised(results: list[smoke.Result]) -> None:
    """The 401 auth-gate check specifically must be present and passing.

    This is the load-bearing proof that the auth wiring fires, so pin it
    explicitly rather than relying only on the aggregate pass.
    """
    by_name = {r.name: r for r in results}
    assert by_name["auth"].ok
    assert by_name["authed"].ok


def test_main_returns_zero() -> None:
    """``ops.smoke.main`` returns exit code 0 when every check passes."""
    assert smoke.main() == 0
