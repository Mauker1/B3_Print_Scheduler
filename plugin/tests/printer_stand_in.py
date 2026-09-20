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

from print_scheduler import PrinterSnapshot, PrintRecord, StartRefusedError

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
    started: list[tuple[str, bool | None, bool | None]] = field(default_factory=list)

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

    def supports_print_preferences(self) -> bool:
        return self.offers_preferences

    def start_print(
        self, filename: str, level_bed: bool | None, record_timelapse: bool | None
    ) -> None:
        if self.refuses_start_with is not None:
            raise StartRefusedError(self.refuses_start_with)
        self.started.append((filename, level_bed, record_timelapse))
