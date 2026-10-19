"""Every path parameter must bind to its own name in the route template.

A ``Path(...)`` instance shared between handlers keeps the alias of the first
parameter it was bound to, so later routes ask for a parameter their path does
not have and answer 400 for every request (found live on /month/ideas/* and
DELETE /design/templates/{template_id}).
"""

from __future__ import annotations

from app.router import build_full_router


def test_path_params_bind_to_their_own_names():
    broken = []
    for route in build_full_router().routes:
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            continue
        for param in dependant.path_params:
            if param.alias != param.name or "{" + param.alias not in route.path:
                broken.append(f"{sorted(route.methods)} {route.path}: {param.name} -> {param.alias}")
    assert not broken, "\n".join(broken)
