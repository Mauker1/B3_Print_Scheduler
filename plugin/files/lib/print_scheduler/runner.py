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
from print_scheduler.history import find_our_print
from print_scheduler.jobs import (
    Attempt,
    HoldReason,
    Job,
    JobState,
    Refusal,
    reason_filename_cannot_start,
)
from print_scheduler.messages import Message, Said, a_duration
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
    # Neither started nor cancelled: set aside for a person to answer. A held job is not
    # considered by the tick again until somebody does.
    HOLD = "hold"


@dataclass(frozen=True)
class Decision:
    """What to do, and the reason, which is recorded whether or not the job ends here.

    The reason is a key and its values rather than a sentence, so the row it settles can be
    read in any language, today or after the wording changes. `detail` is the English
    rendering, which is what the log keeps and what a reader falls back to.
    """

    action: Action
    refusal: Refusal | None = None
    said: Said | None = None

    @property
    def detail(self) -> str:
        return "" if self.said is None else self.said.in_english()


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
    # Whether this printer is started by a gcode command rather than by Moonraker's own print
    # start. It decides which filenames are startable, and nothing else here.
    starts_by_gcode: bool = True
    # Whether a person has just said the bed is clear, in answer to being asked. The promise
    # made when the job was scheduled is not this: it was about a moment that had not come yet.
    bed_confirmed: bool = False


Rule = Callable[[Moment], Decision | None]

ANOTHER_JOB_STARTED = Decision(
    Action.CANCEL,
    Refusal.PRINTER_BUSY,
    Said(Message.ANOTHER_JOB_STARTED),
)


def _too_late(moment: Moment) -> Decision | None:
    lateness = moment.now - moment.job.start_at
    if lateness <= moment.tolerance_seconds:
        return None
    return Decision(
        Action.CANCEL,
        Refusal.MISSED,
        Said(
            Message.MISSED,
            {
                "lateness": a_duration(lateness),
                "tolerance": a_duration(moment.tolerance_seconds),
            },
        ),
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
        Said(Message.PRINTER_DID_NOT_ANSWER, {"message": moment.printer.klipper_message}),
    )


def _klipper_is_still_starting(moment: Moment) -> Decision | None:
    if moment.printer.klipper_state not in KLIPPER_STARTING_STATES:
        return None
    return Decision(
        Action.WAIT,
        Refusal.KLIPPER_NOT_READY,
        Said(
            Message.KLIPPER_STARTING,
            {
                "state": moment.printer.klipper_state,
                "message": moment.printer.klipper_message,
            },
        ),
    )


def _klipper_is_not_ready(moment: Moment) -> Decision | None:
    if moment.printer.klipper_state == KLIPPER_READY:
        return None
    # Anything left is shutdown, error, or a state we do not recognise. None of those
    # resolve on their own, so waiting would only replace this reason with "missed".
    return Decision(
        Action.CANCEL,
        Refusal.PRINTER_IN_ERROR,
        Said(
            Message.KLIPPER_NOT_READY,
            {
                "state": moment.printer.klipper_state,
                "message": moment.printer.klipper_message,
            },
        ),
    )


# Each running state gets its own whole sentence rather than a word slotted into a shared one.
# One phrasing covering both reads as "the printer was busy paused foo.gcode" in English, and a
# language that puts the verb elsewhere cannot be repaired by choosing a better word here.
BUSY_WITH = {
    "printing": Message.PRINTER_WAS_PRINTING,
    "paused": Message.PRINTER_WAS_PAUSED,
}


def _a_print_is_running(moment: Moment) -> Decision | None:
    if moment.printer.print_state not in RUNNING_PRINT_STATES:
        return None
    running = moment.printer.printing_filename or Said(Message.ANOTHER_JOB)
    # Says what happened and stops. Why a busy printer is never waited for belongs in the
    # docstring above and in the README, not in the line somebody reads at six in the morning
    # wanting to know why their print did not run.
    was = BUSY_WITH.get(moment.printer.print_state, Message.PRINTER_WAS_BUSY)
    return Decision(Action.CANCEL, Refusal.PRINTER_BUSY, Said(was, {"file": running}))


