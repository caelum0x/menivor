# API domain ownership

`app/router.py` composes product domains only. The modules under
`app/controllers/v1/` are incremental transport adapters until their request
and persistence code is moved into the corresponding domain; their URL and
response envelopes remain compatibility contracts.

| Domain | Current route adapters | Canonical owner direction |
| --- | --- | --- |
| reels, broll, media, editor | extracted routers | product workflows and workers |
| billing | billing, subscriptions, usage, invoices | payment service and ledger |
| publishing | studio, schedule, social, connections, calendar | publish/OAuth services |
| identity | me, sso, scim, security policy | auth and identity services |
| workspaces | workspace, RBAC, audit | workspace services |
| creator/content/community | brand, voices, profiles, catalogs, ideas, marketplace, share | creator-facing services |
| developer/insights/compliance | API keys, webhooks, analytics, compliance, admin | platform services |
| legacy | video, LLM | contained compatibility only; no new product capability |

No client may import a domain's Python code. Web, Expo, Rust/GPUI desktop, and
SDKs communicate only through `/api/v1` and the generated API contract.
