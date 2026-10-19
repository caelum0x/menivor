"""Product principal resolution shared by every API domain."""

from .principal import (
    get_or_create_clerk_user,
    get_or_create_supabase_user,
    resolve_clerk_principal,
    resolve_principal,
    resolve_supabase_principal,
)

__all__ = [
    "get_or_create_clerk_user",
    "get_or_create_supabase_user",
    "resolve_clerk_principal",
    "resolve_principal",
    "resolve_supabase_principal",
]
