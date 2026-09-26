"""Unit tests for :class:`xtr_cache.bundle.CacheBundle`; no test reaches a server."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from redis.asyncio import Redis
from xtr_console import Application, ApplicationTester, ExitCode
from xtr_dependency_injection import Kernel, ServicesResetter
from xtr_dependency_injection.exception import ServiceResolutionError
from xtr_dependency_injection.testing import assert_zero_config
from xtr_logging_contracts import LoggerInterface

from tests.fixtures.app_cache_connection.services import CACHE
from xtr_cache import (
    AdapterInterface,
    ArrayAdapter,
    CacheInterface,
    CacheItemPoolInterface,
    ChainAdapter,
    FilesystemAdapter,
    InvalidArgumentError,
    LockRegistry,
    NamespacedPoolInterface,
    RedisAdapter,
    SodiumMarshaller,
    TagAwareAdapter,
    TagAwareAdapterInterface,
    TagAwareCacheInterface,
)
from xtr_cache.bundle import CACHE_CHANNEL, CacheBundle

if TYPE_CHECKING:
    from xtr_dependency_injection import BootedKernel

pytestmark = pytest.mark.anyio

APP = "tests.fixtures.app_cache"


def _kernel(tmp_path: Path, app: str = APP, **environ: str) -> Kernel:
    return Kernel(
        app,
        env="test",
        environ={"CACHE_TEST_DSN": "array", "CACHE_TEST_DIR": str(tmp_path), **environ},
    )


async def _pool(booted: BootedKernel, name: str) -> AdapterInterface:
    return await booted.container.get(AdapterInterface, name)


async def test_zero_config_builds_boots_and_shuts_down() -> None:
    await assert_zero_config(CacheBundle)


async def test_the_app_pool_is_provided_under_every_interface_with_and_without_a_qualifier(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        pool = await _pool(booted, "app")
        for interface in (
            AdapterInterface,
            CacheInterface,
            CacheItemPoolInterface,
            NamespacedPoolInterface,
        ):
            assert await booted.container.get(interface) is pool
            assert await booted.container.get(interface, "app") is pool

    assert isinstance(pool, ArrayAdapter)


async def test_each_pool_gets_the_adapter_it_names(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        files = await _pool(booted, "files")
        chained = await _pool(booted, "chained")
        tagged = await _pool(booted, "tagged")
        from_env = await _pool(booted, "from_env")
        redis = await _pool(booted, "redis")
        inherits = await _pool(booted, "inherits")

        assert isinstance(files, FilesystemAdapter)
        assert files.directory.parent == tmp_path
        assert isinstance(chained, ChainAdapter)
        assert [type(adapter) for adapter in chained.adapters] == [ArrayAdapter, FilesystemAdapter]
        assert isinstance(tagged, TagAwareAdapter)
        assert isinstance(from_env, ArrayAdapter)
        assert isinstance(redis, RedisAdapter)
        assert redis.owns_connection
        assert isinstance(inherits, ArrayAdapter)
        assert inherits.default_lifetime == 5


async def test_only_a_pool_with_tags_is_provided_as_tag_aware(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        tagged = await _pool(booted, "tagged")
        container = booted.container

        assert await container.get(TagAwareCacheInterface, "tagged") is tagged
        assert await container.get(TagAwareAdapterInterface, "tagged") is tagged
        assert not container.has(TagAwareCacheInterface, "files")
        assert not container.has(TagAwareCacheInterface)


async def test_every_pool_has_a_namespace_of_its_own_unless_one_is_set(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        files = await _pool(booted, "files")
        other = await _pool(booted, "other_files")
        shared = await _pool(booted, "shared")
        assert isinstance(files, FilesystemAdapter)
        assert isinstance(other, FilesystemAdapter)
        assert isinstance(shared, FilesystemAdapter)

        _ = await files.save((await files.get_item("k")).set("files"))

        assert not await other.has_item("k")
        assert files.namespace != other.namespace
        assert shared.namespace == "shared:"


async def test_namespaces_come_from_the_pool_name_and_the_seed(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as first, await _kernel(tmp_path).boot() as second:
        one = await _pool(first, "files")
        two = await _pool(second, "files")
        assert isinstance(one, FilesystemAdapter)
        assert isinstance(two, FilesystemAdapter)

        _ = await one.save((await one.get_item("k")).set("shared seed"))

        assert (await two.get_item("k")).get() == "shared seed"


async def test_pools_compute_under_the_lock_registry_and_log_to_the_cache_channel(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        pool = await _pool(booted, "app")
        registry = await booted.container.get(LockRegistry)
        channel = await booted.container.get(LoggerInterface, CACHE_CHANNEL)

        assert isinstance(pool, ArrayAdapter)
        assert pool._lock_registry is registry
        assert pool.logger is channel
        assert registry.logger is channel


async def test_deferred_items_are_committed_between_messages_and_at_shutdown(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        files = await _pool(booted, "files")
        assert isinstance(files, FilesystemAdapter)
        _ = await files.save_deferred((await files.get_item("reset")).set(1))
        await (await booted.container.get(ServicesResetter)).reset()
        _ = await files.save_deferred((await files.get_item("shutdown")).set(1))

        assert (
            await FilesystemAdapter(files.namespace.rstrip(":"), directory=tmp_path).get_item(
                "reset"
            )
        ).is_hit()

    reader = FilesystemAdapter(files.namespace.rstrip(":"), directory=tmp_path)
    assert await reader.has_item("shutdown")


async def test_a_redis_connection_opened_from_a_dsn_is_closed_with_the_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[RedisAdapter] = []

    async def record(adapter: RedisAdapter) -> None:
        closed.append(adapter)

    monkeypatch.setattr(RedisAdapter, "aclose", record)

    async with await _kernel(tmp_path).boot() as booted:
        redis = await _pool(booted, "redis")

    assert closed == [redis]


async def test_the_cache_commands_act_on_the_pools(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        pool = await _pool(booted, "app")
        _ = await pool.save((await pool.get_item("k")).set(1))
        tester = ApplicationTester(await booted.container.get(Application))

        assert await tester.execute(["cache:pool:list"]) == ExitCode.SUCCESS
        assert "chained" in tester.display
        assert await tester.execute(["cache:pool:clear", "app"]) == ExitCode.SUCCESS
        assert not await pool.has_item("k")


async def test_an_application_marshaller_replaces_pickle(tmp_path: Path) -> None:
    key = SodiumMarshaller.generate_key()
    kernel = _kernel(tmp_path, "tests.fixtures.app_cache_sodium", CACHE_DECRYPTION_KEY=key)

    async with await kernel.boot() as booted:
        pool = await _pool(booted, "app")
        _ = await pool.save((await pool.get_item("secret")).set("plain text"))

        assert (await pool.get_item("secret")).get() == "plain text"

    written = [path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()]
    assert len(written) == 1
    assert b"plain text" not in written[0]


async def test_a_referenced_connection_is_the_one_the_pool_uses(tmp_path: Path) -> None:
    async with await _kernel(tmp_path, "tests.fixtures.app_cache_connection").boot() as booted:
        pool = await _pool(booted, "app")
        client = await booted.container.get(Redis, CACHE)

        assert isinstance(pool, RedisAdapter)
        assert pool._redis is client
        assert not pool.owns_connection
        assert pool._lock_registry is None


async def test_with_no_configuration_the_app_pool_is_files_under_the_share_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    async with await Kernel("tests.fixtures.app_cache_default", env="test").boot() as booted:
        pool = await _pool(booted, "app")
        share_dir = Path(str(booted.container.get_parameter("kernel.share_dir")))

    assert share_dir.is_relative_to(tmp_path)
    assert isinstance(pool, FilesystemAdapter)
    assert pool.directory.parent == share_dir / "cache"
    assert (share_dir / "cache" / "locks").is_dir()


async def test_boot_refuses_a_dsn_no_adapter_serves_without_echoing_it() -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        _ = await Kernel("tests.fixtures.app_cache_bad_dsn", env="test").boot()

    assert (
        raised.value.reason == 'The "reports" cache pool: Unsupported cache connection: "mysql:".'
    )
    assert "secret" not in str(raised.value)


async def test_boot_refuses_a_connection_the_container_does_not_provide() -> None:
    with pytest.raises(InvalidArgumentError, match=r"uses Redis\['absent'\], which the container"):
        _ = await Kernel("tests.fixtures.app_cache_missing_connection", env="test").boot()


async def test_boot_refuses_a_stampede_lock_no_store_serves() -> None:
    with pytest.raises(InvalidArgumentError, match="The cache stampede lock"):
        _ = await Kernel("tests.fixtures.app_cache_bad_lock", env="test").boot()


async def test_boot_checks_a_dsn_read_from_the_environment(tmp_path: Path) -> None:
    with pytest.raises(InvalidArgumentError, match='The "from_env" cache pool'):
        _ = await _kernel(tmp_path, CACHE_TEST_DSN="bogus://x").boot()


async def test_boot_fails_when_a_dsn_variable_is_not_set(tmp_path: Path) -> None:
    kernel = Kernel(APP, env="test", environ={"CACHE_TEST_DIR": str(tmp_path)})

    with pytest.raises(ServiceResolutionError) as raised:
        _ = await kernel.boot()

    assert "CACHE_TEST_DSN" in str(raised.value.__cause__)


async def test_a_pool_keeps_its_tags_in_the_pool_it_names(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        tagged = await _pool(booted, "tagged_chain")
        versions = await _pool(booted, "versions")

        assert isinstance(tagged, TagAwareAdapter)
        assert tagged._tags is versions
        assert isinstance(tagged._items, ChainAdapter)


async def test_every_layer_of_a_pool_logs_to_the_cache_channel(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        tagged = await _pool(booted, "tagged_chain")
        channel = await booted.container.get(LoggerInterface, CACHE_CHANNEL)

        assert isinstance(tagged, TagAwareAdapter)
        chain = tagged._items
        assert isinstance(chain, ChainAdapter)
        assert tagged.logger is channel
        assert chain.logger is channel
        assert all(
            adapter.logger is channel
            for adapter in chain.adapters
            if isinstance(adapter, ArrayAdapter)
        )


async def test_without_a_stampede_lock_there_is_no_lock_registry(tmp_path: Path) -> None:
    key = SodiumMarshaller.generate_key()
    kernel = _kernel(tmp_path, "tests.fixtures.app_cache_sodium", CACHE_DECRYPTION_KEY=key)

    async with await kernel.boot() as booted:
        pool = await _pool(booted, "app")

        assert not booted.container.has(LockRegistry)
        assert isinstance(pool, FilesystemAdapter)
        assert pool._lock_registry is None
