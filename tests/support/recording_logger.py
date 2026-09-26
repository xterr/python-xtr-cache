"""A logger that keeps what it is told, for asserting on."""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import override
from xtr_logging_contracts import AbstractLogger, Level

if TYPE_CHECKING:
    from xtr_logging_contracts import Context, LevelLike

__all__ = ["RecordingLogger"]


class RecordingLogger(AbstractLogger):
    """Records ``(level name, message, context)`` for every call, in order."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, dict[str, object]]] = []

    @override
    def log(self, level: LevelLike, message: str, /, context: Context | None = None) -> None:
        self.records.append((Level.parse(level).name.lower(), message, dict(context or {})))

    def messages(self, level: str) -> list[str]:
        """Return the messages logged at ``level``."""
        return [message for name, message, _ in self.records if name == level]