def _the_bed_may_be_occupied(moment: Moment) -> Decision | None:
    """Hold the job while the printer shows a print that ended and was never dismissed.

    Held, not started and not cancelled. The promise made when the job was scheduled was about
    the moment it would start, and a printer still showing a finished print at that moment is
    evidence against it. The scheduler cannot see the bed, so it asks: better not to start a
    print than to start one onto a part.

    This replaced a rule that let the promise cover any state the person could see when they
    made it, which existed because `complete` never clears itself and refusing on it could stop
    the scheduler for good. The dismiss button removed that reason: there is now a one-click way
    out from the page, so the scheduler no longer has to take the promise on trust.
    """
    if moment.printer.print_state not in UNCLEARED_BED_STATES or moment.bed_confirmed:
        return None
    return Decision(
        Action.HOLD,
        None,
        Said(Message.HELD_FOR_THE_BED, {"state": moment.printer.print_state}),
    )


def _the_printer_is_in_error(moment: Moment) -> Decision | None:
    if moment.printer.print_state != PRINT_STATE_ERROR:
        return None
    return Decision(
        Action.CANCEL,
        Refusal.PRINTER_IN_ERROR,
        Said(Message.THE_PRINTER_SAID, {"message": moment.printer.klipper_message}),
    )


def _other_gcode_is_running(moment: Moment) -> Decision | None:
    if not moment.printer.other_gcode_running:
        return None
    return Decision(Action.WAIT, Refusal.PRINTER_BUSY, Said(Message.OTHER_GCODE_RUNNING))


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
        Said(Message.FILE_GONE, {"filename": moment.job.filename}),
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
    _the_bed_may_be_occupied,
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
    settled: dict[str, Job] = {}
    already_started = False
    for moment in _moments_for(due, printer, seen, now, tolerance_seconds):
        job = moment.job
        decision = ANOTHER_JOB_STARTED if already_started else decide(moment)
        updated = _carry_out(decision, moment, printer)
        already_started = already_started or updated.state is JobState.STARTING
        settled[job.job_id] = updated
    return settled


def _moments_for(
    jobs: Sequence[Job],
    printer: Printer,
    seen: PrinterAsSeen,
    now: float,
    tolerance_seconds: float,
) -> list[Moment]:
    """Everything the rules look at, for each job, from one look at the printer."""
    snapshot, filenames = _with_the_file_listing(printer, seen.snapshot)
    loaded = _loaded_filaments(printer)
    by_gcode = _starts_by_gcode(printer)
    return [
        Moment(
            job,
            snapshot,
            filenames,
            now,
            tolerance_seconds,
            _plan_the_toolheads(printer, job, loaded),
            by_gcode,
        )
        for job in jobs
    ]


# What somebody pressing "start it now" is told about and left waiting over, rather than having
# the job cancelled under them. Every one of these passes: a printer that comes back, a Klipper
# that is restarted, somebody else's print that finishes. The tick cancels on some of them
# because nobody is there to try again; here somebody is, and has just asked.
WORTH_TRYING_AGAIN = frozenset({
    Refusal.PRINTER_BUSY,
    Refusal.PRINTER_UNREACHABLE,
    Refusal.KLIPPER_NOT_READY,
    Refusal.PRINTER_IN_ERROR,
})


