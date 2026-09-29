# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choosing the toolheads yourself, and the one rule that covers both ways of choosing.

The rule is that a job starts only on a map somebody saw. The runner's half of it, comparing the
record with what is loaded at the moment of starting, is in `test_runner.py`. This is the rest:
what gets recorded when a job is scheduled or edited, what a person's own map may and may not be,
the jobs from before maps were recorded, answering a hold by accepting a map, and how all of it
is stored so that an older version reading the schedule does not lose it.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from print_scheduler import (
    A_LONG_SILENCE_SECONDS,
    Heartbeat,
    HoldReason,
    Job,
    JobRequest,
    JobState,
    LoadedFilament,
    Message,
    ScheduleRejectedError,
    ScheduleService,
    ScheduleStore,
    SeenToolhead,
    Settings,
    job_from_dict,
)
from printer_stand_in import (
    BENCHY,
    IDLE,
    LOADED_ON_THE_PRINTER,
    TOO_MUCH_ASA_METADATA,
    TWO_COLOUR_METADATA,
    WHITE_PLA_METADATA,
    StandInPrinter,
    seen_on,
)

SIX_IN_THE_MORNING = 1_758_348_000.0
LAST_NIGHT = SIX_IN_THE_MORNING - 8 * 3600
TOMORROW = SIX_IN_THE_MORNING + 24 * 3600
ASA_ON_T0 = (SeenToolhead(slot=0, toolhead=0, material="ASA", colour="000000"),)


def a_service(
    tmp_path: Path,
    printer: StandInPrinter | None = None,
    heartbeat: Heartbeat | None = None,
) -> ScheduleService:
    return ScheduleService(
        ScheduleStore(tmp_path / "jobs.json"),
        printer or StandInPrinter(),
        Settings(tmp_path / "user_vars.json"),
        heartbeat,
    )


def a_service_holding(
    tmp_path: Path, jobs: list[Job], printer: StandInPrinter | None = None
) -> ScheduleService:
    ScheduleStore(tmp_path / "jobs.json").save(jobs)
    return a_service(tmp_path, printer)


def a_request(**overrides: object) -> JobRequest:
    base = JobRequest(filename=BENCHY, start_at=SIX_IN_THE_MORNING, bed_acknowledged=True)
    return replace(base, **overrides)  # type: ignore[arg-type]


def a_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "job_id": "job-one",
        "filename": BENCHY,
        "start_at": SIX_IN_THE_MORNING,
        "bed_acknowledged": True,
        "toolheads_seen": seen_on(),
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def refusal_of(action: object) -> Message:
    with pytest.raises(ScheduleRejectedError) as refused:
        action()  # type: ignore[operator]
    return refused.value.said.key


# ---- stored so that an older version does not lose it -----------------------------------------


@pytest.mark.parametrize(
    ("reason", "as_0_4_1_reads_it"),
    [
        (HoldReason.TOOLHEADS_CHANGED, "bed-not-confirmed"),
        (HoldReason.MAP_NOT_CONFIRMED, "long-silence"),
        (HoldReason.BED_NOT_CONFIRMED, "bed-not-confirmed"),
        (HoldReason.LONG_SILENCE, "long-silence"),
    ],
)
def test_a_hold_is_written_so_0_4_1_still_reads_a_hold(
    reason: HoldReason, as_0_4_1_reads_it: str
) -> None:
    """0.4.1 sets the whole schedule aside on a reason it does not know, so it never sees one."""
    written = a_job(hold=reason, held_at=SIX_IN_THE_MORNING).to_dict()
    assert written["hold"] == as_0_4_1_reads_it
    assert written["hold_reason"] == reason.value
    assert job_from_dict(written).hold is reason


def test_a_hold_from_a_later_version_is_still_a_hold() -> None:
    written = a_job().to_dict()
    written["hold_reason"] = "a-question-from-the-future"
    written["hold"] = "bed-not-confirmed"
    assert job_from_dict(written).hold is HoldReason.BED_NOT_CONFIRMED
    written["hold"] = "another-one"
    assert job_from_dict(written).hold is HoldReason.LONG_SILENCE


