"""Contract tests for the canonical AI B-roll route aliases.

The aliases intentionally point at the *same endpoint functions* as legacy
routes. This is stronger than testing duplicate response fixtures: it prevents
the new namespace from accidentally acquiring separate auth, ownership, credit,
or queue-dispatch behavior.
"""

from app.router import root_api_router


def _endpoints_by_path() -> dict[str, object]:
    return {
        route.path: route.endpoint
        for route in root_api_router.routes
        if hasattr(route, "endpoint")
    }


def test_canonical_broll_routes_are_true_legacy_aliases():
    endpoints = _endpoints_by_path()
    pairs = (
        ("/api/v1/broll/generate", "/api/v1/generation/broll/generate"),
        ("/api/v1/broll/generations", "/api/v1/generation/broll/generations"),
        ("/api/v1/broll/generations/{generation_id}", "/api/v1/generation/broll/generations/{generation_id}"),
        ("/api/v1/broll/presets", "/api/v1/generation/broll/presets"),
    )
    for legacy, canonical in pairs:
        assert endpoints[canonical] is endpoints[legacy]
