# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The schedule, and every way it can change.

One object owns the jobs, the lock and the file. The tick thread and the web handlers both go
through it, because they are two threads reaching for the same list and a schedule that decides
whether to start a print is the wrong place to be relaxed about that.

Refusing happens here, not in the page. A page can be bypassed; this cannot.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from print_scheduler.filament_left import Shortfall, needs_of, needs_on, shortfalls
from print_scheduler.gcode_files import FileRow, FileSummary, file_rows, summarise
from print_scheduler.heartbeat import A_LONG_SILENCE_SECONDS, Heartbeat
from print_scheduler.history import SetupTimes, measure_setup_times, verdict_for
from print_scheduler.jobs import (
    TOOLHEAD_HOLDS,
    Attempt,
    HoldReason,
    Job,
    JobState,
    new_job_id,
    reason_filename_cannot_start,
    said_state,
)
from print_scheduler.messages import Message, Said
from print_scheduler.printer import (
    KLIPPER_READY,
    UNCLEARED_BED_STATES,
    DismissRefusedError,
    LoadedFilament,
    Printer,
    PrinterSnapshot,
    PrintRecord,
    SpoolLeft,
)
from print_scheduler.runner import (
    THE_MAP_IS_RIGHT,
    Action,
    Decision,
    cancel_by_hand,
    held_for_a_person,
    run_tick,
    start_now,
)
from print_scheduler.settings import Settings
from print_scheduler.store import ScheduleStore
from print_scheduler.tool_mapping import ToolPlan, plan_chosen, plan_tools, what_was_seen

# How many settled jobs are kept on disk whatever the display cap says. A settled job is the
# only record of which levelling choice a print was started with, and the printer's history
# cannot supply it: history says what ran, never what it was asked for. So the number of rows
# someone wants to look at must not decide how much the projection knows. Thirty is
# comfortably above the ten finished prints the measurement window reaches back over, with
# room for a run that is all one levelling choice.
LABELS_WORTH_KEEPING = 30

# How long one reading of the filament left is reused. It takes several requests to Moonraker and
# one Spoolman lookup per spool, and the page asks every ten seconds from every open tab, for a
# number that only moves while something prints. A swapped spool shows up when this runs out.
FILAMENT_LEFT_KEPT_SECONDS = 30.0

_log = logging.getLogger("bespok3d.print_scheduler")

SETTLED_STATES = (JobState.STARTED, JobState.CANCELLED)


class ScheduleRejectedError(Exception):
    """The schedule will not take this job, with a reason meant to be shown to a person.

    The reason travels as a key and its values, so the browser can say it in the reader's own
    language. The exception's own message is the English rendering, which is what a log line
    and a traceback want.
    """

    def __init__(self, said: Said) -> None:
        super().__init__(said.in_english())
        self.said = said


@dataclass(frozen=True)
class JobRequest:
    """What someone is asking to schedule.

    `start_at` is an absolute instant. The browser resolves the time you picked using its own
    timezone and sends the result, so a printer on UTC and a person who is not still agree.
    """

    filename: str
    start_at: float
    typed_time: str = ""
    timezone_name: str = ""
    bed_acknowledged: bool = False
    level_bed: bool | None = None
    record_timelapse: bool | None = None
    # The person's own slot to toolhead pairs, or None to let the scheduler choose.
    toolheads_chosen: tuple[tuple[int, int], ...] | None = None
    # The slots the person has said may print from a toolhead holding a different material.
    # Asked per slot, because agreeing to one mismatch is not agreeing to another.
    materials_acknowledged: frozenset[int] = frozenset()


def trimmed_to(jobs: Sequence[Job], kept: int) -> list[Job]:
    """Drop the oldest settled jobs past the cap, and nothing else, ever.

    A job that has not run is never dropped by this, whatever the cap says: the list exists to
    be a promise about the future, and quietly forgetting a promise would be the worst failure
    this page could have. Order is preserved, so the page does not reshuffle around a trim.
    """
    settled = [job for job in jobs if job.state in SETTLED_STATES]
    if len(settled) <= kept:
        return list(jobs)
    # Newest by when they were settled, falling back to when they were due, because a job
    # cancelled before it ever fired has no decided_at worth trusting.
    newest = sorted(settled, key=lambda job: (job.decided_at or job.start_at), reverse=True)
    keeping = {job.job_id for job in newest[:kept]}
    return [job for job in jobs if job.state not in SETTLED_STATES or job.job_id in keeping]


