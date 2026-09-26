"""A pool that holds on to expired values until told to let them go."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["PruneableInterface"]


@runtime_checkable
class PruneableInterface(Protocol):
    """A pool whose backend does not expire values on its own.

    Files stay on disk after their value expires: reading one again treats it
    as a miss and removes it, but a key nobody reads keeps its file. Pruning
    removes every expired value at once; run it from a scheduled job.
    """

    async def prune(self) -> bool:
        """Remove every expired value.

        Returns:
            ``False`` when the backend failed for any of them; ``True``
            otherwise.
        """
        ...
