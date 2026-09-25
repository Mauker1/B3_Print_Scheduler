# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A job held because the printer still shows a finished print, from storage to the button.

The rule itself is tested in `test_runner.py`. This is everything around it: what a hold is
stored as, what releases one and what must not, and the one button that starts a held job.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from print_scheduler import (
    HoldReason,
    Job,
    JobState,
    Message,
    ScheduleRejectedError,
    ScheduleService,
    ScheduleStore,
    Settings,
    job_from_dict,
    overlapping_job_ids,
    projected_finish,
)
from printer_stand_in import BENCHY, IDLE, StandInPrinter

SIX_IN_THE_MORNING = 1_758_348_000.0
FINISHED = replace(IDLE, print_state="complete", printing_filename="cube.gcode")


def a_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "job_id": "job-one",
        "filename": BENCHY,
        "start_at": SIX_IN_THE_MORNING,
        "bed_acknowledged": True,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def a_service_holding(tmp_path: Path, jobs: list[Job], printer: StandInPrinter) -> ScheduleService:
    ScheduleStore(tmp_path / "jobs.json").save(jobs)
    return ScheduleService(
        ScheduleStore(tmp_path / "jobs.json"), printer, Settings(tmp_path / "user_vars.json")
    )


def test_a_hold_written_by_0_3_0_reads_as_the_long_silence_it_was() -> None:
    """0.3.0 stored a bare flag, and a long silence was the only thing that could set it."""
    old = a_job().to_dict()
    del old["hold"]
    del old["held_at"]
    old["held"] = True
    assert job_from_dict(old).hold is HoldReason.LONG_SILENCE


def test_a_hold_and_when_it_began_survive_being_stored() -> None:
    held = a_job(hold=HoldReason.BED_NOT_CONFIRMED, held_at=SIX_IN_THE_MORNING)
    stored = json.loads(json.dumps(held.to_dict()))
    assert job_from_dict(stored) == held
    # Written beside the reason, so a downgrade to 0.3.0 still sees a held job.
    assert stored["held"] is True


def test_the_long_silence_button_does_not_release_a_job_waiting_for_the_bed(
    tmp_path: Path,
) -> None:
    """That button answers whether the schedule still stands. Whether this bed is clear is a
    different question, and releasing it here would start a print nobody looked at."""
    silence = a_job(job_id="silence", hold=HoldReason.LONG_SILENCE, held_at=SIX_IN_THE_MORNING)
    bed = a_job(job_id="bed", hold=HoldReason.BED_NOT_CONFIRMED, held_at=SIX_IN_THE_MORNING)
    service = a_service_holding(tmp_path, [silence, bed], StandInPrinter(reports=FINISHED))
    assert service.release_held_jobs() == 1
    after = {job.job_id: job for job in service.jobs()}
    assert after["silence"].hold is None
    assert after["bed"].hold is HoldReason.BED_NOT_CONFIRMED


def test_start_now_starts_a_job_waiting_for_the_bed(tmp_path: Path) -> None:
    printer = StandInPrinter(reports=FINISHED)
    bed = a_job(hold=HoldReason.BED_NOT_CONFIRMED, held_at=SIX_IN_THE_MORNING)
    service = a_service_holding(tmp_path, [bed], printer)
    started = service.start_now("job-one", SIX_IN_THE_MORNING + 3600)
    assert started.state is JobState.STARTING
    assert service.jobs()[0].state is JobState.STARTING
    assert len(printer.started) == 1


def test_start_now_refuses_a_job_that_is_not_waiting_for_the_bed(tmp_path: Path) -> None:
    printer = StandInPrinter(reports=IDLE)
    service = a_service_holding(tmp_path, [a_job()], printer)
    with pytest.raises(ScheduleRejectedError) as refused:
        service.start_now("job-one", SIX_IN_THE_MORNING)
    assert refused.value.said.key is Message.NOT_WAITING_FOR_THE_BED
    assert printer.started == []


def test_a_refused_start_now_leaves_the_job_held_and_says_why(tmp_path: Path) -> None:
    printer = StandInPrinter(
        reports=replace(IDLE, print_state="printing", printing_filename="started-by-hand.gcode")
    )
    bed = a_job(hold=HoldReason.BED_NOT_CONFIRMED, held_at=SIX_IN_THE_MORNING)
    service = a_service_holding(tmp_path, [bed], printer)
    with pytest.raises(ScheduleRejectedError) as refused:
        service.start_now("job-one", SIX_IN_THE_MORNING)
    assert refused.value.said.key is Message.NOT_STARTED_NOW
    assert "started-by-hand.gcode" in str(refused.value)
    assert service.jobs()[0] == bed
    assert printer.started == []


def test_a_held_job_projects_no_finish_it_will_not_make() -> None:
    """It starts when somebody answers. A finish worked out from its scheduled time is a time
    it will not finish at, and it was on screen until 0.4.1."""
    held = a_job(estimated_seconds=600.0, hold=HoldReason.BED_NOT_CONFIRMED,
                 held_at=SIX_IN_THE_MORNING)
    assert projected_finish(held, 120.0) is None
    assert projected_finish(replace(held, hold=None, held_at=None), 120.0) is not None


def test_a_held_job_neither_raises_nor_receives_an_overlap_warning() -> None:
    held = a_job(job_id="held", estimated_seconds=3600.0, hold=HoldReason.BED_NOT_CONFIRMED,
                 held_at=SIX_IN_THE_MORNING)
    soon_after = a_job(job_id="after", start_at=SIX_IN_THE_MORNING + 600, estimated_seconds=60.0)
    overlapped_by_nothing = a_job(job_id="later", start_at=SIX_IN_THE_MORNING + 700,
                                  estimated_seconds=60.0)
    assert overlapping_job_ids([held, soon_after]) == {}
    held_later = replace(held, start_at=SIX_IN_THE_MORNING + 650)
    assert overlapping_job_ids([soon_after, held_later, overlapped_by_nothing]) == {}
