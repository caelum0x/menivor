"""Dub domain: dub any owned video into another language.

The dubbing engine is pyvideotrans (GPL-3.0), run as a separate one-shot
container over its CLI from the worker (``sidecar.py``). Nothing in this
package imports it. The router is mounted via ``from app.domains.dub import
router`` (submodule) so importing the package stays cheap.
"""

from app.domains.dub.catalog import DUB_JOB_KIND, DubOptionError, options_document, resolve_plan

__all__ = ["DUB_JOB_KIND", "DubOptionError", "options_document", "resolve_plan"]
