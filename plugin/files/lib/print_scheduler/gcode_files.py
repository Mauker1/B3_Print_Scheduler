# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading a gcode file's own description of itself.

Two traps live in here and both were found by reading a real printer rather than the documentation.

`referenced_tools` is documented by Moonraker and not written by this slicer, so which tools a
print uses comes from `filament_used_mm`: a non-zero entry means that tool is used. That is a
better signal anyway, because it is the extrusion total rather than a field a slicer may forget.

`filament_colors`, plural, is **not** the file's colours. It is identical across files sliced
months apart and it matches the spools loaded right now. The file's own requirement is
`filament_colour`, singular. Reading the plural one would show you the colours already in the
machine at the exact moment you were trying to check them against the file, which is the one case
the feature exists for.
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
    """One toolhead this file actually extrudes from."""

    index: int
    used_mm: float
    used_grams: float
    filament_type: str
    filament_name: str
    colour: str
    nozzle_temperature: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
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


def tools_used(metadata: dict[str, Any]) -> tuple[ToolUse, ...]:
    """The toolheads this file extrudes from, in order."""
    used_mm = metadata.get("filament_used_mm")
    if not isinstance(used_mm, list):
        return ()
    types = split_slicer_list(str(metadata.get("filament_type", "")))
    names = split_slicer_list(str(metadata.get("filament_name", "")))
    colours = split_slicer_list(str(metadata.get("filament_colour", "")))
    return tuple(
        ToolUse(
            index=index,
            used_mm=_as_float(millimetres),
            used_grams=_number_at(metadata.get("filament_weight"), index),
            filament_type=_text_at(types, index),
            filament_name=_text_at(names, index),
            colour=_text_at(colours, index),
            nozzle_temperature=_number_at(metadata.get("nozzle_temp"), index),
        )
        for index, millimetres in enumerate(used_mm)
        if _as_float(millimetres) > 0
    )


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
