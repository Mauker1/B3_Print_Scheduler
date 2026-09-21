# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The schedule, and every way it can change.

One object owns the jobs, the lock and the file. The tick thread and the web handlers both go
through it, because they are two threads reaching for the same list and a schedule that decides
whether to start a print is the wrong place to be relaxed about that.

Refusing happens here, not in the page. A page can be bypassed; this cannot.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from print_scheduler.gcode_files import FileRow, FileSummary, file_rows, summarise
from print_scheduler.history import SetupTimes, measure_setup_times, verdict_for
from print_scheduler.jobs import (
    Job,
    JobState,
    new_job_id,
    reason_filename_cannot_start,
)
from print_scheduler.printer import (
    LoadedFilament,
    Printer,
    PrinterSnapshot,
    PrintRecord,
)
from print_scheduler.runner import cancel_by_hand, run_tick
from print_scheduler.store import ScheduleStore
from print_scheduler.tool_mapping import ToolPlan, plan_tools

DEFAULT_TOLERANCE_MINUTES = 5.0
SECONDS_PER_MINUTE = 60.0
TOLERANCE_VARIABLE = "START_TOLERANCE_MINUTES"

SETTLED_KEPT_VARIABLE = "SETTLED_JOBS_KEPT"
DEFAULT_SETTLED_KEPT = 25

# How many settled jobs are kept on disk whatever the display cap says. A settled job is the
# only record of which levelling choice a print was started with, and the printer's history
# cannot supply it: history says what ran, never what it was asked for. So the number of rows
# someone wants to look at must not decide how much the projection knows. Thirty is
# comfortably above the ten finished prints the measurement window reaches back over, with
# room for a run that is all one levelling choice.
LABELS_WORTH_KEEPING = 30

SETTLED_STATES = (JobState.STARTED, JobState.CANCELLED)


class ScheduleRejectedError(Exception):
    """The schedule will not take this job, with a reason meant to be shown to a person."""


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


def read_tolerance_seconds(user_vars_path: Path) -> float:
    """Read the lateness tolerance the person set at install.

    Read afresh every time rather than at startup, so changing it in the app takes effect without
    restarting the service. An unreadable or absent file is the default, not a crash: the daemon
    writes this file and we are a guest in it.
    """
    try:
        values = json.loads(user_vars_path.read_text(encoding="utf-8"))
        minutes = float(values[TOLERANCE_VARIABLE])
    except (OSError, ValueError, KeyError, TypeError):
        minutes = DEFAULT_TOLERANCE_MINUTES
    return max(minutes, 0.0) * SECONDS_PER_MINUTE


def read_settled_kept(user_vars_path: Path) -> int:
    """How many settled jobs to keep, from the same file and with the same forgiveness.

    Read afresh rather than at startup, so changing it in the app takes effect without a
    restart. Zero is a real answer, meaning keep nothing once a job has settled; a negative
    one is not, and reads as the default.
    """
    try:
        values = json.loads(user_vars_path.read_text(encoding="utf-8"))
        kept = int(float(values[SETTLED_KEPT_VARIABLE]))
    except (OSError, ValueError, KeyError, TypeError):
        return DEFAULT_SETTLED_KEPT
    return kept if kept >= 0 else DEFAULT_SETTLED_KEPT


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
    """
    if job.estimated_seconds <= 0:
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
    pending = sorted(
        (job for job in jobs if job.state is JobState.SCHEDULED), key=lambda job: job.start_at
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

    def __init__(self, store: ScheduleStore, printer: Printer, user_vars_path: Path) -> None:
        self._store = store
        self._printer = printer
        self._user_vars_path = user_vars_path
        self._lock = threading.Lock()
        self._jobs: list[Job] = store.load()

    def jobs(self) -> list[Job]:
        with self._lock:
            return list(self._jobs)

    def tolerance_seconds(self) -> float:
        return read_tolerance_seconds(self._user_vars_path)

    def settled_kept(self) -> int:
        """How many settled jobs to show. A display preference, and only that."""
        return read_settled_kept(self._user_vars_path)

    def settled_stored(self) -> int:
        """How many settled jobs to keep on disk, which is never fewer than the projection needs."""
        return max(self.settled_kept(), LABELS_WORTH_KEEPING)

    def forget(self, job_id: str) -> None:
        """Remove one settled job from our list. The printer's own history is untouched."""
        with self._lock:
            existing = self._find(job_id)
            if existing.state not in SETTLED_STATES:
                raise ScheduleRejectedError(
                    f"this job is {existing.state.value} and has not settled. Cancel it first."
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
            settled = run_tick(self._jobs, self._printer, now, self.tolerance_seconds())
            self._remember(settled)

    def add(self, request: JobRequest, now: float) -> Job:
        summary = self._vet(request, now)
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
        )
        with self._lock:
            self._remember([*self._jobs, job])
        return job

    def update(self, job_id: str, request: JobRequest, now: float) -> Job:
        """Change a job that has not fired yet."""
        summary = self._vet(request, now)
        with self._lock:
            existing = self._find(job_id)
            if existing.state is not JobState.SCHEDULED:
                raise ScheduleRejectedError(
                    f"this job is already {existing.state.value} and cannot be changed. "
                    "Schedule a new one from it instead."
                )
            updated = replace(
                existing,
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
                raise ScheduleRejectedError(f"this job is already {existing.state.value}")
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
            "jobs": payload_for(shown, self._verdicts_in(records), setups),
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
        raise ScheduleRejectedError("there is no job with that id")

    def _vet(self, request: JobRequest, now: float) -> FileSummary:
        """Refuse everything that can be refused now rather than at six in the morning."""
        unstartable = reason_filename_cannot_start(
            request.filename, self.supports_print_preferences()
        )
        if unstartable is not None:
            raise ScheduleRejectedError(unstartable)
        if not request.bed_acknowledged:
            raise ScheduleRejectedError(
                "the printer cannot see the bed, so someone has to promise it will be clear"
            )
        if request.start_at <= now:
            raise ScheduleRejectedError("that time has already passed")
        if request.filename not in self._printer.gcode_filenames():
            raise ScheduleRejectedError(f"{request.filename} is not on the printer")
        return self._vet_the_file(request.filename)

    def _vet_the_file(self, filename: str) -> FileSummary:
        summary = self.file_summary(filename)
        # Checked again when the job fires, which is the check that counts: a spool can be
        # changed overnight. This one is so you find out now instead of at six.
        plan = self.tool_plan(summary)
        if plan.problem is not None:
            raise ScheduleRejectedError(plan.problem)
        return summary


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
        rendered.append(entry)
    return rendered
