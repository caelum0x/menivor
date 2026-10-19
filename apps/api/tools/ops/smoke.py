#!/usr/bin/env python3
"""ReelForge IN-PROCESS smoke test.

Boots the real FastAPI application (``app.asgi:app``) inside this process behind
a Starlette ``TestClient`` and exercises a handful of EXISTING endpoints that do
not require any external service (no live Postgres, Redis or R2). It proves the
app wires up end-to-end: routing, the response envelope, and the auth gate.

Design
------
* Fully hermetic. Before the app is imported we set a self-contained test
  environment (an in-memory SQLite ``NEON_DATABASE_URL`` plus non-empty ``R2_*``
  and ``SOCIAL_TOKEN_KEY`` placeholders) so importing ``app.config`` never fails
  and no real credentials are needed. Callers may still override any of these via
  the real environment; we only fill what is missing (``setdefault``).
* The persistence layer's lazily-built engine is replaced with an in-memory
  SQLite engine (StaticPool) whose schema is created from the ORM metadata —
  exactly the pattern the ``tests/reelforge/*_api.py`` suite uses. This lets the
  DB-backed auth path resolve cleanly to its expected ``401`` (no user) and lets
  a seeded personal key round-trip to a ``200`` envelope.
* Importing this module has NO side effects: all setup happens inside
  :func:`run_checks` / :func:`main`, so the pytest that imports it stays cheap.

What it checks (each check is independent; all run, one summary is printed):

  1. openapi   : the app's OpenAPI schema builds in-process with non-empty
                 ``paths`` and ``/api/v1`` routes (canonical liveness), and
                 anonymous ``GET /openapi.json`` -> 404 (staff-only by default).
  2. docs      : anonymous ``GET /docs`` -> 404 (the docs are staff-only unless
                 ``MENIVOR_API_DOCS=public``; see ``app.core.api_docs``).
  3. envelope  : ``GET /api/v1/catalog/caption-styles`` -> 200 with the standard
                 ``{"status":200,"message":...,"data":[...]}`` envelope and a
                 non-empty list (a public GET that needs neither auth nor DB).
  4. auth      : ``GET /api/v1/me/api-keys`` with NO ``x-api-key`` -> 401 with
                 the ``{"status":401,...}`` envelope (proves the auth gate fires).
  5. authed    : a demo user + personal key is seeded into the in-memory DB, then
                 ``GET /api/v1/me/api-keys`` WITH that key -> 200 envelope whose
                 ``data`` is a list (proves the authenticated path + repositories).

Every check here is REQUIRED — this harness only uses in-process, deterministic
routes, so any failure is a real regression.

Exit code: 0 when every check passes, 1 otherwise.

Usage:
  python ops/smoke.py
  make -f Makefile.dev gate      # runs this among other checks
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# When invoked as ``python ops/smoke.py`` the interpreter puts ``ops/`` (not the
# repo root) on ``sys.path``, so the ``app`` package would be unimportable.
# Prepend the repo root (this file's parent directory) so the app imports the
# same way it does under pytest (which runs from the repo root).
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Raw personal key seeded for the authenticated round-trip check. Not a secret:
# it only ever exists inside this process's in-memory SQLite DB.
_SEED_API_KEY = "reelforge-smoke-inprocess-key"
_SEED_USER_EMAIL = "smoke@reelforge.local"


@dataclass(frozen=True)
class Result:
    """Immutable outcome of a single smoke check."""

    name: str
    ok: bool
    detail: str


def _apply_hermetic_env() -> None:
    """Fill (never overwrite) the minimal env the app needs to import cleanly.

    Uses ``setdefault`` so a caller-provided environment always wins; we only
    supply safe placeholders for the keys ``app.config`` / worker fail-fasts
    require. No real credentials are ever needed to run this smoke test.
    """
    defaults = {
        "NEON_DATABASE_URL": "sqlite:///:memory:",
        "R2_ACCOUNT_ID": "smoke",
        "R2_BUCKET": "smoke",
        "R2_ACCESS_KEY_ID": "smoke",
        "R2_SECRET_ACCESS_KEY": "smoke",
        "SOCIAL_TOKEN_KEY": "smoke-test-token-key",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _install_inmemory_db() -> Any:
    """Point the persistence layer at a fresh in-memory SQLite DB with schema.

    Returns the ``app.models.db.base`` module (with ``engine`` / ``SessionLocal``
    populated) so callers can open sessions to seed fixtures. Mirrors the
    in-memory StaticPool pattern used across ``tests/reelforge/*_api.py`` — the
    real Neon pool arguments are not valid for SQLite, so we build the engine
    ourselves and publish it onto the module singletons.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import app.models.db.base as db_base

    # Importing the models module registers every ORM table on ``Base.metadata``
    # so ``create_all`` below actually creates them (importing ``base`` alone
    # leaves the metadata empty).
    import app.models.db.models  # noqa: F401 - side-effect: register tables

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    db_base.Base.metadata.create_all(engine)
    db_base.engine = engine
    db_base.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    return db_base


def _seed_personal_key(db_base: Any) -> None:
    """Seed one demo user + one live personal API key into the in-memory DB.

    Uses ONLY existing app code — the ``User`` model, the
    ``UserApiKeyRepository`` and the ``hash_api_key`` helper the auth path itself
    uses — so the seeded key resolves through the exact production code path.
    Best-effort: any failure is swallowed (the authed check will then simply
    report the non-200 it observes) so seeding can never crash the harness.
    """
    try:
        from app.controllers.v1.base import hash_api_key
        from app.models.db.models import User
        from app.models.db.repositories import UserApiKeyRepository

        with db_base.SessionLocal() as session:
            user = User(email=_SEED_USER_EMAIL, credits=0)
            session.add(user)
            session.flush()
            UserApiKeyRepository(session).create(
                user_id=user.id,
                name="smoke",
                key_hash=hash_api_key(_SEED_API_KEY),
                prefix=_SEED_API_KEY[:6],
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001 - seeding is best-effort
        print(f"[smoke] WARN: could not seed personal key: {exc}", file=sys.stderr)


def _build_client() -> Any:
    """Boot the hermetic app in-process and return a Starlette ``TestClient``.

    Order matters: env first (so ``app.config`` imports), then swap the DB engine
    (so DB-backed routes work against SQLite), then import the ASGI app, then
    seed the demo key. Server exceptions are surfaced as 5xx responses rather
    than raised so a broken route becomes a FAIL line, not a traceback.
    """
    _apply_hermetic_env()
    db_base = _install_inmemory_db()
    _seed_personal_key(db_base)

    from starlette.testclient import TestClient

    import app.asgi as asgi

    return TestClient(asgi.app, raise_server_exceptions=False)


def _is_envelope(payload: Any, expected_status: int) -> bool:
    """Return whether ``payload`` is the standard ReelForge response envelope."""
    return (
        isinstance(payload, dict)
        and payload.get("status") == expected_status
        and "message" in payload
    )


def _expected_docs_status() -> int:
    from app.core import api_docs

    return 200 if api_docs.docs_mode() == api_docs.PUBLIC else 404


def check_openapi(client: Any) -> Result:
    """The OpenAPI schema is the canonical liveness probe for the ASGI app.

    The schema is built in-process (the HTTP route is staff-only by default);
    the anonymous HTTP answer must match the configured docs mode.
    """
    spec = client.app.openapi()
    paths = spec.get("paths", {})
    has_v1 = any(str(p).startswith("/api/v1") for p in paths)
    status = client.get("/openapi.json").status_code
    expected = _expected_docs_status()
    ok = bool(paths) and has_v1 and status == expected
    return Result(
        "openapi",
        ok,
        f"{len(paths)} paths, /api/v1={'yes' if has_v1 else 'no'}, "
        f"anonymous GET /openapi.json -> {status} (expected {expected})",
    )


def check_docs(client: Any) -> Result:
    """Anonymous /docs answers as the docs mode says (404 unless public)."""
    status = client.get("/docs").status_code
    expected = _expected_docs_status()
    return Result("docs", status == expected, f"anonymous GET /docs -> {status} (expected {expected})")


def check_catalog_envelope(client: Any) -> Result:
    """A public GET returns the standard envelope with a non-empty data list."""
    url = "/api/v1/catalog/caption-styles"
    resp = client.get(url)
    if resp.status_code != 200:
        return Result("envelope", False, f"GET {url} -> {resp.status_code}")
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    ok = _is_envelope(payload, 200) and isinstance(data, list) and len(data) > 0
    n = len(data) if isinstance(data, list) else 0
    return Result("envelope", ok, f"GET {url} -> 200, data list of {n}")


def check_auth_gate(client: Any) -> Result:
    """An owner-scoped route with NO credentials must return the 401 envelope."""
    url = "/api/v1/me/api-keys"
    resp = client.get(url)
    ok = resp.status_code == 401
    payload = resp.json() if resp.headers.get("content-type", "").startswith(
        "application/json"
    ) else {}
    ok = ok and _is_envelope(payload, 401)
    return Result("auth", ok, f"GET {url} (no key) -> {resp.status_code}")


def check_authed_envelope(client: Any) -> Result:
    """The seeded personal key authenticates and returns a 200 envelope list."""
    url = "/api/v1/me/api-keys"
    resp = client.get(url, headers={"x-api-key": _SEED_API_KEY})
    if resp.status_code != 200:
        return Result("authed", False, f"GET {url} (key) -> {resp.status_code}")
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    ok = _is_envelope(payload, 200) and isinstance(data, list)
    n = len(data) if isinstance(data, list) else 0
    return Result("authed", ok, f"GET {url} (key) -> 200, data list of {n}")


def run_checks() -> list[Result]:
    """Boot the app once and run every check; return the results list.

    Importable and side-effect free at module import — all work happens here so
    the test suite can call this directly.
    """
    client = _build_client()
    return [
        check_openapi(client),
        check_docs(client),
        check_catalog_envelope(client),
        check_auth_gate(client),
        check_authed_envelope(client),
    ]


def main() -> int:
    print("== ReelForge in-process smoke test (app.asgi:app via TestClient) ==\n")
    results = run_checks()
    failed = False
    for r in results:
        tag = "PASS" if r.ok else "FAIL"
        print(f"[{tag}] {r.name:<9} — {r.detail}")
        failed = failed or not r.ok
    print()
    if failed:
        print("SMOKE RESULT: FAIL")
        return 1
    print("SMOKE RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