def projected_finish(job: Job, setup_seconds: float | None = None) -> float | None:
    """When this job should be done, or None if the file did not say how long it takes.

    Two parts, and they have different owners. The slicer says how long the printing takes. The
    printer says how long it spends getting ready, and only history knows that, so a printer
    that has not finished anything yet gets a projection without it rather than a guess.

    None for a held job too. It starts when somebody answers, which nobody can know, so any
    finish computed from its scheduled time is a time it will not finish at. That was on screen
    until 0.4.1, and it fed the overlap warning a finish that was not going to happen.
    """
    if job.estimated_seconds <= 0 or job.held:
        return None
    return job.start_at + (setup_seconds or 0.0) + job.estimated_seconds


def _slowest_setup_for(job: Job, setups: SetupTimes | None) -> float | None:
    measured = None if setups is None else setups.for_choice(job.level_bed)
    return None if measured is None else measured.longest


def overlapping_job_ids(jobs: Sequence[Job], setups: SetupTimes | None = None) -> dict[str, str]:
    """Pending jobs that would start before an earlier pending job is projected to finish.

    Shown as a warning while you are still looking at the screen, rather than left to become a
    silent cancellation at six in the morning. It takes the setup time for the same reason the
    projection does: without it this was optimistic by ten minutes a job, which is the difference
    between a warning and a warning that arrives too late to act on.

    It assumes the slowest setup the printer has managed of the earlier job's own kind, rather
    than a typical one, because a warning that a job might collide is worth having and a
    collision that was not warned about costs a cancelled print.
    """
    # Held jobs are left out on both sides: neither the time one was due nor the time it would
    # finish says anything about when it will actually run.
    pending = sorted(
        (job for job in jobs if job.state is JobState.SCHEDULED and not job.held),
        key=lambda job: job.start_at,
    )
    clashes: dict[str, str] = {}
    for position, job in enumerate(pending):
        for earlier in pending[:position]:
            finish = projected_finish(earlier, _slowest_setup_for(earlier, setups))
            if finish is not None and job.start_at < finish:
                clashes[job.job_id] = earlier.job_id
    return clashes


