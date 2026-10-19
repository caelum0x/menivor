#!/usr/bin/env python3
"""Export ReelForge's public FastAPI schema deterministically.

The committed artifact is the review boundary shared by first-party clients and
SDKs. The script deliberately imports the real application/router rather than
reconstructing routes from documentation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
ENGINE_ROOT = API_ROOT / "engine"
OUTPUT_PATH = PACKAGE_ROOT / "openapi" / "reelforge-v1.json"

REQUIRED_PATHS = frozenset(
    {
        "/api/v1/jobs",
        "/api/v1/jobs/{job_id}",
        "/api/v1/jobs/{job_id}/exports",
        "/api/v1/uploads/presign",
        "/api/v1/uploads/register",
        "/api/v1/pilot/capabilities",
        "/api/v1/generation/broll/generate",
        "/api/v1/generation/broll/generations/{generation_id}",
        # Unified media gateway (OpenRouter-style), namespaced under /media.
        "/api/v1/media/models",
        "/api/v1/media/images",
        "/api/v1/media/videos",
        "/api/v1/media/videos/{job_id}",
        "/api/v1/media/audio",
        "/api/v1/media/audio/{job_id}",
        "/api/v1/media/credits",
        "/api/v1/media/usage",
        "/api/v1/media/generation/{job_id}",
        "/api/v1/media/generation/{job_id}/provenance",
        "/api/v1/media/generation/{job_id}/evidence",
        "/api/v1/media/identities",
    }
)
FORBIDDEN_PATH_PREFIXES = ("/generation/api/",)


def _load_schema() -> dict[str, Any]:
    os.environ.setdefault("REELFORGE_BACKEND_ROOT", str(API_ROOT))
    for path in (str(API_ROOT), str(ENGINE_ROOT), str(REPOSITORY_ROOT)):
        if path not in sys.path:
            sys.path.insert(0, path)

    from app.asgi import app

    schema = app.openapi()
    schema["info"] = {
        "title": "ReelForge API",
        "version": "1.0.0",
        "description": "Authoritative public ReelForge /api/v1 contract.",
    }
    schema.pop("servers", None)
    return schema


def _validate_contract(schema: dict[str, Any]) -> None:
    paths = set(schema.get("paths", {}))
    missing = sorted(REQUIRED_PATHS - paths)
    forbidden = sorted(
        path for path in paths if path.startswith(FORBIDDEN_PATH_PREFIXES)
    )
    if missing or forbidden:
        details = []
        if missing:
            details.append(f"missing canonical paths: {', '.join(missing)}")
        if forbidden:
            details.append(f"mis-prefixed paths: {', '.join(forbidden)}")
        raise SystemExit("OpenAPI contract validation failed: " + "; ".join(details))


def _render(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed artifact differs from the API schema",
    )
    args = parser.parse_args()

    schema = _load_schema()
    _validate_contract(schema)
    rendered = _render(schema)

    if args.check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                "OpenAPI artifact is stale; run the api-contract contract:export script"
            )
        print(f"OpenAPI contract is current: {OUTPUT_PATH.relative_to(REPOSITORY_ROOT)}")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH.relative_to(REPOSITORY_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
