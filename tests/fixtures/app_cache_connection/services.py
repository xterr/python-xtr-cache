"""The application's own Redis client, which it opens and closes; it never connects in the tests."""

from __future__ import annotations

from collections.abc import AsyncIterator  # noqa: TC003 — the container reads the annotation.

from redis.asyncio import Redis
from xtr_dependency_injection import as_service

CACHE = "cache"


@as_service(qualifier=CACHE)
async def cache_redis() -> AsyncIterator[Redis]:
    # Only the keyword arguments are untyped, and none are passed.
    client = Redis.from_url("redis://localhost:6379/15")  # pyright: ignore[reportUnknownMemberType]
    try:
        yield client
    finally:
        await client.aclose()
