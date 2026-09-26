"""The fake Redis client behaves like the server for the calls the adapter makes."""

from __future__ import annotations

import pytest
from redis.exceptions import ResponseError
from xtr_clock.testing import mock_time

from tests.support.fake_redis import FakeRedis, glob_pattern

pytestmark = pytest.mark.anyio


async def test_set_then_mget_exists_and_unlink() -> None:
    redis = FakeRedis()
    pipeline = redis.pipeline(transaction=False)
    _ = pipeline.set("a", b"1").set("b", b"2")

    assert await pipeline.execute() == [True, True]
    assert await redis.mget(["a", "x", "b"]) == [b"1", None, b"2"]
    assert await redis.exists("a", "x") == 1
    assert await redis.unlink("a", "x") == 1
    assert await redis.mget(["a"]) == [None]


async def test_a_key_set_with_px_expires_on_the_clock_in_force() -> None:
    redis = FakeRedis()

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await redis.pipeline().set("a", b"1", px=1000).execute()
        clock.sleep(0.999)
        assert await redis.exists("a") == 1
        clock.sleep(0.001)
        assert await redis.exists("a") == 0


async def test_a_failing_set_replies_with_an_error_or_raises() -> None:
    redis = FakeRedis()
    redis.failing.add("b")

    replies = await redis.pipeline().set("a", b"1").set("b", b"2").execute(raise_on_error=False)
    assert replies[0] is True
    assert isinstance(replies[1], ResponseError)

    with pytest.raises(ResponseError):
        _ = await redis.pipeline().set("b", b"2").execute()


async def test_scan_matches_a_glob() -> None:
    redis = FakeRedis()
    for key in ("ns:a", "ns:b", "other:a"):
        _ = await redis.pipeline().set(key, b"1").execute()

    assert [key async for key in redis.scan_iter(match="ns:*", count=10)] == [b"ns:a", b"ns:b"]


@pytest.mark.parametrize(
    ("pattern", "key", "matches"),
    [
        ("a*", "abc", True),
        ("a?c", "abc", True),
        ("a[bx]c", "axc", True),
        (r"a\[b\]c*", "a[b]c:k", True),
        (r"a\[b\]c*", "abc:k", False),
        (r"a\*", "ab", False),
    ],
)
def test_globs_translate_as_the_server_reads_them(pattern: str, key: str, matches: bool) -> None:
    assert (glob_pattern(pattern).fullmatch(key) is not None) is matches


def test_it_reports_how_it_was_created() -> None:
    assert FakeRedis().get_connection_kwargs() == {"decode_responses": False}
    assert FakeRedis(decode_responses=True).get_connection_kwargs() == {"decode_responses": True}


async def test_closing_is_recorded() -> None:
    redis = FakeRedis()

    await redis.aclose()

    assert redis.closed
