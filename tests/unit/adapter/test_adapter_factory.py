from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from tests.support.fake_redis import FakeRedis
from xtr_cache import (
    AdapterFactory,
    ArrayAdapter,
    DefaultMarshaller,
    FilesystemAdapter,
    InvalidArgumentError,
    NullAdapter,
    RedisAdapter,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio


def test_array_and_null_are_keywords() -> None:
    assert isinstance(AdapterFactory.create_adapter("array", "ns", 5), ArrayAdapter)
    assert isinstance(AdapterFactory.create_adapter("null"), NullAdapter)


def test_filesystem_uses_the_directory_given_or_the_one_in_the_dsn(tmp_path: Path) -> None:
    given = AdapterFactory.create_adapter("filesystem", "ns", directory=tmp_path)
    named = AdapterFactory.create_adapter(
        f"filesystem://{tmp_path}/named", "ns", directory=tmp_path
    )

    assert isinstance(given, FilesystemAdapter)
    assert given.directory == tmp_path / "ns"
    assert isinstance(named, FilesystemAdapter)
    assert named.directory == tmp_path / "named" / "ns"


async def test_a_redis_dsn_makes_an_adapter_owning_its_connection() -> None:
    marshaller = DefaultMarshaller()

    adapter = AdapterFactory.create_adapter(
        "valkey://localhost:6379/15", "ns", marshaller=marshaller
    )

    assert isinstance(adapter, RedisAdapter)
    assert adapter.owns_connection
    assert adapter.namespace == "ns:"
    await adapter.aclose()


async def test_a_redis_client_makes_an_adapter_on_that_client() -> None:
    client = RedisAdapter.create_connection("redis://localhost")

    adapter = AdapterFactory.create_adapter(client, "ns")

    assert isinstance(adapter, RedisAdapter)
    assert not adapter.owns_connection
    await client.aclose()


def test_anything_else_is_refused_naming_its_scheme_or_type_only() -> None:
    with pytest.raises(InvalidArgumentError) as dsn:
        _ = AdapterFactory.create_adapter("memcached://user:secret@host")
    with pytest.raises(InvalidArgumentError) as keyword:
        _ = AdapterFactory.create_adapter("apcu")
    with pytest.raises(InvalidArgumentError) as client:
        _ = AdapterFactory.create_adapter(FakeRedis())

    assert dsn.value.reason == 'Unsupported cache connection: "memcached:".'
    assert keyword.value.reason == 'Unsupported cache connection: "apcu".'
    assert client.value.reason == 'Unsupported cache connection: "FakeRedis".'


def test_a_redis_dsn_validates_with_the_redis_extra_installed() -> None:
    AdapterFactory.validate("redis://localhost")


@pytest.mark.usefixtures("nothing_installed")
def test_validating_a_redis_dsn_needs_the_redis_extra() -> None:
    with pytest.raises(InvalidArgumentError, match=r'install "xtr-cache\[redis\]"'):
        AdapterFactory.validate("redis://localhost")


def test_a_client_is_not_recognised_before_the_client_library_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "redis.asyncio")

    with pytest.raises(InvalidArgumentError):
        _ = AdapterFactory.create_adapter(object())
