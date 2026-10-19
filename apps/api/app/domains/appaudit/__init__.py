"""Free App Store / Play audit (Menivor Growth phase 1).

Given a public App Store or Google Play listing URL, scores the listing's
packaging and estimates its keyword visibility, using only public data: the
iTunes Lookup + Search APIs and the Play listing page already parsed by
:mod:`app.domains.capture.store`. No authentication, no stored user data.

See :mod:`app.domains.appaudit.service` for the orchestration entry point and
:mod:`app.domains.appaudit.router` for the HTTP surface.
"""

from __future__ import annotations

__all__: list[str] = []
