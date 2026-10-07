"""A pool keeping one file per value in a directory."""

from __future__ import annotations

import asyncio
import os
import secrets
import stat
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final, final
from urllib.parse import quote, unquote

from typing_extensions import override

from xtr_cache._digest import urlsafe_digest
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

_HEADER_BYTES: Final = 4096
"""Enough of a file to hold its expiry and identifier lines, in all but freak cases."""

_PRIVATE_MODE: Final = 0o700
"""The default directory's mode: in the shared temporary directory, only its owner may enter."""

_PRIVATE_FILE_MODE: Final = 0o600
_PRIVATE_DIR_MODE: Final = 0o700
"""A pool's own files and directories, reachable by their owner alone, the default."""

_SHARED_FILE_MODE: Final = 0o666
_SHARED_DIR_MODE: Final = 0o777
"""The modes ``shared`` opts into, so processes run as other users can read the files."""


@final
class FilesystemAdapter(AbstractAdapter, PruneableInterface):
    """Keeps each value in a file of its own, under a directory per namespace.

    A file holds the value's expiry, its identifier and its bytes. Writing
    goes to a temporary file first and replaces the old one in one step, so
    a reader never sees half a value, and processes sharing the directory
    share the cache. File work runs on a worker thread, off the event loop.

    Nothing is created until the first value is written. An expired file is
    removed when it is read; :meth:`prune` removes the ones nobody reads.

    Files are the owner's alone (``0o600``) in directories the owner alone may
    enter (``0o700``), unless ``shared`` opens them to everyone (``0o666`` and
    ``0o777``, as the umask allows) so processes run as other users can read
    them. A shared directory is dangerous with the pickle marshaller: anyone
    who can write a file into it chooses what this process unpickles, which is
    code execution. Share a directory only with a marshaller that
    authenticates what it reads, such as
    :class:`~xtr_cache.marshaller.SodiumMarshaller`.

    Without a directory of its own, a pool keeps its files in the system's
    temporary directory, where every user may create one first. Values are
    unpickled when read, so there the directory is made for this user alone,
    and one belonging to anybody else is refused: every read misses and every
    write fails, and the pool logs why.
    """

    _directory: Path
    _marshaller: MarshallerInterface
    _private_root: Path | None
    _private_root_checked: bool
    _file_mode: int
    _dir_mode: int

    def __init__(  # noqa: PLR0913 — every option past the directory is keyword-only.
        self,
        namespace: str = "",
        default_lifetime: float = 0.0,
        directory: str | os.PathLike[str] | None = None,
        *,
        shared: bool = False,
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
            shared: Create files and directories readable by every user
                (``0o666``/``0o777``, as the umask allows) rather than the
                owner alone (``0o600``/``0o700``). Dangerous with pickle: a
                shared directory lets anyone choose what is unpickled, which
                is code execution. Pair it with an authenticating marshaller.
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
        self._private_root = base if directory is None else None
        self._private_root_checked = False
        self._marshaller = marshaller if marshaller is not None else DefaultMarshaller()
        self._file_mode = _SHARED_FILE_MODE if shared else _PRIVATE_FILE_MODE
        self._dir_mode = _SHARED_DIR_MODE if shared else _PRIVATE_DIR_MODE

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
        digest = urlsafe_digest(id_)
        return self._directory / digest[0] / digest[1] / digest[2:]

    def _read_all(self, ids: Sequence[str], now: float) -> dict[str, bytes]:
        found: dict[str, bytes] = {}
        if not self._is_trusted(create=False):
            return found
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
        if not self._is_trusted(create=False):
            return False
        header = self._read_header(self._path(id_))
        if header is None or header[1] != id_:
            return False
        return not header[0] or header[0] > now

    def _clear(self, namespace: str) -> bool:
        ok = True
        for path in self._files():
            if namespace:
                header = self._read_header(path)
                if header is None or not header[1].startswith(namespace):
                    continue
            ok = _unlink(path) and ok

        return ok

    def _delete(self, ids: Sequence[str]) -> bool:
        ok = True
        for id_ in ids:
            ok = _unlink(self._path(id_)) and ok
        return ok

    def _write_all(self, encoded: Mapping[str, bytes], expiry: float) -> list[str]:
        if not self._is_trusted(create=True):
            return list(encoded)
        failed: list[str] = []
        for id_, data in encoded.items():
            path = self._path(id_)
            header = f"{expiry:.6f}\n{quote(id_, safe='')}\n".encode("ascii")
            temporary = path.parent / f"{_TEMPORARY_PREFIX}{secrets.token_hex(8)}"
            try:
                path.parent.mkdir(self._dir_mode, parents=True, exist_ok=True)
                # The owner's alone by default; readable by whoever the umask lets read it
                # when shared, so processes run as other users can share the directory.
                with os.fdopen(os.open(temporary, _WRITE_FLAGS, self._file_mode), "wb") as file:
                    _ = file.write(header)
                    _ = file.write(data)
                _ = temporary.replace(path)
            except OSError as error:
                failed.append(id_)
                _ = _unlink(temporary)
                self._log('Failed to write key "{key}": {reason}', error, key=id_)

        return failed

    def _is_trusted(self, *, create: bool) -> bool:
        """Tell whether the files under the default directory may be read and written.

        Only the default directory is checked: one the application chose is
        its own. Creating it makes it private; an existing one of this user's
        is made private too. Once found trustworthy, it stays so: in a
        temporary directory nobody else may rename or remove it. Where the
        system has no user ids, as on Windows, the owner compared is the
        directory's own, so the check passes: the directory is taken as it is.
        """
        root = self._private_root
        if root is None or self._private_root_checked:
            return True
        try:
            if create:
                root.mkdir(mode=_PRIVATE_MODE, parents=True, exist_ok=True)
            status = root.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            self._log(
                'Cannot use the cache directory "{directory}": {reason}', error, directory=root
            )
            return False

        owner = os.getuid() if hasattr(os, "getuid") else status.st_uid
        if not stat.S_ISDIR(status.st_mode) or status.st_uid != owner:
            self._log(
                'Refusing the cache directory "{directory}": it is not a directory of this user.',
                directory=root,
            )
            return False
        if stat.S_IMODE(status.st_mode) != _PRIVATE_MODE:
            try:
                root.chmod(_PRIVATE_MODE)
            except OSError as error:
                self._log(
                    'Cannot make the cache directory "{directory}" private: {reason}',
                    error,
                    directory=root,
                )
                return False
        self._private_root_checked = True
        return True

    def _prune(self) -> bool:
        now = self._clock.now().timestamp()
        ok = True
        for path in self._files():
            header = self._read_header(path)
            if header is not None and header[0] and header[0] <= now:
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
    def _read_header(path: Path) -> tuple[float, str] | None:
        """Return a file's expiry and identifier, reading no more of it than they take.

        Pruning and clearing look at every file; reading each value in full
        to see two short lines would read the whole cache.
        """
        try:
            with path.open("rb") as file:
                head = file.read(_HEADER_BYTES)
        except OSError:
            return None
        if head.count(b"\n") < 2:  # noqa: PLR2004 — the expiry line and the identifier line
            # An identifier longer than the bound: read the file as a whole.
            content = FilesystemAdapter._read(path)
            return None if content is None else (content[0], content[1])
        expiry, _, rest = head.partition(b"\n")
        stored_id, _, _ = rest.partition(b"\n")
        try:
            return float(expiry), unquote(stored_id.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            return None

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
