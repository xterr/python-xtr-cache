"""A Redis client kept in a dictionary: the calls the Redis adapter makes, and nothing else."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Self, cast, final

from redis.exceptions import ResponseError
from xtr_clock import Clock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from redis.asyncio import Redis

__all__ = ["FakeRedis"]

_CLOCK = Clock()


def glob_pattern(pattern: str) -> re.Pattern[str]:
    """Translate a Redis ``MATCH`` glob — ``*``, ``?``, ``[...]``, ``\\`` escapes — to a regex."""
    translated: list[str] = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "\\" and index + 1 < len(pattern):
            index += 1
            translated.append(re.escape(pattern[index]))
        elif character == "*":
            translated.append(".*")
        elif character == "?":
            translated.append(".")
        elif character == "[":
            end = pattern.find("]", index + 1)
            translated.append(f"[{re.escape(pattern[index + 1 : end])}]")
            index = end
        else:
            translated.append(re.escape(character))
        index += 1

    return re.compile("".join(translated), re.DOTALL)


@final
class FakeRedis:
    """Holds string keys with an optional expiry, read on the clock in force.

    ``failing`` names keys whose ``SET`` replies with an error, the way a
    server over its memory limit would. ``closed`` tells whether ``aclose``
    was called. ``decode_responses`` is what the client says it was created
    with.
    """

    def __init__(self, *, decode_responses: bool = False) -> None:
        self.data: dict[str, tuple[bytes, float | None]] = {}
        self.failing: set[str] = set()
        self.closed = False
        self.decode_responses = decode_responses

    def as_client(self) -> Redis:
        """Return this fake typed as the client an adapter takes."""
        return cast("Redis", cast("object", self))

    async def mget(self, keys: Sequence[str]) -> list[bytes | None]:
        return [self._live(key) for key in keys]

    async def exists(self, *names: str) -> int:
        return sum(self._live(name) is not None for name in names)

    async def unlink(self, *names: str) -> int:
        return sum(self.data.pop(name, None) is not None for name in names)

    async def scan_iter(
        self, match: str | None = None, count: int | None = None
    ) -> AsyncIterator[bytes]:
        del count
        pattern = glob_pattern(match or "*")
        for key in list(self.data):
            if pattern.fullmatch(key) and self._live(key) is not None:
                yield key.encode()

    def pipeline(self, transaction: bool = True) -> _FakePipeline:
        del transaction
        return _FakePipeline(self)

    async def aclose(self) -> None:
        self.closed = True

    def get_connection_kwargs(self) -> dict[str, object]:
        return {"decode_responses": self.decode_responses}

    def set_now(self, name: str, value: bytes, px: int | None) -> bool | ResponseError:
        if name in self.failing:
            return ResponseError("OOM command not allowed when used memory > 'maxmemory'.")
        expiry = _CLOCK.now().timestamp() + px / 1000 if px is not None else None
        self.data[name] = (value, expiry)
        return True

    def _live(self, key: str) -> bytes | None:
        entry = self.data.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if expiry is not None and expiry <= _CLOCK.now().timestamp():
            del self.data[key]
            return None
        return value


@final
class _FakePipeline:
    """Queues ``SET``s and runs them on ``execute``, replying per command."""

    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._queued: list[tuple[str, bytes, int | None]] = []

    def set(self, name: str, value: bytes, px: int | None = None) -> Self:
        self._queued.append((name, value, px))
        return self

    async def execute(self, raise_on_error: bool = True) -> list[object]:
        replies: list[object] = [self._redis.set_now(*command) for command in self._queued]
        self._queued = []
        if raise_on_error:
            for reply in replies:
                if isinstance(reply, Exception):
                    raise reply
        return replies
