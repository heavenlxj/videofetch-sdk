"""Async entrypoint mirror (import-friendly for asyncio users).

    from videofetch.asyncio import AsyncVideoFetch
"""
from .client import AsyncVideoFetch  # noqa: F401

__all__ = ["AsyncVideoFetch"]
