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
from math import dist
from typing import Any

from print_scheduler.gcode_files import ToolUse
from print_scheduler.printer import LoadedFilament

HEX_COLOUR_LENGTH = 6
HEX_DIGITS = frozenset("0123456789ABCDEF")

# A colour neither side stated cannot be scored, and must not look better or worse than one
# that matches. Zero, so it neither attracts nor repels, and the toolhead index decides.
UNKNOWN_COLOUR_DISTANCE = 0.0


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


def _channels(value: str) -> tuple[int, int, int] | None:
    text = normalise_colour(value)
    if not text:
        return None
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def colour_distance(wanted: str, loaded: str) -> float | None:
    """How far apart two colours are, or None when either side did not say.

    Straight line distance in RGB, which is a crude model of how colours look and an entirely
    adequate one for the question being asked: of the toolheads holding the right material,
    which is nearest to what the file asked for.
    """
    first, second = _channels(wanted), _channels(loaded)
    if first is None or second is None:
        return None
    return dist(first, second)


def _same_material(wanted: str, loaded: str) -> bool:
    return bool(wanted) and wanted.strip().upper() == loaded.strip().upper()


def _cost(slot: ToolUse, candidate: LoadedFilament) -> float:
    apart = colour_distance(slot.colour, candidate.colour)
    return UNKNOWN_COLOUR_DISTANCE if apart is None else apart


def _describe_what_is_loaded(loaded: Sequence[LoadedFilament]) -> str:
    present = [f"T{one.index} {one.filament_type or 'nothing'}" for one in loaded if one.present]
    return ", ".join(present) if present else "nothing"


def plan_tools(slots: Sequence[ToolUse], loaded: Sequence[LoadedFilament]) -> ToolPlan:
    """Work out which toolhead each slot runs on, or say why none will do."""
    if not loaded:
        return ToolPlan(applicable=False)
    if not slots:
        return ToolPlan(problem="the file does not say what material it needs")
    return _assign_each(sorted(slots, key=lambda one: one.slot), loaded)


def _assign_each(slots: Sequence[ToolUse], loaded: Sequence[LoadedFilament]) -> ToolPlan:
    """Choose the whole mapping at once, rather than one slot at a time.

    Taking each slot's own best toolhead in turn is the obvious thing and it is wrong: slot 0
    can take the toolhead slot 1 needed far more, when slot 0 had an almost as good second
    choice. The assignments are not independent, so the thing being minimised is the total
    across all of them. With a handful of slots and a handful of toolheads the search is small
    enough to be exhaustive, which is better than being clever.
    """
    usable = [one for one in loaded if one.present]
    options: list[list[LoadedFilament]] = []
    for slot in slots:
        if not slot.filament_type:
            return ToolPlan(problem=f"the file does not say what material slot {slot.slot} needs")
        matching = [one for one in usable if _same_material(slot.filament_type, one.filament_type)]
        if not matching:
            return ToolPlan(
                problem=f"no free toolhead has {slot.filament_type} loaded. The printer reports "
                f"{_describe_what_is_loaded(loaded)}."
            )
        # Nearest colour first, then lowest toolhead, so the search reaches a good answer early
        # and the pruning has something to prune against.
        matching.sort(key=lambda one: (_cost(slot, one), one.index))
        options.append(matching)

    chosen = _cheapest_whole_assignment(slots, options)
    if chosen is None:
        return ToolPlan(problem=_why_there_are_not_enough(slots, loaded))
    return ToolPlan(
        assignments=tuple(
            ToolAssignment(
                slot=slot.slot,
                toolhead=candidate.index,
                filament_type=candidate.filament_type,
                wanted_colour=normalise_colour(slot.colour),
                loaded_colour=normalise_colour(candidate.colour),
            )
            for slot, candidate in zip(slots, chosen, strict=True)
        )
    )


def _cheapest_whole_assignment(
    slots: Sequence[ToolUse], options: Sequence[Sequence[LoadedFilament]]
) -> tuple[LoadedFilament, ...] | None:
    """The assignment with the least total colour distance, or None if there is not one.

    Ties are broken on the toolhead numbers, lowest first, so that two equally good answers
    always come out the same way round and a person watching the page sees something stable.
    """
    best: tuple[float, tuple[int, ...]] | None = None
    best_choice: tuple[LoadedFilament, ...] | None = None

    def walk(
        position: int, taken: frozenset[int], picked: list[LoadedFilament], running: float
    ) -> None:
        nonlocal best, best_choice
        # Distances are never negative, so a partial assignment already worse than the best
        # complete one cannot be rescued by the slots that remain.
        if best is not None and running > best[0]:
            return
        if position == len(slots):
            score = (running, tuple(one.index for one in picked))
            if best is None or score < best:
                best, best_choice = score, tuple(picked)
            return
        for candidate in options[position]:
            if candidate.index in taken:
                continue
            walk(
                position + 1,
                taken | {candidate.index},
                [*picked, candidate],
                running + _cost(slots[position], candidate),
            )

    walk(0, frozenset(), [], 0.0)
    return best_choice


def _why_there_are_not_enough(
    slots: Sequence[ToolUse], loaded: Sequence[LoadedFilament]
) -> str:
    """Every slot had somewhere it could go, and they could not all go somewhere at once."""
    usable = [one for one in loaded if one.present]
    for material in dict.fromkeys(slot.filament_type for slot in slots):
        needed = sum(1 for slot in slots if _same_material(slot.filament_type, material))
        held = sum(1 for one in usable if _same_material(material, one.filament_type))
        if needed > held:
            return (
                f"This file needs {needed} toolheads with {material} and the printer has "
                f"{held}. The printer reports {_describe_what_is_loaded(loaded)}."
            )
    return (
        f"the file's slots cannot all be given a toolhead of their own. The printer reports "
        f"{_describe_what_is_loaded(loaded)}."
    )
