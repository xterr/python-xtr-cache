from __future__ import annotations

import xtr_cache_contracts

from xtr_cache import CacheError, InvalidArgumentError, MarshallingError


def test_it_carries_the_reason_and_is_a_cache_error() -> None:
    error = MarshallingError("corrupt")

    assert error.reason == "corrupt"
    assert str(error) == "corrupt"
    assert isinstance(error, CacheError)


def test_the_contract_errors_are_the_contracts_own() -> None:
    assert CacheError is xtr_cache_contracts.CacheError
    assert InvalidArgumentError is xtr_cache_contracts.InvalidArgumentError
