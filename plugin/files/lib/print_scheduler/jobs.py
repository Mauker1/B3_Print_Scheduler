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

from print_scheduler.messages import Message, Said

# The printer's gcode parser decides both of these, and both are cheap to catch when the job is
# created rather than at the moment it was supposed to start. Non-ASCII is deliberately absent:
# `M118 顶盖前靴` echoed back intact on the hardware, and this printer ships files with Chinese
# names, so refusing them would be wrong.
#
# They apply only to a printer started by gcode. A printer without the parameterised start is
# sent its filename as a URL parameter instead, which takes both characters without complaint,
# so refusing them there would be refusing files the machine can print.
UNSTARTABLE_CHARACTERS = {
    "#": Message.FILENAME_HAS_HASH,
    '"': Message.FILENAME_HAS_QUOTE,
}


class JobState(str, Enum):
    """Where a job is.

    STARTING means the printer accepted the start and we have not yet seen it take effect.
    A command that answers "ok" and then does nothing is the failure this state exists to
    catch, and it is the one nobody notices until the morning.
    """

    SCHEDULED = "scheduled"
    STARTING = "starting"
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
    START_DID_NOT_TAKE = "start-did-not-take"
    NO_TOOLHEAD_FOR_THE_MATERIAL = "no-toolhead-for-the-material"
    CANCELLED_BY_YOU = "cancelled-by-you"


class HoldReason(str, Enum):
    """Why a waiting job is not being considered, which decides what releases it.

    A hold is a question for a person, and the questions are different. After a long silence
    the question is whether the schedule as a whole still says what somebody wants, so one answer
    releases every job held for it. When the printer still shows a finished print the question
    is whether this bed is clear for this job, so each job has its own answer, and that answer
    starts it. The two about toolheads are per job too: whether the map somebody saw still
    describes what is loaded, and, for a job scheduled before maps were recorded, whether the
    map is right at all.
    """

    LONG_SILENCE = "long-silence"
    BED_NOT_CONFIRMED = "bed-not-confirmed"
    TOOLHEADS_CHANGED = "toolheads-changed"
    MAP_NOT_CONFIRMED = "map-not-confirmed"


# The holds a person answers by accepting a toolhead map.
TOOLHEAD_HOLDS = frozenset({HoldReason.TOOLHEADS_CHANGED, HoldReason.MAP_NOT_CONFIRMED})

# What an older version is told a hold is, when it reads a schedule this one wrote. 0.4.1 reads
# the `hold` key and treats a value it does not know as an unreadable schedule, which sets the
# whole file aside and starts empty. So `hold` only ever carries a reason 0.4.1 knows, the
# nearest one, and the real reason goes under a key it never reads. Each stand in keeps the job
# held there and asks a person before it starts, which is the part that matters.
UNDERSTOOD_BY_0_4_1 = {
    HoldReason.LONG_SILENCE: HoldReason.LONG_SILENCE,
    HoldReason.BED_NOT_CONFIRMED: HoldReason.BED_NOT_CONFIRMED,
    HoldReason.TOOLHEADS_CHANGED: HoldReason.BED_NOT_CONFIRMED,
    HoldReason.MAP_NOT_CONFIRMED: HoldReason.LONG_SILENCE,
}


@dataclass(frozen=True)
class SeenToolhead:
    """One slot, the toolhead it was given, and what that toolhead held when somebody saw it.

    This is the record a job starts on. What is loaded is compared against it at the moment of
    starting, and a job whose toolheads no longer hold what somebody saw is held rather than
    started, because the map it would print with is one nobody has looked at.
    """

    slot: int
    toolhead: int
    material: str
    # Six hex digits, or empty when the printer did not say.
    colour: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "toolhead": self.toolhead,
            "material": self.material,
            "colour": self.colour,
        }


