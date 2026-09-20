# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tick: what is due, whether it may start, and what to record when it may not.

The rules are a list rather than a chain of conditionals, in the order they are checked, because
that order is the design. Reading the tuple below should tell you what the scheduler will do
without reading any of the functions.

Two of them deserve their own sentence.

A print already running cancels the job outright. It occupies the printer for hours, and starting
someone's print that much later, unattended, is a surprise that moves a hot nozzle.

Other gcode activity, a calibration someone started by hand, only waits. It is a matter of minutes,
so it gets the retry budget the tolerance exists for, and it cancels when that runs out like any
other transient condition.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import Enum

from print_scheduler.jobs import Attempt, Job, JobState, Refusal, reason_filename_cannot_start
from print_scheduler.printer import (
    KLIPPER_READY,
    KLIPPER_STARTING_STATES,
    PRINT_STATE_ERROR,
    RUNNING_PRINT_STATES,
    UNCLEARED_BED_STATES,
    Printer,
    PrinterSnapshot,
    StartRefusedError,
)

SECONDS_PER_MINUTE = 60


class Action(str, Enum):
    """What the tick does with a job."""

    START = "start"
    WAIT = "wait"
    CANCEL = "cancel"


@dataclass(frozen=True)
class Decision:
    """What to do, and the reason, which is recorded whether or not the job ends here."""

    action: Action
    refusal: Refusal | None = None
    detail: str = ""


@dataclass(frozen=True)
class Moment:
    """One job, and everything the rules may look at, as of one instant."""

    job: Job
    printer: PrinterSnapshot
    gcode_filenames: frozenset[str]
    now: float
    tolerance_seconds: float


Rule = Callable[[Moment], Decision | None]

ANOTHER_JOB_STARTED = Decision(
    Action.CANCEL,
    Refusal.PRINTER_BUSY,
    "another scheduled job started in the same tick",
)