def test_a_schedule_with_a_reason_nobody_knows_is_not_set_aside(tmp_path: Path) -> None:
    written = a_job().to_dict()
    written["hold_reason"] = "a-question-from-the-future"
    written["hold"] = "another-one"
    (tmp_path / "jobs.json").write_text(json.dumps({"jobs": [written]}), encoding="utf-8")
    loaded = ScheduleStore(tmp_path / "jobs.json").load()
    assert [job.hold for job in loaded] == [HoldReason.LONG_SILENCE]


def test_never_recorded_and_nothing_to_record_are_stored_as_different_things() -> None:
    assert job_from_dict(a_job(toolheads_seen=None).to_dict()).toolheads_seen is None
    assert job_from_dict(a_job(toolheads_seen=()).to_dict()).toolheads_seen == ()
    assert job_from_dict(a_job().to_dict()).toolheads_seen == seen_on()


def test_a_chosen_map_survives_the_file() -> None:
    chosen = a_job(toolheads_chosen=((0, 2), (1, 2)))
    assert job_from_dict(chosen.to_dict()).toolheads_chosen == ((0, 2), (1, 2))
    assert job_from_dict(a_job().to_dict()).toolheads_chosen is None


# ---- what is recorded when a job is scheduled -------------------------------------------------


def test_a_job_the_scheduler_mapped_records_the_map_it_showed(tmp_path: Path) -> None:
    job = a_service(tmp_path).add(a_request(), LAST_NIGHT)
    assert job.toolheads_chosen is None
    assert job.toolheads_seen == ASA_ON_T0


def test_a_map_somebody_chose_is_recorded_as_theirs(tmp_path: Path) -> None:
    # The file wants white PLA, which the scheduler would put on T2. The person wants the blue.
    service = a_service(tmp_path, StandInPrinter(describes=dict(WHITE_PLA_METADATA)))
    job = service.add(a_request(toolheads_chosen=((0, 1),)), LAST_NIGHT)
    assert job.toolheads_chosen == ((0, 1),)
    assert job.toolheads_seen == (
        SeenToolhead(slot=0, toolhead=1, material="PLA", colour="0A2989"),
    )


def test_a_different_material_needs_the_person_to_say_so(tmp_path: Path) -> None:
    service = a_service(tmp_path, StandInPrinter(describes=dict(WHITE_PLA_METADATA)))
    on_the_asa = a_request(toolheads_chosen=((0, 0),))
    assert refusal_of(lambda: service.add(on_the_asa, LAST_NIGHT)) is (
        Message.MATERIAL_NOT_ACKNOWLEDGED
    )
    job = service.add(replace(on_the_asa, materials_acknowledged=frozenset({0})), LAST_NIGHT)
    assert job.toolheads_seen == ASA_ON_T0


def test_saying_so_for_one_slot_is_not_saying_so_for_another(tmp_path: Path) -> None:
    service = a_service(tmp_path, StandInPrinter(describes=dict(TWO_COLOUR_METADATA)))
    both_on_the_asa = a_request(
        toolheads_chosen=((0, 0), (1, 0)), materials_acknowledged=frozenset({0})
    )
    with pytest.raises(ScheduleRejectedError) as refused:
        service.add(both_on_the_asa, LAST_NIGHT)
    assert refused.value.said.values["slot"] == 1


def test_two_slots_on_one_toolhead_are_allowed(tmp_path: Path) -> None:
    service = a_service(tmp_path, StandInPrinter(describes=dict(TWO_COLOUR_METADATA)))
    job = service.add(a_request(toolheads_chosen=((0, 2), (1, 2))), LAST_NIGHT)
    assert [(one.slot, one.toolhead) for one in job.toolheads_seen or ()] == [(0, 2), (1, 2)]


