"""The recording logger keeps every call, in order, by level."""

from __future__ import annotations

from tests.support.recording_logger import RecordingLogger


def test_it_records_each_call_with_its_level_and_context() -> None:
    logger = RecordingLogger()

    logger.warning("w {key}", {"key": "a"})
    logger.info("i")

    assert logger.records == [("warning", "w {key}", {"key": "a"}), ("info", "i", {})]
    assert logger.messages("warning") == ["w {key}"]