def seen_toolhead_from_dict(payload: dict[str, Any]) -> SeenToolhead:
    return SeenToolhead(
        slot=int(payload["slot"]),
        toolhead=int(payload["toolhead"]),
        material=str(payload.get("material", "")),
        colour=str(payload.get("colour", "")),
    )


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
    # When the bed was promised clear. The printer's own 'a print ended and nobody
    # acknowledged it' states are only a warning about what changed after that moment: a
    # state you could see when you promised is a state you promised in spite of.
    created_at: float = 0.0
    typed_time: str = ""
    timezone_name: str = ""
    bed_acknowledged: bool = False
    level_bed: bool | None = None
    record_timelapse: bool | None = None
    # The slicer's estimate, taken once when the job was created. It is what the page uses
    # to project a finish time and to warn about two jobs running into each other, so it is
    # kept rather than looked up: a listing should not need one metadata read per job.
    estimated_seconds: float = 0.0
    state: JobState = JobState.SCHEDULED
    refusal: Refusal | None = None
    # `detail` is the English sentence, written when the job settled. `detail_key` and
    # `detail_values` are the same thing unrendered, so a reader gets it in their own language
    # and a rewording reaches rows that settled before it. A row written before this existed
    # has no key and renders from `detail` forever, which is why there is no migration.
    detail: str = ""
    detail_key: str = ""
    detail_values: dict[str, Any] = field(default_factory=dict)
    decided_at: float | None = None
    # The printer's own id for the print this job started, captured once the printer
    # confirms it. It is how the page asks the printer what became of the print, and it is
    # deliberately the only thing we keep about that: the outcome is the printer's claim, so
    # it is looked up when someone asks rather than copied into our own record.
    printer_job_id: str = ""
    # Why this job is waiting on a person, or None when it is not. A held job is not considered
    # by the tick at all, not even for lateness: it is a question nobody has answered yet, and
    # the tick would otherwise answer it on the person's behalf by letting the time run out.
    hold: HoldReason | None = None
    # When the hold began, so the page can say what the printer showed and when, even after
    # the reason has gone away. A job held for the bed does not start by itself once the bed
    # is dismissed, and a job that does not start with no reason on screen reads as a bug.
    held_at: float | None = None
    # What exactly the hold is about, unrendered like `detail_key`: which toolhead changed, and
    # from what to what. Empty when the reason says it all.
    hold_detail_key: str = ""
    hold_detail_values: dict[str, Any] = field(default_factory=dict)
    # The slot to toolhead pairs the person chose on the form, or None when the scheduler chose.
    # Kept so that Edit and "Schedule another like this" carry the choice, and so the row can
    # say whose choice it was. It is not what the job starts on; `toolheads_seen` is.
    toolheads_chosen: tuple[tuple[int, int], ...] | None = None
    # The map somebody saw and accepted, with what each toolhead held at that moment. None means
    # it was never recorded, which is every job scheduled before 0.5.0. An empty tuple means it
    # was recorded and there was nothing to map, on a printer that does not report what is
    # loaded. The two are different on purpose: the first is a question, the second an answer.
    toolheads_seen: tuple[SeenToolhead, ...] | None = None
    # The slicer's grams per slot, taken when the job was scheduled like the time estimate, so
    # the waiting row can say whether a spool has enough left without reading the file again.
    # Empty for a job scheduled before 0.6.0, which then simply says nothing about it.
    slot_grams: tuple[tuple[int, float], ...] = ()
    attempts: tuple[Attempt, ...] = field(default_factory=tuple)

    @property
    def held(self) -> bool:
        return self.hold is not None

    def to_dict(self) -> dict[str, Any]:
        """Render for the schedule file and for the JSON endpoints."""
        return {
            "job_id": self.job_id,
            "filename": self.filename,
            "start_at": self.start_at,
            "created_at": self.created_at,
            "typed_time": self.typed_time,
            "timezone_name": self.timezone_name,
            "bed_acknowledged": self.bed_acknowledged,
            "level_bed": self.level_bed,
            "record_timelapse": self.record_timelapse,
            "estimated_seconds": self.estimated_seconds,
            "state": self.state.value,
            "refusal": None if self.refusal is None else self.refusal.value,
            "detail": self.detail,
            "detail_key": self.detail_key,
            "detail_values": self.detail_values,
            "decided_at": self.decided_at,
            "printer_job_id": self.printer_job_id,
            # Written beside the reason so that a schedule saved by this version still reads
            # correctly in 0.3.0, which knew only the flag.
            "held": self.held,
            # For 0.4.1, which knows two reasons and sets the whole schedule aside on a third.
            # See UNDERSTOOD_BY_0_4_1. Nothing from 0.5.0 on reads it when the next key is there.
            "hold": None if self.hold is None else UNDERSTOOD_BY_0_4_1[self.hold].value,
            "hold_reason": None if self.hold is None else self.hold.value,
            "held_at": self.held_at,
            "hold_detail_key": self.hold_detail_key,
            "hold_detail_values": self.hold_detail_values,
            "toolheads_chosen": None
            if self.toolheads_chosen is None
            else [[slot, toolhead] for slot, toolhead in self.toolheads_chosen],
            "toolheads_seen": None
            if self.toolheads_seen is None
            else [one.to_dict() for one in self.toolheads_seen],
            "slot_grams": [[slot, grams] for slot, grams in self.slot_grams],
            "attempts": [{"at": attempt.at, "detail": attempt.detail} for attempt in self.attempts],
        }


