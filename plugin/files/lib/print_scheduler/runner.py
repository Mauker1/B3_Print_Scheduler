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

from print_scheduler.gcode_files import tools_used
from print_scheduler.history import find_our_print, last_print_ended_at
from print_scheduler.jobs import Attempt, Job, JobState, Refusal, reason_filename_cannot_start
from print_scheduler.printer import (
    KLIPPER_READY,
    KLIPPER_STARTING_STATES,
    PRINT_STATE_ERROR,
    RUNNING_PRINT_STATES,
    STATES_MEANING_OUR_PRINT_RAN,
    UNCLEARED_BED_STATES,
    LoadedFilament,
    Printer,
    PrinterSnapshot,
    PrintRecord,
    StartRefusedError,
)
from print_scheduler.tool_mapping import ToolPlan, plan_tools

SECONDS_PER_MINUTE = 60

# How long a start is given to show up before we conclude it did not take. The printer
# reports `printing` from the moment it begins parsing the file, so this is generous; it is
# wide enough that a slow accept or a tick landing awkwardly cannot produce a false alarm.
START_CONFIRMATION_SECONDS = 60.0


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
class PrinterAsSeen:
    """One look at the printer, shared by everything this tick has to settle."""

    snapshot: PrinterSnapshot
    recent_prints: tuple[PrintRecord, ...] = ()


@dataclass(frozen=True)
class Moment:
    """One job, and everything the rules may look at, as of one instant."""

    job: Job
    printer: PrinterSnapshot
    gcode_filenames: frozenset[str]
    now: float
    tolerance_seconds: float
    # Which toolhead each of the file's slots will run on, worked out now rather than when
    # the job was scheduled, because a spool can be changed overnight.
    tool_plan: ToolPlan = ToolPlan(applicable=False)
    # When the printer's most recent print ended. None when it keeps no record.
    last_print_ended_at: float | None = None
    # Whether this printer is started by a gcode command rather than by Moonraker's own print
    # start. It decides which filenames are startable, and nothing else here.
    starts_by_gcode: bool = True


Rule = Callable[[Moment], Decision | None]

ANOTHER_JOB_STARTED = Decision(
    Action.CANCEL,
    Refusal.PRINTER_BUSY,
    "another scheduled job started in the same tick",
)