class ScheduleService:
    """Owns the schedule.

    Every change goes through here and is on disk before the call returns.
    """

    def __init__(
        self,
        store: ScheduleStore,
        printer: Printer,
        settings: Settings,
        heartbeat: Heartbeat | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._printer = printer
        self._settings = settings
        self._heartbeat = heartbeat
        # Asked once, on the first tick, because that is the first moment a clock is handed in
        # and the last moment before anything could be started.
        self._asked_about_the_silence = False
        # Asked on every tick until the printer has said what is loaded once, because until it
        # has there is no telling a job that needs a map from one that does not.
        self._looked_for_unrecorded_maps = False
        self._lock = threading.Lock()
        self._jobs: list[Job] = store.load()
        # Its own lock, never the schedule's: a slow Spoolman must not hold up a start. Holding
        # it while reading means two tabs refreshing together make one reading, not two.
        self._clock = clock
        self._filament_lock = threading.Lock()
        self._filament_reading: tuple[float, tuple[SpoolLeft, ...]] | None = None

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs)

    def settings(self) -> Settings:
        return self._settings

    def tolerance_seconds(self) -> float:
        return self._settings.tolerance_seconds()

    def settled_kept(self) -> int:
        """How many settled jobs to show. A display preference, and only that."""
        return self._settings.settled_kept()

    def settled_stored(self) -> int:
        """How many settled jobs to keep on disk, which is never fewer than the projection needs."""
        return max(self.settled_kept(), LABELS_WORTH_KEEPING)

    def forget(self, job_id: str) -> None:
        """Remove one settled job from our list. The printer's own history is untouched."""
        with self._lock:
            existing = self._find(job_id)
            if existing.state not in SETTLED_STATES:
                raise ScheduleRejectedError(
                    Said(Message.NOT_SETTLED_YET, {"state": said_state(existing.state)})
                )
            self._remember([job for job in self._jobs if job.job_id != job_id])

    def forget_every_settled_job(self) -> int:
        """Empty the settled list, and only the settled list. Returns how many went."""
        with self._lock:
            keeping = [job for job in self._jobs if job.state not in SETTLED_STATES]
            gone = len(self._jobs) - len(keeping)
            if gone:
                self._remember(keeping)
            return gone

    def tick(self, now: float) -> None:
        """Settle whatever has come due. Called on a timer, and never from a web handler."""
        with self._lock:
            # Before the silence, so a job from before maps were recorded asks about its map,
            # which a person answers on its own row, rather than joining the silence's banner,
            # whose answer would only lead to the map question anyway.
            self._hold_what_was_scheduled_before_maps(now)
            self._hold_what_a_long_silence_left_behind(now)
            settled = run_tick(self._jobs, self._printer, now, self.tolerance_seconds())
            self._remember(settled)
        if self._heartbeat is not None:
            self._heartbeat.mark(now)

    def _hold_what_was_scheduled_before_maps(self, now: float) -> None:
        """Hold every waiting job that has no record of the map somebody saw.

        That is every job scheduled before 0.5.0, which chose its map again at the moment of
        starting and never showed it to anybody. Held as soon as this version runs rather than
        when each comes due, so the question is on the page tonight and not at six in the
        morning.

        Only on a printer that reports what is loaded. A printer that does not has no map to
        confirm, and an old job there starts exactly as it always did. A printer that is not
        answering yet cannot be told apart from one of those, so the question is asked again
        on the next tick, and the runner holds any job that comes due in the meantime.
        """
        if self._looked_for_unrecorded_maps:
            return
        unrecorded = {
            job.job_id
            for job in self._jobs
            if job.state is JobState.SCHEDULED and not job.held and job.toolheads_seen is None
        }
        if not unrecorded:
            self._looked_for_unrecorded_maps = True
            return
        if not self.loaded_filaments():
            return
        self._looked_for_unrecorded_maps = True
        _log.warning(
            "holding %d job(s) scheduled before toolhead maps were recorded, "
            "until somebody confirms each map",
            len(unrecorded),
        )
        asked = Decision(
            Action.HOLD, None, Said(Message.MAP_NEVER_CONFIRMED), HoldReason.MAP_NOT_CONFIRMED
        )
        self._remember([
            held_for_a_person(job, now, asked) if job.job_id in unrecorded else job
            for job in self._jobs
        ])

    def _hold_what_a_long_silence_left_behind(self, now: float) -> None:
        """Once per run: if the scheduler was away a long time, nothing waiting may fire yet.

        Held before anything is settled, in the same tick, because the first tick happens as
        the service comes up and a job that came due during the silence would otherwise be
        started by it.

        Only jobs still waiting are held. A job that already ran is history and a cancelled one
        is finished; neither is a promise about the future, which is the only thing at stake.
        """
        if self._asked_about_the_silence or self._heartbeat is None:
            return
        self._asked_about_the_silence = True
        away = self._heartbeat.silence_before(now)
        if away < A_LONG_SILENCE_SECONDS:
            return
        waiting = [job for job in self._jobs if job.state is JobState.SCHEDULED and not job.held]
        if not waiting:
            return
        held = {job.job_id for job in waiting}
        _log.warning(
            "the scheduler was away for %.0f hours; holding %d scheduled job(s) "
            "until somebody confirms them",
            away / 3600,
            len(held),
        )
        self._remember(
            [
                replace(job, hold=HoldReason.LONG_SILENCE, held_at=now)
                if job.job_id in held
                else job
                for job in self._jobs
            ]
        )

    def dismiss_finished_print(self) -> None:
        """Clear a finished print, on the person's word that the bed is clear.

        The printer is asked its state here, afresh, and never taken from the page, which can
        be seconds out of date. The command behind this stops a print that is running, and a
        print somebody started from the touchscreen since the page last looked is exactly the
        one that must not be stopped. So the answer is read and acted on with nothing in
        between.

        Both happen under the schedule's lock, which the tick holds while it starts prints.
        The likeliest thing to start a print in that gap is not another client, it is this
        scheduler, and the lock is what rules it out. What remains is one round trip to a
        Moonraker on the same machine, and nothing short of a Klipper macro can close that,
        because Klipper only evaluates a condition inside a macro.
        """
        with self._lock:
            seen = self._printer.snapshot()
            why_not = why_nothing_can_be_dismissed(seen)
            if why_not is not None:
                raise ScheduleRejectedError(why_not)
            try:
                self._printer.dismiss_finished_print()
            except DismissRefusedError as refused:
                raise ScheduleRejectedError(
                    Said(Message.THE_PRINTER_SAID, {"message": str(refused)})
                ) from refused
        _log.info("cleared a %s print on request, on the word that the bed is clear",
                  seen.print_state)

    def release_held_jobs(self) -> int:
        """Let every held job stand again. Returns how many were released.

        All at once and never one at a time. The question a hold asks is whether the schedule
        as a whole still reflects what somebody wants, and answering it job by job would make a
        person confirm six promises to get at the one they care about.
        """
        with self._lock:
            # Only the holds this button was asked about. A job waiting for the bed has its own
            # question, answered on its own row, and releasing it here would start a print over
            # a bed nobody has looked at.
            held = [job for job in self._jobs if job.hold is HoldReason.LONG_SILENCE]
            if held:
                self._remember([
                    replace(job, hold=None, held_at=None)
                    if job.hold is HoldReason.LONG_SILENCE
                    else job
                    for job in self._jobs
                ])
            return len(held)

    def start_now(self, job_id: str, now: float) -> Job:
        """Start a job held for the bed, now, on the word of the person asking.

        Under the same lock as the tick, so the scheduler cannot start something of its own in
        between. A reason worth trying again is refused in words and leaves the job held; see
        `runner.start_now` for which reasons those are.
        """
        with self._lock:
            existing = self._find(job_id)
            if existing.state is not JobState.SCHEDULED:
                raise ScheduleRejectedError(
                    Said(Message.ALREADY_SETTLED, {"state": said_state(existing.state)})
                )
            if existing.hold is not HoldReason.BED_NOT_CONFIRMED:
                raise ScheduleRejectedError(Said(Message.NOT_WAITING_FOR_THE_BED))
            updated, not_now = start_now(existing, self._printer, now, self.tolerance_seconds())
            if not_now is not None:
                raise ScheduleRejectedError(not_now)
            self._remember([updated if job.job_id == job_id else job for job in self._jobs])
        _log.info("%s after the word that the bed is clear: %s", existing.filename,
                  "held again" if updated.held else updated.state.value)
        return updated

    def accept_toolheads(
        self, job_id: str, toolheads: Sequence[tuple[int, int]], now: float
    ) -> Job:
        """Record the map a person just accepted for a held job, then carry on from there.

        The map sent is checked against one worked out afresh, and refused if they differ.
        The page can be seconds old, and a spool changed in those seconds would otherwise be
        accepted by somebody who never saw it.

        A job whose time has come is started now, under the same lock as the tick. Its answer
        was about the toolheads, not the bed, so the bed is still asked about: one question at
        a time. A job whose time is still ahead simply stands again.
        """
        with self._lock:
            existing = self._find(job_id)
            if existing.state is not JobState.SCHEDULED:
                raise ScheduleRejectedError(
                    Said(Message.ALREADY_SETTLED, {"state": said_state(existing.state)})
                )
            if existing.hold not in TOOLHEAD_HOLDS:
                raise ScheduleRejectedError(Said(Message.NOT_WAITING_FOR_THE_TOOLHEADS))
            plan, grams = self._proposal_for(existing, self.loaded_filaments())
            if plan.problem is not None:
                raise ScheduleRejectedError(plan.problem)
            if plan.as_pairs() != tuple(sorted(toolheads)):
                raise ScheduleRejectedError(Said(Message.TOOLHEADS_CHANGED_AGAIN))
            # The grams are recorded with the map, so a job from before they were kept warns
            # about its spools from here on, as a job scheduled today does.
            recorded = replace(
                existing,
                toolheads_chosen=None,
                toolheads_seen=what_was_seen(plan),
                slot_grams=grams or existing.slot_grams,
            )
            if existing.start_at > now:
                updated = replace(
                    recorded,
                    hold=None,
                    held_at=None,
                    hold_detail_key="",
                    hold_detail_values={},
                    attempts=recorded.attempts
                    + (Attempt(now, THE_MAP_IS_RIGHT.said.in_english()),),
                )
            else:
                updated, not_now = start_now(
                    recorded, self._printer, now, self.tolerance_seconds(), THE_MAP_IS_RIGHT
                )
                if not_now is not None:
                    raise ScheduleRejectedError(not_now)
            self._remember([updated if job.job_id == job_id else job for job in self._jobs])
        _log.info("%s: toolhead map confirmed, %s", existing.filename,
                  "held again" if updated.held else updated.state.value)
        return updated

    def _proposal_for(
        self, job: Job, loaded: Sequence[LoadedFilament]
    ) -> tuple[ToolPlan, tuple[tuple[int, float], ...]]:
        """The map a held job would start on, if somebody accepted it now, and its grams per slot.

        Always the scheduler's own, worked out against what is loaded now, whoever chose the
        map before. Somebody who wants a different one has Edit, which asks for everything
        again. The grams come from the same reading of the file, so a job that never recorded
        them, or lost them to an older version, can still be checked against its spools.
        """
        if not loaded:
            return ToolPlan(problem=Said(Message.NOT_REPORTED_NOW)), ()
        try:
            summary = self.file_summary(job.filename)
        except OSError:
            return ToolPlan(
                problem=Said(Message.COULD_NOT_DESCRIBE_FILE, {"filename": job.filename})
            ), ()
        return plan_tools(summary.tools, loaded), _grams_by_slot(summary)

    def _proposals_for(self, jobs: Sequence[Job]) -> dict[str, dict[str, Any]]:
        """A proposal for each job waiting on its toolheads, off one reading of what is loaded.

        Each carries whether its spools have enough on them, so the warning is on screen before
        somebody presses the button that accepts it, not only after.
        """
        waiting = [
            job for job in jobs if job.state is JobState.SCHEDULED and job.hold in TOOLHEAD_HOLDS
        ]
        if not waiting:
            return {}
        loaded = self.loaded_filaments()
        proposals: dict[str, dict[str, Any]] = {}
        for job in waiting:
            plan, grams = self._proposal_for(job, loaded)
            needs = needs_on(plan.as_pairs(), grams) if plan.problem is None else []
            short = shortfalls(needs, self.filament_left()) if needs else ()
            proposals[job.job_id] = proposal_payload(plan, short)
        return proposals

    def add(self, request: JobRequest, now: float) -> Job:
        summary, plan = self._vet(request, now)
        job = Job(
            job_id=new_job_id(),
            filename=request.filename,
            start_at=request.start_at,
            created_at=now,
            typed_time=request.typed_time,
            timezone_name=request.timezone_name,
            bed_acknowledged=request.bed_acknowledged,
            level_bed=request.level_bed,
            record_timelapse=request.record_timelapse,
            estimated_seconds=summary.estimated_seconds,
            toolheads_chosen=_chosen_in(request, plan),
            toolheads_seen=what_was_seen(plan),
            slot_grams=_grams_by_slot(summary),
        )
        with self._lock:
            self._remember([*self._jobs, job])
        return job

    def update(self, job_id: str, request: JobRequest, now: float) -> Job:
        """Change a job that has not fired yet.

        Editing shows the map again and asks for it again, so it answers a hold about the
        toolheads, and the map recorded is the one on screen now. A hold about the bed or a
        long silence is a different question, and stands.
        """
        summary, plan = self._vet(request, now)
        with self._lock:
            existing = self._find(job_id)
            if existing.state is not JobState.SCHEDULED:
                raise ScheduleRejectedError(
                    Said(Message.ALREADY_UNDERWAY, {"state": said_state(existing.state)})
                )
            answered = existing.hold in TOOLHEAD_HOLDS
            updated = replace(
                existing,
                hold=None if answered else existing.hold,
                held_at=None if answered else existing.held_at,
                hold_detail_key="" if answered else existing.hold_detail_key,
                hold_detail_values={} if answered else existing.hold_detail_values,
                toolheads_chosen=_chosen_in(request, plan),
                toolheads_seen=what_was_seen(plan),
                slot_grams=_grams_by_slot(summary),
                filename=request.filename,
                start_at=request.start_at,
                # Editing re-asks for the promise about the bed, so it is a new promise,
                # made now, and it covers what the printer is saying now.
                created_at=now,
                typed_time=request.typed_time,
                timezone_name=request.timezone_name,
                bed_acknowledged=request.bed_acknowledged,
                level_bed=request.level_bed,
                record_timelapse=request.record_timelapse,
                estimated_seconds=summary.estimated_seconds,
            )
            self._remember([updated if job.job_id == job_id else job for job in self._jobs])
        return updated

    def cancel(self, job_id: str, now: float) -> Job:
        with self._lock:
            existing = self._find(job_id)
            if existing.state is not JobState.SCHEDULED:
                raise ScheduleRejectedError(
                    Said(Message.ALREADY_SETTLED, {"state": said_state(existing.state)})
                )
            cancelled = cancel_by_hand(existing, now)
            self._remember([cancelled if job.job_id == job_id else job for job in self._jobs])
        return cancelled

    def printer_snapshot(self) -> PrinterSnapshot:
        return self._printer.snapshot()

    def supports_print_preferences(self) -> bool:
        """Whether this printer lets a job carry its own bed mesh and timelapse choices."""
        try:
            return self._printer.supports_print_preferences()
        except OSError:
            return False

    def loaded_filaments(self) -> tuple[LoadedFilament, ...]:
        try:
            return self._printer.loaded_filaments()
        except OSError:
            return ()

    def filament_left(self) -> tuple[SpoolLeft, ...]:
        """How much is left on each toolhead's spool, read at most once every 30 seconds."""
        with self._filament_lock:
            now = self._clock()
            if self._filament_reading is not None:
                read_at, reading = self._filament_reading
                if now - read_at < FILAMENT_LEFT_KEPT_SECONDS:
                    return reading
            try:
                reading = self._printer.filament_left()
            except OSError:
                reading = ()
            self._filament_reading = (now, reading)
            return reading

    def _shortfalls_for(self, jobs: Sequence[Job]) -> dict[str, list[dict[str, Any]]]:
        """For each waiting job, the toolheads with less left than it needs. Read only if asked."""
        # A job held over its toolheads is left out: the map it recorded is the one in doubt, and
        # its offer carries the warning for the map that would replace it.
        waiting = [
            (job, needs) for job in jobs
            if job.state is JobState.SCHEDULED
            and job.hold not in TOOLHEAD_HOLDS
            and (needs := needs_of(job))
        ]
        if not waiting:
            return {}
        left = self.filament_left()
        found = {job.job_id: shortfalls(needs, left) for job, needs in waiting}
        return {
            job_id: [one.to_dict() for one in short] for job_id, short in found.items() if short
        }

    def tool_plan(self, summary: FileSummary) -> ToolPlan:
        """Which toolhead each of the file's slots would run on, as things stand now."""
        return plan_tools(summary.tools, self.loaded_filaments())

    def file_summary(self, filename: str) -> FileSummary:
        return summarise(filename, self._printer.file_metadata(filename))

    def gcode_filenames(self) -> list[str]:
        return sorted(self._printer.gcode_filenames())

    def files_on_the_printer(self) -> tuple[FileRow, ...]:
        """Every file, newest first, described as far as the printer will describe it."""
        try:
            listing = self._printer.file_listing()
        except OSError:
            return ()
        try:
            described = self._printer.described_files()
        except OSError:
            described = {}
        return file_rows(listing, described)

    def thumbnail(self, filename: str) -> tuple[bytes, str] | None:
        try:
            return self._printer.thumbnail(filename)
        except OSError:
            return None

    def recent_prints(self) -> tuple[PrintRecord, ...]:
        try:
            return self._printer.recent_prints()
        except OSError:
            return ()

    def verdicts(self) -> dict[str, PrintRecord]:
        """What the printer says became of each started job. Its claim, read when asked."""
        return self._verdicts_in(self.recent_prints())

    def schedule_payload(self) -> dict[str, Any]:
        """Everything the page needs about the schedule, off one reading of the history.

        The verdicts and the setup time both come out of the same listing, so asking for it
        twice would be two round trips to say one thing.
        """
        records = self.recent_prints()
        jobs = self.jobs()
        # Measured against every settled job we still hold, then rendered down to the ones
        # someone asked to see. The two numbers are deliberately different: turning the list
        # down to two rows should tidy the page, not blind the projection.
        setups = measure_setup_times(records, _levelling_by_printer_job(jobs))
        shown = trimmed_to(jobs, self.settled_kept())
        return {
            "jobs": payload_for(
                shown,
                self._verdicts_in(records),
                setups,
                self._proposals_for(shown),
                self._shortfalls_for(shown),
            ),
            "setup": setups.to_dict(),
        }

    def _verdicts_in(self, records: Sequence[PrintRecord]) -> dict[str, PrintRecord]:
        found = ((job, verdict_for(job, records)) for job in self.jobs())
        return {job.job_id: record for job, record in found if record is not None}

    def _remember(self, jobs: Sequence[Job]) -> None:
        # Every change goes through here, so this is the one place the cap has to be applied
        # for the list never to grow. It only ever drops settled jobs. The cap applied here is
        # the storage one, not the display one: forgetting a job on disk also forgets which
        # levelling choice its print was started with, and that cannot be recovered.
        self._jobs = trimmed_to(jobs, self.settled_stored())
        self._store.save(self._jobs)

    def _find(self, job_id: str) -> Job:
        for job in self._jobs:
            if job.job_id == job_id:
                return job
        raise ScheduleRejectedError(Said(Message.NO_SUCH_JOB))

    def _vet(self, request: JobRequest, now: float) -> tuple[FileSummary, ToolPlan]:
        """Refuse everything that can be refused now rather than at six in the morning."""
        unstartable = reason_filename_cannot_start(
            request.filename, self.supports_print_preferences()
        )
        if unstartable is not None:
            raise ScheduleRejectedError(unstartable)
        if not request.bed_acknowledged:
            raise ScheduleRejectedError(Said(Message.BED_NOT_PROMISED))
        if request.start_at <= now:
            raise ScheduleRejectedError(Said(Message.TIME_ALREADY_PASSED))
        if request.filename not in self._printer.gcode_filenames():
            raise ScheduleRejectedError(
                Said(Message.NOT_ON_THE_PRINTER, {"filename": request.filename})
            )
        return self._vet_the_file(request)

    def _vet_the_file(self, request: JobRequest) -> tuple[FileSummary, ToolPlan]:
        """The file's summary and the map it will be recorded with, or why there is none.

        The map is checked again when the job fires, against what is loaded then, and the job
        is held if the two differ: a spool can be changed overnight. This check is so you find
        out now instead of at six.
        """
        summary = self.file_summary(request.filename)
        loaded = self.loaded_filaments()
        if request.toolheads_chosen is None:
            plan = plan_tools(summary.tools, loaded)
        else:
            plan = plan_chosen(summary.tools, loaded, request.toolheads_chosen)
        if plan.problem is not None:
            raise ScheduleRejectedError(plan.problem)
        for one in plan.assignments:
            if one.materials_differ and one.slot not in request.materials_acknowledged:
                raise ScheduleRejectedError(
                    Said(
                        Message.MATERIAL_NOT_ACKNOWLEDGED,
                        {
                            "slot": one.slot,
                            "wanted": one.wanted_material,
                            "toolhead": one.toolhead,
                            "loaded": one.filament_type,
                        },
                    )
                )
        return summary, plan


