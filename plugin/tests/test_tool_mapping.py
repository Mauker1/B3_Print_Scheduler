# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choosing which toolhead each of a file's filament slots runs on.

The first test is the regression. The first scheduled print on real hardware went into ASA because
slot 0 was taken to mean toolhead 0, and the file's slot 0 wanted white PLA, which was on toolhead
2. Everything else here exists so that cannot come back by a different route.
"""

from __future__ import annotations

import pytest
from print_scheduler import (
    LoadedFilament,
    Message,
    SeenToolhead,
    ToolUse,
    colour_distance,
    normalise_colour,
    plan_as_seen,
    plan_chosen,
    plan_tools,
    tools_used,
    what_was_seen,
)
from printer_stand_in import (
    FOUR_TOOL_METADATA,
    LOADED_ON_THE_PRINTER,
    SINGLE_TOOL_METADATA,
    TWO_COLOUR_METADATA,
    WHITE_PLA_METADATA,
)

NOTHING_LOADED: tuple[LoadedFilament, ...] = ()


def test_slot_zero_goes_to_the_toolhead_with_the_right_material_not_to_toolhead_zero() -> None:
    plan = plan_tools(tools_used(WHITE_PLA_METADATA), LOADED_ON_THE_PRINTER)
    assert plan.problem is None
    assert plan.as_pairs() == ((0, 2),)
    assert plan.assignments[0].filament_type == "PLA"


def test_a_slot_wanting_asa_goes_to_the_only_toolhead_that_has_it() -> None:
    plan = plan_tools(tools_used(SINGLE_TOOL_METADATA), LOADED_ON_THE_PRINTER)
    assert plan.as_pairs() == ((0, 0),)


def test_material_decides_even_when_the_colour_does_not_match() -> None:
    # A real file on this printer asks for white ASA while the only ASA loaded is black. That
    # print is fine. Refusing over the colour would be refusing over a slicer project setting.
    asa_in_white = dict(SINGLE_TOOL_METADATA, filament_colour="#FFFFFF;#000000;#000000;#000000")
    plan = plan_tools(tools_used(asa_in_white), LOADED_ON_THE_PRINTER)
    assert plan.as_pairs() == ((0, 0),)
    assert plan.assignments[0].colours_differ is True


def test_colour_breaks_a_tie_between_two_toolheads_of_the_same_material() -> None:
    # T1, T2 and T3 all hold PLA. Only T2 holds the white the file asks for.
    plan = plan_tools(tools_used(WHITE_PLA_METADATA), LOADED_ON_THE_PRINTER)
    assert plan.assignments[0].toolhead == 2
    assert plan.assignments[0].colours_differ is False


def test_the_lowest_toolhead_wins_when_two_are_genuinely_identical() -> None:
    twins = (
        LoadedFilament(index=0, filament_type="PLA", colour="E2DEDBFF", present=True),
        LoadedFilament(index=1, filament_type="PLA", colour="E2DEDBFF", present=True),
    )
    assert plan_tools(tools_used(WHITE_PLA_METADATA), twins).as_pairs() == ((0, 0),)


def test_no_toolhead_with_that_material_is_a_refusal_naming_what_is_loaded() -> None:
    only_asa = (LoadedFilament(index=0, filament_type="ASA", colour="000000FF", present=True),)
    plan = plan_tools(tools_used(WHITE_PLA_METADATA), only_asa)
    assert plan.problem is not None
    assert plan.problem.key is Message.NONE_FREE_WITH_MATERIAL
    assert "PLA" in plan.problem.in_english()
    assert "T0 ASA" in plan.problem.in_english()


def test_an_empty_toolhead_is_not_a_candidate() -> None:
    empty_bay = tuple(
        LoadedFilament(index=one.index, filament_type=one.filament_type, colour=one.colour,
                       present=one.index != 2)
        for one in LOADED_ON_THE_PRINTER
    )
    # T2 held the white; with it gone, T1 navy and T3 purple both still match on material, and
    # the purple is the nearer of the two to white. Not the lower numbered one: nearest.
    plan = plan_tools(tools_used(WHITE_PLA_METADATA), empty_bay)
    assert plan.as_pairs() == ((0, 3),)


def test_two_slots_never_land_on_the_same_toolhead() -> None:
    plan = plan_tools(tools_used(FOUR_TOOL_METADATA), LOADED_ON_THE_PRINTER)
    assert plan.problem is None
    toolheads = [assignment.toolhead for assignment in plan.assignments]
    assert len(set(toolheads)) == len(toolheads)


def test_more_slots_than_matching_toolheads_is_a_refusal() -> None:
    one_pla = (LoadedFilament(index=0, filament_type="PLA", colour="000000FF", present=True),)
    plan = plan_tools(tools_used(FOUR_TOOL_METADATA), one_pla)
    assert plan.problem is not None


def test_a_printer_that_tracks_nothing_has_no_map_to_get_wrong() -> None:
    plan = plan_tools(tools_used(WHITE_PLA_METADATA), NOTHING_LOADED)
    assert plan.applicable is False
    assert plan.problem is None
    assert plan.as_pairs() == ()


def test_a_file_that_declares_no_material_is_refused() -> None:
    plan = plan_tools(tools_used({"filament_used_mm": [1.0]}), LOADED_ON_THE_PRINTER)
    assert plan.problem is not None


def test_a_file_that_declares_no_slots_is_refused() -> None:
    assert plan_tools((), LOADED_ON_THE_PRINTER).problem is not None


def test_colours_are_compared_whatever_shape_they_arrive_in() -> None:
    # The file writes #E2DEDB and the printer writes E2DEDBFF for the same filament.
    assert normalise_colour("#E2DEDB") == normalise_colour("E2DEDBFF") == "E2DEDB"
    assert normalise_colour("") == ""
    assert normalise_colour("nonsense") == ""


def a_slot(slot: int, colour: str, filament_type: str = "PLA") -> ToolUse:
    return ToolUse(
        slot=slot,
        used_mm=10.0,
        used_grams=0.1,
        filament_type=filament_type,
        filament_name="",
        colour=colour,
        nozzle_temperature=220.0,
    )


def a_toolhead(index: int, colour: str, filament_type: str = "PLA") -> LoadedFilament:
    return LoadedFilament(
        index=index, filament_type=filament_type, colour=colour, present=True
    )


def test_a_colour_one_digit_out_still_finds_its_toolhead() -> None:
    # The real case, from the hardware. The slicer recorded #5343B7 for the purple and the
    # printer holds #5E43B7: a typo's worth of difference, eleven units apart in one channel.
    # Exact matching found nothing and fell back to the lowest numbered PLA toolhead, which
    # was the navy on T1, about ninety units away. Nearest is not a nicety here.
    plan = plan_tools([a_slot(0, "#5343B7")], LOADED_ON_THE_PRINTER)
    assert plan.as_pairs() == ((0, 3),)
    assert plan.assignments[0].colours_differ is True


def test_an_exact_match_still_wins_over_a_near_one() -> None:
    plan = plan_tools([a_slot(0, "#5E43B7")], LOADED_ON_THE_PRINTER)
    assert plan.as_pairs() == ((0, 3),)
    assert plan.assignments[0].colours_differ is False


def test_the_best_mapping_is_not_the_one_greedy_would_reach() -> None:
    # Slot 0 is eight units from either toolhead and takes the lower numbered one on a tie.
    # Slot 1 then has only T1 left, sixteen units away, for a total of twenty four. Choosing
    # the pair together costs eight: slot 0 gives up nothing it cannot spare.
    toolheads = (a_toolhead(0, "#000000"), a_toolhead(1, "#000010"))
    plan = plan_tools([a_slot(0, "#000008"), a_slot(1, "#000000")], toolheads)
    assert plan.as_pairs() == ((0, 1), (1, 0))


def test_two_equally_good_mappings_always_come_out_the_same_way_round() -> None:
    toolheads = (a_toolhead(0, "#FF0000"), a_toolhead(1, "#FF0000"))
    slots = [a_slot(0, "#FF0000"), a_slot(1, "#FF0000")]
    assert plan_tools(slots, toolheads).as_pairs() == ((0, 0), (1, 1))


def test_a_colour_nobody_stated_neither_attracts_nor_repels() -> None:
    assert colour_distance("", "#FF0000") is None
    assert colour_distance("#FF0000", "not a colour") is None
    # With no colour to go on it is the toolhead number that decides, not an accident.
    toolheads = (a_toolhead(2, "#FF0000"), a_toolhead(3, "#00FF00"))
    assert plan_tools([a_slot(0, "")], toolheads).as_pairs() == ((0, 2),)


def test_the_distance_is_the_straight_line_between_the_channels() -> None:
    assert colour_distance("#000000", "#000000") == 0.0
    assert colour_distance("#5343B7", "#5E43B7") == 11.0
    assert colour_distance("#000000", "#FFFFFF") == pytest.approx(441.67, abs=0.01)


def test_not_enough_toolheads_of_one_material_says_how_many_short() -> None:
    three_asa = [a_slot(index, "#000000", "ASA") for index in range(3)]
    plan = plan_tools(three_asa, LOADED_ON_THE_PRINTER)
    assert plan.problem is not None
    assert plan.problem.key is Message.NOT_ENOUGH_OF_MATERIAL
    assert "needs 3 toolheads with ASA" in plan.problem.in_english()
    assert "the printer has 1" in plan.problem.in_english()


# ---- a map somebody chose, and a map somebody saw ------------------------------------------------


def test_a_chosen_map_keeps_what_the_file_asked_for_beside_what_it_gets() -> None:
    plan = plan_chosen(tools_used(WHITE_PLA_METADATA), LOADED_ON_THE_PRINTER, [(0, 0)])
    [one] = plan.assignments
    assert (one.wanted_material, one.filament_type) == ("PLA", "ASA")
    assert one.materials_differ is True


def test_the_schedulers_own_map_never_differs_in_material() -> None:
    plan = plan_tools(tools_used(FOUR_TOOL_METADATA), LOADED_ON_THE_PRINTER)
    assert [one.materials_differ for one in plan.assignments] == [False] * 4


def test_a_slot_whose_file_names_no_material_cannot_differ_from_anything() -> None:
    unnamed = dict(WHITE_PLA_METADATA, filament_type=";ASA;PLA;PLA")
    plan = plan_chosen(tools_used(unnamed), LOADED_ON_THE_PRINTER, [(0, 0)])
    assert plan.problem is None
    assert plan.assignments[0].materials_differ is False


def test_a_chosen_map_on_a_printer_with_nothing_to_map_is_no_map() -> None:
    plan = plan_chosen(tools_used(WHITE_PLA_METADATA), NOTHING_LOADED, [(0, 3)])
    assert plan.applicable is False
    assert what_was_seen(plan) == ()


def test_what_was_seen_is_what_the_toolhead_held() -> None:
    plan = plan_tools(tools_used(WHITE_PLA_METADATA), LOADED_ON_THE_PRINTER)
    assert what_was_seen(plan) == (
        SeenToolhead(slot=0, toolhead=2, material="PLA", colour="E2DEDB"),
    )


def test_a_map_as_seen_starts_on_exactly_those_toolheads() -> None:
    seen = what_was_seen(plan_tools(tools_used(TWO_COLOUR_METADATA), LOADED_ON_THE_PRINTER))
    plan = plan_as_seen(tools_used(TWO_COLOUR_METADATA), LOADED_ON_THE_PRINTER, seen)
    assert plan.problem is None
    assert plan.as_pairs() == ((0, 2), (1, 3))


def test_a_material_that_differs_only_in_case_is_not_a_change() -> None:
    seen = (SeenToolhead(slot=0, toolhead=2, material="pla", colour="E2DEDB"),)
    plan = plan_as_seen(tools_used(WHITE_PLA_METADATA), LOADED_ON_THE_PRINTER, seen)
    assert plan.problem is None


def test_two_slots_on_a_changed_toolhead_make_one_change_naming_both() -> None:
    seen = (
        SeenToolhead(slot=0, toolhead=1, material="PETG", colour="0A2989"),
        SeenToolhead(slot=1, toolhead=1, material="PETG", colour="0A2989"),
    )
    plan = plan_as_seen(tools_used(TWO_COLOUR_METADATA), LOADED_ON_THE_PRINTER, seen)
    assert plan.problem is not None
    assert plan.problem.in_english() == (
        "Held because the toolheads no longer hold what they held when the map was seen: "
        "T1 held PETG #0A2989 for slots 0, 1 and now holds PLA #0A2989"
    )


def test_every_change_is_named_not_just_the_first() -> None:
    seen = (
        SeenToolhead(slot=0, toolhead=6, material="PLA", colour=""),
        SeenToolhead(slot=1, toolhead=3, material="PLA", colour="5E43B7"),
    )
    emptied = tuple(
        LoadedFilament(one.index, one.filament_type, one.colour, one.index != 3)  # noqa: PLR2004
        for one in LOADED_ON_THE_PRINTER
    )
    plan = plan_as_seen(tools_used(TWO_COLOUR_METADATA), emptied, seen)
    assert plan.problem is not None
    said = plan.problem.in_english()
    assert "T3 held PLA #5E43B7 for slot 1 and is now empty" in said
    assert "T6 was chosen for slot 0 and the printer no longer reports it" in said


def test_nothing_seen_is_a_question_once_there_is_something_to_map() -> None:
    plan = plan_as_seen(tools_used(WHITE_PLA_METADATA), LOADED_ON_THE_PRINTER, ())
    assert plan.problem is not None
    assert plan.problem.key is Message.NOT_REPORTED_WHEN_SCHEDULED
