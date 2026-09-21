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
    Job,
    JobRequest,
    JobState,
    LoadedFilament,
    PrintRecord,
    ScheduleRejectedError,
    ScheduleService,
    ScheduleStore,
    overlapping_job_ids,
    payload_for,
    projected_finish,
    read_settled_kept,
    read_tolerance_seconds,
    trimmed_to,
)
from printer_stand_in import (
    BENCHY,
    FOUR_TOOL_METADATA,
    PRINTING_OURS,
    TOO_MUCH_ASA_METADATA,
    TWO_COLOUR_METADATA,
    WHITE_PLA_METADATA,
    StandInPrinter,
)

SIX_IN_THE_MORNING = 1_758_348_000.0
LAST_NIGHT = SIX_IN_THE_MORNING - 8 * 3600
BENCHY_SECONDS = 2920.0
# Measured on the printer: 638.67 total against 40.03 printing.
SETUP_SECONDS = 598.64


def a_finished_print() -> PrintRecord:
    return PrintRecord(
        job_id="0000BE",
        filename=BENCHY,
        start_time=LAST_NIGHT,
        status="completed",
        end_time=LAST_NIGHT + 638.67,
        total_duration=638.67,
        print_duration=40.03,
    )


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


def test_a_four_slot_file_is_scheduled_and_every_slot_gets_a_toolhead(tmp_path: Path) -> None:
    service = a_service(tmp_path, StandInPrinter(describes=dict(FOUR_TOOL_METADATA)))
    job = service.add(a_request(), LAST_NIGHT)
    assert job.state is JobState.SCHEDULED
    plan = service.tool_plan(service.file_summary(BENCHY))
    assert plan.problem is None
    assert len(plan.assignments) == 4
    assert len({one.toolhead for one in plan.assignments}) == 4


def test_two_slots_of_one_material_go_to_the_toolheads_holding_their_colours(
    tmp_path: Path,
) -> None:
    # The case the identity map would have got wrong in both directions: slot 0 wants the white
    # PLA on T2 and slot 1 the purple on T3.
    service = a_service(tmp_path, StandInPrinter(describes=dict(TWO_COLOUR_METADATA)))
    service.add(a_request(), LAST_NIGHT)
    plan = service.tool_plan(service.file_summary(BENCHY))
    assert plan.as_pairs() == ((0, 2), (1, 3))


def test_more_slots_of_a_material_than_the_machine_holds_is_refused(tmp_path: Path) -> None:
    # Three ASA slots against one ASA toolhead. A toolhead cannot run two slots of a print, so
    # the third has nowhere to go and the job is refused rather than quietly doubled up.
    printer = StandInPrinter(describes=dict(TOO_MUCH_ASA_METADATA))
    with pytest.raises(ScheduleRejectedError, match="needs 3 toolheads with ASA"):
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


def test_the_projection_adds_the_printers_own_setup_time(tmp_path: Path) -> None:
    # The defect this version exists for: the page quoted 26 seconds for a print that took
    # ten minutes and twenty six seconds to be done with.
    job = a_service(tmp_path).add(a_request(), LAST_NIGHT)
    assert projected_finish(job, SETUP_SECONDS) == (
        SIX_IN_THE_MORNING + SETUP_SECONDS + BENCHY_SECONDS
    )


def test_a_printer_with_nothing_measured_projects_without_it(tmp_path: Path) -> None:
    job = a_service(tmp_path).add(a_request(), LAST_NIGHT)
    assert projected_finish(job, None) == SIX_IN_THE_MORNING + BENCHY_SECONDS


def test_the_overlap_warning_uses_the_same_setup_time(tmp_path: Path) -> None:
    # Two jobs far enough apart to look safe on the slicer estimate alone, and not once the
    # printer's own ten minutes are counted. Without this the warning arrives after the fact.
    service = a_service(tmp_path)
    first = service.add(a_request(), LAST_NIGHT)
    second = service.add(
        a_request(start_at=SIX_IN_THE_MORNING + BENCHY_SECONDS + 60), LAST_NIGHT
    )
    assert overlapping_job_ids(service.jobs()) == {}
    assert overlapping_job_ids(service.jobs(), SETUP_SECONDS) == {second.job_id: first.job_id}