def test_a_person_can_schedule_a_file_the_scheduler_could_not_map(tmp_path: Path) -> None:
    # Three ASA slots and one ASA toolhead: no map of the scheduler's own, and the person's is
    # all three from the one spool.
    service = a_service(tmp_path, StandInPrinter(describes=dict(TOO_MUCH_ASA_METADATA)))
    assert refusal_of(lambda: service.add(a_request(), LAST_NIGHT)) is (
        Message.NOT_ENOUGH_OF_MATERIAL
    )
    job = service.add(a_request(toolheads_chosen=((0, 0), (1, 0), (2, 0))), LAST_NIGHT)
    assert job.toolheads_chosen == ((0, 0), (1, 0), (2, 0))


@pytest.mark.parametrize(
    ("chosen", "why"),
    [
        (((1, 0),), Message.MAP_INCOMPLETE),
        (((0, 0), (0, 1)), Message.MAP_INCOMPLETE),
        ((), Message.MAP_INCOMPLETE),
        (((0, 7),), Message.MAP_TOOLHEAD_UNKNOWN),
    ],
)
def test_a_map_that_cannot_be_carried_out_is_refused(
    tmp_path: Path, chosen: tuple[tuple[int, int], ...], why: Message
) -> None:
    service = a_service(tmp_path)
    assert refusal_of(lambda: service.add(a_request(toolheads_chosen=chosen), LAST_NIGHT)) is why


def test_an_empty_toolhead_cannot_be_chosen(tmp_path: Path) -> None:
    emptied = tuple(
        replace(one, present=False) if one.index == 1 else one for one in LOADED_ON_THE_PRINTER
    )
    service = a_service(tmp_path, StandInPrinter(loads=emptied))
    chosen = a_request(toolheads_chosen=((0, 1),), materials_acknowledged=frozenset({0}))
    assert refusal_of(lambda: service.add(chosen, LAST_NIGHT)) is Message.MAP_TOOLHEAD_EMPTY


def test_a_map_sent_to_a_printer_with_nothing_to_map_means_nothing(tmp_path: Path) -> None:
    service = a_service(tmp_path, StandInPrinter(loads=()))
    job = service.add(a_request(toolheads_chosen=((0, 3),)), LAST_NIGHT)
    assert job.toolheads_chosen is None
    assert job.toolheads_seen == ()


def test_editing_answers_a_toolhead_hold_with_the_map_on_screen_now(tmp_path: Path) -> None:
    stale = (SeenToolhead(slot=0, toolhead=0, material="PETG", colour="FFFFFF"),)
    held = a_job(toolheads_seen=stale, hold=HoldReason.TOOLHEADS_CHANGED, held_at=LAST_NIGHT,
                 hold_detail_key="detail.toolheads-changed")
    service = a_service_holding(tmp_path, [held])
    edited = service.update("job-one", a_request(start_at=TOMORROW), SIX_IN_THE_MORNING)
    assert edited.hold is None
    assert edited.hold_detail_key == ""
    assert edited.toolheads_seen == seen_on()


def test_editing_leaves_a_question_about_the_bed_standing(tmp_path: Path) -> None:
    held = a_job(hold=HoldReason.BED_NOT_CONFIRMED, held_at=LAST_NIGHT)
    service = a_service_holding(tmp_path, [held])
    edited = service.update("job-one", a_request(start_at=TOMORROW), SIX_IN_THE_MORNING)
    assert edited.hold is HoldReason.BED_NOT_CONFIRMED


# ---- jobs from before maps were recorded ------------------------------------------------------


def test_a_job_from_before_maps_is_held_as_soon_as_the_scheduler_runs(tmp_path: Path) -> None:
    """Tonight, not at six in the morning: it is not due until tomorrow and is held anyway."""
    service = a_service_holding(tmp_path, [a_job(toolheads_seen=None, start_at=TOMORROW)])
    service.tick(SIX_IN_THE_MORNING)
    [job] = service.jobs()
    assert job.hold is HoldReason.MAP_NOT_CONFIRMED
    assert job.hold_detail_key == "detail.map-never-confirmed"
    assert job.state is JobState.SCHEDULED


