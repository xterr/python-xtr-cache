from __future__ import annotations

import os
import stat
import sys
import tempfile
import time
from typing import TYPE_CHECKING

import pytest
from xtr_clock.testing import mock_time

from tests.support.pool_conformance import PoolTests
from tests.support.recording_logger import RecordingLogger
from xtr_cache import FilesystemAdapter, InvalidArgumentError, PruneableInterface

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="file ownership and modes are POSIX"
)


class TestFilesystemAdapter(PoolTests):
    @pytest.fixture
    def pool(self, tmp_path: Path) -> FilesystemAdapter:
        return FilesystemAdapter("pool", directory=tmp_path)


def _files(directory: Path) -> list[Path]:
    return [path for path in directory.rglob("*") if path.is_file()]


def test_nothing_is_created_until_a_value_is_written(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path / "cache")

    assert pool.directory == tmp_path / "cache" / "pool"
    assert not (tmp_path / "cache").exists()


def test_a_pool_without_a_namespace_has_a_directory_of_its_own(tmp_path: Path) -> None:
    assert FilesystemAdapter(directory=tmp_path).directory == tmp_path / "@"


def test_a_namespace_of_dots_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidArgumentError, match="cannot name a directory"):
        _ = FilesystemAdapter("..", directory=tmp_path)


async def test_each_value_is_one_file_holding_its_expiry_and_key(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item("a")).set(1).expires_after(10))
        expiry = clock.now().timestamp() + 10

    (path,) = _files(tmp_path)
    header = path.read_bytes().split(b"\n", 2)
    assert header[:2] == [f"{expiry:.6f}".encode(), b"pool%3Aa"]


async def test_pruning_removes_expired_files_and_keeps_the_rest(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item("short")).set(1).expires_after(1))
        _ = await pool.save((await pool.get_item("long")).set(1).expires_after(60))
        _ = await pool.save((await pool.get_item("forever")).set(1))
        clock.sleep(2)

        assert await pool.prune()

    assert len(_files(tmp_path)) == 2
    assert isinstance(pool, PruneableInterface)


async def test_pruning_an_empty_pool_is_fine(tmp_path: Path) -> None:
    assert await FilesystemAdapter("pool", directory=tmp_path / "none").prune()


async def test_an_expired_file_is_removed_when_read(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item("a")).set(1).expires_after(1))
        clock.sleep(1)

        assert not (await pool.get_item("a")).is_hit()

    assert _files(tmp_path) == []


async def test_a_file_that_is_not_a_value_reads_as_a_miss(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)
    logger = RecordingLogger()
    pool.set_logger(logger)
    _ = await pool.save((await pool.get_item("a")).set(1))
    (path,) = _files(tmp_path)

    _ = path.write_bytes(b"garbage")
    assert not (await pool.get_item("a")).is_hit()
    assert not await pool.has_item("a")

    _ = path.write_bytes(b"not a time\npool%3Aa\n")
    assert not (await pool.get_item("a")).is_hit()

    _ = path.write_bytes(b"0\npool%3Aa\nnot a pickle")
    assert not (await pool.get_item("a")).is_hit()
    assert logger.messages("warning") == ['Failed to read key "{key}": {reason}']


async def test_another_key_hashing_to_the_same_file_reads_as_a_miss(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)
    _ = await pool.save((await pool.get_item("a")).set(1))
    (path,) = _files(tmp_path)

    _ = path.write_bytes(path.read_bytes().replace(b"pool%3Aa", b"pool%3Ab"))

    assert not (await pool.get_item("a")).is_hit()
    assert not await pool.has_item("a")


async def test_two_pools_on_one_directory_share_their_values(tmp_path: Path) -> None:
    writer = FilesystemAdapter("pool", directory=tmp_path)
    reader = FilesystemAdapter("pool", directory=tmp_path)

    _ = await writer.save((await writer.get_item("a")).set("shared"))

    assert (await reader.get_item("a")).get() == "shared"


