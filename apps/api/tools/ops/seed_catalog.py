#!/usr/bin/env python3
"""ReelForge marketplace catalog seeder (idempotent).

Publishes the curated multi-provider catalog (providers, model listings across
script/voice/avatar/video/image/music, illustrative prices, and generation
profiles) into a freshly-migrated database, and can additionally import
OpenRouter's live model list as SHADOW entries.

Everything is seeded in **shadow mode** (browsable/quotable internally, not a
live billable route) unless a model is explicitly promoted with ``--live``.
Prices are illustrative and MUST be reconciled with finance before any live
charge. Uses ONLY existing app code (the session factory + catalog domain
services); it adds no tables or migrations.

Prerequisites
-------------
  * ``NEON_DATABASE_URL`` points at your database.
  * The schema exists (``alembic upgrade head``).

Usage
-----
  python tools/ops/seed_catalog.py                     # seed curated catalog (shadow)
  python tools/ops/seed_catalog.py --live pixelle/wan-i2v --live heygen/avatar-v3
  python tools/ops/seed_catalog.py --openrouter        # + import OpenRouter models
  python tools/ops/seed_catalog.py --openrouter --openrouter-limit 200
"""

from __future__ import annotations

import argparse
import os
import sys

from loguru import logger


def _seed(args: argparse.Namespace) -> int:
    from app.models.db.base import get_session
    from app.domains.catalog.seed_data import seed_default_catalog

    live = set(args.live or [])
    with get_session() as session:
        counts = seed_default_catalog(session, live_models=live)
    logger.info(
        f"curated catalog seeded: {counts['providers']} providers, "
        f"{counts['models']} models, {counts['profiles']} profiles "
        f"({len(live)} promoted live, unchecked)"
    )

    # CHECKED promotion: refuses to go live unless the model has a reconciled
    # price AND a registered adapter (credentials present). Registers adapters
    # first so the adapter-review gate can see them.
    if args.promote:
        from app.domains.catalog.admin import CatalogAdmin, PromotionError
        from app.domains.routing.providers.registry import register_available_adapters

        register_available_adapters()
        with get_session() as session:
            admin = CatalogAdmin(session)
            for model_id in args.promote:
                try:
                    admin.promote_model_live(model_id)
                    logger.info(f"promoted live (checked): {model_id}")
                except PromotionError as exc:
                    logger.error(f"NOT promoted: {exc}")

    if args.openrouter:
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            logger.warning(
                "--openrouter requested but OPENROUTER_API_KEY is unset; skipping import"
            )
            return 0
        from app.domains.catalog.openrouter_import import import_openrouter_models
        from app.domains.routing.providers.openrouter import OpenRouterAdapter

        adapter = OpenRouterAdapter(api_key=api_key)
        with get_session() as session:
            result = import_openrouter_models(
                session, adapter=adapter, limit=args.openrouter_limit
            )
        logger.info(
            f"OpenRouter import: {result['imported']} models "
            f"({result['priced']} priced) in shadow"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the ReelForge model catalog.")
    parser.add_argument(
        "--live",
        action="append",
        default=[],
        metavar="MODEL_ID",
        help="UNCHECKED: force a model_id live (repeatable). Default: all shadow.",
    )
    parser.add_argument(
        "--promote",
        action="append",
        default=[],
        metavar="MODEL_ID",
        help="CHECKED: promote a model live only if it has a reconciled price + "
        "a registered adapter (repeatable).",
    )
    parser.add_argument(
        "--openrouter",
        action="store_true",
        help="Also import OpenRouter's model list as shadow entries.",
    )
    parser.add_argument(
        "--openrouter-limit",
        type=int,
        default=None,
        help="Cap the number of OpenRouter models imported.",
    )
    args = parser.parse_args(argv)
    try:
        return _seed(args)
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        logger.error(f"catalog seed failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