def _in_minutes(seconds: float) -> int:
    return int(seconds // SECONDS_PER_MINUTE)


def _too_late(moment: Moment) -> Decision | None:
    lateness = moment.now - moment.job.start_at
    if lateness <= moment.tolerance_seconds:
        return None
    return Decision(
        Action.CANCEL,
        Refusal.MISSED,
        f"its time passed {_in_minutes(lateness)} minutes ago, beyond the "
        f"{_in_minutes(moment.tolerance_seconds)} minute tolerance. A job that came due while the "
        "printer was off meets this on the way back up, which is deliberate.",
    )


def _filename_cannot_be_started(moment: Moment) -> Decision | None:
    problem = reason_filename_cannot_start(moment.job.filename)
    if problem is None:
        return None
    return Decision(Action.CANCEL, Refusal.FILENAME_NOT_STARTABLE, problem)


def _printer_unreachable(moment: Moment) -> Decision | None:
    if moment.printer.reachable:
        return None
    return Decision(
        Action.WAIT,
        Refusal.PRINTER_UNREACHABLE,
        f"the printer did not answer: {moment.printer.klipper_message}",
    )


def _klipper_is_still_starting(moment: Moment) -> Decision | None:
    if moment.printer.klipper_state not in KLIPPER_STARTING_STATES:
        return None
    return Decision(
        Action.WAIT,
        Refusal.KLIPPER_NOT_READY,
        f"klipper reports {moment.printer.klipper_state}: {moment.printer.klipper_message}",
    )


def _klipper_is_not_ready(moment: Moment) -> Decision | None:
    if moment.printer.klipper_state == KLIPPER_READY:
        return None
    # Anything left is shutdown, error, or a state we do not recognise. None of those
    # resolve on their own, so waiting would only replace this reason with "missed".
    return Decision(
        Action.CANCEL,
        Refusal.PRINTER_IN_ERROR,
        f"klipper reports {moment.printer.klipper_state}: {moment.printer.klipper_message}",
    )


def _a_print_is_running(moment: Moment) -> Decision | None:
    if moment.printer.print_state not in RUNNING_PRINT_STATES:
        return None
    running = moment.printer.printing_filename or "another job"
    return Decision(
        Action.CANCEL,
        Refusal.PRINTER_BUSY,
        f"the printer was {moment.printer.print_state} {running}. A busy printer is never waited "
        "for: starting this hours late, unattended, would be worse than not starting it.",
    )


def _the_bed_was_not_cleared(moment: Moment) -> Decision | None:
    if moment.printer.print_state not in UNCLEARED_BED_STATES:
        return None
    return Decision(
        Action.CANCEL,
        Refusal.BED_NOT_CLEARED,
        f"the printer still reports the previous print as {moment.printer.print_state}, so the bed "
        "is presumed to be occupied. Clear it and dismiss the finished print on the screen.",
    )


def _the_printer_is_in_error(moment: Moment) -> Decision | None:
    if moment.printer.print_state != PRINT_STATE_ERROR:
        return None
    return Decision(Action.CANCEL, Refusal.PRINTER_IN_ERROR, moment.printer.klipper_message)


def _other_gcode_is_running(moment: Moment) -> Decision | None:
    if not moment.printer.other_gcode_running:
        return None
    return Decision(
        Action.WAIT,
        Refusal.PRINTER_BUSY,
        "something other than a print is running on the printer",
    )


def _the_file_is_gone(moment: Moment) -> Decision | None:
    if moment.job.filename in moment.gcode_filenames:
        return None
    return Decision(
        Action.CANCEL,
        Refusal.FILE_GONE,
        f"{moment.job.filename} is no longer on the printer",
    )


# The order is the design. Lateness first, because a job whose moment has passed must not start
# however healthy the printer looks. The two cheap local checks next, then the printer, from
# "cannot be asked" through "must not be disturbed" to "can, but the file went away".
DECISION_RULES: tuple[Rule, ...] = (
    _too_late,
    _filename_cannot_be_started,
    _printer_unreachable,
    _klipper_is_still_starting,
    _klipper_is_not_ready,
    _a_print_is_running,
    _the_bed_was_not_cleared,
    _the_printer_is_in_error,
    _other_gcode_is_running,
    _the_file_is_gone,
)


def decide(moment: Moment) -> Decision:
    """Apply the rules in order and return the first that has something to say."""
    for rule in DECISION_RULES:
        decision = rule(moment)
        if decision is not None:
            return decision
    return Decision(Action.START)


def is_due(job: Job, now: float) -> bool:
    """Whether the tick should consider this job at all."""
    return job.state is JobState.SCHEDULED and job.start_at <= now


def run_tick(
    jobs: Sequence[Job], printer: Printer, now: float, tolerance_seconds: float
) -> list[Job]:
    """Settle every job that has come due, and return the whole schedule as it now stands."""
    due = [job for job in jobs if is_due(job, now)]
    if not due:
        return list(jobs)

    snapshot, filenames = _look_at_the_printer(printer)
    settled: dict[str, Job] = {}
    already_started = False
    for job in due:
        moment = Moment(job, snapshot, filenames, now, tolerance_seconds)
        decision = ANOTHER_JOB_STARTED if already_started else decide(moment)
        updated = _carry_out(decision, job, printer, now)
        already_started = already_started or updated.state is JobState.STARTED
        settled[job.job_id] = updated
    return [settled.get(job.job_id, job) for job in jobs]


def _look_at_the_printer(printer: Printer) -> tuple[PrinterSnapshot, frozenset[str]]:
    snapshot = printer.snapshot()
    if not snapshot.reachable:
        return snapshot, frozenset()
    try:
        return snapshot, printer.gcode_filenames()
    except OSError as unreachable:
        # The state query answered and the file listing did not. Treat the printer as unreachable
        # rather than as a printer whose files have all vanished, which would cancel every job.
        return PrinterSnapshot(reachable=False, klipper_message=str(unreachable)), frozenset()


def _carry_out(decision: Decision, job: Job, printer: Printer, now: float) -> Job:
    if decision.action is Action.WAIT:
        return _waited(job, now, decision)
    if decision.action is Action.CANCEL:
        return _cancelled(job, now, decision)
    return _started(job, printer, now)


def _waited(job: Job, now: float, decision: Decision) -> Job:
    return replace(job, attempts=job.attempts + (Attempt(now, decision.detail),))


def _cancelled(job: Job, now: float, decision: Decision) -> Job:
    return replace(
        job,
        state=JobState.CANCELLED,
        refusal=decision.refusal,
        detail=decision.detail,
        decided_at=now,
        attempts=job.attempts + (Attempt(now, decision.detail),),
    )


def _started(job: Job, printer: Printer, now: float) -> Job:
    try:
        printer.start_print(job.filename, job.level_bed, job.record_timelapse)
    except StartRefusedError as refused:
        return _cancelled(
            job, now, Decision(Action.CANCEL, Refusal.START_REFUSED, str(refused))
        )
    return replace(
        job,
        state=JobState.STARTED,
        decided_at=now,
        attempts=job.attempts + (Attempt(now, "started"),),
    )


def cancel_by_hand(job: Job, now: float) -> Job:
    """Cancel a pending job because the person asked, which is not a refusal by the printer."""
    return _cancelled(
        job, now, Decision(Action.CANCEL, Refusal.CANCELLED_BY_YOU, "you cancelled it")
    )