def _said_plainly(seconds: float) -> str:
    """A duration in the largest unit that does not round it away.

    Flooring to whole minutes was the whole of this, which reported anything under a minute as
    "0 minutes" and produced "its time passed 0 minutes ago, beyond a tolerance of 0 minutes"
    for a job cancelled seven seconds late. A reason that reads as nonsense is worse than no
    reason at all, because it sends the reader looking for a bug in the plugin rather than at
    the setting they typed.
    """
    if seconds < SECONDS_PER_MINUTE:
        whole = int(seconds)
        return f"{whole} second" if whole == 1 else f"{whole} seconds"
    minutes = int(seconds // SECONDS_PER_MINUTE)
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def _too_late(moment: Moment) -> Decision | None:
    lateness = moment.now - moment.job.start_at
    if lateness <= moment.tolerance_seconds:
        return None
    return Decision(
        Action.CANCEL,
        Refusal.MISSED,
        f"its time passed {_said_plainly(lateness)} ago, beyond a tolerance of "
        f"{_said_plainly(moment.tolerance_seconds)}",
    )


def _filename_cannot_be_started(moment: Moment) -> Decision | None:
    problem = reason_filename_cannot_start(moment.job.filename, moment.starts_by_gcode)
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


# Each running state, said the way a person would say it. Without this, one phrasing has to
# cover both and "the printer was busy paused foo.gcode" is what that looks like.
BUSY_WITH = {"printing": "printing", "paused": "paused on"}


def _a_print_is_running(moment: Moment) -> Decision | None:
    if moment.printer.print_state not in RUNNING_PRINT_STATES:
        return None
    running = moment.printer.printing_filename or "another job"
    # Says what happened and stops. Why a busy printer is never waited for belongs in the
    # docstring above and in the README, not in the line somebody reads at six in the morning
    # wanting to know why their print did not run.
    was = BUSY_WITH.get(moment.printer.print_state, "busy with")
    return Decision(Action.CANCEL, Refusal.PRINTER_BUSY, f"the printer was {was} {running}")


def _the_bed_was_not_cleared(moment: Moment) -> Decision | None:
    if moment.printer.print_state not in UNCLEARED_BED_STATES:
        return None
    if _the_promise_already_covered_this(moment):
        return None
    return Decision(Action.CANCEL, Refusal.BED_NOT_CLEARED, _why_the_bed_is_suspect(moment))


def _the_promise_already_covered_this(moment: Moment) -> bool:
    """Whether the printer was already saying this when the bed was promised clear.

    The promise is made when the job is scheduled, so a state you could see at that moment is
    one you promised in spite of. Blocking on it anyway means a single cancelled print stops
    the scheduler forever, because `cancelled` never clears itself. A state that arrived
    afterwards is a different thing: you could not have known, so it wins.
    """
    ended = moment.last_print_ended_at
    return ended is not None and moment.job.created_at > 0 and ended <= moment.job.created_at


def _why_the_bed_is_suspect(moment: Moment) -> str:
    state = moment.printer.print_state
    if moment.last_print_ended_at is None or moment.job.created_at <= 0:
        return (
            f"the printer reports the previous print as {state} and gives no usable record of "
            "when it ended, so there is no telling whether that happened after you promised "
            "the bed would be clear. Dismiss the last print on the printer, then reschedule."
        )
    return (
        f"a print was {state} after you scheduled this, so there may be something on the bed "
        "that you could not have known about when you promised it would be clear."
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


def _no_toolhead_for_the_material(moment: Moment) -> Decision | None:
    if moment.tool_plan.problem is None:
        return None
    return Decision(
        Action.CANCEL, Refusal.NO_TOOLHEAD_FOR_THE_MATERIAL, moment.tool_plan.problem
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
    # After the file check: a file that is gone has no materials to match.
    _no_toolhead_for_the_material,
)


def decide(moment: Moment) -> Decision:
    """Apply the rules in order and return the first that has something to say."""
    for rule in DECISION_RULES:
        decision = rule(moment)
        if decision is not None:
            return decision
    return Decision(Action.START)


def is_due(job: Job, now: float) -> bool:
    """Whether the tick should consider this job at all.

    A held job is never due, however far past its time it is. It is waiting on a person, and
    the rules below would otherwise cancel it as missed the moment the tolerance ran out,
    which would answer the question on the person's behalf by letting the promise expire. Once
    released it meets those rules like any other job, and a released job whose moment has gone
    is cancelled as missed with the reason said out loud.
    """
    return not job.held and job.state is JobState.SCHEDULED and job.start_at <= now


def run_tick(
    jobs: Sequence[Job], printer: Printer, now: float, tolerance_seconds: float
) -> list[Job]:
    """Settle what has come due, confirm what was started, and return the whole schedule."""
    due = [job for job in jobs if is_due(job, now)]
    awaiting = [job for job in jobs if job.state is JobState.STARTING]
    if not due and not awaiting:
        return list(jobs)

    seen = PrinterAsSeen(printer.snapshot(), _recent_prints(printer))
    settled = {job.job_id: _confirm(job, seen, now) for job in awaiting}
    settled.update(_settle_due(due, printer, seen, now, tolerance_seconds))
    return [settled.get(job.job_id, job) for job in jobs]


def _settle_due(
    due: Sequence[Job],
    printer: Printer,
    seen: PrinterAsSeen,
    now: float,
    tolerance_seconds: float,
) -> dict[str, Job]:
    if not due:
        return {}
    snapshot, filenames = _with_the_file_listing(printer, seen.snapshot)
    settled: dict[str, Job] = {}
    already_started = False
    loaded = _loaded_filaments(printer)
    ended = last_print_ended_at(seen.recent_prints)
    by_gcode = _starts_by_gcode(printer)
    for job in due:
        moment = Moment(
            job,
            snapshot,
            filenames,
            now,
            tolerance_seconds,
            _plan_the_toolheads(printer, job, loaded),
            ended,
            by_gcode,
        )
        decision = ANOTHER_JOB_STARTED if already_started else decide(moment)
        updated = _carry_out(decision, moment, printer)
        already_started = already_started or updated.state is JobState.STARTING
        settled[job.job_id] = updated
    return settled


def _starts_by_gcode(printer: Printer) -> bool:
    """Asked again at the moment of starting, not carried from when the job was scheduled.

    A printer that cannot be asked is assumed to be started by gcode, which is the stricter
    answer: it refuses a name rather than sending one the parser would truncate.
    """
    try:
        return printer.supports_print_preferences()
    except OSError:
        return True


def _confirm(job: Job, seen: PrinterAsSeen, now: float) -> Job:
    """Decide whether a start we made actually took effect."""
    ours = find_our_print(job, seen.recent_prints)
    if ours is not None:
        return _confirmed(job, now, ours.job_id, f"the printer recorded it as job {ours.job_id}")
    if _the_printer_is_running_our_file(job, seen.snapshot):
        return _confirmed(job, now, "", "the printer is running it, with no history entry yet")
    waited_for = now - (job.decided_at or now)
    if waited_for <= START_CONFIRMATION_SECONDS:
        return _waited(job, now, Decision(Action.WAIT, Refusal.START_DID_NOT_TAKE,
                                          "the start has not shown up on the printer yet"))
    return _cancelled(job, now, Decision(
        Action.CANCEL,
        Refusal.START_DID_NOT_TAKE,
        f"the printer accepted the start and then did not run it within "
        f"{_said_plainly(START_CONFIRMATION_SECONDS)}",
    ))


def _the_printer_is_running_our_file(job: Job, snapshot: PrinterSnapshot) -> bool:
    return (
        snapshot.reachable
        and snapshot.print_state in STATES_MEANING_OUR_PRINT_RAN
        and snapshot.printing_filename == job.filename
    )


def _loaded_filaments(printer: Printer) -> tuple[LoadedFilament, ...]:
    try:
        return printer.loaded_filaments()
    except OSError:
        # Read as a printer that does not track what is loaded, which means no map to make
        # and no map to get wrong. It cannot silently produce a wrong assignment.
        return ()


def _plan_the_toolheads(
    printer: Printer, job: Job, loaded: Sequence[LoadedFilament]
) -> ToolPlan:
    if not loaded:
        return ToolPlan(applicable=False)
    try:
        metadata = printer.file_metadata(job.filename)
    except OSError:
        # The file check runs before this rule, so a file that is simply gone is already
        # settled. Anything else unreadable leaves us unable to say what it needs.
        return ToolPlan(problem=f"the printer could not describe {job.filename}")
    return plan_tools(tools_used(metadata), loaded)


def _recent_prints(printer: Printer) -> tuple[PrintRecord, ...]:
    try:
        return printer.recent_prints()
    except OSError:
        # No history is not evidence that the start failed, so the caller falls through to
        # the live state and then to the confirmation window.
        return ()


def _with_the_file_listing(
    printer: Printer, snapshot: PrinterSnapshot
) -> tuple[PrinterSnapshot, frozenset[str]]:
    if not snapshot.reachable:
        return snapshot, frozenset()
    try:
        return snapshot, printer.gcode_filenames()
    except OSError as unreachable:
        # The state query answered and the file listing did not. Treat the printer as
        # unreachable rather than as one whose files have all vanished, which would cancel
        # every pending job at once.
        return PrinterSnapshot(reachable=False, klipper_message=str(unreachable)), frozenset()


def _carry_out(decision: Decision, moment: Moment, printer: Printer) -> Job:
    if decision.action is Action.WAIT:
        return _waited(moment.job, moment.now, decision)
    if decision.action is Action.CANCEL:
        return _cancelled(moment.job, moment.now, decision)
    return _started(moment, printer)


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


def _started(moment: Moment, printer: Printer) -> Job:
    job, now = moment.job, moment.now
    try:
        printer.start_print(
            job.filename,
            job.level_bed,
            job.record_timelapse,
            moment.tool_plan.as_pairs(),
        )
    except StartRefusedError as refused:
        return _cancelled(
            job, now, Decision(Action.CANCEL, Refusal.START_REFUSED, str(refused))
        )
    # STARTING, not STARTED: the printer said yes, and whether it meant it is the next
    # tick's question.
    return replace(
        job,
        state=JobState.STARTING,
        decided_at=now,
        attempts=job.attempts + (Attempt(now, _what_was_asked_for(moment)),),
    )


def _what_was_asked_for(moment: Moment) -> str:
    assignments = moment.tool_plan.assignments
    if not assignments:
        return "the printer accepted the start"
    mapping = ", ".join(
        f"slot {one.slot} on T{one.toolhead} ({one.filament_type})" for one in assignments
    )
    return f"the printer accepted the start, {mapping}"


def _confirmed(job: Job, now: float, printer_job_id: str, detail: str) -> Job:
    return replace(
        job,
        state=JobState.STARTED,
        printer_job_id=printer_job_id,
        attempts=job.attempts + (Attempt(now, detail),),
    )


def cancel_by_hand(job: Job, now: float) -> Job:
    """Cancel a pending job because the person asked, which is not a refusal by the printer."""
    return _cancelled(
        job, now, Decision(Action.CANCEL, Refusal.CANCELLED_BY_YOU, "you cancelled it")
    )
