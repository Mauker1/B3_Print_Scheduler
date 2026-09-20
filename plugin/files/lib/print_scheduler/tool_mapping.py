# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deciding which toolhead each of a file's filament slots runs on.

A gcode file numbers its filaments by slicer slot. The printer numbers its hardware by toolhead.
They are not the same thing, and there is no default worth trusting: the printer falls back to
slot 0 on toolhead 0, which on a machine with four toolheads is right only by luck. It was not
right here. The first scheduled print on real hardware went into ASA because the file's slot 0
wanted white PLA, which was on toolhead 2.

So the map is chosen, not assumed, by matching what each slot needs against what is actually
loaded. Material must match; that is the part that ruins a print and a nozzle. Colour is a
tiebreaker and nothing more, because a slicer project's colours are whatever the person had set
that day: one file on this printer asks for white ASA while the only ASA loaded is black, and that
print is perfectly fine.

The match is made again at the moment the job fires, never trusted from when it was scheduled. A
job set at ten at night and run at six in the morning has had all night for someone to change a
spool.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from print_scheduler.gcode_files import ToolUse
from print_scheduler.printer import LoadedFilament

HEX_COLOUR_LENGTH = 6
HEX_DIGITS = frozenset("0123456789ABCDEF")


@dataclass(frozen=True)
class ToolAssignment:
    """One slicer slot, and the toolhead it will run on."""

    slot: int
    toolhead: int
    filament_type: str
    wanted_colour: str
    loaded_colour: str

    @property
    def colours_differ(self) -> bool:
        """Worth mentioning, never worth refusing over."""
        return bool(self.wanted_colour) and bool(self.loaded_colour) and (
            self.wanted_colour != self.loaded_colour
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "toolhead": self.toolhead,
            "filament_type": self.filament_type,
            "wanted_colour": self.wanted_colour,
            "loaded_colour": self.loaded_colour,
            "colours_differ": self.colours_differ,
        }


@dataclass(frozen=True)
class ToolPlan:
    """How a file's slots map onto toolheads, or why they cannot."""

    assignments: tuple[ToolAssignment, ...] = ()
    problem: str | None = None
    # False on a printer that does not track what is loaded. There is no map to get wrong there,
    # so the print starts without one rather than being refused for a question nobody asked.
    applicable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "problem": self.problem,
            "applicable": self.applicable,
        }

    def as_pairs(self) -> tuple[tuple[int, int], ...]:
        return tuple((one.slot, one.toolhead) for one in self.assignments)


def normalise_colour(value: str) -> str:
    """Reduce a colour to six hex digits, whether it arrived as #E2DEDB or as E2DEDBFF.

    Anything that is not six hex digits becomes empty rather than being truncated into
    something that could accidentally equal another truncation.
    """
    text = value.strip().lstrip("#").upper()[:HEX_COLOUR_LENGTH]
    if len(text) < HEX_COLOUR_LENGTH:
        return ""
    return text if all(character in HEX_DIGITS for character in text) else ""


def _same_material(wanted: str, loaded: str) -> bool:
    return bool(wanted) and wanted.strip().upper() == loaded.strip().upper()


def _choose_toolhead(
    slot: ToolUse, loaded: Sequence[LoadedFilament], taken: set[int]
) -> LoadedFilament | None:
    by_material = [
        candidate
        for candidate in loaded
        if candidate.present
        and candidate.index not in taken
        and _same_material(slot.filament_type, candidate.filament_type)
    ]
    if not by_material:
        return None
    wanted = normalise_colour(slot.colour)
    by_colour = [
        candidate for candidate in by_material if normalise_colour(candidate.colour) == wanted
    ]
    # Same material and same colour is the same filament as far as a print is concerned, so when
    # two are equally good the lower toolhead wins and the choice is at least predictable.
    return (by_colour or by_material)[0]


def _describe_what_is_loaded(loaded: Sequence[LoadedFilament]) -> str:
    present = [f"T{one.index} {one.filament_type or 'nothing'}" for one in loaded if one.present]
    return ", ".join(present) if present else "nothing"


def plan_tools(slots: Sequence[ToolUse], loaded: Sequence[LoadedFilament]) -> ToolPlan:
    """Work out which toolhead each slot runs on, or say why none will do."""
    if not loaded:
        return ToolPlan(applicable=False)
    if not slots:
        return ToolPlan(problem="the file does not say what material it needs")
    return _assign_each(slots, loaded)


def _assign_each(slots: Sequence[ToolUse], loaded: Sequence[LoadedFilament]) -> ToolPlan:
    assignments: list[ToolAssignment] = []
    taken: set[int] = set()
    for slot in sorted(slots, key=lambda one: one.slot):
        if not slot.filament_type:
            return ToolPlan(problem=f"the file does not say what material slot {slot.slot} needs")
        chosen = _choose_toolhead(slot, loaded, taken)
        if chosen is None:
            return ToolPlan(
                problem=f"no free toolhead has {slot.filament_type} loaded. The printer reports "
                f"{_describe_what_is_loaded(loaded)}."
            )
        taken.add(chosen.index)
        assignments.append(
            ToolAssignment(
                slot=slot.slot,
                toolhead=chosen.index,
                filament_type=chosen.filament_type,
                wanted_colour=normalise_colour(slot.colour),
                loaded_colour=normalise_colour(chosen.colour),
            )
        )
    return ToolPlan(assignments=tuple(assignments))
