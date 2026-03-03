"""
Simple in-memory cache for the MCP session.

Keyed by a string that encodes the function + arguments.
Values are the already-formatted string responses returned to the LLM.
Cache is process-scoped — it resets when the MCP server restarts.
"""

from typing import Any

_store: dict[str, Any] = {}


def get(key: str) -> Any | None:
    """Return cached value or None if not present."""
    return _store.get(key)


def set(key: str, value: Any) -> None:
    """Store a value under key."""
    _store[key] = value


def clear() -> None:
    """Wipe the entire cache (useful in tests)."""
    _store.clear()


def size() -> int:
    return len(_store)
