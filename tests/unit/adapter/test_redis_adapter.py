"""The Redis adapter, on a fake client kept in memory: no server is reached."""

from __future__ import annotations

import sys

import pytest
from redis.asyncio import Redis

from tests.support.fake_redis import FakeRedis
from tests.support.pool_conformance import PoolTests
from tests.support.recording_logger import RecordingLogger
from xtr_cache import CacheError, InvalidArgumentError, RedisAdapter, SodiumMarshaller

pytestmark = pytest.mark.anyio


class TestRedisAdapter(PoolTests):
    @pytest.fixture
    def pool(self) -> RedisAdapter:
        return RedisAdapter(FakeRedis().as_client(), "pool")


async def test_values_are_stored_under_the_namespace_as_the_marshaller_encoded_them() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(
        redis.as_client(),
        "ns",
        marshaller=SodiumMarshaller([SodiumMarshaller.generate_key()]),
    )

    _ = await pool.save((await pool.get_item("secret")).set("plain text"))

    stored, _ = redis.data["ns:secret"]
    assert b"plain text" not in stored
    assert (await pool.get_item("secret")).get() == "plain text"


async def test_the_lifetime_is_sent_in_milliseconds_and_none_for_no_limit() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(redis.as_client(), default_lifetime=1.5)

    _ = await pool.save((await pool.get_item("timed")).set(1))
    _ = await RedisAdapter(redis.as_client()).save((await pool.get_item("forever")).set(1))

    assert redis.data["timed"][1] is not None
    assert redis.data["forever"][1] is None


async def test_clearing_a_namespace_leaves_every_other_key_alone() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(redis.as_client(), "ns")
    neighbour = RedisAdapter(redis.as_client(), "ns-other")
    _ = await pool.save((await pool.get_item("a")).set(1))
    _ = await neighbour.save((await neighbour.get_item("a")).set(1))

    assert await pool.clear()

    assert not await pool.has_item("a")
    assert await neighbour.has_item("a")


async def test_a_namespace_with_glob_characters_clears_only_itself() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(redis.as_client(), "a[b]c")
    lookalike = RedisAdapter(redis.as_client(), "abc")
    _ = await pool.save((await pool.get_item("k")).set(1))
    _ = await lookalike.save((await lookalike.get_item("k")).set(1))

    assert await pool.clear()

    assert await lookalike.has_item("k")


async def test_clearing_many_keys_unlinks_them_in_batches() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(redis.as_client(), "ns")
    for index in range(1001):
        redis.data[f"ns:{index}"] = (b"x", None)

    assert await pool.clear()

    assert not redis.data


async def test_a_value_written_by_something_else_reads_as_a_miss_and_is_logged() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(redis.as_client(), "ns")
    logger = RecordingLogger()
    pool.set_logger(logger)
    redis.data["ns:foreign"] = (b"not a pickle", None)

    assert not (await pool.get_item("foreign")).is_hit()
    assert logger.messages("warning") == ['Failed to read key "{key}": {reason}']


async def test_a_key_the_server_refuses_is_reported_and_the_rest_saved() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(redis.as_client())
    logger = RecordingLogger()
    pool.set_logger(logger)
    redis.failing.add("b")
    for key in ("a", "b"):
        _ = await pool.save_deferred((await pool.get_item(key)).set(key))

    assert not await pool.commit()

    assert set(redis.data) == {"a"}
    assert 'Failed to save key "{key}": {reason}' in logger.messages("warning")


async def test_a_value_that_does_not_encode_is_not_sent() -> None:
    redis = FakeRedis()
    pool = RedisAdapter(redis.as_client())

    assert not await pool.save((await pool.get_item("a")).set(lambda: None))

    assert not redis.data


async def test_a_dsn_makes_a_client_that_connects_on_first_use() -> None:
    client = RedisAdapter.create_connection("valkey://localhost:6379/2")

    assert isinstance(client, Redis)
    await client.aclose()


def test_a_scheme_that_is_not_redis_is_refused_as_a_cache_error() -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        _ = RedisAdapter.create_connection("mysql://user:secret@host/db")

    assert isinstance(raised.value, CacheError)
    assert raised.value.reason.startswith('"mysql" is not a Redis scheme')


def test_the_redis_extra_missing_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)

    with pytest.raises(InvalidArgumentError, match=r'install "xtr-cache\[redis\]"'):
        _ = RedisAdapter.create_connection("redis://localhost")


def test_a_client_decoding_replies_into_text_is_refused() -> None:
    with pytest.raises(InvalidArgumentError, match="decode_responses=True"):
        _ = RedisAdapter(FakeRedis(decode_responses=True).as_client())


async def test_a_client_given_stays_the_callers() -> None:
    redis = FakeRedis()
    adapter = RedisAdapter(redis.as_client(), "ns")

    await adapter.aclose()

    assert not adapter.owns_connection
    assert not redis.closed
    assert repr(adapter) == f"RedisAdapter({redis!r}, 'ns:', 0.0)"


async def test_a_client_opened_from_a_dsn_is_the_adapters_to_close() -> None:
    adapter = RedisAdapter.from_url("redis://localhost:6379/15", "ns", 5)

    assert adapter.owns_connection
    await adapter.aclose()
