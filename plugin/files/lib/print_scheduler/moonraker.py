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

from print_scheduler.gcode_files import best_thumbnail
from print_scheduler.printer import (
    LoadedFilament,
    PrinterSnapshot,
    PrintRecord,
    StartRefusedError,
)

PARAMETERISED_START_COMMAND = "SDCARD_PRINT_FILE_WITH_PARAMETERS"

READ_TIMEOUT_SECONDS = 10.0
# Starting resets the loaded file and runs PRINT_PRESTART_CHECK before it answers.
START_TIMEOUT_SECONDS = 60.0

# Enough history to confirm a start moments after making it, and to answer what became of a
# print scheduled within the last few days. Moonraker offers a single-job endpoint too; the
# list is one code path for both questions and has not needed the other.
HISTORY_LIMIT = 50


def build_start_script(
    filename: str,
    level_bed: bool | None,
    record_timelapse: bool | None,
    assignments: tuple[tuple[int, int], ...] = (),
) -> str:
    """Build the start command.

    One command. The printer's own interface also sends `SET_PRINT_EXTRUDER_MAP` and
    `SET_PRINT_USED_EXTRUDERS` first, and we copied that until it was understood. It is now:
    `SET_PRINT_TASK_PARAMETERS`, which this command calls with the same parameters, resets both
    the toolhead map and the used list unconditionally before it applies `MAP_TABLE`. Anything
    those two set is wiped microseconds later, so sending them would only mislead whoever reads
    this next.

    A preference left as None is omitted, which leaves the printer's current value alone rather
    than silently choosing one on the person's behalf. No assignments means a printer with no
    toolhead map to program, so nothing about it is sent.
    """
    parameters = [f'FILENAME="{filename}"']
    if assignments:
        pairs = ", ".join(f"[{slot}, {toolhead}]" for slot, toolhead in assignments)
        parameters.append(f'MAP_TABLE="[{pairs}]"')
    if level_bed is not None:
        parameters.append(f"BED_LEVEL={int(level_bed)}")
    if record_timelapse is not None:
        parameters.append(f"TIME_LAPSE_CAMERA={int(record_timelapse)}")
    return f"{PARAMETERISED_START_COMMAND} " + " ".join(parameters)


def loaded_filaments_from_config(config: dict[str, Any]) -> tuple[LoadedFilament, ...]:
    """Read what each toolhead holds out of the printer's print task config."""
    materials = config.get("filament_type") or []
    colours = config.get("filament_color_rgba") or []
    present = config.get("filament_exist") or []
    return tuple(
        LoadedFilament(
            index=index,
            filament_type=str(materials[index]),
            colour=str(colours[index]) if index < len(colours) else "",
            present=bool(present[index]) if index < len(present) else True,
        )
        for index in range(len(materials))
    )


def print_records_from_history(entries: Any) -> tuple[PrintRecord, ...]:
    """Read history entries out of a Moonraker history listing."""
    return tuple(
        PrintRecord(
            job_id=str(entry.get("job_id", "")),
            filename=str(entry.get("filename", "")),
            start_time=float(entry.get("start_time") or 0.0),
            status=str(entry.get("status", "")),
            end_time=float(entry.get("end_time") or 0.0),
            total_duration=float(entry.get("total_duration") or 0.0),
            print_duration=float(entry.get("print_duration") or 0.0),
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

    def file_listing(self) -> dict[str, float]:
        """Every gcode file and when it was last modified, subdirectories included."""
        return {
            str(entry["path"]): float(entry.get("modified") or 0.0)
            for entry in self._get_result("/server/files/list?root=gcodes")
        }

    def described_files(self) -> dict[str, dict[str, Any]]:
        """Everything the printer knows about the files in the gcode root, in one read.

        One request for the whole directory rather than one per file, which on a printer
        holding a hundred and fifty of them is the difference between a page and a stampede.
        Files kept in subdirectories are not described, only listed; a name and a date is a
        better answer than hiding them.
        """
        try:
            result = self._get_result(
                "/server/files/directory?path=gcodes&extended=true"
            )
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        files = result.get("files") if isinstance(result, dict) else None
        if not isinstance(files, list):
            return {}
        return {
            str(entry["filename"]): dict(entry)
            for entry in files
            if isinstance(entry, dict) and entry.get("filename")
        }

    def thumbnail(self, filename: str) -> tuple[bytes, str] | None:
        """The largest thumbnail this file offers, fetched from the printer.

        The path comes from the file's own metadata rather than from the caller, so nothing a
        browser sends decides which file is read.
        """
        relative = best_thumbnail(self.file_metadata(filename))
        if relative is None:
            return None
        directory = filename.rsplit("/", 1)[0] if "/" in filename else ""
        within_gcodes = f"{directory}/{relative}" if directory else relative
        if ".." in within_gcodes.split("/"):
            return None
        request = Request(  # noqa: S310  loopback http, the base URL is ours
            f"{self.base_url}/server/files/gcodes/{quote(within_gcodes)}",
            method="GET",
        )
        with urlopen(request, timeout=READ_TIMEOUT_SECONDS) as response:  # noqa: S310
            content_type = response.headers.get("Content-Type") or "image/png"
            return response.read(), str(content_type)

    def recent_prints(self) -> tuple[PrintRecord, ...]:
        """The printer's own recent job history, newest first."""
        result = self._get_result(f"/server/history/list?limit={HISTORY_LIMIT}")
        return print_records_from_history(result["jobs"])

    def file_metadata(self, filename: str) -> dict[str, Any]:
        """What the slicer wrote into one gcode file, as Moonraker reports it."""
        metadata = self._get_result(f"/server/files/metadata?filename={quote(filename)}")
        return dict(metadata)

    def loaded_filaments(self) -> tuple[LoadedFilament, ...]:
        """What is in each toolhead. Empty on a printer with no print task config."""
        result = self._get_result("/printer/objects/query?print_task_config")
        config = result["status"].get("print_task_config")
        return () if config is None else loaded_filaments_from_config(config)

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
        self,
        filename: str,
        level_bed: bool | None,
        record_timelapse: bool | None,
        assignments: tuple[tuple[int, int], ...] = (),
    ) -> None:
        """Start the print, or raise StartRefusedError carrying the printer's own message."""
        if self.supports_print_preferences():
            script = build_start_script(filename, level_bed, record_timelapse, assignments)
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