def job_from_dict(payload: dict[str, Any]) -> Job:
    """Rebuild a job from the schedule file."""
    refusal = payload.get("refusal")
    return Job(
        job_id=str(payload["job_id"]),
        filename=str(payload["filename"]),
        start_at=float(payload["start_at"]),
        created_at=float(payload.get("created_at", 0.0)),
        typed_time=str(payload.get("typed_time", "")),
        timezone_name=str(payload.get("timezone_name", "")),
        bed_acknowledged=bool(payload.get("bed_acknowledged", False)),
        level_bed=payload.get("level_bed"),
        record_timelapse=payload.get("record_timelapse"),
        estimated_seconds=float(payload.get("estimated_seconds", 0.0)),
        state=JobState(payload.get("state", JobState.SCHEDULED.value)),
        refusal=None if refusal is None else Refusal(refusal),
        detail=str(payload.get("detail", "")),
        detail_key=str(payload.get("detail_key", "")),
        detail_values=dict(payload.get("detail_values") or {}),
        decided_at=payload.get("decided_at"),
        printer_job_id=str(payload.get("printer_job_id", "")),
        hold=_hold_from(payload),
        held_at=payload.get("held_at"),
        hold_detail_key=str(payload.get("hold_detail_key", "")),
        hold_detail_values=dict(payload.get("hold_detail_values") or {}),
        toolheads_chosen=_pairs_from(payload.get("toolheads_chosen")),
        toolheads_seen=None
        if payload.get("toolheads_seen") is None
        else tuple(seen_toolhead_from_dict(one) for one in payload["toolheads_seen"]),
        slot_grams=tuple(
            (int(slot), float(grams)) for slot, grams in payload.get("slot_grams") or []
        ),
        attempts=tuple(
            Attempt(at=float(entry["at"]), detail=str(entry["detail"]))
            for entry in payload.get("attempts", [])
        ),
    )


def _hold_from(payload: dict[str, Any]) -> HoldReason | None:
    """The hold, including one written by an older version or a newer one.

    The real reason first, then the key 0.4.1 wrote, then the flag 0.3.0 wrote, which only a
    long silence could set. A reason this version has never heard of, written by a later one,
    is still a hold: it falls back to the older key, and failing that is read as the one that
    asks the broadest question. Never as an unreadable schedule, which would set every job
    aside to answer a question about one.
    """
    stated = [payload.get(key) for key in ("hold_reason", "hold")]
    for value in stated:
        if value is not None:
            try:
                return HoldReason(value)
            except ValueError:
                continue
    if any(value is not None for value in stated) or payload.get("held"):
        return HoldReason.LONG_SILENCE
    return None


def _pairs_from(value: Any) -> tuple[tuple[int, int], ...] | None:
    if value is None:
        return None
    return tuple((int(slot), int(toolhead)) for slot, toolhead in value)


def new_job_id() -> str:
    """A job identifier that survives a restart and never collides with an existing one."""
    return uuid.uuid4().hex


def reason_filename_cannot_start(filename: str, starts_by_gcode: bool = True) -> Said | None:
    """Return why this name cannot be handed to this printer, or None when it can.

    `starts_by_gcode` says whether the start goes out as a gcode command. It defaults to the
    strict answer, so a caller that has not thought about it refuses more rather than less.
    """
    if not filename.strip():
        return Said(Message.FILENAME_EMPTY)
    if not starts_by_gcode:
        return None
    for character, why in UNSTARTABLE_CHARACTERS.items():
        if character in filename:
            return Said(why)
    return None


# A job's state said as a word, which is ours rather than the printer's and so is translated.
STATE_WORDS = {
    JobState.SCHEDULED: Message.STATE_SCHEDULED,
    JobState.STARTING: Message.STATE_STARTING,
    JobState.STARTED: Message.STATE_STARTED,
    JobState.CANCELLED: Message.STATE_CANCELLED,
}


def said_state(state: JobState) -> Said:
    """The state as a word a person reads, for the sentences that name one."""
    return Said(STATE_WORDS[state])
