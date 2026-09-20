# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the scheduler needs to know about the printer, and the seam for standing in for one.

Nothing in this module talks to a network. The decision engine depends on `Printer` and on
`PrinterSnapshot`, so every outcome in the table can be described as data in a test and none of the
tests need a printer, a socket or a clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

KLIPPER_READY = "ready"

# Klipper is on its way up and will very likely be ready in a few seconds, so a job that
# meets this waits. Its other non-ready states, shutdown and error, are not transient and a
# job that waits through them only cancels later with the wrong reason recorded.
KLIPPER_STARTING_STATES = frozenset({"startup"})

# A print is under way. The printer is occupied for hours, so a scheduled job that meets this is
# cancelled rather than waited for.
RUNNING_PRINT_STATES = frozenset({"printing", "paused"})

# A print has ended and nobody has dismissed it on the printer's screen. Clearing the bed and
# dismissing the job are the same habit, so this is the closest thing to a bed sensor we have, and
# the interface is honest about it being a proxy.
UNCLEARED_BED_STATES = frozenset({"complete", "cancelled"})

PRINT_STATE_ERROR = "error"


class StartRefusedError(Exception):
    """The printer refused to start the print. The message is the printer's own."""


@dataclass(frozen=True)
class PrinterSnapshot:
    """Everything the decision engine looks at, read in one pass."""

    reachable: bool
    klipper_state: str = ""
    klipper_message: str = ""
    print_state: str = ""
    printing_filename: str = ""
    # idle_timeout reports Printing for any gcode activity, including a calibration started by
    # hand, while print_stats only knows about print jobs. Both are needed to answer "is the
    # printer busy", and they mean different things: see the rules in runner.py.
    other_gcode_running: bool = False


class Printer(Protocol):
    """The printer, as much of it as the scheduler needs."""

    def snapshot(self) -> PrinterSnapshot:
        """Read the printer's current state, without raising if it cannot be reached."""
        ...

    def gcode_filenames(self) -> frozenset[str]:
        """Every gcode file the printer can currently start."""
        ...

    def start_print(
        self, filename: str, level_bed: bool | None, record_timelapse: bool | None
    ) -> None:
        """Start the print.

        Raises StartRefusedError carrying the printer's own message if it will not.
        """
        ...
