"""1-body/N-hooks experiments for one-flow create runs.

``hook_styles`` defines the opening-hook angles a generated script can be forced
into (so the N variants of one run are guaranteed to open differently), and
``registration`` turns a multi-variant run into a persisted experiment plus a
remake-winner loop so the insights tick measures it without a manual step.

Kept import-light on purpose: the render worker imports ``hook_styles`` from the
script stage, so nothing here may pull in FastAPI routers or the DB layer at
module import time.
"""