def test_the_page_is_told_the_setup_time_and_gets_it_off_one_reading(tmp_path: Path) -> None:
    printer = StandInPrinter(remembers=(a_finished_print(),))
    service = a_service(tmp_path, printer)
    service.add(a_request(), LAST_NIGHT)
    payload = service.schedule_payload()
    assert payload["setup"] is not None
    assert round(payload["setup"]["typical"], 2) == SETUP_SECONDS
    assert payload["jobs"][0]["projected_finish"] == (
        SIX_IN_THE_MORNING + payload["setup"]["typical"] + BENCHY_SECONDS
    )


def test_the_finish_comes_out_as_a_range_when_the_printer_has_two_habits(
    tmp_path: Path,
) -> None:
    # The two clusters this printer actually has: a couple of minutes, or ten. The middle of
    # them is a moment almost no print finishes at, so both ends are published.
    quick = replace(a_finished_print(), job_id="0000C0", total_duration=338.41,
                    print_duration=128.60)
    printer = StandInPrinter(remembers=(quick, a_finished_print()))
    service = a_service(tmp_path, printer)
    service.add(a_request(), LAST_NIGHT)
    entry = service.schedule_payload()["jobs"][0]
    assert entry["projected_finish_from"] == SIX_IN_THE_MORNING + 209.81 + BENCHY_SECONDS
    assert entry["projected_finish_to"] == SIX_IN_THE_MORNING + SETUP_SECONDS + BENCHY_SECONDS
    assert entry["projected_finish_from"] < entry["projected_finish"] <= entry[
        "projected_finish_to"
    ]


def test_a_printer_with_one_habit_publishes_the_same_time_at_both_ends(
    tmp_path: Path,
) -> None:
    printer = StandInPrinter(remembers=(a_finished_print(),))
    service = a_service(tmp_path, printer)
    service.add(a_request(), LAST_NIGHT)
    entry = service.schedule_payload()["jobs"][0]
    assert entry["projected_finish_from"] == entry["projected_finish_to"]


def test_the_overlap_warning_assumes_the_slowest_setup_the_printer_has_managed(
    tmp_path: Path,
) -> None:
    # A warning that a job might collide is worth having; a collision nobody warned about
    # costs a print. So this one is deliberately pessimistic where the finish time is not.
    quick = replace(a_finished_print(), job_id="0000C0", total_duration=338.41,
                    print_duration=128.60)
    printer = StandInPrinter(remembers=(quick, a_finished_print()))
    service = a_service(tmp_path, printer)
    first = service.add(a_request(), LAST_NIGHT)
    second = service.add(
        a_request(start_at=SIX_IN_THE_MORNING + BENCHY_SECONDS + 400), LAST_NIGHT
    )
    entries = {one["job_id"]: one for one in service.schedule_payload()["jobs"]}
    # 400 seconds clear of the typical setup, not clear of the slowest one.
    assert entries[second.job_id]["overlaps_with"] == first.job_id


def test_a_printer_that_cannot_be_reached_still_renders_the_schedule(tmp_path: Path) -> None:
    printer = StandInPrinter(history_raises=OSError("connection refused"))
    service = a_service(tmp_path, printer)
    service.add(a_request(), LAST_NIGHT)
    payload = service.schedule_payload()
    assert payload["setup"] is None
    assert payload["jobs"][0]["projected_finish"] == SIX_IN_THE_MORNING + BENCHY_SECONDS


