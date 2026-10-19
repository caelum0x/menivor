# Generation workflow manifests

Every provider workflow selected by product code needs a manifest with an
immutable source checksum, model/source revision, input/output contract, limits,
owner, and approval state.

`candidate` manifests are inventory only and must set `dispatch_enabled: false`.
An `approved` manifest must contain a non-empty approval date, a completed model
weight license review, a real output node, and a matching workflow checksum.

Provider deployment IDs and secrets stay in environment configuration. Client
requests are restricted to those configured identifiers by
`app.domains.broll.workflows` and can never select arbitrary upstream graphs.
