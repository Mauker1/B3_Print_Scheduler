# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How much filament is left on each toolhead's spool, and whether a job needs more than that.

The readings here are the two real printers' own answers of 6 October: the U1 with the Bespok3d
Spoolman and AFC plugins, and the Ender with neither. Everything is a warning, so the tests that
matter most are the quiet ones: a printer that cannot say anything says nothing, without asking
for things it does not have and without raising.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from print_scheduler import (
    HoldReason,
    Job,
    JobRequest,
    JobState,
    MoonrakerPrinter,
    ScheduleService,
    ScheduleStore,
    Settings,
    Shortfall,
    SpoolLeft,
    coerce_spool_id,
    job_from_dict,
    needs_of,
    shortfalls,
    spools_from_afc_lanes,
    spools_from_tool_macros,
    toolhead_of_extruder,
)
from printer_stand_in import BENCHY, WHITE_PLA_METADATA, StandInPrinter, seen_on

SIX_IN_THE_MORNING = 1_758_348_000.0
LAST_NIGHT = SIX_IN_THE_MORNING - 8 * 3600
TOMORROW = SIX_IN_THE_MORNING + 24 * 3600

# `gcode_macro T0`..`T3` on the U1, as Moonraker's objects query returned them.
U1_TOOL_MACROS: dict[str, Any] = {
    "gcode_macro T0": {"spool_id": 77},
    "gcode_macro T1": {"spool_id": 154},
    "gcode_macro T2": {"spool_id": 11},
    "gcode_macro T3": {"spool_id": 129},
}

# The U1's lanes with T0's carrier attached, trimmed to the fields that matter. `map` is filled
# on E0 alone, which is why the toolhead is taken from `extruder`.
U1_AFC_LANES: dict[str, Any] = {
    "AFC_lane E0": {"extruder": "extruder", "map": ["T0"], "spool_id": 77, "mounted": True},
    "AFC_lane E1": {"extruder": "extruder1", "map": [], "spool_id": 154, "mounted": False},
    "AFC_lane E2": {"extruder": "extruder2", "map": [], "spool_id": 11, "mounted": False},
    "AFC_lane E3": {"extruder": "extruder3", "map": [], "spool_id": 129, "mounted": False},
}

# Spoolman's remaining weight for those four spools.
U1_SPOOLS_LEFT = {77: 28.408782106862986, 154: 731.7169400872014, 11: 32.14925916043012,
                  129: 256.49097977359577}

U1_COMPONENTS = ["klippy_connection", "file_manager", "history", "afc_ui_defaults", "spoolman",
                 "spoolman_proxy"]
ENDER_COMPONENTS = ["klippy_connection", "file_manager", "history", "update_manager", "timelapse"]


# ---- reading the parts ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [(77, 77), ("11", 11), (" 11 ", 11), (0, None), ("0", None), ("", None), (None, None),
     (True, None), (-3, None), ("eleven", None), (11.0, None)],
)
def test_a_spool_id_arrives_as_a_number_or_as_text_and_zero_means_none(
    value: object, expected: int | None
) -> None:
    assert coerce_spool_id(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("extruder", 0), ("extruder1", 1), ("extruder3", 3), ("heater_bed", None), ("", None)],
)
def test_an_extruder_name_says_which_toolhead(name: str, expected: int | None) -> None:
    assert toolhead_of_extruder(name) == expected


def test_the_tool_macros_say_which_spool_each_toolhead_holds() -> None:
    assert spools_from_tool_macros(U1_TOOL_MACROS) == {0: 77, 1: 154, 2: 11, 3: 129}


def test_a_tool_macro_with_no_spool_says_nothing_about_that_toolhead() -> None:
    status = {**U1_TOOL_MACROS, "gcode_macro T1": {"spool_id": ""},
              "gcode_macro T2": {}, "gcode_macro PRINT_START": {"spool_id": 5}}
    assert spools_from_tool_macros(status) == {0: 77, 3: 129}