def a_settled_job(**overrides: object) -> Job:
    base = Job(
        job_id=str(overrides.pop("job_id", "settled")),
        filename=BENCHY,
        start_at=SIX_IN_THE_MORNING,
        state=JobState.CANCELLED,
        decided_at=SIX_IN_THE_MORNING,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_a_job_that_has_not_run_is_never_trimmed_however_low_the_cap() -> None:
    # The list is a promise about the future. Quietly forgetting one would be the worst thing
    # this page could do, so the cap cannot reach a job that has not settled.
    pending = Job(job_id="pending", filename=BENCHY, start_at=SIX_IN_THE_MORNING)
    kept = trimmed_to([pending, a_settled_job()], 0)
    assert [job.job_id for job in kept] == ["pending"]


def test_the_oldest_settled_jobs_go_first() -> None:
    jobs = [
        a_settled_job(job_id="oldest", decided_at=100.0),
        a_settled_job(job_id="newest", decided_at=300.0),
        a_settled_job(job_id="middle", decided_at=200.0),
    ]
    kept = trimmed_to(jobs, 2)
    assert {job.job_id for job in kept} == {"newest", "middle"}
    # The order on the page does not reshuffle around a trim.
    assert [job.job_id for job in kept] == ["newest", "middle"]


def test_a_list_under_the_cap_is_left_exactly_as_it_was() -> None:
    jobs = [a_settled_job(job_id="one"), a_settled_job(job_id="two")]
    assert trimmed_to(jobs, 25) == jobs


def test_the_cap_applies_itself_whenever_the_schedule_is_written(tmp_path: Path) -> None:
    (tmp_path / "user_vars.json").write_text(json.dumps({"SETTLED_JOBS_KEPT": 1}))
    service = a_service(tmp_path)
    first = service.add(a_request(), LAST_NIGHT)
    second = service.add(a_request(start_at=SIX_IN_THE_MORNING + 3600), LAST_NIGHT)
    service.cancel(first.job_id, LAST_NIGHT)
    service.cancel(second.job_id, LAST_NIGHT + 1)
    remaining = [job.job_id for job in service.jobs()]
    assert remaining == [second.job_id]


def test_an_unset_cap_is_the_default_rather_than_nothing_kept(tmp_path: Path) -> None:
    assert read_settled_kept(tmp_path / "absent.json") == 25
    (tmp_path / "nonsense.json").write_text(json.dumps({"SETTLED_JOBS_KEPT": "many"}))
    assert read_settled_kept(tmp_path / "nonsense.json") == 25
    (tmp_path / "negative.json").write_text(json.dumps({"SETTLED_JOBS_KEPT": -3}))
    assert read_settled_kept(tmp_path / "negative.json") == 25
    # Zero is a real answer: keep nothing once a job has settled.
    (tmp_path / "none.json").write_text(json.dumps({"SETTLED_JOBS_KEPT": 0}))
    assert read_settled_kept(tmp_path / "none.json") == 0


def test_a_settled_job_can_be_forgotten(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    job = service.add(a_request(), LAST_NIGHT)
    service.cancel(job.job_id, LAST_NIGHT)
    service.forget(job.job_id)
    assert service.jobs() == []


def test_a_job_that_has_not_run_cannot_be_forgotten(tmp_path: Path) -> None:
    service = a_service(tmp_path)
    job = service.add(a_request(), LAST_NIGHT)
    with pytest.raises(ScheduleRejectedError, match="Cancel it first"):
        service.forget(job.job_id)
    assert len(service.jobs()) == 1


def test_clearing_the_settled_list_leaves_everything_scheduled_alone(tmp_path: Path) -> None:
    # The one property that makes the button safe to press without reading it.
    service = a_service(tmp_path)
    doomed = service.add(a_request(), LAST_NIGHT)
    service.cancel(doomed.job_id, LAST_NIGHT)
    pending = service.add(a_request(start_at=SIX_IN_THE_MORNING + 7200), LAST_NIGHT)
    assert service.forget_every_settled_job() == 1
    assert [job.job_id for job in service.jobs()] == [pending.job_id]
