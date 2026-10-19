"""Core cross-cutting concerns for ReelForge (auth, etc.).

Kept dependency-light and import-safe: submodules guard optional third-party
imports (e.g. PyJWT) so importing this package never crashes app startup.
"""
