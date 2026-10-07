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
import re
from collections.abc import Iterable
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from print_scheduler.gcode_files import best_thumbnail
from print_scheduler.printer import (
    DismissRefusedError,
    LoadedFilament,
    PrinterSnapshot,
    PrintRecord,
    SpoolLeft,
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

# A toolchanger's tool macro, `gcode_macro T0` and so on. The `spool_id` variable on it is the
# convention Mainsail and Fluidd both document for telling Spoolman which spool each tool holds,
# and it is where the Bespok3d Spoolman plugin writes them on the U1.
TOOL_MACRO = re.compile(r"gcode_macro T(\d+)")
# AFC's lanes, `AFC_lane E0` and so on, each naming its extruder and the spool on it.
AFC_LANE_PREFIX = "AFC_lane "
# Klipper's extruders: `extruder` is the first, `extruder1` the second.
EXTRUDER_NAME = re.compile(r"extruder(\d*)")
SPOOLMAN_COMPONENT = "spoolman"


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


def coerce_spool_id(value: Any) -> int | None:
    """A Spoolman spool id, or None for every way of saying there is no spool.

    Ids arrive as numbers from the tool macros and from AFC, and as text from a card: an OpenSpool
    tag carries its id as a string, `"0"` when blank. Zero, blank and missing all mean no spool,
    as they do to the Spoolman plugin itself.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def toolhead_of_extruder(name: Any) -> int | None:
    """`extruder` is toolhead 0, `extruder1` toolhead 1, and anything else is not one."""
    found = EXTRUDER_NAME.fullmatch(str(name))
    if found is None:
        return None
    return int(found.group(1) or 0)


def spools_from_tool_macros(status: dict[str, Any]) -> dict[int, int]:
    """Toolhead to spool id, from the tool macros' `spool_id` variables."""
    spools: dict[int, int] = {}
    for name, variables in status.items():
        found = TOOL_MACRO.fullmatch(name)
        if found is None or not isinstance(variables, dict):
            continue
        spool_id = coerce_spool_id(variables.get("spool_id"))
        if spool_id is not None:
            spools[int(found.group(1))] = spool_id
    return spools


def spools_from_afc_lanes(status: dict[str, Any]) -> dict[int, int]:
    """Toolhead to spool id, from AFC's lanes.

    The toolhead comes from each lane's `extruder`, never from its `map`: the map is AFC's tool
    numbering and is empty on every lane but one when the U1's carriers are parked, while the
    extruder a lane feeds does not change.
    """
    spools: dict[int, int] = {}
    for name, lane in status.items():
        if not name.startswith(AFC_LANE_PREFIX) or not isinstance(lane, dict):
            continue
        toolhead = toolhead_of_extruder(lane.get("extruder"))
        spool_id = coerce_spool_id(lane.get("spool_id"))
        if toolhead is not None and spool_id is not None:
            spools[toolhead] = spool_id
    return spools


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


# Clears a finished print. Also stops a running one, which is the whole reason it is only ever
# sent by `ScheduleService.dismiss_finished_print`, straight after asking the printer its state.
DISMISS_COMMAND = "SDCARD_RESET_FILE"

class MoonrakerPrinter:
    """Talks to Moonraker over the loopback interface."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._parameterised_start: bool | None = None

    # Moonraker's payloads are JSON of a shape this class checks at each use, so the transport
    # returns Any rather than pretending to a type it has not verified.
    def _request(
        self, path: str, method: str, timeout_seconds: float, body: Any = None
    ) -> Any:
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = Request(  # noqa: S310  loopback http, the base URL is ours
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers=headers,
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

    def filament_left(self) -> tuple[SpoolLeft, ...]:
        """How much is left on the spool in each toolhead, from Spoolman, where it can be known.

        Everything it needs is asked of Moonraker, so no other plugin is a dependency. Moonraker's
        component list comes first: on a printer without Spoolman nothing else is asked, so its
        endpoints are never probed and never answer with a 404 and a traceback. Then which spool
        is in which toolhead, from the tool macros or failing those from AFC's lanes, and only
        then one Spoolman lookup per spool. A spool Spoolman cannot describe is left out, and
        anything else going wrong means nothing to say.
        """
        try:
            components = self._get_result("/server/info").get("components") or []
            if SPOOLMAN_COMPONENT not in components:
                return ()
            if not self._get_result("/server/spoolman/status").get("spoolman_connected"):
                return ()
            spools = self._spools_by_toolhead(self._get_result("/printer/objects/list")["objects"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return ()
        grams = {spool_id: self._grams_left(spool_id) for spool_id in set(spools.values())}
        measured = {spool_id: left for spool_id, left in grams.items() if left is not None}
        return tuple(
            SpoolLeft(toolhead=toolhead, spool_id=spool_id, grams=measured[spool_id])
            for toolhead, spool_id in sorted(spools.items())
            if spool_id in measured
        )

    def _spools_by_toolhead(self, objects: Iterable[str]) -> dict[int, int]:
        names = [str(name) for name in objects]
        macros = [name for name in names if TOOL_MACRO.fullmatch(name)]
        if macros:
            found = spools_from_tool_macros(self._objects(macros))
            if found:
                return found
        lanes = [name for name in names if name.startswith(AFC_LANE_PREFIX)]
        return spools_from_afc_lanes(self._objects(lanes)) if lanes else {}

    def _objects(self, names: list[str]) -> dict[str, Any]:
        query = "&".join(quote(name) for name in names)
        return dict(self._get_result(f"/printer/objects/query?{query}")["status"])

    def _grams_left(self, spool_id: int) -> float | None:
        """One spool from Spoolman, through Moonraker's proxy, which only reads it."""
        try:
            spool = self._request(
                "/server/spoolman/proxy",
                "POST",
                READ_TIMEOUT_SECONDS,
                {"request_method": "GET", "path": f"/v1/spool/{spool_id}"},
            )["result"]
            return float(spool["remaining_weight"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

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

    def dismiss_finished_print(self) -> None:
        """Send the command Mainsail's own Clear button sends, and nothing else.

        `SDCARD_RESET_FILE` is core Klipper, so it exists on every machine this plugin runs
        on. Its own help text says it stops a print if necessary, which is why this method
        never decides for itself whether to send it.
        """
        path = f"/printer/gcode/script?script={quote(DISMISS_COMMAND)}"
        try:
            self._request(path, "POST", START_TIMEOUT_SECONDS)
        except HTTPError as refused:
            raise DismissRefusedError(refused.read().decode("utf-8", "replace")) from refused
        except (OSError, ValueError) as unreachable:
            raise DismissRefusedError(str(unreachable)) from unreachable

    def _post(self, path: str) -> None:
        try:
            self._request(path, "POST", START_TIMEOUT_SECONDS)
        except HTTPError as refused:
            raise StartRefusedError(refused.read().decode("utf-8", "replace")) from refused
        except (OSError, ValueError) as unreachable:
            raise StartRefusedError(str(unreachable)) from unreachable
