# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading a gcode file's own description of itself.

The fixtures are copied from two real files on the printer this was written against, separators
and all, because both traps in here are things a reasonable reading of the documentation gets
wrong.
"""

from __future__ import annotations

from print_scheduler import split_slicer_list, summarise, tools_used
from printer_stand_in import (
    BENCHY,
    FOUR_TOOL_METADATA,
    MAINLINE_METADATA,
    SINGLE_TOOL_METADATA,
)

# Verbatim from the printer. filament_name uses a different separator from its neighbours.
REAL_FILAMENT_NAME = (
    'BBL ASA @U1 0.4 nozzle";"Snapmaker PLA SnapSpeed @U1";"Snapmaker PLA SnapSpeed @U1'
)

# Verbatim, and identical across two files sliced months apart with different filament loaded.
LOADED_SPOOLS_NOT_THE_FILES = ["#000000", "#0A2989", "#E2DEDB", "#5E43B7"]


def test_a_plain_semicolon_list_splits() -> None:
    assert split_slicer_list("ASA;PLA;PLA;PLA") == ("ASA", "PLA", "PLA", "PLA")


def test_the_quote_semicolon_quote_separator_splits_too() -> None:
    assert split_slicer_list(REAL_FILAMENT_NAME) == (
        "BBL ASA @U1 0.4 nozzle",
        "Snapmaker PLA SnapSpeed @U1",
        "Snapmaker PLA SnapSpeed @U1",
    )


def test_an_empty_list_is_empty() -> None:
    assert split_slicer_list("") == ()


def test_only_the_tools_that_extrude_are_reported() -> None:
    tools = tools_used(SINGLE_TOOL_METADATA)
    assert [tool.slot for tool in tools] == [0]
    assert tools[0].filament_type == "ASA"
    assert tools[0].used_grams == 8.89
    assert tools[0].nozzle_temperature == 270.0


def test_a_four_tool_file_reports_all_four() -> None:
    assert [tool.slot for tool in tools_used(FOUR_TOOL_METADATA)] == [0, 1, 2, 3]


def test_the_colour_comes_from_the_file_and_not_from_the_loaded_spools() -> None:
    # filament_colors, plural, is the spools in the machine right now. Reading it would show the
    # loaded colours at the exact moment someone was trying to check them against the file.
    metadata = dict(SINGLE_TOOL_METADATA)
    metadata["filament_colors"] = LOADED_SPOOLS_NOT_THE_FILES
    assert tools_used(metadata)[0].colour == "#09070A"


def test_a_file_that_declares_no_tools_reports_none_rather_than_guessing() -> None:
    assert tools_used({"estimated_time": 100}) == ()


def test_a_summary_carries_what_the_page_shows() -> None:
    summary = summarise(BENCHY, SINGLE_TOOL_METADATA)
    assert summary.filename == BENCHY
    assert summary.estimated_seconds == 2920
    assert summary.bed_temperature == 100.0
    assert summary.chamber_temperature == 50.0
    assert summary.layer_count == 240
    assert summary.slicer == "SnapmakerOrca"


def test_a_summary_of_an_empty_metadata_block_does_not_raise() -> None:
    summary = summarise("mystery.gcode", {})
    assert summary.tools == ()
    assert summary.estimated_seconds == 0.0


def test_a_mainline_moonraker_file_is_read_from_its_own_field_names() -> None:
    # Not one of the fields the U1 writes is in this file. Everything comes from Moonraker's
    # own standard set, and the page has to show the same things either way.
    tools = tools_used(MAINLINE_METADATA)
    assert len(tools) == 1
    assert tools[0].slot == 0
    assert tools[0].filament_type == "PLA"
    assert tools[0].colour == "#FF8040"
    assert tools[0].nozzle_temperature == 220.0
    assert tools[0].used_grams == 10.74


def test_the_files_own_total_is_attributed_when_there_is_only_one_slot() -> None:
    # filament_total is for the whole file, so it is only this slot's when this slot is all
    # of them. With several it is left at zero rather than divided by a guess.
    assert tools_used(MAINLINE_METADATA)[0].used_mm == 3600.3


def test_the_rest_of_a_mainline_file_reads_as_it_always_did() -> None:
    summary = summarise("3DBenchy_0.2mm_PLA_43m59s.gcode", MAINLINE_METADATA)
    assert summary.estimated_seconds == 2639
    assert summary.bed_temperature == 55.0
    assert summary.layer_count == 240
    assert summary.slicer == "OrcaSlicer"


def test_the_detailed_colour_wins_wherever_both_are_present() -> None:
    # The whole reason for the preference order. On the U1 the plural field is the spools in
    # the machine, so reading it first would compare the machine against itself.
    both = dict(SINGLE_TOOL_METADATA, filament_colors=LOADED_SPOOLS_NOT_THE_FILES)
    assert tools_used(both)[0].colour == "#09070A"


def test_a_slot_weighing_nothing_is_not_in_use() -> None:
    # Mainline gives no per slot extrusion, so weight is the only usage figure there is.
    two_slots = dict(
        MAINLINE_METADATA,
        filament_type="PLA;PETG",
        filament_colors=["#FF8040", "#00FF00"],
        filament_weights=[10.74, 0.0],
        filament_temps=[220, 240],
    )
    tools = tools_used(two_slots)
    assert len(tools) == 1
    assert tools[0].slot == 0


def test_a_second_slot_that_is_used_keeps_its_own_number() -> None:
    two_slots = dict(
        MAINLINE_METADATA,
        filament_type="PLA;PETG",
        filament_colors=["#FF8040", "#00FF00"],
        filament_weights=[0.0, 4.2],
        filament_temps=[220, 240],
    )
    tools = tools_used(two_slots)
    assert len(tools) == 1
    assert tools[0].slot == 1
    assert tools[0].filament_type == "PETG"
    # Two slots, so the file's total belongs to neither of them on its own.
    assert tools[0].used_mm == 0.0


def test_a_file_describing_no_slots_at_all_has_none() -> None:
    assert tools_used({"estimated_time": 1800, "layer_count": 60}) == ()
