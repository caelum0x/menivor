"""Session-wide pytest setup for tests/reelforge.

Makes the suite hermetic before any test module (or ``app.config``) is
imported. See :mod:`tests.reelforge._session_env` for what is isolated and the
``REELFORGE_TEST_KEEP_ENV`` opt-out for live integration runs.
"""

from tests.reelforge._session_env import apply_hermetic_env

apply_hermetic_env()

import pytest  # noqa: E402 - after the hermetic env is applied


@pytest.fixture(autouse=True)
def _fresh_in_process_rate_limits():
    """Each test starts with empty in-process limiter buckets (Redis-down path)."""
    from app.services import ratelimit

    ratelimit.reset_local_buckets()
    yield
