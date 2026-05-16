"""Mutable runtime flags — the kill-switch lives here.

Env vars are read-once at startup. Sneha's kill-switch (`OUTBOUND_FETCH_ENABLED`)
needs to flip at runtime without a restart. So we keep a module-level
container that's seeded from settings on first import but can be mutated
at runtime (via the admin endpoint).

Thread-safety: assignment to a Python attribute is atomic for the GIL,
and we only have a handful of writers. No lock needed for booleans.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    """Permissive bool parse: accept '1', 'true', 'yes' (any case)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RuntimeFlags:
    """Singleton container for live-mutable flags."""

    outbound_fetch_enabled: bool = True


_flags = RuntimeFlags(
    outbound_fetch_enabled=_bool_env("OUTBOUND_FETCH_ENABLED", True),
)


def get_flags() -> RuntimeFlags:
    """Return the live flags object. Same instance every call."""
    return _flags
