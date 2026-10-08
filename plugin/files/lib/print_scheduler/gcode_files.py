# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading a gcode file's own description of itself.

**There are two families of metadata field and a printer may have either.** Moonraker writes a
standard set for any slicer: `filament_colors`, `filament_temps`, `filament_weights`,
`filament_total`. The Snapmaker firmware adds a parallel set under different names, with more
detail per slot: `filament_colour`, `nozzle_temp`, `filament_weight`, `filament_used_mm`. Both
were read off real printers, a U1 and an Ender on mainline Klipper, and neither is a superset of
the other in naming.

So every field here is read as "the detailed one if this printer has it, otherwise Moonraker's
own". That order is not arbitrary, and the reason is the second trap below.

Two traps, both found by reading a real printer rather than the documentation.

`referenced_tools` is documented by Moonraker and written by neither slicer we have seen: it came
back empty on a mainline file that plainly uses one tool. So which slots a file uses comes from
`filament_used_mm` where that exists, and from whatever per-slot lists the file carries where it
does not.

`filament_colors`, plural, is **not** the file's colours on the U1. It is identical across files
sliced months apart and it matches the spools loaded right now. There the file's own requirement
is `filament_colour`, singular. On a mainline Moonraker the singular does not exist and the plural
is the file's own colour, which is why the preference order matters: reading the plural first
would show you the colours already in the machine at the exact moment you were trying to check
them against the file, which is the one case the feature exists for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Some lists are separated by a literal quote-semicolon-quote and some by a plain semicolon, in the
# same metadata block: `filament_name` uses the first, `filament_type` and `filament_colour` the
# second. Normalising the first into the second handles both without guessing which is which.
QUOTED_SEPARATOR = '";"'

# Never read as file data. Named here so the intent is greppable and so the test can assert it.
LOADED_SPOOL_FIELD = "filament_colors"


@dataclass(frozen=True)
class ToolUse:
    """One slicer slot this file actually extrudes from."""

    # The slicer's slot number, not a toolhead. Which toolhead it runs on is decided at
    # start time, by matching what this slot needs against what is loaded.
    slot: int
    used_mm: float
    used_grams: float
    filament_type: str
    filament_name: str
    colour: str
    nozzle_temperature: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "used_mm": self.used_mm,
            "used_grams": self.used_grams,
            "filament_type": self.filament_type,
            "filament_name": self.filament_name,
            "colour": self.colour,
            "nozzle_temperature": self.nozzle_temperature,
        }


@dataclass(frozen=True)
class FileSummary:
    """What a gcode file says about itself, as much of it as the person choosing needs."""

    filename: str
    tools: tuple[ToolUse, ...]
    estimated_seconds: float
    bed_temperature: float
    chamber_temperature: float
    layer_count: int
    slicer: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "tools": [tool.to_dict() for tool in self.tools],
            "estimated_seconds": self.estimated_seconds,
            "bed_temperature": self.bed_temperature,
            "chamber_temperature": self.chamber_temperature,
            "layer_count": self.layer_count,
            "slicer": self.slicer,
        }


@dataclass(frozen=True)
class FileRow:
    """One line in the file picker.

    Everything here is cheap: it comes from a single directory listing rather than a metadata
    read per file, so a printer holding a hundred and fifty files costs one request.
    """

    filename: str
    modified: float
    estimated_seconds: float = 0.0
    # When the printer last started this file, from its own metadata. Zero means never, which
    # is worth saying out loud on a page that schedules unattended prints.
    last_printed: float = 0.0
    has_thumbnail: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "modified": self.modified,
            "estimated_seconds": self.estimated_seconds,
            "last_printed": self.last_printed,
            "has_thumbnail": self.has_thumbnail,
        }


def best_thumbnail(metadata: dict[str, Any]) -> str | None:
    """The largest thumbnail the file offers, as a path relative to the file's own directory."""
    thumbnails = metadata.get("thumbnails")
    if not isinstance(thumbnails, list) or not thumbnails:
        return None
    largest = max(
        (one for one in thumbnails if isinstance(one, dict) and one.get("relative_path")),
        key=lambda one: _as_float(one.get("width")),
        default=None,
    )
    return None if largest is None else str(largest["relative_path"])


def file_rows(
    listing: dict[str, float], described: dict[str, dict[str, Any]]
) -> tuple[FileRow, ...]:
    """Every file the printer holds, newest first, enriched where the printer described it.

    The listing is the truth about what exists, because it reaches into subdirectories. The
    descriptions come from one directory read of the root, so a file kept in a subfolder still
    appears, with a name and a date and nothing else. That is a better failure than hiding it.
    """
    rows = [
        FileRow(
            filename=filename,
            modified=modified,
            estimated_seconds=_as_float(described.get(filename, {}).get("estimated_time")),
            last_printed=_as_float(described.get(filename, {}).get("print_start_time")),
            has_thumbnail=best_thumbnail(described.get(filename, {})) is not None,
        )
        for filename, modified in listing.items()
    ]
    # Newest first, because the file you are looking for is almost always the one you just
    # sliced. Alphabetical put it wherever its name happened to fall.
    return tuple(sorted(rows, key=lambda row: (-row.modified, row.filename)))