def _chosen_in(request: JobRequest, plan: ToolPlan) -> tuple[tuple[int, int], ...] | None:
    """The person's map as it will be carried through Edit, or None if the scheduler chose.

    None as well on a printer with no map to make, where a choice sent anyway means nothing.
    """
    if request.toolheads_chosen is None or not plan.applicable:
        return None
    return plan.as_pairs()


def _grams_by_slot(summary: FileSummary) -> tuple[tuple[int, float], ...]:
    return tuple((tool.slot, tool.used_grams) for tool in summary.tools if tool.used_grams > 0)


def proposal_payload(plan: ToolPlan, short: Sequence[Shortfall] = ()) -> dict[str, Any]:
    """A proposed map for the page, with the pairs the page sends back to accept it."""
    return {
        **plan.to_dict(),
        "toolheads": [[slot, toolhead] for slot, toolhead in plan.as_pairs()],
        "acceptable": plan.problem is None,
        "filament_short": [one.to_dict() for one in short],
    }


def why_nothing_can_be_dismissed(seen: PrinterSnapshot) -> Said | None:
    """Why this printer must not be sent the dismiss command right now, or None if it may.

    Only a print that ended and was not dismissed qualifies, on a Klipper that is ready. An
    error is deliberately not among them: a print that failed deserves somebody walking over
    to the printer, not a button on a phone.
    """
    if not seen.reachable:
        return Said(Message.PRINTER_DID_NOT_ANSWER, {"message": seen.klipper_message})
    if seen.klipper_state != KLIPPER_READY:
        return Said(
            Message.KLIPPER_NOT_READY,
            {"state": seen.klipper_state, "message": seen.klipper_message},
        )
    if seen.print_state not in UNCLEARED_BED_STATES:
        return Said(Message.NOTHING_TO_DISMISS, {"state": seen.print_state})
    return None


