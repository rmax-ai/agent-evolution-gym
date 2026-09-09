"""Unit tests for the append-only trajectory recorder."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentgym.core.trajectory import TrajectoryEventType
from agentgym.runner.recorder import TrajectoryLoadError, TrajectoryRecorder


def test_recorder_assigns_monotonic_sequences_and_utc_timestamps() -> None:
    recorder = TrajectoryRecorder()

    first = recorder.append(TrajectoryEventType.RUN_STARTED, "runner", {"ok": True})
    second = recorder.append(TrajectoryEventType.RUN_COMPLETED, "runner", {"ok": True})

    assert [event.sequence for event in recorder.events] == [1, 2]
    assert all(datetime.fromisoformat(event.timestamp).tzinfo == UTC for event in recorder)
    assert first.type is TrajectoryEventType.RUN_STARTED
    assert second.type is TrajectoryEventType.RUN_COMPLETED


def test_flush_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.jsonl"
    recorder = TrajectoryRecorder()
    recorder.append(TrajectoryEventType.TOOL_CALL, "agent", {"name": "read"})
    recorder.flush(path)

    loaded = TrajectoryRecorder.load(path)

    assert loaded == recorder.events
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_flush_is_append_safe_across_recorder_instances(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.jsonl"
    first = TrajectoryRecorder()
    second = TrajectoryRecorder()
    first.append(TrajectoryEventType.RUN_STARTED, "runner", {})
    second.append(TrajectoryEventType.RUN_COMPLETED, "runner", {})

    first.flush(path)
    second.flush(path)

    assert [event.type for event in TrajectoryRecorder.load(path)] == [
        TrajectoryEventType.RUN_STARTED,
        TrajectoryEventType.RUN_COMPLETED,
    ]


def test_load_reports_corrupt_line_number(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.jsonl"
    recorder = TrajectoryRecorder()
    recorder.append(TrajectoryEventType.RUN_STARTED, "runner", {})
    recorder.flush(path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("not-json\n")

    with pytest.raises(TrajectoryLoadError, match=r"line 2"):
        TrajectoryRecorder.load(path)


def test_load_can_skip_and_record_corrupt_lines_when_opted_in(tmp_path: Path) -> None:
    path = tmp_path / "trajectory.jsonl"
    path.write_text(
        json.dumps(
            {
                "sequence": 1,
                "timestamp": "2026-09-06T00:00:00+00:00",
                "type": "run.started",
                "actor": "runner",
                "payload": {},
            }
        )
        + "\nnot-json\n",
        encoding="utf-8",
    )
    errors: list[TrajectoryLoadError] = []

    loaded = TrajectoryRecorder.load(path, skip_and_record=True, errors=errors)

    assert len(loaded) == 1
    assert [error.line_number for error in errors] == [2]
