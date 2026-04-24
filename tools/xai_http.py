"""Shared helpers for direct xAI HTTP integrations."""

from __future__ import annotations


def jue_xai_user_agent() -> str:
    """Return a stable Jue-specific User-Agent for xAI HTTP calls."""
    try:
        from hermes_cli import __version__
    except Exception:
        __version__ = "unknown"
    return f"Jue-Agent/{__version__}"
