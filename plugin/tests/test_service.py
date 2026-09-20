# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The schedule and every way it can change.

Refusing lives here rather than in the page, so this is where it is tested. A page can be
bypassed; a service cannot.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from print_scheduler import (
    JobRequest,
    JobState,
    LoadedFilament,
    ScheduleRejectedError,
    ScheduleService,
    ScheduleStore,
    overlapping_job_ids,
    payload_for,
    projected_finish,
    read_tolerance_seconds,
)
from printer_stand_in import (
    BENCHY,
    FOUR_TOOL_METADATA,
    PRINTING_OURS,
    WHITE_PLA_METADATA,
    StandInPrinter,
)

SIX_IN_THE_MORNING = 1_758_348_000.0
LAST_NIGHT = SIX_IN_THE_MORNING - 8 * 3600
BENCHY_SECONDS = 2920.0


def a_service(tmp_path: Path, printer: StandInPrinter | None = None) -> ScheduleService:
    return ScheduleService(
        ScheduleStore(tmp_path / "jobs.json"),
        printer or StandInPrinter(),
        tmp_path / "user_vars.json",
    )


def a_request(**overrides: object) -> JobRequest:
    base = JobRequest(filename=BENCHY, start_at=SIX_IN_THE_MORNING, bed_acknowledged=True)
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_a_job_is_accepted_and_written_to_disk(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    job = service.add(a_request(), LAST_NIGHT)
    assert job.state is JobState.SCHEDULED
    assert ScheduleStore(tmp_path / "jobs.json").load() == [job]


def test_the_slicer_estimate_is_kept_so_a_listing_needs_no_metadata_reads(tmp_path: Path) -> None:
    job = a_service(tmp_path).add(a_request(), LAST_NIGHT)
    assert job.estimated_seconds == BENCHY_SECONDS
    assert projected_finish(job) == SIX_IN_THE_MORNING + BENCHY_SECONDS


def test_a_job_records_when_the_bed_was_promised(tmp_path: Path) -> None:
    assert a_service(tmp_path).add(a_request(), LAST_NIGHT).created_at == LAST_NIGHT


def test_editing_re_asks_for_the_promise_so_it_is_re_dated(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    job = service.add(a_request(), LAST_NIGHT)
    later = service.update(job.job_id, a_request(), LAST_NIGHT + 3600)
    assert later.created_at == LAST_NIGHT + 3600


def test_a_time_that_has_already_passed_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScheduleRejectedError, match="already passed"):
        a_service(tmp_path).add(a_request(), SIX_IN_THE_MORNING + 1)


def test_an_unpromised_bed_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScheduleRejectedError, match="promise"):
        a_service(tmp_path).add(a_request(bed_acknowledged=False), LAST_NIGHT)


def test_a_file_the_printer_does_not_have_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ScheduleRejectedError, match="not on the printer"):
        a_service(tmp_path).add(a_request(filename="imaginary.gcode"), LAST_NIGHT)


def test_a_filename_the_gcode_parser_cannot_carry_is_refused(tmp_path: Path) -> None:
    printer = StandInPrinter(holds=frozenset({"plate #2.gcode"}))
    with pytest.raises(ScheduleRejectedError, match="comment"):
        a_service(tmp_path, printer).add(a_request(filename="plate #2.gcode"), LAST_NIGHT)


def test_a_material_no_toolhead_holds_is_refused_while_you_are_still_looking(
    tmp_path: Path,
) -> None:
    only_asa = (LoadedFilament(index=0, filament_type="ASA", colour="000000FF", present=True),)
    printer = StandInPrinter(describes=dict(WHITE_PLA_METADATA), loads=only_asa)
    with pytest.raises(ScheduleRejectedError, match="no free toolhead"):
        a_service(tmp_path, printer).add(a_request(), LAST_NIGHT)


def test_a_multi_tool_file_is_refused_with_the_reason(tmp_path: Path) -> None:
    printer = StandInPrinter(describes=dict(FOUR_TOOL_METADATA))
    with pytest.raises(ScheduleRejectedError, match="4 toolheads"):
        a_service(tmp_path, printer).add(a_request(), LAST_NIGHT)