def _levelling_by_printer_job(jobs: Sequence[Job]) -> dict[str, bool]:
    """Which of the printer's own prints we know the levelling choice for.

    Only jobs this scheduler started, and only on a printer that offers the choice at all. The
    printer's history records what ran, never what it was asked for, so this is the only place
    the two can be joined.
    """
    return {
        job.printer_job_id: job.level_bed
        for job in jobs
        if job.printer_job_id and job.level_bed is not None
    }


def payload_for(
    jobs: Sequence[Job],
    verdicts: dict[str, PrintRecord],
    setups: SetupTimes | None = None,
    proposals: dict[str, dict[str, Any]] | None = None,
    short_of_filament: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Render the schedule for the page: what we did, and separately what the printer says.

    The finish comes out as three numbers rather than one. This printer's setup time is not a
    bell curve with a middle; it is two clusters, nine minutes apart, and a median of them is a
    value almost no print is near. One such projection was six minutes out on a job lasting
    five and a half, while the range around it contained the truth comfortably.

    Each job is measured against prints that made the same levelling choice where there are
    enough of them, so two jobs on one page can carry honestly different numbers.
    """
    clashes = overlapping_job_ids(jobs, setups)
    rendered = []
    for job in jobs:
        setup = None if setups is None else setups.for_choice(job.level_bed)
        entry = job.to_dict()
        entry["setup"] = None if setup is None else setup.to_dict()
        entry["projected_finish"] = projected_finish(job, None if setup is None else setup.typical)
        entry["projected_finish_from"] = projected_finish(
            job, None if setup is None else setup.shortest
        )
        entry["projected_finish_to"] = projected_finish(
            job, None if setup is None else setup.longest
        )
        entry["overlaps_with"] = clashes.get(job.job_id)
        verdict = verdicts.get(job.job_id)
        entry["printer_says"] = None if verdict is None else verdict.status
        entry["toolheads_proposal"] = (proposals or {}).get(job.job_id)
        entry["filament_short"] = (short_of_filament or {}).get(job.job_id, [])
        rendered.append(entry)
    return rendered
