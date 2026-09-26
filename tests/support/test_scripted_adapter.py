"""The scripted adapter keeps the pool contract while nothing is scripted to fail."""

from __future__ import annotations

import pytest

from tests.support.pool_conformance import PoolTests
from tests.support.scripted_adapter import BackendDownError, ScriptedAdapter

pytestmark = pytest.mark.anyio


class TestScriptedAdapter(PoolTests):
    @pytest.fixture
    def pool(self) -> ScriptedAdapter:
        return ScriptedAdapter("pool")


async def test_a_scripted_operation_raises_and_is_recorded() -> None:
    pool = ScriptedAdapter()
    pool.fail.add("have")

    with pytest.raises(BackendDownError):
        _ = await pool._do_have("a")

    assert pool.calls == [("have", ("a",))]


async def test_batches_can_be_refused_while_single_values_go_through() -> None:
    pool = ScriptedAdapter()
    pool.refuse_batches = True

    assert await pool._do_save({"a": 1, "b": 2}, 0) is False
    assert await pool._do_save({"a": 1}, 0) is True
    assert await pool._do_delete(["a", "b"]) is False


async def test_everything_can_be_refused() -> None:
    pool = ScriptedAdapter()
    pool.refuse_all = True

    assert await pool._do_save({"a": 1}, 0) is False
    assert await pool._do_delete(["a"]) is False


async def test_rejected_identifiers_are_reported_and_not_stored() -> None:
    pool = ScriptedAdapter()
    pool.reject.add("b")

    assert await pool._do_save({"a": 1, "b": 2}, 0) == ["b"]
    assert set(pool.stored) == {"a"}
