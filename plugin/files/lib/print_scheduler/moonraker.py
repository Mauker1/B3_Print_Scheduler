# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Moonraker implementation of `Printer`.

Two ways to start a print, chosen by what the printer offers rather than by what it is.

`SDCARD_PRINT_FILE_WITH_PARAMETERS` is what the Snapmaker interface itself calls, and it is the only
way to set the per-print preferences: whether the bed is meshed and whether a timelapse is recorded
are held in the printer's print task config, not in the gcode file, so a print started any other way
inherits whatever the last one used. Every parameter of that command is optional and an omitted one
keeps its previous value, which is why only the three we understand exactly are sent. The interface
also sends the whole slicer parameter set, but its encoding is not the metadata's encoding and a
wrong flow ratio changes how the print extrudes, so those are left alone.

Where the command does not exist, Moonraker's own `/printer/print/start` is used and the preference
toggles have nothing to act on.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from print_scheduler.printer import PrinterSnapshot, PrintRecord, StartRefusedError

PARAMETERISED_START_COMMAND = "SDCARD_PRINT_FILE_WITH_PARAMETERS"

READ_TIMEOUT_SECONDS = 10.0
# Starting resets the loaded file and runs PRINT_PRESTART_CHECK before it answers.
START_TIMEOUT_SECONDS = 60.0

# Enough history to confirm a start moments after making it, and to answer what became of a
# print scheduled within the last few days. Moonraker offers a single-job endpoint too; the
# list is one code path for both questions and has not needed the other.
HISTORY_LIMIT = 50


def build_start_script(
    filename: str, level_bed: bool | None, record_timelapse: bool | None
) -> str:
    """Build the parameterised start command.

    A preference left as None is omitted, which leaves the printer's current value alone rather
    than silently choosing one on the person's behalf.
    """
    parameters = [f'FILENAME="{filename}"']
    if level_bed is not None:
        parameters.append(f"BED_LEVEL={int(level_bed)}")
    if record_timelapse is not None:
        parameters.append(f"TIME_LAPSE_CAMERA={int(record_timelapse)}")
    return f"{PARAMETERISED_START_COMMAND} " + " ".join(parameters)


def print_records_from_history(entries: Any) -> tuple[PrintRecord, ...]:
    """Read history entries out of a Moonraker history listing."""
    return tuple(
        PrintRecord(
            job_id=str(entry.get("job_id", "")),
            filename=str(entry.get("filename", "")),
            start_time=float(entry.get("start_time") or 0.0),
            status=str(entry.get("status", "")),
        )
        for entry in entries
    )


def snapshot_from_status(status: dict[str, Any]) -> PrinterSnapshot:
    """Read a snapshot out of a Moonraker objects query result."""
    print_stats = status.get("print_stats", {})
    webhooks = status.get("webhooks", {})
    idle_timeout = status.get("idle_timeout", {})
    return PrinterSnapshot(
        reachable=True,
        klipper_state=str(webhooks.get("state", "")),
        klipper_message=str(webhooks.get("state_message", "")),
        print_state=str(print_stats.get("state", "")),
        printing_filename=str(print_stats.get("filename", "")),
        other_gcode_running=str(idle_timeout.get("state", "")) == "Printing",
    )


class MoonrakerPrinter:
    """Talks to Moonraker over the loopback interface."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._parameterised_start: bool | None = None

    # Moonraker's payloads are JSON of a shape this class checks at each use, so the transport
    # returns Any rather than pretending to a type it has not verified.
    def _request(self, path: str, method: str, timeout_seconds: float) -> Any:
        request = Request(  # noqa: S310  loopback http, the base URL is ours
            f"{self.base_url}{path}",
            method=method,
            headers={"Accept": "application/json"},
        )
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def _get_result(self, path: str) -> Any:
        return self._request(path, "GET", READ_TIMEOUT_SECONDS)["result"]

    def snapshot(self) -> PrinterSnapshot:
        """Read the printer's state. Unreachable is an answer, not an exception."""
        try:
            result = self._get_result(
                "/printer/objects/query?print_stats&idle_timeout&webhooks"
            )
            return snapshot_from_status(result["status"])
        except (OSError, ValueError, KeyError, TypeError) as unreachable:
            return PrinterSnapshot(reachable=False, klipper_message=str(unreachable))

    def gcode_filenames(self) -> frozenset[str]:
        """Every gcode file the printer can currently start."""
        return frozenset(str(entry["path"]) for entry in self._get_result(
            "/server/files/list?root=gcodes"
        ))

    def recent_prints(self) -> tuple[PrintRecord, ...]:
        """The printer's own recent job history, newest first."""
        result = self._get_result(f"/server/history/list?limit={HISTORY_LIMIT}")
        return print_records_from_history(result["jobs"])

    def file_metadata(self, filename: str) -> dict[str, Any]:
        """What the slicer wrote into one gcode file, as Moonraker reports it."""
        metadata = self._get_result(f"/server/files/metadata?filename={quote(filename)}")
        return dict(metadata)

    def supports_print_preferences(self) -> bool:
        """Whether this printer offers the parameterised start command. Asked once, then kept."""
        if self._parameterised_start is None:
            try:
                commands = self._get_result("/printer/gcode/help")
                self._parameterised_start = PARAMETERISED_START_COMMAND in commands
            except (OSError, ValueError, KeyError, TypeError):
                return False
        return self._parameterised_start

    def start_print(
        self, filename: str, level_bed: bool | None, record_timelapse: bool | None
    ) -> None:
        """Start the print, or raise StartRefusedError carrying the printer's own message."""
        if self.supports_print_preferences():
            script = build_start_script(filename, level_bed, record_timelapse)
            self._post(f"/printer/gcode/script?script={quote(script)}")
            return
        self._post(f"/printer/print/start?filename={quote(filename)}")

    def _post(self, path: str) -> None:
        try:
            self._request(path, "POST", START_TIMEOUT_SECONDS)
        except HTTPError as refused:
            raise StartRefusedError(refused.read().decode("utf-8", "replace")) from refused
        except (OSError, ValueError) as unreachable:
            raise StartRefusedError(str(unreachable)) from unreachable
