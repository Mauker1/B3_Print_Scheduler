# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Matching our jobs against the printer's own history.

The awkward case is the same file printed more than once, which is the normal case for anyone
iterating on a part. Getting it wrong would attach yesterday's outcome to this morning's job.
"""

from __future__ import annotations

from dataclasses import replace

from print_scheduler import (
    Job,
    JobState,
    PrintRecord,
    find_our_print,
    last_print_ended_at,
    verdict_for,
)

BENCHY = "3DBenchy_ASA_HF_48m40s.gcode"
SIX_IN_THE_MORNING = 1_758_348_000.0


def a_started_job(**overrides: object) -> Job:
    base = Job(
        job_id="job-one",
        filename=BENCHY,
        start_at=SIX_IN_THE_MORNING,
        state=JobState.STARTING,
        decided_at=SIX_IN_THE_MORNING,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def a_record(**overrides: object) -> PrintRecord:
    defaults: dict[str, object] = {
        "job_id": "0000B9",
        "filename": BENCHY,
        "start_time": SIX_IN_THE_MORNING + 2,
        "status": "completed",
        "end_time": SIX_IN_THE_MORNING + 900,
    }
    defaults.update(overrides)
    return PrintRecord(**defaults)  # type: ignore[arg-type]


def test_the_entry_the_printer_made_just_after_we_asked_is_ours() -> None:
    assert find_our_print(a_started_job(), [a_record()]) == a_record()


def test_an_earlier_run_of_the_same_file_is_not_ours() -> None:
    yesterday = a_record(job_id="000097", start_time=SIX_IN_THE_MORNING - 86_400)
    assert find_our_print(a_started_job(), [yesterday]) is None


def test_the_earliest_match_wins_when_the_same_file_was_started_twice() -> None:
    ours = a_record(job_id="0000B9", start_time=SIX_IN_THE_MORNING + 2)
    theirs = a_record(job_id="0000BA", start_time=SIX_IN_THE_MORNING + 400)
    assert find_our_print(a_started_job(), [theirs, ours]) == ours


def test_a_record_a_second_or_two_before_our_start_is_still_ours() -> None:
    # A clock a little out, or an accept that took its time, should not lose the match.
    just_before = a_record(start_time=SIX_IN_THE_MORNING - 3)
    assert find_our_print(a_started_job(), [just_before]) == just_before


def test_a_record_well_before_our_start_is_not() -> None:
    long_before = a_record(start_time=SIX_IN_THE_MORNING - 3600)
    assert find_our_print(a_started_job(), [long_before]) is None


def test_another_file_is_never_ours() -> None:
    assert find_our_print(a_started_job(), [a_record(filename="Cube.gcode")]) is None


def test_a_job_that_never_started_has_no_print_to_find() -> None:
    assert find_our_print(a_started_job(decided_at=None), [a_record()]) is None


def test_the_most_recent_finished_print_is_the_one_that_dates_the_bed() -> None:
    records = [
        a_record(job_id="000097", end_time=SIX_IN_THE_MORNING - 8000),
        a_record(job_id="0000BC", end_time=SIX_IN_THE_MORNING - 600),
    ]
    assert last_print_ended_at(records) == SIX_IN_THE_MORNING - 600


def test_a_print_still_running_has_no_end_time_to_offer() -> None:
    assert last_print_ended_at([a_record(end_time=0.0)]) is None


def test_no_history_at_all_dates_nothing() -> None:
    assert last_print_ended_at([]) is None


def test_the_verdict_is_looked_up_by_the_printers_own_id() -> None:
    job = a_started_job(state=JobState.STARTED, printer_job_id="0000B9")
    found = verdict_for(job, [a_record(job_id="000097"), a_record()])
    assert found is not None
    assert found.status == "completed"


def test_a_job_with_no_printer_id_has_no_verdict() -> None:
    job = a_started_job(state=JobState.STARTED)
    assert verdict_for(job, [a_record()]) is None


def test_a_printer_that_no_longer_remembers_the_print_has_no_verdict() -> None:
    job = a_started_job(state=JobState.STARTED, printer_job_id="0000B9")
    assert verdict_for(job, [a_record(job_id="000001")]) is None


def test_the_status_is_whatever_the_printer_called_it() -> None:
    # Never translated into a vocabulary of ours: what became of a print is the printer's claim.
    job = a_started_job(state=JobState.STARTED, printer_job_id="0000B9")
    found = verdict_for(job, [a_record(status="klippy_shutdown")])
    assert found is not None
    assert found.status == "klippy_shutdown"
