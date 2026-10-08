# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Matching our jobs against the printer's own job history.

Two separate questions live here, and keeping them apart is the point of the module.

**Did our start take?** That one is ours. We told the printer to start something and we are
responsible for noticing when it did not, because a command that answers "ok" and then does nothing
would otherwise be recorded as a success and found out about in the morning.

**What became of the print?** That one is not ours. The printer tracks it, better than we could,
and we look it up when someone asks rather than keeping a copy that can drift. A job carries the
printer's id for the print and nothing else about it.

**How long does this printer take before it prints anything?** That one is the printer's to
answer and nobody else's, which is why it is measured here rather than written down.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

from print_scheduler.jobs import Job
from print_scheduler.printer import PrintRecord

# The printer records the start a moment after we ask for it, but a clock that is a second out, or
# an accept that took its time, could put the record marginally before. A few seconds either way
# identifies our own print without ever reaching back to an earlier run of the same file.
START_MATCH_SLACK_SECONDS = 15.0

# The printer's own word for a print that ran to the end. Only these can be measured: a print
# cancelled during the start routine records a print_duration of exactly zero, so its whole
# duration would read as setup and drag the figure down.
FINISHED = "completed"

# Enough to ride out one unusual print without going so far back that a changed start routine
# takes days to show up.
PRINTS_WORTH_MEASURING = 10

# With this many measurements the extremes are dropped before the range is quoted, so one print
# that sat paused widens nothing. Below it there is nothing to trim: throwing away two of three
# samples would leave a range of one number pretending to be a range.
TRIM_THE_ENDS_FROM = 5

# How many prints of one kind before that kind is measured on its own rather than lumped in
# with the other. Three is not many; one would be a single print stated as a fact.
ENOUGH_TO_TELL_THEM_APART = 3


def find_our_print(job: Job, records: Sequence[PrintRecord]) -> PrintRecord | None:
    """The history entry this job started, if the printer has one yet.

    When the same file was started twice, the earliest match at or after our own start is ours: a
    later one belongs to whoever pressed print after us.
    """
    if job.decided_at is None:
        return None
    earliest_that_could_be_ours = job.decided_at - START_MATCH_SLACK_SECONDS
    ours = [
        record
        for record in records
        if record.filename == job.filename and record.start_time >= earliest_that_could_be_ours
    ]
    if not ours:
        return None
    return min(ours, key=lambda record: record.start_time)


def last_print_ended_at(records: Sequence[PrintRecord]) -> float | None:
    """When the most recent finished print ended, or None if the printer has no record.

    This is what tells an uncleared bed state apart from a latch. `complete` clears when
    someone acknowledges it on the printer, but `cancelled` does not: it sat there for
    forty five minutes with nothing on screen to dismiss, and it would have sat there for
    days. Its name describes what last happened, not what is true now, so the useful
    question is not what the state says but when it started saying it.
    """
    ended = [record.end_time for record in records if record.end_time > 0]
    return max(ended) if ended else None


@dataclass(frozen=True)
class SetupTime:
    """What this printer spends getting ready, as a typical figure and the spread around it."""

    typical: float
    shortest: float
    longest: float

    def to_dict(self) -> dict[str, float]:
        return {"typical": self.typical, "shortest": self.shortest, "longest": self.longest}


def measure_start_routine(records: Sequence[PrintRecord]) -> SetupTime | None:
    """How long this printer spends between accepting a print and finishing it, minus printing.

    Heating, levelling, purging and parking: everything the slicer's estimate leaves out. On the
    machine this was written against it is eight to ten minutes, which made a projected finish
    for a short print wrong by a factor of twenty three. So the page cannot quote a slicer
    estimate as a finish time, and it cannot carry a number of mine either. It has to ask the
    printer.

    It comes back as a range because setup time is not a property of the job. It depends on what
    the last print left behind: levelling costs time, and a bed that has to cool from 70 C to
    45 C costs time in the same way a cold one does, only slower. Three prints on one printer
    spanned 459 to 614 seconds. Quoting the middle of that as a single number reads as a promise
    the printer never made, so the page says both when they differ.

    The middle is the median rather than the mean, and the extremes are trimmed once there are
    enough of them, so one print somebody paused for an hour moves neither the figure nor the
    range.
    """
    # Newest first, as the printer lists them, so the window is the last few finished prints
    # rather than the last few entries, which on a bad morning are all cancellations.
    usable = usable_gaps(records)
    if not usable:
        return None
    kept = usable[1:-1] if len(usable) >= TRIM_THE_ENDS_FROM else usable
    return SetupTime(typical=median(kept), shortest=kept[0], longest=kept[-1])


def usable_gaps(records: Sequence[PrintRecord]) -> list[float]:
    """What the most recent finished prints spent not printing, smallest first."""
    # Newest first, as the printer lists them, so the window is the last few finished prints
    # rather than the last few entries, which on a bad morning are all cancellations.
    measured = [
        record.total_duration - record.print_duration
        for record in records
        if record.status == FINISHED and record.print_duration > 0 and record.total_duration > 0
    ]
    return sorted(gap for gap in measured[:PRINTS_WORTH_MEASURING] if gap > 0)


@dataclass(frozen=True)
class SetupTimes:
    """The setup time overall, and separately for prints that levelled and prints that did not.

    Levelling costs about six and a half minutes on the machine this was measured on, which is
    most of the difference between a two minute setup and a ten minute one. A job knows whether
    it asked for levelling, so it can be projected against prints that made the same choice
    rather than against an average of two habits it is not going to have.
    """

    overall: SetupTime | None = None
    levelled: SetupTime | None = None
    unlevelled: SetupTime | None = None

    def for_choice(self, level_bed: bool | None) -> SetupTime | None:
        """The measurement that fits this job, or the general one when none does."""
        if level_bed is True and self.levelled is not None:
            return self.levelled
        if level_bed is False and self.unlevelled is not None:
            return self.unlevelled
        return self.overall

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": None if self.overall is None else self.overall.to_dict(),
            "levelled": None if self.levelled is None else self.levelled.to_dict(),
            "unlevelled": None if self.unlevelled is None else self.unlevelled.to_dict(),
        }


def measure_setup_times(
    records: Sequence[PrintRecord], levelling: Mapping[str, bool]
) -> SetupTimes:
    """Measure the start routine overall, and by levelling choice where we know it.

    Only prints this scheduler started carry a levelling label, because only then did anyone
    record the choice: the printer's history says what ran, never what it was asked for. So a
    person who mostly presses print by hand keeps the general figure, which is correct rather
    than unfortunate.
    """
    return SetupTimes(
        overall=measure_start_routine(records),
        levelled=_measured_if_there_are_enough(records, levelling, wanted=True),
        unlevelled=_measured_if_there_are_enough(records, levelling, wanted=False),
    )


def _measured_if_there_are_enough(
    records: Sequence[PrintRecord], levelling: Mapping[str, bool], wanted: bool
) -> SetupTime | None:
    """Below a handful of prints, a partition is a rumour rather than a measurement.

    One sample would collapse the range to a single number and the page would quote a
    confident time from a single print, which is the overconfidence the range exists to avoid.
    """
    matching = [record for record in records if levelling.get(record.job_id) is wanted]
    if len(usable_gaps(matching)) < ENOUGH_TO_TELL_THEM_APART:
        return None
    return measure_start_routine(matching)


def verdict_for(job: Job, records: Sequence[PrintRecord]) -> PrintRecord | None:
    """What the printer says became of this job's print, or None if it has no record of it."""
    if not job.printer_job_id:
        return None
    for record in records:
        if record.job_id == job.printer_job_id:
            return record
    return None
