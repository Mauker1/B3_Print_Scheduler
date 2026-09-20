# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The two pieces of the Moonraker client that can be tested without a printer.

The command this builds is the one that actually starts prints, so it is worth asserting character
by character. A preference left unset must be absent from the command rather than sent as zero:
every parameter of `SDCARD_PRINT_FILE_WITH_PARAMETERS` is optional, and an omitted one keeps the
printer's current value while a sent one overwrites it.
"""

from __future__ import annotations

from print_scheduler import build_start_script, snapshot_from_status

BENCHY = "3DBenchy_ASA_HF_48m40s.gcode"


def test_the_filename_is_quoted_because_real_files_have_spaces_in_their_names() -> None:
    spaced = "06_Baby Dragon Teen_PLA_HF_4h35m.gcode"
    assert build_start_script(spaced, None, None) == (
        f'SDCARD_PRINT_FILE_WITH_PARAMETERS FILENAME="{spaced}"'
    )


def test_an_unset_preference_is_left_out_of_the_command() -> None:
    assert build_start_script(BENCHY, None, None) == (
        f'SDCARD_PRINT_FILE_WITH_PARAMETERS FILENAME="{BENCHY}"'
    )


def test_preferences_are_sent_as_the_integers_the_printer_parses() -> None:
    assert build_start_script(BENCHY, True, False) == (
        f'SDCARD_PRINT_FILE_WITH_PARAMETERS FILENAME="{BENCHY}" BED_LEVEL=1 TIME_LAPSE_CAMERA=0'
    )


def test_one_preference_can_be_set_without_the_other() -> None:
    assert "TIME_LAPSE_CAMERA" not in build_start_script(BENCHY, True, None)
    assert "BED_LEVEL" not in build_start_script(BENCHY, None, True)


def test_no_slicer_parameter_is_sent() -> None:
    # Sending them means reconstructing an encoding we do not understand, and a wrong flow ratio
    # changes how the print extrudes. Omitting them leaves the printer's current values alone.
    script = build_start_script(BENCHY, True, True)
    for parameter in ("FILAMENT_FLOW_RATIO", "NOZZLE_TEMP", "LINE_WIDTH", "SLICER"):
        assert parameter not in script


def test_a_printer_with_no_toolhead_map_is_sent_nothing_about_one() -> None:
    script = build_start_script(BENCHY, True, True)
    assert "MAP_TABLE" not in script
    assert "EXTRUDER" not in script


def test_the_start_programs_the_toolhead_map_the_way_the_printers_interface_does() -> None:
    # Three commands, matching the sequence captured from the printer's own interface.
    assert build_start_script(BENCHY, True, False, ((0, 2),)).splitlines() == [
        "SET_PRINT_EXTRUDER_MAP CONFIG_EXTRUDER=0 MAP_EXTRUDER=2",
        "SET_PRINT_USED_EXTRUDERS EXTRUDERS=2",
        f'SDCARD_PRINT_FILE_WITH_PARAMETERS FILENAME="{BENCHY}" MAP_TABLE="[[0, 2]]" '
        "BED_LEVEL=1 TIME_LAPSE_CAMERA=0",
    ]


def test_every_slot_gets_its_own_line_and_its_own_pair() -> None:
    script = build_start_script(BENCHY, None, None, ((0, 2), (1, 0)))
    assert "SET_PRINT_EXTRUDER_MAP CONFIG_EXTRUDER=0 MAP_EXTRUDER=2" in script
    assert "SET_PRINT_EXTRUDER_MAP CONFIG_EXTRUDER=1 MAP_EXTRUDER=0" in script
    assert "SET_PRINT_USED_EXTRUDERS EXTRUDERS=2,0" in script
    assert 'MAP_TABLE="[[0, 2], [1, 0]]"' in script


def test_a_snapshot_is_read_out_of_a_moonraker_objects_query() -> None:
    snapshot = snapshot_from_status({
        "print_stats": {"state": "complete", "filename": BENCHY},
        "idle_timeout": {"state": "Idle"},
        "webhooks": {"state": "ready", "state_message": "Printer is ready"},
    })
    assert snapshot.reachable
    assert snapshot.klipper_state == "ready"
    assert snapshot.print_state == "complete"
    assert snapshot.printing_filename == BENCHY
    assert not snapshot.other_gcode_running


def test_idle_timeout_printing_means_some_gcode_is_running() -> None:
    snapshot = snapshot_from_status({
        "print_stats": {"state": "standby"},
        "idle_timeout": {"state": "Printing"},
        "webhooks": {"state": "ready"},
    })
    assert snapshot.print_state == "standby"
    assert snapshot.other_gcode_running


def test_a_query_missing_an_object_does_not_raise() -> None:
    # Moonraker omits an object it does not have rather than reporting it empty.
    snapshot = snapshot_from_status({})
    assert snapshot.reachable
    assert snapshot.klipper_state == ""