def test_afc_lanes_are_read_by_their_extruder_not_their_map() -> None:
    assert spools_from_afc_lanes(U1_AFC_LANES) == {0: 77, 1: 154, 2: 11, 3: 129}


def test_a_lane_with_a_card_id_written_as_text_still_counts() -> None:
    lanes = {"AFC_lane E2": {"extruder": "extruder2", "spool_id": "11"}}
    assert spools_from_afc_lanes(lanes) == {2: 11}


# ---- asking Moonraker ----------------------------------------------------------------------------


class ScriptedMoonraker(MoonrakerPrinter):
    """A MoonrakerPrinter whose transport answers from a script and remembers what it was asked."""

    def __init__(self, answers: dict[str, Any]) -> None:
        super().__init__("http://printer.invalid")
        self.answers = answers
        self.asked: list[str] = []

    def _request(
        self, path: str, method: str, timeout_seconds: float, body: Any = None
    ) -> Any:
        asked = path if body is None else f"{path} {body['path']}"
        self.asked.append(asked)
        answer = self.answers.get(asked)
        if answer is None:
            raise OSError(f"HTTP 404 for {asked}")
        if isinstance(answer, Exception):
            raise answer
        return {"result": answer}


def a_u1(**changes: Any) -> ScriptedMoonraker:
    answers: dict[str, Any] = {
        "/server/info": {"components": U1_COMPONENTS},
        "/server/spoolman/status": {"spoolman_connected": True, "spool_id": 77},
        "/printer/objects/list": {"objects": ["print_stats", *U1_TOOL_MACROS, *U1_AFC_LANES]},
        "/printer/objects/query?gcode_macro%20T0&gcode_macro%20T1&gcode_macro%20T2"
        "&gcode_macro%20T3": {"status": U1_TOOL_MACROS},
        "/printer/objects/query?AFC_lane%20E0&AFC_lane%20E1&AFC_lane%20E2&AFC_lane%20E3":
            {"status": U1_AFC_LANES},
    }
    for spool_id, grams in U1_SPOOLS_LEFT.items():
        answers[f"/server/spoolman/proxy /v1/spool/{spool_id}"] = {
            "id": spool_id, "remaining_weight": grams
        }
    answers.update(changes)
    return ScriptedMoonraker(answers)


def test_the_u1_says_what_is_left_on_each_toolhead() -> None:
    printer = a_u1()
    assert printer.filament_left() == (
        SpoolLeft(toolhead=0, spool_id=77, grams=U1_SPOOLS_LEFT[77]),
        SpoolLeft(toolhead=1, spool_id=154, grams=U1_SPOOLS_LEFT[154]),
        SpoolLeft(toolhead=2, spool_id=11, grams=U1_SPOOLS_LEFT[11]),
        SpoolLeft(toolhead=3, spool_id=129, grams=U1_SPOOLS_LEFT[129]),
    )
    # The macros answered, so the lanes were never asked.
    assert not any("AFC_lane" in asked for asked in printer.asked)


def test_the_lanes_answer_when_the_tool_macros_hold_no_spools() -> None:
    empty_macros = {name: {"spool_id": ""} for name in U1_TOOL_MACROS}
    printer = a_u1(**{
        "/printer/objects/query?gcode_macro%20T0&gcode_macro%20T1&gcode_macro%20T2"
        "&gcode_macro%20T3": {"status": empty_macros},
    })
    assert [one.spool_id for one in printer.filament_left()] == [77, 154, 11, 129]


def test_the_ender_is_asked_one_question_and_nothing_that_would_404() -> None:
    printer = ScriptedMoonraker({"/server/info": {"components": ENDER_COMPONENTS}})
    assert printer.filament_left() == ()
    assert printer.asked == ["/server/info"]


def test_spoolman_installed_but_not_connected_says_nothing() -> None:
    printer = a_u1(**{"/server/spoolman/status": {"spoolman_connected": False}})
    assert printer.filament_left() == ()
    assert printer.asked == ["/server/info", "/server/spoolman/status"]


def test_nothing_saying_which_spool_is_where_says_nothing() -> None:
    printer = a_u1(**{"/printer/objects/list": {"objects": ["print_stats", "toolhead"]}})
    assert printer.filament_left() == ()


