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

Or the person chooses, and then the map is theirs as they chose it: a different material, if they
say so, and several slots on one toolhead, if they want two of the file's colours from one spool.
The scheduler's record of what is loaded can be wrong, and that is exactly when somebody needs to
overrule it.

Either way, a job starts only on a map somebody saw. What each toolhead held at that moment is
recorded, and it is compared with what is loaded when the job fires. A job set at ten at night
and run at six in the morning has had all night for someone to change a spool, and if somebody
did, the job waits for a person rather than starting on a map nobody has looked at.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import dist
from typing import Any

from print_scheduler.gcode_files import ToolUse
from print_scheduler.jobs import SeenToolhead
from print_scheduler.messages import Message, Said, Value
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
    # What the toolhead holds, which is what the print will actually use.
    filament_type: str
    wanted_colour: str
    loaded_colour: str
    # What the file asked for. The same material as `filament_type` whenever the scheduler
    # chose; possibly not when a person did.
    wanted_material: str = ""

    @property
    def colours_differ(self) -> bool:
        """Worth mentioning, never worth refusing over."""
        return bool(self.wanted_colour) and bool(self.loaded_colour) and (
            self.wanted_colour != self.loaded_colour
        )

    @property
    def materials_differ(self) -> bool:
        """Only ever by a person's choice, and only printed once they have said they mean it.

        A slot whose file names no material cannot differ from anything, so it asks nothing.
        """
        return bool(self.wanted_material) and not _same_material(
            self.wanted_material, self.filament_type
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot": self.slot,
            "toolhead": self.toolhead,
            "filament_type": self.filament_type,
            "wanted_colour": self.wanted_colour,
            "loaded_colour": self.loaded_colour,
            "colours_differ": self.colours_differ,
            "wanted_material": self.wanted_material,
            "materials_differ": self.materials_differ,
        }


@dataclass(frozen=True)
class ToolPlan:
    """How a file's slots map onto toolheads, or why they cannot."""

    assignments: tuple[ToolAssignment, ...] = ()
    problem: Said | None = None
    # False on a printer that does not track what is loaded. There is no map to get wrong there,
    # so the print starts without one rather than being refused for a question nobody asked.
    applicable: bool = True
    # True when there is a map to make and nobody has ever seen one: a job scheduled before
    # maps were recorded, on a printer that reports what is loaded.
    unconfirmed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignments": [assignment.to_dict() for assignment in self.assignments],
            "problem": None if self.problem is None else self.problem.in_english(),
            "problem_key": "" if self.problem is None else self.problem.key.value,
            "problem_values": {} if self.problem is None else self.problem.wire_values(),
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


def _describe_what_is_loaded(loaded: Sequence[LoadedFilament]) -> Value:
    """What the printer has loaded, as a phrase the reader's own language can order.

    A list of toolheads is built from three separate messages: each entry, the word for an
    empty one, and the separator. Joining translated pieces is normally the thing not to do,
    and this is the exception the design allows, because every piece here is a noun phrase and
    none of them is a fragment of a sentence.
    """
    present = [
        Said(
            Message.LOADED_TOOLHEAD,
            {"index": one.index, "material": one.filament_type or Said(Message.NOTHING_LOADED)},
        )
        for one in loaded
        if one.present
    ]
    if not present:
        return Said(Message.NOTHING_LOADED)
    return tuple(present)


def plan_tools(slots: Sequence[ToolUse], loaded: Sequence[LoadedFilament]) -> ToolPlan:
    """Work out which toolhead each slot runs on, or say why none will do."""
    if not loaded:
        return ToolPlan(applicable=False)
    if not slots:
        return ToolPlan(problem=Said(Message.MATERIAL_UNKNOWN))
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
            return ToolPlan(
                problem=Said(Message.SLOT_MATERIAL_UNKNOWN, {"slot": slot.slot})
            )
        matching = [one for one in usable if _same_material(slot.filament_type, one.filament_type)]
        if not matching:
            return ToolPlan(
                problem=Said(
                    Message.NONE_FREE_WITH_MATERIAL,
                    {
                        "material": slot.filament_type,
                        "loaded": _describe_what_is_loaded(loaded),
                    },
                )
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
                wanted_material=slot.filament_type,
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
) -> Said:
    """Every slot had somewhere it could go, and they could not all go somewhere at once."""
    usable = [one for one in loaded if one.present]
    for material in dict.fromkeys(slot.filament_type for slot in slots):
        needed = sum(1 for slot in slots if _same_material(slot.filament_type, material))
        held = sum(1 for one in usable if _same_material(material, one.filament_type))
        if needed > held:
            return Said(
                Message.NOT_ENOUGH_OF_MATERIAL,
                {
                    "needed": Said(Message.TOOLHEAD_COUNT, {"count": needed}),
                    "material": material,
                    "held": held,
                    "loaded": _describe_what_is_loaded(loaded),
                },
            )
    return Said(
        Message.CANNOT_GIVE_EACH_ITS_OWN, {"loaded": _describe_what_is_loaded(loaded)}
    )


