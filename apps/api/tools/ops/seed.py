#!/usr/bin/env python3
"""ReelForge demo data seeder (idempotent).

Populates a freshly-migrated database with a minimal, self-consistent demo set
so an operator who opens the app is not staring at an empty account:

  * one demo **user** (keyed by a unique email),
  * one demo **workspace** owned by that user (with the owner membership row),
  * one demo **preset** ("brand kit"), shared into the demo workspace.

It uses ONLY existing app code — the SQLAlchemy session factory
(``app.models.db.base.get_session``), the ORM ``User`` model, and the existing
``WorkspaceRepository`` / ``UserPresetRepository``. It adds NO tables,
migrations, services or backend routes, and never modifies any of them.

Idempotency
-----------
Every entity is looked up before it is created and re-running is always safe:

  * the user is matched by ``email`` (``SEED_USER_EMAIL``),
  * the workspace by ``(owner, name)``,
  * the preset by ``(user, name)``.

So the script converges to exactly one of each and prints, per entity, whether
it was *created* or was *existing*.

Prerequisites
-------------
  * ``NEON_DATABASE_URL`` points at your database (docker-compose.full.yml wires
    it to the bundled Postgres).
  * The schema exists (``alembic upgrade head`` — run by the ``migrate`` service
    or ``make -f Makefile.dev migrate``).

Usage:
  python ops/seed.py
  make -f Makefile.dev seed
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Allow ``python ops/seed.py`` from the repo root: put the repo root (not
# ``ops/``) on the path so the ``app`` package imports the same way it does under
# pytest.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

DEMO_EMAIL = os.getenv("SEED_USER_EMAIL", "demo@reelforge.local")
DEMO_DISPLAY_NAME = os.getenv("SEED_USER_DISPLAY_NAME", "ReelForge Demo")
DEMO_CREDITS = int(os.getenv("SEED_USER_CREDITS", "100"))
DEMO_WORKSPACE_NAME = os.getenv("SEED_WORKSPACE_NAME", "Demo Workspace")
DEMO_PRESET_NAME = os.getenv("SEED_PRESET_NAME", "Demo Brand Kit")

# A representative "brand kit" preset config. Plain, JSON-serializable values
# only — no secrets — so it is safe to commit and re-apply.
DEMO_PRESET_CONFIG: dict[str, Any] = {
    "caption_style": "karaoke_yellow",
    "primary_color": "#FDCB2E",
    "font": "Montserrat",
    "aspect_ratio": "9:16",
    "seeded": True,
}


def _fail(msg: str) -> int:
    print(f"[seed] ERROR: {msg}", file=sys.stderr)
    return 1


def _get_or_create_user(session: Any, User: Any, select: Any) -> tuple[Any, bool]:
    """Return the demo user, creating it (idempotently by email) if absent."""
    user = (
        session.execute(select(User).where(User.email == DEMO_EMAIL).limit(1))
        .scalars()
        .first()
    )
    if user is not None:
        return user, False
    user = User(
        email=DEMO_EMAIL,
        display_name=DEMO_DISPLAY_NAME,
        credits=DEMO_CREDITS,
    )
    session.add(user)
    session.flush()  # populate user.id
    return user, True


def _get_or_create_workspace(
    workspaces: Any, user_id: str
) -> tuple[Any, bool]:
    """Return the demo workspace for the user, creating it if absent.

    Idempotent on ``(owner, name)``: reuses an existing workspace of the same
    name the user is already a member of rather than minting a duplicate.
    """
    for ws in workspaces.list_for_user(user_id):
        if ws.name == DEMO_WORKSPACE_NAME:
            return ws, False
    ws = workspaces.create_workspace(name=DEMO_WORKSPACE_NAME, owner_id=user_id)
    return ws, True


def _get_or_create_preset(
    presets: Any, user_id: str, workspace_id: str
) -> tuple[Any, bool]:
    """Return the demo preset for the user, creating it (shared to ws) if absent.

    Idempotent on ``(user, name)``: reuses an existing preset of the same name.
    """
    for preset in presets.list_for_user(user_id):
        if preset.name == DEMO_PRESET_NAME:
            return preset, False
    preset = presets.create(
        user_id=user_id,
        name=DEMO_PRESET_NAME,
        config=DEMO_PRESET_CONFIG,
        workspace_id=workspace_id,
    )
    return preset, True


def main() -> int:
    if not os.getenv("NEON_DATABASE_URL") and not os.getenv("SEED_ALLOW_NO_ENV"):
        return _fail(
            "NEON_DATABASE_URL is not set. Point it at your database (the local "
            "stack sets it in .env.full) before seeding."
        )

    # Guarded imports: keep a clear message if the app package is not importable
    # (e.g. run outside the repo root or without dependencies installed).
    try:
        from sqlalchemy import select

        from app.models.db.base import get_session
        from app.models.db.models import User
        from app.models.db.repositories import (
            UserPresetRepository,
            WorkspaceRepository,
        )
    except Exception as exc:  # pragma: no cover - environment/setup issue
        return _fail(
            f"could not import the app persistence layer ({exc}). Run from the "
            "repo root with dependencies installed (scripts/dev-bootstrap.sh)."
        )

    try:
        with get_session() as session:
            user, created_user = _get_or_create_user(session, User, select)
            workspace, created_ws = _get_or_create_workspace(
                WorkspaceRepository(session), user.id
            )
            preset, created_preset = _get_or_create_preset(
                UserPresetRepository(session), user.id, workspace.id
            )
            # Snapshot ids before the session closes so we can print them.
            user_id, ws_id, preset_id = user.id, workspace.id, preset.id
            # get_session() commits on a clean exit.
    except Exception as exc:  # pragma: no cover - DB connectivity/schema issue
        return _fail(
            f"seeding failed ({exc}). Is the database up and migrated "
            "(`alembic upgrade head`)?"
        )

    def _tag(created: bool) -> str:
        return "created" if created else "existing"

    print("[seed] done.")
    print(f"[seed]   user      : {DEMO_EMAIL} (id={user_id}) [{_tag(created_user)}]")
    print(
        f"[seed]   workspace : {DEMO_WORKSPACE_NAME} (id={ws_id}) "
        f"[{_tag(created_ws)}]"
    )
    print(
        f"[seed]   preset    : {DEMO_PRESET_NAME} (id={preset_id}) "
        f"[{_tag(created_preset)}]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
