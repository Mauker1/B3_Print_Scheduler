# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a scheduled job is, and the vocabulary for how one ends.

A job reaches exactly one terminal state and carries the reason it got there. That is the whole
point of the type: a scheduler that starts prints while nobody is watching has to be able to answer
"why did this not run" hours after the fact, and a boolean cannot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# The printer's gcode parser decides both of these, and both are cheap to catch when the job is
# created rather than at the moment it was supposed to start. Non-ASCII is deliberately absent:
# `M118 顶盖前靴` echoed back intact on the hardware, and this printer ships files with Chinese
# names, so refusing them would be wrong.
UNSTARTABLE_CHARACTERS = {
    "#": "the gcode parser treats it as the start of a comment, so the name would be truncated",
    '"': "the name is passed as a quoted gcode parameter, which a double quote would end early",
}


class JobState(str, Enum):
    """Where a job is. SCHEDULED is the only state it can leave."""

    SCHEDULED = "scheduled"
    STARTED = "started"
    CANCELLED = "cancelled"


class Refusal(str, Enum):
    """Why a job did not start.

    Every value here is a row of the table in `plugin/doc/README.md`, and the tests cover one case
    per value, so a new way to refuse cannot be added without both of those noticing.
    """

    PRINTER_BUSY = "printer-busy"
    BED_NOT_CLEARED = "bed-not-cleared"
    PRINTER_IN_ERROR = "printer-in-error"
    PRINTER_UNREACHABLE = "printer-unreachable"
    KLIPPER_NOT_READY = "klipper-not-ready"
    MISSED = "missed"
    FILE_GONE = "file-gone"
    FILENAME_NOT_STARTABLE = "filename-not-startable"
    START_REFUSED = "start-refused"
    CANCELLED_BY_YOU = "cancelled-by-you"


@dataclass(frozen=True)
class Attempt:
    """One pass over a job that did not settle it, kept so a retry loop is visible afterwards."""

    at: float
    detail: str


@dataclass(frozen=True)
class Job:
    """One scheduled print.

    `start_at` is an absolute instant in epoch seconds and is the only field the scheduler compares
    against. `typed_time` and `timezone_name` are what the person actually chose, kept for the log
    and the page so a confusing outcome can be explained rather than guessed at. The printer this
    was written against runs on UTC while its owner does not.
    """

    job_id: str
    filename: str
    start_at: float
    typed_time: str = ""
    timezone_name: str = ""
    bed_acknowledged: bool = False
    level_bed: bool | None = None
    record_timelapse: bool | None = None
    state: JobState = JobState.SCHEDULED
    refusal: Refusal | None = None
    detail: str = ""
    decided_at: float | None = None
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Render for the schedule file and for the JSON endpoints."""
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "start_at": self.start_at,
            "typed_time": self.typed_time,
            "timezone_name": self.timezone_name,
            "bed_acknowledged": self.bed_acknowledged,
            "level_bed": self.level_bed,
            "record_timelapse": self.record_timelapse,
            "state": self.state.value,
            "refusal": None if self.refusal is None else self.refusal.value,
            "detail": self.detail,
            "decided_at": self.decided_at,
            "attempts": [{"at": attempt.at, "detail": attempt.detail} for attempt in self.attempts],
        }


def job_from_dict(payload: dict[str, Any]) -> Job:
    """Rebuild a job from the schedule file."""
    refusal = payload.get("refusal")
    return Job(
        job_id=str(payload["job_id"]),
        filename=str(payload["filename"]),
        start_at=float(payload["start_at"]),
        typed_time=str(payload.get("typed_time", "")),
        timezone_name=str(payload.get("timezone_name", "")),
        bed_acknowledged=bool(payload.get("bed_acknowledged", False)),
        level_bed=payload.get("level_bed"),
        record_timelapse=payload.get("record_timelapse"),
        state=JobState(payload.get("state", JobState.SCHEDULED.value)),
        refusal=None if refusal is None else Refusal(refusal),
        detail=str(payload.get("detail", "")),
        decided_at=payload.get("decided_at"),
        attempts=tuple(
            Attempt(at=float(entry["at"]), detail=str(entry["detail"]))
            for entry in payload.get("attempts", [])
        ),
    )


def new_job_id() -> str:
    """A job identifier that survives a restart and never collides with an existing one."""
    return uuid.uuid4().hex


def reason_filename_cannot_start(filename: str) -> str | None:
    """Return why this name cannot be handed to the printer, or None when it can."""
    if not filename.strip():
        return "the filename is empty"
    for character, why in UNSTARTABLE_CHARACTERS.items():
        if character in filename:
            return f"the name contains {character}, and {why}"
    return None