async def test_a_sub_namespace_keeps_its_keys_apart_and_clears_alone(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)
    tenant = pool.with_sub_namespace("tenant")
    _ = await pool.save((await pool.get_item("a")).set("root"))
    _ = await tenant.save((await tenant.get_item("a")).set("tenant"))

    assert (await pool.get_item("a")).get() == "root"
    assert (await tenant.get_item("a")).get() == "tenant"

    assert await tenant.clear()
    assert not await tenant.has_item("a")
    assert await pool.has_item("a")


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions")
async def test_a_directory_that_cannot_be_written_fails_the_save(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    pool = FilesystemAdapter("pool", directory=locked)
    logger = RecordingLogger()
    pool.set_logger(logger)

    try:
        assert not await pool.save((await pool.get_item("a")).set(1))
    finally:
        locked.chmod(0o700)

    assert 'Failed to write key "{key}": {reason}' in logger.messages("warning")


def test_it_describes_itself(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", 5, tmp_path)

    assert repr(pool) == f"FilesystemAdapter('pool:', 5, {str(tmp_path / 'pool')!r})"


@posix_only
async def test_files_and_their_directories_are_the_owners_alone_by_default(
    tmp_path: Path,
) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)

    _ = await pool.save((await pool.get_item("a")).set(1))

    (path,) = _files(tmp_path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


@posix_only
async def test_shared_files_are_created_as_the_umask_allows_so_other_users_can_share_them(
    tmp_path: Path,
) -> None:
    umask = os.umask(0)
    _ = os.umask(umask)
    pool = FilesystemAdapter("pool", directory=tmp_path, shared=True)

    _ = await pool.save((await pool.get_item("a")).set(1))

    (path,) = _files(tmp_path)
    assert path.stat().st_mode & 0o777 == 0o666 & ~umask


async def test_pruning_removes_what_an_interrupted_write_left_long_ago(tmp_path: Path) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)
    shard = tmp_path / "pool" / "x" / "y"
    shard.mkdir(parents=True)
    abandoned = shard / ".xtr-cache-abandoned"
    in_progress = shard / ".xtr-cache-in-progress"
    _ = abandoned.write_bytes(b"half")
    _ = in_progress.write_bytes(b"half")
    two_hours_ago = time.time() - 7200
    os.utime(abandoned, (two_hours_ago, two_hours_ago))

    assert await pool.prune()

    assert not abandoned.exists()
    assert in_progress.exists()


@pytest.fixture
def temporary_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Stand in for the system's temporary directory, where the default one goes."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path / "xtr-cache"


@posix_only
async def test_the_default_directory_is_made_for_this_user_alone(temporary_directory: Path) -> None:
    pool = FilesystemAdapter("pool")

    assert await pool.save((await pool.get_item("a")).set(1))

    assert stat.S_IMODE(temporary_directory.stat().st_mode) == 0o700


@posix_only
async def test_a_default_directory_of_this_user_is_made_private(temporary_directory: Path) -> None:
    temporary_directory.mkdir(mode=0o777)
    temporary_directory.chmod(0o777)
    pool = FilesystemAdapter("pool")

    assert await pool.save((await pool.get_item("a")).set(1))

    assert stat.S_IMODE(temporary_directory.stat().st_mode) == 0o700


@posix_only
async def test_a_default_directory_of_another_user_is_refused(
    temporary_directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = FilesystemAdapter("pool")
    assert await writer.save((await writer.get_item("a")).set(1))
    monkeypatch.setattr(os, "getuid", lambda: temporary_directory.stat().st_uid + 1)
    pool = FilesystemAdapter("pool")
    logger = RecordingLogger()
    pool.set_logger(logger)

    assert not (await pool.get_item("a")).is_hit()
    assert not await pool.save((await pool.get_item("b")).set(1))
    assert any("Refusing" in message for message in logger.messages("warning"))


@posix_only
async def test_a_file_in_place_of_the_default_directory_is_refused(
    temporary_directory: Path,
) -> None:
    _ = temporary_directory.write_text("not a directory")
    pool = FilesystemAdapter("pool")

    assert not await pool.save((await pool.get_item("a")).set(1))


async def test_a_directory_the_application_chose_is_left_as_it_is(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    pool = FilesystemAdapter("pool", directory=tmp_path)

    assert await pool.save((await pool.get_item("a")).set(1))

    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o755


async def test_pruning_and_clearing_read_no_value_in_full(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)
    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item("short")).set(b"x" * 100_000).expires_after(1))
        _ = await pool.save((await pool.get_item("kept")).set(b"x" * 100_000))
        clock.sleep(2)

        def whole_value_read(_path: Path) -> None:
            raise AssertionError

        monkeypatch.setattr(FilesystemAdapter, "_read", staticmethod(whole_value_read))
        assert await pool.prune()
        assert len(_files(tmp_path)) == 1
        assert await pool.clear("kept")

    assert _files(tmp_path) == []


async def test_a_file_whose_identifier_outgrows_the_header_read_is_still_pruned(
    tmp_path: Path,
) -> None:
    pool = FilesystemAdapter("pool", directory=tmp_path)
    key = "k" * 5000

    with mock_time("2024-04-09 12:00:00") as clock:
        _ = await pool.save((await pool.get_item(key)).set(1).expires_after(1))
        clock.sleep(2)

        assert await pool.prune()

    assert _files(tmp_path) == []