def test_a_spool_spoolman_cannot_describe_is_left_out_and_the_rest_still_count() -> None:
    printer = a_u1(**{"/server/spoolman/proxy /v1/spool/154": OSError("HTTP 404")})
    assert [one.toolhead for one in printer.filament_left()] == [0, 2, 3]


def test_a_printer_that_stops_answering_part_way_says_nothing_rather_than_raising() -> None:
    printer = a_u1(**{"/printer/objects/list": OSError("connection reset")})
    assert printer.filament_left() == ()


# ---- whether a job needs more than is left -------------------------------------------------------


LEFT_ON_THE_U1 = tuple(
    SpoolLeft(toolhead=toolhead, spool_id=spool_id, grams=U1_SPOOLS_LEFT[spool_id])
    for toolhead, spool_id in enumerate((77, 154, 11, 129))
)


def test_a_toolhead_with_less_left_than_needed_is_named() -> None:
    assert shortfalls([(0, 40.0), (1, 40.0)], LEFT_ON_THE_U1) == (
        Shortfall(toolhead=0, needed=40.0, left=U1_SPOOLS_LEFT[77]),
    )


def test_two_slots_on_one_spool_are_added_together() -> None:
    assert shortfalls([(2, 20.0)], LEFT_ON_THE_U1) == ()
    assert [one.needed for one in shortfalls([(2, 20.0), (2, 20.0)], LEFT_ON_THE_U1)] == [40.0]


def test_exactly_enough_is_not_a_shortage() -> None:
    assert shortfalls([(0, U1_SPOOLS_LEFT[77])], LEFT_ON_THE_U1) == ()


def test_a_toolhead_nobody_can_measure_is_not_a_shortage() -> None:
    assert shortfalls([(5, 999.0)], LEFT_ON_THE_U1) == ()


def a_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "job_id": "job-one",
        "filename": BENCHY,
        "start_at": SIX_IN_THE_MORNING,
        "bed_acknowledged": True,
        "toolheads_seen": seen_on(WHITE_PLA_METADATA),
        "slot_grams": ((0, 40.0),),
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def test_a_job_takes_from_the_toolheads_on_its_recorded_map() -> None:
    # Slot 0 of the white PLA file runs on T2.
    assert needs_of(a_job()) == [(2, 40.0)]


def test_a_job_with_nothing_to_map_takes_slot_n_from_t_n() -> None:
    assert needs_of(a_job(toolheads_seen=(), slot_grams=((1, 5.0),))) == [(1, 5.0)]


def test_a_job_waiting_for_its_map_or_with_no_grams_says_nothing() -> None:
    assert needs_of(a_job(toolheads_seen=None)) == []
    assert needs_of(a_job(slot_grams=())) == []


def test_the_grams_survive_the_file_and_an_older_file_has_none() -> None:
    assert job_from_dict(a_job().to_dict()).slot_grams == ((0, 40.0),)
    older = a_job().to_dict()
    del older["slot_grams"]
    assert job_from_dict(older).slot_grams == ()


# ---- the service: reading once in a while, and telling the page ----------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def a_service(
    tmp_path: Path, printer: StandInPrinter, clock: Clock | None = None
) -> ScheduleService:
    return ScheduleService(
        ScheduleStore(tmp_path / "jobs.json"),
        printer,
        Settings(tmp_path / "user_vars.json"),
        clock=clock or Clock(),
    )


def test_one_reading_is_reused_for_thirty_seconds(tmp_path: Path) -> None:
    clock = Clock()
    printer = StandInPrinter(spools_left=LEFT_ON_THE_U1)
    service = a_service(tmp_path, printer, clock)
    assert service.filament_left() == LEFT_ON_THE_U1
    clock.now += 29
    service.filament_left()
    assert printer.asked_for_filament_left == 1
    clock.now += 2
    service.filament_left()
    assert printer.asked_for_filament_left == 2


