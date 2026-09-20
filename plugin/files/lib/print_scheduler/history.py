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

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

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
    measured = [
        record.total_duration - record.print_duration
        for record in records
        if record.status == FINISHED and record.print_duration > 0 and record.total_duration > 0
    ]
    usable = sorted(gap for gap in measured[:PRINTS_WORTH_MEASURING] if gap > 0)
    if not usable:
        return None
    kept = usable[1:-1] if len(usable) >= TRIM_THE_ENDS_FROM else usable
    return SetupTime(typical=median(kept), shortest=kept[0], longest=kept[-1])


def verdict_for(job: Job, records: Sequence[PrintRecord]) -> PrintRecord | None:
    """What the printer says became of this job's print, or None if it has no record of it."""
    if not job.printer_job_id:
        return None
    for record in records:
        if record.job_id == job.printer_job_id:
            return record
    return None
