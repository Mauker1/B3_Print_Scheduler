# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A printer described as data.

Every field is a state to report or an error to raise, so a test can describe a printer that is
busy, or one that refuses a start, or one with no job history at all, as plainly as one that works.
Nothing in the suite needs a socket, a clock, or a machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from print_scheduler import (
    LoadedFilament,
    PrinterSnapshot,
    PrintRecord,
    StartRefusedError,
)

BENCHY = "3DBenchy_ASA_HF_48m40s.gcode"
CHINESE_NAME = "顶盖前靴_TPU_13m5s.gcode"

IDLE = PrinterSnapshot(reachable=True, klipper_state="ready", print_state="standby")
PRINTING_OURS = replace(IDLE, print_state="printing", printing_filename=BENCHY)

# One tool, the shape every 0.1.0 job has to have. A multi tool file is the same with more
# non-zero entries, which is how the refusal is tested.
SINGLE_TOOL_METADATA: dict[str, Any] = {
    "filament_used_mm": [3518.66, 0.0, 0.0, 0.0],
    "filament_weight": [8.89, 0.0, 0.0, 0.0],
    "filament_type": "ASA;PLA;PLA;PLA",
    "filament_colour": "#09070A;#080A0D;#080A0D;#080A0D",
    "nozzle_temp": [270.0, 220.0, 220.0, 220.0],
    "estimated_time": 2920,
    "first_layer_bed_temp": 100.0,
    "chamber_temp": 50.0,
    "layer_count": 240,
    "slicer": "SnapmakerOrca",
}

# What is actually in the four toolheads of the machine this was written against. Slot 0 of
# SINGLE_TOOL_METADATA wants ASA, and only T0 has ASA, so it maps there.
LOADED_ON_THE_PRINTER = (
    LoadedFilament(index=0, filament_type="ASA", colour="000000FF", present=True),
    LoadedFilament(index=1, filament_type="PLA", colour="0A2989FF", present=True),
    LoadedFilament(index=2, filament_type="PLA", colour="E2DEDBFF", present=True),
    LoadedFilament(index=3, filament_type="PLA", colour="5E43B7FF", present=True),
)

# Cube_PLA_26s.gcode, verbatim from the printer, and the file that exposed the bug: its slot 0
# wants white PLA, which is on T2, and the scheduler sent it to T0 where the ASA is.
WHITE_PLA_METADATA: dict[str, Any] = {
    "filament_used_mm": [22.8, 0.0, 0.0, 0.0],
    "filament_weight": [0.07, 0.0, 0.0, 0.0],
    "filament_type": "PLA;ASA;PLA;PLA",
    "filament_colour": "#E2DEDB;#000000;#E2DEDB;#FF8040",
    "nozzle_temp": [230.0, 270.0, 220.0, 220.0],
    "estimated_time": 26,
    "first_layer_bed_temp": 45.0,
    "chamber_temp": 0.0,
    "layer_count": 1,
    "slicer": "SnapmakerOrca",
}

# A file sliced for a printer that tracks nothing: no per tool lists, no colours, no bed
# temperature. Everything the page shows is optional except the name, and this is the fixture
# that proves it.
SPARSE_METADATA: dict[str, Any] = {
    "estimated_time": 1800,
    "layer_count": 60,
}

# Two slots, both PLA, and neither maps to the toolhead of the same number: slot 0 wants the
# white on T2 and slot 1 the purple on T3. The identity map that 0.1.0 relied on would put both
# on the wrong toolhead, so this is the fixture that proves the map is a map.
TWO_COLOUR_METADATA: dict[str, Any] = {
    "filament_used_mm": [180.0, 95.0, 0.0, 0.0],
    "filament_weight": [0.54, 0.28, 0.0, 0.0],
    "filament_type": "PLA;PLA;PLA;PLA",
    "filament_colour": "#E2DEDB;#5E43B7;#000000;#000000",
    "nozzle_temp": [230.0, 230.0, 220.0, 220.0],
    "estimated_time": 1020,
    "first_layer_bed_temp": 45.0,
    "chamber_temp": 0.0,
    "layer_count": 30,
    "slicer": "SnapmakerOrca",
}

# More of one material than the machine holds: three ASA slots against a single ASA toolhead.
TOO_MUCH_ASA_METADATA: dict[str, Any] = {
    **SINGLE_TOOL_METADATA,
    "filament_used_mm": [100.0, 100.0, 100.0, 0.0],
    "filament_type": "ASA;ASA;ASA;PLA",
}

FOUR_TOOL_METADATA: dict[str, Any] = {
    **SINGLE_TOOL_METADATA,
    "filament_used_mm": [647.39, 277.65, 267.72, 94.26],
    "filament_weight": [1.93, 0.83, 0.8, 0.28],
    "estimated_time": 865,
}


@dataclass
class StandInPrinter:
    """Everything the scheduler asks a printer, answered from fields."""

    reports: PrinterSnapshot = IDLE
    holds: frozenset[str] = frozenset({BENCHY, CHINESE_NAME})
    describes: dict[str, Any] = field(default_factory=lambda: dict(SINGLE_TOOL_METADATA))
    remembers: tuple[PrintRecord, ...] = ()
    refuses_start_with: str | None = None
    listing_raises: OSError | None = None
    history_raises: OSError | None = None
    offers_preferences: bool = True
    loads: tuple[LoadedFilament, ...] = LOADED_ON_THE_PRINTER
    loading_raises: OSError | None = None
    # filename, level bed, record timelapse, and the slot to toolhead pairs it was given.
    started: list[tuple[str, bool | None, bool | None, tuple[tuple[int, int], ...]]] = field(
        default_factory=list
    )

    def snapshot(self) -> PrinterSnapshot:
        return self.reports

    def gcode_filenames(self) -> frozenset[str]:
        if self.listing_raises is not None:
            raise self.listing_raises
        return self.holds

    def recent_prints(self) -> tuple[PrintRecord, ...]:
        if self.history_raises is not None:
            raise self.history_raises
        return self.remembers

    def file_metadata(self, filename: str) -> dict[str, Any]:
        if filename not in self.holds:
            raise OSError(f"no metadata for {filename}")
        return self.describes

    def loaded_filaments(self) -> tuple[LoadedFilament, ...]:
        if self.loading_raises is not None:
            raise self.loading_raises
        return self.loads

    def supports_print_preferences(self) -> bool:
        return self.offers_preferences

    def start_print(
        self,
        filename: str,
        level_bed: bool | None,
        record_timelapse: bool | None,
        assignments: tuple[tuple[int, int], ...] = (),
    ) -> None:
        if self.refuses_start_with is not None:
            raise StartRefusedError(self.refuses_start_with)
        self.started.append((filename, level_bed, record_timelapse, assignments))


def a_generic_klipper(**overrides: Any) -> StandInPrinter:
    """A printer with no parameterised start and nothing loaded that it will admit to.

    Which is to say: any Klipper that is not the machine this plugin was written against. It
    has never been run against real hardware of this shape, so it is described here instead,
    and every rule that has to behave differently for it is tested against this fixture.
    """
    base: dict[str, Any] = {
        "offers_preferences": False,
        "loads": (),
        "describes": dict(SPARSE_METADATA),
    }
    base.update(overrides)
    return StandInPrinter(**base)
