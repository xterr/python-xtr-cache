"""What every pool must do, as a test class a pool's own tests inherit.

A pool's test class inherits :class:`PoolTests` and defines a ``pool``
fixture. Keys are plain; a pool on a shared server gets a namespace of its
own from the ``namespace`` fixture, so it never sees another test's keys.
A pool whose backend expires values on its own clock sets
``expires_on_frozen_time = False``: its expiry tests then wait for real.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar, Self, final

import pytest
from typing_extensions import override
from xtr_clock.testing import mock_time

from tests.support.callbacks import Computation
from xtr_cache import InvalidArgumentError, ItemInterface, Metadata

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from xtr_cache import AdapterInterface

__all__ = ["Point", "PoolTests"]


@dataclass(frozen=True)
class Point:
    """A value a pool must hand back as what it was, not as a dictionary."""

    x: int
    y: int


class PoolTests:
    """Reading, writing, deleting, clearing, expiring and computing, for any pool."""

    expires_on_frozen_time: ClassVar[bool] = True

    @pytest.mark.anyio
    async def test_a_key_never_saved_is_a_miss(self, pool: AdapterInterface) -> None:
        item = await pool.get_item("absent")

        assert item.key == "absent"
        assert not item.is_hit()
        assert item.get() is None
        assert not await pool.has_item("absent")

    @pytest.mark.anyio
    async def test_a_saved_value_comes_back_as_what_it_was(self, pool: AdapterInterface) -> None:
        assert await pool.save((await pool.get_item("point")).set(Point(1, 2)))

        item = await pool.get_item("point")

        assert item.is_hit()
        assert item.get() == Point(1, 2)
        assert await pool.has_item("point")

    @pytest.mark.anyio
    async def test_a_saved_none_is_a_hit(self, pool: AdapterInterface) -> None:
        _ = await pool.save((await pool.get_item("none")).set(None))

        assert (await pool.get_item("none")).is_hit()

    @pytest.mark.anyio
    async def test_items_come_back_for_every_key_in_the_order_asked(
        self,
        pool: AdapterInterface,
    ) -> None:
        _ = await pool.save((await pool.get_item("b")).set("bee"))

        items = await pool.get_items(["c", "b", "a", "b"])

        assert list(items) == ["c", "b", "a"]
        assert [item.is_hit() for item in items.values()] == [False, True, False]
        assert items["b"].get() == "bee"
        assert await pool.get_items([]) == {}

    @pytest.mark.anyio
    async def test_reading_several_keys_commits_a_deferred_one_first(
        self,
        pool: AdapterInterface,
    ) -> None:
        _ = await pool.save_deferred((await pool.get_item("a")).set(1))

        assert (await pool.get_items(["a", "b"]))["a"].get() == 1

    @pytest.mark.anyio
    async def test_deleting_removes_the_value_and_a_missing_key_is_fine(
        self,
        pool: AdapterInterface,
    ) -> None:
        _ = await pool.save((await pool.get_item("a")).set(1))
        _ = await pool.save((await pool.get_item("b")).set(2))

        assert await pool.delete_item("a")
        assert await pool.delete_items(["b", "never"])
        assert await pool.delete_items([])

        assert not await pool.has_item("a")
        assert not await pool.has_item("b")

    @pytest.mark.anyio
    async def test_clearing_removes_every_value(self, pool: AdapterInterface) -> None:
        _ = await pool.save((await pool.get_item("a")).set(1))
        _ = await pool.save_deferred((await pool.get_item("b")).set(2))

        assert await pool.clear()

        assert not await pool.has_item("a")
        assert not await pool.has_item("b")

    @pytest.mark.anyio
    async def test_clearing_a_prefix_keeps_the_other_keys(self, pool: AdapterInterface) -> None:
        _ = await pool.save((await pool.get_item("user.1")).set(1))
        _ = await pool.save((await pool.get_item("order.1")).set(1))

        assert await pool.clear("user.")

        assert not await pool.has_item("user.1")
        assert await pool.has_item("order.1")

    @pytest.mark.anyio
    async def test_clearing_a_prefix_keeps_items_deferred_under_other_keys(
        self,
        pool: AdapterInterface,
    ) -> None:
        _ = await pool.save_deferred((await pool.get_item("keep.me")).set(1))
        _ = await pool.save_deferred((await pool.get_item("other.one")).set(1))

        assert await pool.clear("other.")

        assert await pool.has_item("keep.me")
        assert not await pool.has_item("other.one")

    @pytest.mark.anyio
    async def test_a_prefix_with_characters_no_backend_matches_is_refused(
        self,
        pool: AdapterInterface,
    ) -> None:
        _ = await pool.save((await pool.get_item("a")).set(1))

        assert not await pool.clear("a*b")
        assert await pool.has_item("a")

    @pytest.mark.anyio
    async def test_a_deferred_item_is_stored_on_commit(self, pool: AdapterInterface) -> None:
        assert await pool.save_deferred((await pool.get_item("a")).set(1))
        assert await pool.save_deferred((await pool.get_item("b")).set(2))

        assert await pool.commit()

        items = await pool.get_items(["a", "b"])
        assert [item.get() for item in items.values()] == [1, 2]

    @pytest.mark.anyio
    async def test_reading_a_deferred_key_commits_it_first(self, pool: AdapterInterface) -> None:
        _ = await pool.save_deferred((await pool.get_item("a")).set(1))

        assert (await pool.get_item("a")).get() == 1

    @pytest.mark.anyio
    async def test_resetting_commits_what_was_deferred(self, pool: AdapterInterface) -> None:
        _ = await pool.save_deferred((await pool.get_item("a")).set(1))

        await pool.reset()

        assert await pool.has_item("a")

    @pytest.mark.anyio
    async def test_a_lifetime_of_zero_or_less_removes_the_key(self, pool: AdapterInterface) -> None:
        _ = await pool.save((await pool.get_item("a")).set(1))

        assert await pool.save((await pool.get_item("a")).set(2).expires_after(0))

        assert not await pool.has_item("a")

    @pytest.mark.anyio
    async def test_an_item_expires_after_its_lifetime(self, pool: AdapterInterface) -> None:
        if not self.expires_on_frozen_time:
            _ = await pool.save((await pool.get_item("a")).set(1).expires_after(0.3))
            assert await pool.has_item("a")
            await asyncio.sleep(0.5)
            assert not await pool.has_item("a")
            return

        with mock_time("2024-04-09 12:00:00") as clock:
            _ = await pool.save(
                (await pool.get_item("a")).set(1).expires_after(timedelta(seconds=10))
            )
            clock.sleep(9)
            assert (await pool.get_item("a")).is_hit()
            clock.sleep(1)
            assert not (await pool.get_item("a")).is_hit()

    @pytest.mark.anyio
    async def test_an_item_from_another_implementation_is_refused(
        self,
        pool: AdapterInterface,
    ) -> None:
        foreign = _ForeignItem()

        assert not await pool.save(foreign)
        assert not await pool.save_deferred(foreign)

    @pytest.mark.anyio
    @pytest.mark.parametrize("key", ["", "a:b", "a/b", "{a}", "a@b"])
    async def test_an_invalid_key_is_refused(self, pool: AdapterInterface, key: str) -> None:
        with pytest.raises(InvalidArgumentError):
            _ = await pool.get_item(key)
        with pytest.raises(InvalidArgumentError):
            _ = await pool.has_item(key)
        with pytest.raises(InvalidArgumentError):
            _ = await pool.delete_item(key)

    @pytest.mark.anyio
    async def test_a_value_is_computed_once_then_read(self, pool: AdapterInterface) -> None:
        compute = Computation(Point(3, 4), lifetime=60)

        assert await pool.get("computed", compute) == Point(3, 4)
        assert await pool.get("computed", compute) == Point(3, 4)
        assert compute.calls == 1

    @pytest.mark.anyio
    async def test_a_computed_value_is_stored_with_its_expiry_and_cost(
        self,
        pool: AdapterInterface,
    ) -> None:
        _ = await pool.get("timed", Computation(1, lifetime=60))

        metadata = (await pool.get_item("timed")).metadata
        assert "expiry" in metadata
        assert "ctime" in metadata

    @pytest.mark.anyio
    async def test_deleting_through_the_cache_removes_the_value(
        self, pool: AdapterInterface
    ) -> None:
        _ = await pool.get("a", Computation(1))

        assert await pool.delete("a")
        assert not await pool.has_item("a")


@final
class _ForeignItem(ItemInterface):
    """An item of another implementation, which no pool of this library stores."""

    @property
    @override
    def key(self) -> str:
        return "foreign"

    @override
    def get(self) -> object:
        return None

    @override
    def is_hit(self) -> bool:
        return False

    @override
    def set(self, value: object, /) -> Self:
        return self

    @override
    def expires_at(self, expiration: datetime | None, /) -> Self:
        return self

    @override
    def expires_after(self, ttl: float | timedelta | None, /) -> Self:
        return self

    @override
    def tag(self, tags: str | Iterable[str], /) -> Self:
        return self

    @property
    @override
    def metadata(self) -> Metadata:
        return Metadata()