def test_a_job_from_before_maps_is_not_held_where_there_is_no_map(tmp_path: Path) -> None:
    printer = StandInPrinter(loads=())
    service = a_service_holding(tmp_path, [a_job(toolheads_seen=None)], printer)
    service.tick(SIX_IN_THE_MORNING)
    [job] = service.jobs()
    assert job.state is JobState.STARTING
    assert printer.started == [(BENCHY, None, None, ())]


def test_a_printer_not_answering_yet_is_asked_again_on_the_next_tick(tmp_path: Path) -> None:
    printer = StandInPrinter(loading_raises=OSError("connection refused"))
    service = a_service_holding(tmp_path, [a_job(toolheads_seen=None, start_at=TOMORROW)], printer)
    service.tick(SIX_IN_THE_MORNING)
    assert not service.jobs()[0].held
    printer.loading_raises = None
    service.tick(SIX_IN_THE_MORNING + 30)
    assert service.jobs()[0].hold is HoldReason.MAP_NOT_CONFIRMED


def test_a_job_that_already_has_a_record_is_not_held(tmp_path: Path) -> None:
    service = a_service_holding(tmp_path, [a_job(start_at=TOMORROW)])
    service.tick(SIX_IN_THE_MORNING)
    assert not service.jobs()[0].held


def test_the_map_question_comes_before_the_long_silence(tmp_path: Path) -> None:
    beat = Heartbeat(tmp_path / "last-seen")
    beat.mark(LAST_NIGHT - A_LONG_SILENCE_SECONDS)
    ScheduleStore(tmp_path / "jobs.json").save([
        a_job(job_id="old", toolheads_seen=None, start_at=TOMORROW),
        a_job(job_id="new", start_at=TOMORROW),
    ])
    service = a_service(tmp_path, heartbeat=Heartbeat(tmp_path / "last-seen"))
    service.tick(SIX_IN_THE_MORNING)
    holds = {job.job_id: job.hold for job in service.jobs()}
    assert holds == {"old": HoldReason.MAP_NOT_CONFIRMED, "new": HoldReason.LONG_SILENCE}


def test_releasing_after_a_long_silence_does_not_answer_the_map_question(tmp_path: Path) -> None:
    held = a_job(toolheads_seen=None, hold=HoldReason.MAP_NOT_CONFIRMED, held_at=LAST_NIGHT)
    service = a_service_holding(tmp_path, [held])
    assert service.release_held_jobs() == 0
    assert service.jobs()[0].hold is HoldReason.MAP_NOT_CONFIRMED


# ---- answering a hold by accepting a map ------------------------------------------------------


def a_job_held_over_its_map(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "toolheads_seen": None,
        "hold": HoldReason.MAP_NOT_CONFIRMED,
        "held_at": LAST_NIGHT,
        "hold_detail_key": "detail.map-never-confirmed",
    }
    defaults.update(overrides)
    return a_job(**defaults)


def test_the_page_is_offered_the_map_a_held_job_would_start_on(tmp_path: Path) -> None:
    service = a_service_holding(
        tmp_path, [a_job_held_over_its_map(), a_job(job_id="ordinary", start_at=TOMORROW)]
    )
    rows = {row["job_id"]: row for row in service.schedule_payload()["jobs"]}
    offered = rows["job-one"]["toolheads_proposal"]
    assert offered["toolheads"] == [[0, 0]]
    assert offered["acceptable"] is True
    assert rows["job-one"]["hold_reason"] == "map-not-confirmed"
    assert rows["ordinary"]["toolheads_proposal"] is None


