"""Append-only trajectory recording and JSONL persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from pydantic import ValidationError

from agentgym.core.trajectory import TrajectoryEvent, TrajectoryEventType


class TrajectoryLoadError(ValueError):
    """Raised when one JSONL line is not a valid trajectory event."""

    def __init__(self, line_number: int, reason: str) -> None:
        self.line_number = line_number
        super().__init__(f"invalid trajectory event at line {line_number}: {reason}")


class TrajectoryRecorder:
    """Collect observable events and append them to JSONL files.

    ``append`` is the synchronous primitive used by storage and tests.  The
    async ``emit`` adapter keeps the recorder compatible with the runtime's
    :class:`~agentgym.runtime.base.EventSink` protocol.
    """

    _MISSING: ClassVar[object] = object()

    def __init__(self, events: Sequence[TrajectoryEvent] | None = None) -> None:
        self.events: list[TrajectoryEvent] = []
        self._flushed_counts: dict[Path, int] = {}
        if events is not None:
            for event in events:
                self.append(event)

    def append(
        self,
        event_or_type: TrajectoryEvent | TrajectoryEventType | str,
        actor: str | None = None,
        payload: Mapping[str, Any] | object | None = _MISSING,
    ) -> TrajectoryEvent:
        """Append one event and assign its sequence and UTC timestamp.

        Passing a :class:`TrajectoryEvent` is useful when replaying or
        adapting an event, but its sequence and timestamp are deliberately
        replaced so the recorder remains the source of ordering metadata.
        Passing an event type requires ``actor`` and ``payload``.
        """

        if isinstance(event_or_type, TrajectoryEvent):
            if actor is not None or payload is not self._MISSING:
                raise TypeError("actor and payload are not accepted with a TrajectoryEvent")
            event = event_or_type.model_copy(
                update={
                    "sequence": len(self.events) + 1,
                    "timestamp": _utc_timestamp(),
                }
            )
        else:
            if actor is None:
                raise TypeError("actor is required when appending an event type")
            if payload is self._MISSING or payload is None:
                raise TypeError("payload is required when appending an event type")
            if not isinstance(payload, Mapping):
                raise TypeError("trajectory payload must be a mapping")
            event = TrajectoryEvent(
                sequence=len(self.events) + 1,
                timestamp=_utc_timestamp(),
                type=event_or_type,
                actor=actor,
                payload=dict(payload),
            )
        self.events.append(event)
        return event

    async def emit(
        self,
        event_type: TrajectoryEventType | str,
        actor: str,
        payload: dict[str, Any],
    ) -> None:
        """Append an event through the runtime's async event-sink boundary."""

        self.append(event_type, actor, payload)

    def flush(self, path: str | Path) -> Path:
        """Append pending events to ``path`` as one JSON object per line.

        The file is opened in append mode.  A recorder remembers how many
        events it has already flushed to each path, so incremental flushes do
        not duplicate lines while independent recorders can safely append to
        the same file.
        """

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        start = self._flushed_counts.get(target, 0)
        pending = self.events[start:]
        # Opening in append mode even for an empty recorder creates the
        # requested JSONL artifact and preserves any existing contents.
        with target.open("a", encoding="utf-8") as stream:
            for event in pending:
                line = json.dumps(
                    event.model_dump(mode="json"),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.write(f"{line}\n")
        self._flushed_counts[target] = len(self.events)
        return target

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        skip_corrupt: bool = False,
        skip_and_record: bool | None = None,
        errors: list[TrajectoryLoadError] | None = None,
    ) -> list[TrajectoryEvent]:
        """Load and validate every event in a JSONL file.

        Corrupt lines raise :class:`TrajectoryLoadError` by default.  The
        optional skip mode continues after a bad line and records the error in
        the supplied ``errors`` list when one is provided.  The alias
        ``skip_and_record`` makes the opt-in behavior explicit for callers.
        """

        if skip_and_record is not None:
            skip_corrupt = skip_and_record

        target = Path(path)
        loaded: list[TrajectoryEvent] = []
        with target.open(encoding="utf-8") as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                try:
                    value = json.loads(raw_line)
                    if not isinstance(value, Mapping):
                        raise TypeError("JSONL event must be a JSON object")
                    loaded.append(TrajectoryEvent.model_validate(value))
                except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as error:
                    load_error = error
                    if not isinstance(error, TrajectoryLoadError):
                        wrapped = TrajectoryLoadError(line_number, str(error))
                    else:
                        wrapped = error
                    if skip_corrupt:
                        if errors is not None:
                            errors.append(wrapped)
                        continue
                    raise wrapped from load_error
        return loaded

    def __len__(self) -> int:
        """Return the number of recorded events."""

        return len(self.events)

    def __iter__(self):
        """Iterate over recorded events in append order."""

        return iter(self.events)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat()


__all__ = ["TrajectoryLoadError", "TrajectoryRecorder"]
