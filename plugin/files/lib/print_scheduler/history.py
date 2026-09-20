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
"""

from __future__ import annotations

from collections.abc import Sequence

from print_scheduler.jobs import Job
from print_scheduler.printer import PrintRecord

# The printer records the start a moment after we ask for it, but a clock that is a second out, or
# an accept that took its time, could put the record marginally before. A few seconds either way
# identifies our own print without ever reaching back to an earlier run of the same file.
START_MATCH_SLACK_SECONDS = 15.0


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


def verdict_for(job: Job, records: Sequence[PrintRecord]) -> PrintRecord | None:
    """What the printer says became of this job's print, or None if it has no record of it."""
    if not job.printer_job_id:
        return None
    for record in records:
        if record.job_id == job.printer_job_id:
            return record
    return None
