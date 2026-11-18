"""Unit tests for :mod:`xtr_cache.data_collector._masking`."""

from __future__ import annotations

import pytest

from xtr_cache.data_collector._masking import MASK, masked_key


@pytest.mark.parametrize(
    "key",
    ["reset_token.3f9a", "user.PASSWORD", "app_secret", "passwd", "api_key.7", "ApiKey"],
)
def test_a_key_named_like_a_credential_is_masked(key: str) -> None:
    assert masked_key(key) == MASK


def test_any_other_key_is_kept() -> None:
    assert masked_key("invoice.7") == "invoice.7"