def test_a_pending_job_can_be_edited(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    job = service.add(a_request(), LAST_NIGHT)
    moved = service.update(
        job.job_id, a_request(start_at=SIX_IN_THE_MORNING + 3600), LAST_NIGHT
    )
    assert moved.job_id == job.job_id
    assert moved.start_at == SIX_IN_THE_MORNING + 3600
    assert len(service.jobs()) == 1


def test_editing_re_applies_every_refusal(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    job = service.add(a_request(), LAST_NIGHT)
    with pytest.raises(ScheduleRejectedError, match="promise"):
        service.update(job.job_id, a_request(bed_acknowledged=False), LAST_NIGHT)


def test_a_job_that_has_already_fired_cannot_be_edited(tmp_path: Path) -> None:
    service = a_service(tmp_path, StandInPrinter(reports=PRINTING_OURS))
    job = service.add(a_request(), LAST_NIGHT)
    service.tick(SIX_IN_THE_MORNING)
    with pytest.raises(ScheduleRejectedError, match="cannot be changed"):
        service.update(job.job_id, a_request(), LAST_NIGHT)


def test_a_pending_job_can_be_cancelled(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    job = service.add(a_request(), LAST_NIGHT)
    assert service.cancel(job.job_id, LAST_NIGHT).state is JobState.CANCELLED


def test_cancelling_an_unknown_job_says_so(tmp_path: Path) -> None:
    with pytest.raises(ScheduleRejectedError, match="no job with that id"):
        a_service(tmp_path).cancel("never-existed", LAST_NIGHT)


def test_a_tick_starts_what_is_due_and_saves_the_result(tmp_path: Path) -> None:
    printer = StandInPrinter()
    service = a_service(tmp_path, printer)
    service.add(a_request(), LAST_NIGHT)
    service.tick(SIX_IN_THE_MORNING)
    assert printer.started == [(BENCHY, None, None, ((0, 0),))]
    assert ScheduleStore(tmp_path / "jobs.json").load()[0].state is JobState.STARTING


def test_the_tolerance_is_read_fresh_so_a_change_needs_no_restart(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    assert service.tolerance_seconds() == 5 * 60

    (tmp_path / "user_vars.json").write_text(
        json.dumps({"START_TOLERANCE_MINUTES": 12}), encoding="utf-8"
    )
    assert service.tolerance_seconds() == 12 * 60


def test_a_missing_or_broken_user_vars_file_is_the_default(tmp_path: Path) -> None:
    assert read_tolerance_seconds(tmp_path / "never-written.json") == 5 * 60
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert read_tolerance_seconds(broken) == 5 * 60


def test_a_tolerance_written_as_text_by_the_daemon_still_reads(tmp_path: Path) -> None:
    # The config field is declared as a number, but the daemon owns this file and we are a guest.
    path = tmp_path / "user_vars.json"
    path.write_text(json.dumps({"START_TOLERANCE_MINUTES": "9"}), encoding="utf-8")
    assert read_tolerance_seconds(path) == 9 * 60


def test_a_job_landing_inside_an_earlier_ones_run_is_flagged(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    first = service.add(a_request(), LAST_NIGHT)
    second = service.add(a_request(start_at=SIX_IN_THE_MORNING + 600), LAST_NIGHT)
    clashes = overlapping_job_ids(service.jobs())
    assert clashes == {second.job_id: first.job_id}


def test_a_job_starting_after_the_earlier_one_finishes_is_not_flagged(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    service.add(a_request(), LAST_NIGHT)
    service.add(a_request(start_at=SIX_IN_THE_MORNING + BENCHY_SECONDS + 60), LAST_NIGHT)
    assert overlapping_job_ids(service.jobs()) == {}


def test_the_payload_separates_what_we_did_from_what_the_printer_says(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    service.add(a_request(), LAST_NIGHT)
    entry = payload_for(service.jobs(), {})[0]
    assert entry["state"] == "scheduled"
    assert entry["printer_says"] is None
    assert entry["projected_finish"] == SIX_IN_THE_MORNING + BENCHY_SECONDS
