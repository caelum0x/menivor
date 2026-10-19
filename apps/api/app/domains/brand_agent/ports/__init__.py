"""Brand Agent ports: one small module per outside capability.

| Module            | Implemented by                           | Runtime lookup (env override)                                                   |
| ----------------- | ---------------------------------------- | ------------------------------------------------------------------------------- |
| ``ad_clone``      | branch ``ad-clone-2026-10-06``           | ``app.domains.adclone.agent_port:PORT`` (``BRAND_AGENT_AD_CLONE_PORT``)         |
| ``integrations``  | branch ``integrations-2026-10-06`` (Max) | ``app.domains.integrations.agent_port:PORT`` (``BRAND_AGENT_INTEGRATIONS_PORT``) |
| ``generation``    | this branch, over the media gateway      | built in                                                                        |
| ``publishing``    | this branch, over scheduled publishing   | built in                                                                        |
| ``search``        | this branch: SearXNG / DuckDuckGo HTML   | ``SEARXNG_URL`` or ``BRAND_AGENT_SEARCH`` (off by default)                       |
| ``llm``           | this branch, over Relay (Claude credits) | used only when Relay is configured                                              |

The other branches add their ``agent_port.py`` module exposing ``PORT``; they
never edit this package. Until then each port's stub raises
:class:`~.base.PortUnavailable` with a plain reason the agent shows the user.
"""
