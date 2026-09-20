# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Choosing which toolhead each of a file's filament slots runs on.

The first test is the regression. The first scheduled print on real hardware went into ASA because
slot 0 was taken to mean toolhead 0, and the file's slot 0 wanted white PLA, which was on toolhead
2. Everything else here exists so that cannot come back by a different route.
"""

from __future__ import annotations

from print_scheduler import LoadedFilament, normalise_colour, plan_tools, tools_used
from printer_stand_in import (
    FOUR_TOOL_METADATA,
    LOADED_ON_THE_PRINTER,
    SINGLE_TOOL_METADATA,
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
    assert "PLA" in plan.problem
    assert "T0 ASA" in plan.problem


def test_an_empty_toolhead_is_not_a_candidate() -> None:
    empty_bay = tuple(
        LoadedFilament(index=one.index, filament_type=one.filament_type, colour=one.colour,
                       present=one.index != 2)
        for one in LOADED_ON_THE_PRINTER
    )
    # T2 held the white; with it gone the other PLA toolheads still match on material.
    plan = plan_tools(tools_used(WHITE_PLA_METADATA), empty_bay)
    assert plan.as_pairs() == ((0, 1),)


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
