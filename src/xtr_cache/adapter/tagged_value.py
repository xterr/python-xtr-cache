"""What a tag-aware pool stores: a value, and the versions its tags had."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["TaggedValue"]


@final
@dataclass(frozen=True, slots=True)
class TaggedValue:
    """A value as a tag-aware pool stores it, with each tag's version at the time.

    Part of the stored format: its module and name must not change, or
    values already stored would no longer be read back.

    Attributes:
        value: The cached value.
        versions: Each tag's version when the value was saved.
    """

    value: object
    versions: Mapping[str, str]