def test_a_map_nothing_can_make_is_offered_as_not_acceptable(tmp_path: Path) -> None:
    only_pla = (LoadedFilament(index=0, filament_type="PLA", colour="FFFFFFFF", present=True),)
    service = a_service_holding(
        tmp_path, [a_job_held_over_its_map()], StandInPrinter(loads=only_pla)
    )
    offered = service.schedule_payload()["jobs"][0]["toolheads_proposal"]
    assert offered["acceptable"] is False
    assert offered["problem_key"] == "toolhead.none-free-with-material"


def test_accepting_a_map_for_a_job_still_ahead_lets_it_stand(tmp_path: Path) -> None:
    printer = StandInPrinter()
    service = a_service_holding(tmp_path, [a_job_held_over_its_map(start_at=TOMORROW)], printer)
    accepted = service.accept_toolheads("job-one", [(0, 0)], SIX_IN_THE_MORNING)
    assert accepted.hold is None
    assert accepted.state is JobState.SCHEDULED
    assert accepted.start_at == TOMORROW
    assert accepted.toolheads_seen == seen_on()
    assert printer.started == []
    assert service.jobs()[0] == accepted


def test_accepting_a_map_for_a_job_whose_time_has_come_starts_it(tmp_path: Path) -> None:
    printer = StandInPrinter()
    service = a_service_holding(tmp_path, [a_job_held_over_its_map()], printer)
    accepted = service.accept_toolheads("job-one", [(0, 0)], SIX_IN_THE_MORNING + 3600)
    assert accepted.state is JobState.STARTING
    assert printer.started == [(BENCHY, None, None, ((0, 0),))]
    assert "You confirmed the toolhead map" in [one.detail for one in accepted.attempts]


def test_accepting_a_map_still_asks_about_the_bed(tmp_path: Path) -> None:
    printer = StandInPrinter(reports=replace(IDLE, print_state="complete"))
    service = a_service_holding(tmp_path, [a_job_held_over_its_map()], printer)
    accepted = service.accept_toolheads("job-one", [(0, 0)], SIX_IN_THE_MORNING + 3600)
    assert accepted.hold is HoldReason.BED_NOT_CONFIRMED
    assert accepted.toolheads_seen == seen_on()
    assert printer.started == []


def test_a_map_that_changed_while_somebody_looked_is_refused(tmp_path: Path) -> None:
    printer = StandInPrinter(describes=dict(WHITE_PLA_METADATA))
    held = a_job_held_over_its_map()
    service = a_service_holding(tmp_path, [held], printer)
    # The page offered T2; a spool moved and the scheduler would now say something else.
    with pytest.raises(ScheduleRejectedError) as refused:
        service.accept_toolheads("job-one", [(0, 3)], SIX_IN_THE_MORNING)
    assert refused.value.said.key is Message.TOOLHEADS_CHANGED_AGAIN
    assert service.jobs()[0] == held
    assert printer.started == []


def test_only_a_job_waiting_on_its_toolheads_takes_a_map(tmp_path: Path) -> None:
    service = a_service_holding(tmp_path, [a_job(hold=HoldReason.BED_NOT_CONFIRMED)])
    with pytest.raises(ScheduleRejectedError) as refused:
        service.accept_toolheads("job-one", [(0, 0)], SIX_IN_THE_MORNING)
    assert refused.value.said.key is Message.NOT_WAITING_FOR_THE_TOOLHEADS


def test_a_map_the_printer_cannot_make_now_cannot_be_accepted(tmp_path: Path) -> None:
    service = a_service_holding(tmp_path, [a_job_held_over_its_map()], StandInPrinter(loads=()))
    assert refusal_of(lambda: service.accept_toolheads("job-one", [], SIX_IN_THE_MORNING)) is (
        Message.NOT_REPORTED_NOW
    )


def test_cancelling_a_job_held_over_its_map_clears_what_it_was_waiting_for(
    tmp_path: Path,
) -> None:
    service = a_service_holding(tmp_path, [a_job_held_over_its_map()])
    cancelled = service.cancel("job-one", SIX_IN_THE_MORNING)
    assert cancelled.hold is None
    assert cancelled.hold_detail_key == ""
