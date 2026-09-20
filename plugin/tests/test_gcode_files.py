# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading a gcode file's own description of itself.

The fixtures are copied from two real files on the printer this was written against, separators
and all, because both traps in here are things a reasonable reading of the documentation gets
wrong.
"""

from __future__ import annotations

from print_scheduler import split_slicer_list, summarise, tools_used
from printer_stand_in import BENCHY, FOUR_TOOL_METADATA, SINGLE_TOOL_METADATA

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
    assert [tool.index for tool in tools] == [0]
    assert tools[0].filament_type == "ASA"
    assert tools[0].used_grams == 8.89
    assert tools[0].nozzle_temperature == 270.0


def test_a_four_tool_file_reports_all_four() -> None:
    assert [tool.index for tool in tools_used(FOUR_TOOL_METADATA)] == [0, 1, 2, 3]


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