def start_now(
    job: Job, printer: Printer, now: float, tolerance_seconds: float
) -> tuple[Job, Said | None]:
    """Start a job held for the bed, on the word of the person who just said the bed is clear.

    Now, however late, because a person pressing a button labelled "start it now" is the one
    case where starting late is exactly what was asked for. The rule against starting late is
    about the machine deciding that on its own, unattended.

    Every other rule still applies, checked afresh. A condition that passes leaves the job
    exactly as it was, still held, and returns why, so the person can try again; a condition
    that never will, a file that has gone or a material nothing holds, settles the job the same
    way a normal start would. There is no separate dismiss: starting a print clears the finished
    one by itself, because the start command resets the file before loading the new one.
    """
    asked = replace(
        job,
        start_at=now,
        hold=None,
        held_at=None,
        attempts=job.attempts + (Attempt(now, Said(Message.CONFIRMED_START_NOW).in_english()),),
    )
    seen = PrinterAsSeen(printer.snapshot(), _recent_prints(printer))
    moment = replace(
        _moments_for([asked], printer, seen, now, tolerance_seconds)[0], bed_confirmed=True
    )
    decision = decide(moment)
    if decision.action is Action.WAIT or decision.refusal in WORTH_TRYING_AGAIN:
        return job, Said(Message.NOT_STARTED_NOW, {"why": decision.said})
    return _carry_out(decision, moment, printer), None


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
        return _confirmed(
            job,
            now,
            ours.job_id,
            Said(Message.RECORDED_AS_JOB, {"printer_job_id": ours.job_id}),
        )
    if _the_printer_is_running_our_file(job, seen.snapshot):
        return _confirmed(job, now, "", Said(Message.RUNNING_WITH_NO_HISTORY))
    waited_for = now - (job.decided_at or now)
    if waited_for <= START_CONFIRMATION_SECONDS:
        return _waited(job, now, Decision(Action.WAIT, Refusal.START_DID_NOT_TAKE,
                                          Said(Message.START_NOT_SEEN_YET)))
    return _cancelled(job, now, Decision(
        Action.CANCEL,
        Refusal.START_DID_NOT_TAKE,
        Said(
            Message.START_DID_NOT_TAKE,
            {"window": a_duration(START_CONFIRMATION_SECONDS)},
        ),
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
        return ToolPlan(
            problem=Said(Message.COULD_NOT_DESCRIBE_FILE, {"filename": job.filename})
        )
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
    if decision.action is Action.HOLD:
        return _held_for_the_bed(moment.job, moment.now, decision)
    if decision.action is Action.CANCEL:
        return _cancelled(moment.job, moment.now, decision)
    return _started(moment, printer)


def _waited(job: Job, now: float, decision: Decision) -> Job:
    return replace(job, attempts=job.attempts + (Attempt(now, decision.detail),))


def _held_for_the_bed(job: Job, now: float, decision: Decision) -> Job:
    return replace(
        job,
        hold=HoldReason.BED_NOT_CONFIRMED,
        held_at=now,
        attempts=job.attempts + (Attempt(now, decision.detail),),
    )


def _cancelled(job: Job, now: float, decision: Decision) -> Job:
    said = decision.said
    return replace(
        job,
        state=JobState.CANCELLED,
        refusal=decision.refusal,
        detail=decision.detail,
        detail_key="" if said is None else said.key.value,
        detail_values={} if said is None else said.wire_values(),
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
            job,
            now,
            Decision(
                Action.CANCEL,
                Refusal.START_REFUSED,
                Said(Message.THE_PRINTER_SAID, {"message": str(refused)}),
            ),
        )
    # STARTING, not STARTED: the printer said yes, and whether it meant it is the next
    # tick's question.
    return replace(
        job,
        state=JobState.STARTING,
        decided_at=now,
        attempts=job.attempts + (Attempt(now, _what_was_asked_for(moment).in_english()),),
    )


def _what_was_asked_for(moment: Moment) -> Said:
    assignments = moment.tool_plan.assignments
    if not assignments:
        return Said(Message.ACCEPTED_THE_START)
    return Said(
        Message.ACCEPTED_THE_START_WITH_SLOTS,
        {
            "mapping": tuple(
                Said(
                    Message.SLOT_ON_TOOLHEAD,
                    {
                        "slot": one.slot,
                        "toolhead": one.toolhead,
                        "material": one.filament_type,
                    },
                )
                for one in assignments
            )
        },
    )


def _confirmed(job: Job, now: float, printer_job_id: str, said: Said) -> Job:
    return replace(
        job,
        state=JobState.STARTED,
        printer_job_id=printer_job_id,
        attempts=job.attempts + (Attempt(now, said.in_english()),),
    )


def cancel_by_hand(job: Job, now: float) -> Job:
    """Cancel a pending job because the person asked, which is not a refusal by the printer.

    The hold goes with it. A held job is a promise waiting on a person, and cancelling it *is*
    that person answering, so a settled job carrying a hold would be a row claiming to wait for
    a decision that has already been made. This and `start_now` are the only ways a held job can
    settle: the tick
    refuses to consider one at all.
    """
    return replace(
        _cancelled(
            job,
            now,
            Decision(Action.CANCEL, Refusal.CANCELLED_BY_YOU, Said(Message.CANCELLED_BY_YOU)),
        ),
        hold=None,
        held_at=None,
    )