def plan_chosen(
    slots: Sequence[ToolUse],
    loaded: Sequence[LoadedFilament],
    chosen: Sequence[tuple[int, int]],
) -> ToolPlan:
    """The person's own map, taken as it is and refused only where it cannot be carried out.

    Every slot the file uses, exactly once, each on a toolhead the printer reports and that has
    something in it. A different material from the one the file asks for is not refused here:
    the printer's record of what is loaded can be wrong, which is the case this exists for, and
    the service asks the person to say they mean it. Two slots on one toolhead are not refused
    either. They print from the same spool, and some people want exactly that.
    """
    if not loaded:
        return ToolPlan(applicable=False)
    problem = _why_the_choice_cannot_be_carried_out(slots, loaded, chosen)
    if problem is not None:
        return ToolPlan(problem=problem)
    wanted = {one.slot: one for one in slots}
    by_index = {one.index: one for one in loaded}
    return ToolPlan(
        assignments=tuple(
            ToolAssignment(
                slot=slot,
                toolhead=toolhead,
                filament_type=by_index[toolhead].filament_type,
                wanted_colour=normalise_colour(wanted[slot].colour),
                loaded_colour=normalise_colour(by_index[toolhead].colour),
                wanted_material=wanted[slot].filament_type,
            )
            for slot, toolhead in sorted(chosen)
        )
    )


def _why_the_choice_cannot_be_carried_out(
    slots: Sequence[ToolUse],
    loaded: Sequence[LoadedFilament],
    chosen: Sequence[tuple[int, int]],
) -> Said | None:
    if not slots:
        return Said(Message.MATERIAL_UNKNOWN)
    wanted = sorted(one.slot for one in slots)
    if sorted(slot for slot, _ in chosen) != wanted:
        return Said(Message.MAP_INCOMPLETE, {"slots": tuple(wanted), "count": len(wanted)})
    by_index = {one.index: one for one in loaded}
    for _, toolhead in sorted(chosen):
        why = _why_not_this_toolhead(toolhead, by_index.get(toolhead))
        if why is not None:
            return why
    return None


def _why_not_this_toolhead(toolhead: int, candidate: LoadedFilament | None) -> Said | None:
    if candidate is None:
        return Said(Message.MAP_TOOLHEAD_UNKNOWN, {"toolhead": toolhead})
    if not candidate.present:
        return Said(Message.MAP_TOOLHEAD_EMPTY, {"toolhead": toolhead})
    return None


def what_was_seen(plan: ToolPlan) -> tuple[SeenToolhead, ...]:
    """The record a job starts on: each slot, its toolhead, and what that toolhead held.

    Empty where there is no map, on a printer that does not report what is loaded, which is a
    record in its own right and not the same thing as having none.
    """
    if not plan.applicable:
        return ()
    return tuple(
        SeenToolhead(
            slot=one.slot,
            toolhead=one.toolhead,
            material=one.filament_type,
            colour=one.loaded_colour,
        )
        for one in plan.assignments
    )


def plan_as_seen(
    slots: Sequence[ToolUse],
    loaded: Sequence[LoadedFilament],
    seen: Sequence[SeenToolhead],
) -> ToolPlan:
    """The map somebody saw, if the printer still holds what they saw, or what has changed.

    Material and colour both count. The colour is only a tiebreaker when the scheduler chooses,
    but a person who saw white on T2 and accepted it did not accept whatever T2 holds now.
    Every change is named, not just the first, so one look at the row says all of it.
    """
    if not seen:
        return ToolPlan(problem=Said(Message.NOT_REPORTED_WHEN_SCHEDULED))
    changes: list[Said] = []
    now_slots = tuple(sorted(one.slot for one in slots))
    was_slots = tuple(sorted(one.slot for one in seen))
    if now_slots != was_slots:
        changes.append(Said(Message.SLOTS_CHANGED, {"was": was_slots, "now": now_slots}))
    by_index = {one.index: one for one in loaded}
    for toolhead, entries in _by_toolhead(seen):
        first = entries[0]
        values: dict[str, Any] = {
            "toolhead": toolhead,
            "slots": tuple(one.slot for one in entries),
            "count": len(entries),
            "was": _filament(first.material, first.colour),
        }
        current = by_index.get(toolhead)
        if current is None:
            changes.append(Said(Message.TOOLHEAD_GONE, values))
        elif not current.present:
            changes.append(Said(Message.TOOLHEAD_NOW_EMPTY, values))
        elif not _still_holds(first, current):
            values["now"] = _filament(current.filament_type, normalise_colour(current.colour))
            changes.append(Said(Message.TOOLHEAD_NOW_HOLDS, values))
    if changes:
        return ToolPlan(problem=Said(Message.TOOLHEADS_CHANGED, {"changes": tuple(changes)}))
    wanted = {one.slot: one for one in slots}
    return ToolPlan(
        assignments=tuple(
            ToolAssignment(
                slot=one.slot,
                toolhead=one.toolhead,
                filament_type=one.material,
                wanted_colour=normalise_colour(wanted[one.slot].colour),
                loaded_colour=one.colour,
                wanted_material=wanted[one.slot].filament_type,
            )
            for one in sorted(seen, key=lambda entry: entry.slot)
        )
    )


def _by_toolhead(
    seen: Sequence[SeenToolhead],
) -> list[tuple[int, tuple[SeenToolhead, ...]]]:
    """Grouped, so two slots sharing a toolhead make one change rather than two."""
    grouped: dict[int, list[SeenToolhead]] = {}
    for one in sorted(seen, key=lambda entry: (entry.toolhead, entry.slot)):
        grouped.setdefault(one.toolhead, []).append(one)
    return [(toolhead, tuple(entries)) for toolhead, entries in grouped.items()]


def _still_holds(seen: SeenToolhead, current: LoadedFilament) -> bool:
    return (
        seen.material.strip().upper() == current.filament_type.strip().upper()
        and seen.colour == normalise_colour(current.colour)
    )


def _filament(material: str, colour: str) -> Value:
    named: Value = material or Said(Message.UNNAMED_MATERIAL)
    if not colour:
        return named
    return Said(Message.FILAMENT_WITH_COLOUR, {"material": named, "colour": colour})