def split_slicer_list(value: str) -> tuple[str, ...]:
    """Split one of the slicer's per-tool lists, whichever separator it happens to use."""
    if not value:
        return ()
    normalised = value.replace(QUOTED_SEPARATOR, ";")
    return tuple(part.strip().strip('"') for part in normalised.split(";"))


def _number_at(values: Any, index: int) -> float:
    if not isinstance(values, list) or index >= len(values):
        return 0.0
    try:
        return float(values[index])
    except (TypeError, ValueError):
        return 0.0


def _text_at(values: tuple[str, ...], index: int) -> str:
    return values[index] if index < len(values) else ""


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _detailed_or_standard(metadata: dict[str, Any], detailed: str, standard: str) -> Any:
    """One per-slot list, preferring the field with more in it.

    The detailed name is the Snapmaker one and the standard name is Moonraker's. A printer has
    one or the other, and on the printer that has both the detailed one is the file's own while
    the standard one describes the machine, so the order is load bearing rather than tidy.
    """
    value = metadata.get(detailed)
    if isinstance(value, list) and value:
        return value
    return metadata.get(standard)


def _colours_of(metadata: dict[str, Any]) -> tuple[str, ...]:
    """What colour each slot asks for, from whichever field this printer writes."""
    detailed = str(metadata.get("filament_colour", ""))
    if detailed:
        return split_slicer_list(detailed)
    standard = metadata.get("filament_colors") or metadata.get("extruder_colors")
    return tuple(str(one) for one in standard) if isinstance(standard, list) else ()


def tools_used(metadata: dict[str, Any]) -> tuple[ToolUse, ...]:
    """The slots this file extrudes from, in order."""
    weights = _detailed_or_standard(metadata, "filament_weight", "filament_weights")
    temperatures = _detailed_or_standard(metadata, "nozzle_temp", "filament_temps")
    described = _Described(
        types=split_slicer_list(str(metadata.get("filament_type", ""))),
        names=split_slicer_list(str(metadata.get("filament_name", ""))),
        colours=_colours_of(metadata),
        weights=weights,
        temperatures=temperatures,
    )
    used_mm = metadata.get("filament_used_mm")
    if isinstance(used_mm, list):
        return tuple(
            _one_slot(described, index, _as_float(millimetres))
            for index, millimetres in enumerate(used_mm)
            if _as_float(millimetres) > 0
        )
    return _slots_without_a_usage_list(metadata, described)


@dataclass(frozen=True)
class _Described:
    """The per-slot lists, already resolved to whichever field this printer writes."""

    types: tuple[str, ...]
    names: tuple[str, ...]
    colours: tuple[str, ...]
    weights: Any
    temperatures: Any


def _one_slot(described: _Described, index: int, used_mm: float) -> ToolUse:
    return ToolUse(
        slot=index,
        used_mm=used_mm,
        used_grams=_number_at(described.weights, index),
        filament_type=_text_at(described.types, index),
        filament_name=_text_at(described.names, index),
        colour=_text_at(described.colours, index),
        nozzle_temperature=_number_at(described.temperatures, index),
    )


def _slots_without_a_usage_list(
    metadata: dict[str, Any], described: _Described
) -> tuple[ToolUse, ...]:
    """A printer whose Moonraker reports no per-slot extrusion, which is most of them.

    The slot count is however many entries the per-slot lists carry. Weight is the only usage
    figure on offer, so a slot weighing nothing is treated as unused, exactly as a slot
    extruding nothing is on a printer that reports millimetres.
    """
    counted = [len(one) for one in (described.colours, described.types, described.names)]
    counted += [
        len(one)
        for one in (described.weights, described.temperatures)
        if isinstance(one, list)
    ]
    how_many = max(counted, default=0)
    if not how_many:
        return ()
    # The total is for the whole file, so it can only be attributed when there is one slot.
    total = _as_float(metadata.get("filament_total")) if how_many == 1 else 0.0
    slots = tuple(_one_slot(described, index, total) for index in range(how_many))
    weighed = tuple(one for one in slots if one.used_grams > 0)
    return weighed or slots


def summarise(filename: str, metadata: dict[str, Any]) -> FileSummary:
    """Describe one gcode file from the metadata the printer reports for it."""
    return FileSummary(
        filename=filename,
        tools=tools_used(metadata),
        estimated_seconds=_as_float(metadata.get("estimated_time")),
        bed_temperature=_as_float(metadata.get("first_layer_bed_temp")),
        chamber_temperature=_as_float(metadata.get("chamber_temp")),
        layer_count=int(_as_float(metadata.get("layer_count"))),
        slicer=str(metadata.get("slicer", "")),
    )