def test_a_scheduled_job_records_the_grams_each_slot_needs(tmp_path: Path) -> None:
    service = a_service(tmp_path, StandInPrinter(describes=dict(WHITE_PLA_METADATA)))
    request = JobRequest(filename=BENCHY, start_at=SIX_IN_THE_MORNING, bed_acknowledged=True)
    assert service.add(request, LAST_NIGHT).slot_grams == ((0, 0.07),)


def test_a_waiting_row_says_which_toolhead_is_short(tmp_path: Path) -> None:
    low_on_t2 = (SpoolLeft(toolhead=2, spool_id=11, grams=32.1),)
    ScheduleStore(tmp_path / "jobs.json").save([
        a_job(),
        a_job(job_id="small", slot_grams=((0, 1.0),)),
        replace(a_job(job_id="ran"), state=JobState.STARTED),
    ])
    service = a_service(tmp_path, StandInPrinter(spools_left=low_on_t2))
    rows = {row["job_id"]: row for row in service.schedule_payload()["jobs"]}
    assert rows["job-one"]["filament_short"] == [{"toolhead": 2, "needed": 40.0, "left": 32.1}]
    assert rows["small"]["filament_short"] == []
    assert rows["ran"]["filament_short"] == []


def test_nothing_is_asked_when_no_waiting_job_could_be_short(tmp_path: Path) -> None:
    printer = StandInPrinter(spools_left=LEFT_ON_THE_U1)
    ScheduleStore(tmp_path / "jobs.json").save([a_job(slot_grams=())])
    a_service(tmp_path, printer).schedule_payload()
    assert printer.asked_for_filament_left == 0



# ---- a job held over its map: the offer, and accepting it ---------------------------------------


def a_job_from_before_maps(**overrides: object) -> Job:
    """The Bunny case: held because nobody saw its map, with no grams of its own."""
    defaults: dict[str, object] = {
        "toolheads_seen": None,
        "slot_grams": (),
        "hold": HoldReason.MAP_NOT_CONFIRMED,
        "held_at": LAST_NIGHT,
    }
    defaults.update(overrides)
    return a_job(**defaults)


SHORT_ON_T2 = (SpoolLeft(toolhead=2, spool_id=11, grams=0.05),)


def test_the_offer_on_a_held_row_says_its_spool_is_short(tmp_path: Path) -> None:
    # The white PLA file needs 0.07 g from T2, which the offer would print from.
    ScheduleStore(tmp_path / "jobs.json").save([a_job_from_before_maps()])
    printer = StandInPrinter(describes=dict(WHITE_PLA_METADATA), spools_left=SHORT_ON_T2)
    [row] = a_service(tmp_path, printer).schedule_payload()["jobs"]
    assert row["toolheads_proposal"]["filament_short"] == [
        {"toolhead": 2, "needed": 0.07, "left": 0.05}
    ]
    # Said once, on the offer, and not again for a map the job is not going to use.
    assert row["filament_short"] == []


def test_an_offer_with_enough_on_its_spools_says_nothing(tmp_path: Path) -> None:
    ScheduleStore(tmp_path / "jobs.json").save([a_job_from_before_maps()])
    printer = StandInPrinter(describes=dict(WHITE_PLA_METADATA))
    [row] = a_service(tmp_path, printer).schedule_payload()["jobs"]
    assert row["toolheads_proposal"]["filament_short"] == []


def test_accepting_a_map_records_the_grams_so_the_row_keeps_warning(tmp_path: Path) -> None:
    ScheduleStore(tmp_path / "jobs.json").save([a_job_from_before_maps(start_at=TOMORROW)])
    printer = StandInPrinter(describes=dict(WHITE_PLA_METADATA), spools_left=SHORT_ON_T2)
    service = a_service(tmp_path, printer)
    accepted = service.accept_toolheads("job-one", [(0, 2)], SIX_IN_THE_MORNING)
    assert accepted.slot_grams == ((0, 0.07),)
    [row] = service.schedule_payload()["jobs"]
    assert row["filament_short"] == [{"toolhead": 2, "needed": 0.07, "left": 0.05}]
