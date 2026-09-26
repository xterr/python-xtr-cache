"""A pool keeping one file per value in a directory."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, final
from urllib.parse import quote, unquote

from typing_extensions import override

from xtr_cache.exception import InvalidArgumentError
from xtr_cache.marshaller.default_marshaller import DefaultMarshaller
from xtr_cache.pruneable_interface import PruneableInterface

from .abstract_adapter import AbstractAdapter

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from xtr_clock import ClockInterface

    from xtr_cache.marshaller.marshaller_interface import MarshallerInterface

__all__ = ["FilesystemAdapter"]

_NO_NAMESPACE: Final = "@"
"""The subdirectory of a pool without a namespace."""

_TEMPORARY_PREFIX: Final = ".xtr-cache-"
"""What a file being written starts with, until it replaces the value's file."""

_ABANDONED_AFTER: Final = 3600.0
"""Seconds after which a file still being written was left by a write that never finished."""

_WRITE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL


@final
class FilesystemAdapter(AbstractAdapter, PruneableInterface):
    """Keeps each value in a file of its own, under a directory per namespace.

    A file holds the value's expiry, its identifier and its bytes. Writing
    goes to a temporary file first and replaces the old one in one step, so
    a reader never sees half a value, and processes sharing the directory
    share the cache. File work runs on a worker thread, off the event loop.

    Nothing is created until the first value is written. An expired file is
    removed when it is read; :meth:`prune` removes the ones nobody reads.
    """

    _directory: Path
    _marshaller: MarshallerInterface

    def __init__(
        self,
        namespace: str = "",
        default_lifetime: float = 0.0,
        directory: str | os.PathLike[str] | None = None,
        *,
        marshaller: MarshallerInterface | None = None,
        clock: ClockInterface | None = None,
    ) -> None:
        """Keep values in files under ``directory``.

        Args:
            namespace: Put in front of every key, and names the directory's
                subdirectory the files go in.
            default_lifetime: Seconds a value lives when its item sets no
                expiry; ``0`` for no limit.
            directory: Where the files go. ``None`` uses ``xtr-cache`` under
                the system's temporary directory.
            marshaller: What turns values into bytes. Pickle when omitted.
            clock: What lifetimes are counted from. ``None`` reads the clock
                in force.

        Raises:
            InvalidArgumentError: When ``namespace`` is not valid, or is only dots.
        """
        super().__init__(namespace, default_lifetime, clock=clock)
        if namespace and not namespace.strip("."):
            raise InvalidArgumentError(f'Cache namespace "{namespace}" cannot name a directory.')

        base = (
            Path(directory) if directory is not None else Path(tempfile.gettempdir()) / "xtr-cache"
        )
        self._directory = base / (namespace or _NO_NAMESPACE)
        self._marshaller = marshaller if marshaller is not None else DefaultMarshaller()

    @property
    def directory(self) -> Path:
        """The directory this pool's files go in."""
        return self._directory

    @override
    async def prune(self) -> bool:
        return await asyncio.to_thread(self._prune)

    @override
    async def _do_fetch(self, ids: Sequence[str]) -> Mapping[str, object]:
        raw = await asyncio.to_thread(self._read_all, ids, self._clock.now().timestamp())
        return self._unmarshall_found(self._marshaller, raw)

    @override
    async def _do_have(self, id_: str) -> bool:
        return await asyncio.to_thread(self._is_live, id_, self._clock.now().timestamp())

    @override
    async def _do_clear(self, namespace: str) -> bool:
        return await asyncio.to_thread(self._clear, namespace)

    @override
    async def _do_delete(self, ids: Sequence[str]) -> bool:
        return await asyncio.to_thread(self._delete, ids)

    @override
    async def _do_save(self, values: Mapping[str, object], lifetime: float) -> bool | Sequence[str]:
        encoded, failed = self._marshaller.marshall(values)
        expiry = self._clock.now().timestamp() + lifetime if lifetime else 0.0
        failed.extend(await asyncio.to_thread(self._write_all, encoded, expiry))
        return failed or True

    @override
    def __repr__(self) -> str:
        name = type(self).__name__
        return f"{name}({self._namespace!r}, {self._default_lifetime!r}, {str(self._directory)!r})"

    def _path(self, id_: str) -> Path:
        digest = base64.urlsafe_b64encode(hashlib.sha256(id_.encode()).digest()).decode()
        digest = digest.rstrip("=")
        return self._directory / digest[0] / digest[1] / digest[2:]

    def _read_all(self, ids: Sequence[str], now: float) -> dict[str, bytes]:
        found: dict[str, bytes] = {}
        for id_ in ids:
            content = self._read(self._path(id_))
            if content is None:
                continue
            expiry, stored_id, data = content
            if stored_id != id_:
                continue
            if expiry and expiry <= now:
                _ = _unlink(self._path(id_))
                continue
            found[id_] = data

        return found

    def _is_live(self, id_: str, now: float) -> bool:
        content = self._read(self._path(id_))
        if content is None or content[1] != id_:
            return False
        return not content[0] or content[0] > now

    def _clear(self, namespace: str) -> bool:
        ok = True
        for path in self._files():
            if namespace:
                content = self._read(path)
                if content is None or not content[1].startswith(namespace):
                    continue
            ok = _unlink(path) and ok

        return ok

    def _delete(self, ids: Sequence[str]) -> bool:
        ok = True
        for id_ in ids:
            ok = _unlink(self._path(id_)) and ok
        return ok

    def _write_all(self, encoded: Mapping[str, bytes], expiry: float) -> list[str]:
        failed: list[str] = []
        for id_, data in encoded.items():
            path = self._path(id_)
            header = f"{expiry:.6f}\n{quote(id_, safe='')}\n".encode("ascii")
            temporary = path.parent / f"{_TEMPORARY_PREFIX}{secrets.token_hex(8)}"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Readable by whoever the umask lets read it, so processes run as other users
                # can share the directory.
                with os.fdopen(os.open(temporary, _WRITE_FLAGS, 0o666), "wb") as file:
                    _ = file.write(header)
                    _ = file.write(data)
                _ = temporary.replace(path)
            except OSError as error:
                failed.append(id_)
                _ = _unlink(temporary)
                self._log('Failed to write key "{key}": {reason}', error, key=id_)

        return failed

    def _prune(self) -> bool:
        now = self._clock.now().timestamp()
        ok = True
        for path in self._files():
            content = self._read(path)
            if content is not None and content[0] and content[0] <= now:
                ok = _unlink(path) and ok

        # File times are the file system's, so they are compared with the machine's clock.
        abandoned = time.time() - _ABANDONED_AFTER
        for path in self._files(temporary=True):
            if _modified(path) < abandoned:
                ok = _unlink(path) and ok

        return ok

    def _files(self, *, temporary: bool = False) -> Iterator[Path]:
        """Yield the values' files, or the files of writes in progress when ``temporary``."""
        if not self._directory.is_dir():
            return
        for root, _, names in os.walk(self._directory):
            for name in names:
                if name.startswith(_TEMPORARY_PREFIX) is temporary:
                    yield Path(root) / name

    @staticmethod
    def _read(path: Path) -> tuple[float, str, bytes] | None:
        """Return a file's expiry, identifier and value bytes; ``None`` when missing or not ours."""
        try:
            content = path.read_bytes()
        except OSError:
            return None

        expiry, _, rest = content.partition(b"\n")
        stored_id, separator, data = rest.partition(b"\n")
        if not separator:
            return None
        try:
            return float(expiry), unquote(stored_id.decode("ascii")), data
        except (UnicodeDecodeError, ValueError):
            return None


def _modified(path: Path) -> float:
    """Return when ``path`` was last written; infinitely recent when it is already gone."""
    try:
        return path.stat().st_mtime
    except OSError:
        return float("inf")


def _unlink(path: Path) -> bool:
    """Remove ``path``; a file already gone counts as removed."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return False
    return True
