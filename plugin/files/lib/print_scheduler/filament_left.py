# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether a spool has enough left on it for what a job will take from it.

A warning and nothing more. Running out is something a printer can recover from: it refills from
another spool or pauses for somebody to load one. So nothing here holds a job or refuses one; it
only says, beside the slot and on the waiting row, that a toolhead has less left than the file
asks of it, and leaves the rest to the printer and to whoever reads it.

Both numbers are estimates. The grams a slot needs are the slicer's, and the grams left are
Spoolman's, counted from what it was told was used. So a spool is only flagged when what is
needed is more than what is left, never when it is merely close: a warning for every spool that
might be close would be read once and then ignored.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from print_scheduler.jobs import Job
from print_scheduler.printer import SpoolLeft


@dataclass(frozen=True)
class Shortfall:
    """One toolhead whose spool has less left than the job needs from it."""

    toolhead: int
    needed: float
    left: float

    def to_dict(self) -> dict[str, Any]:
        return {"toolhead": self.toolhead, "needed": self.needed, "left": self.left}


def shortfalls(
    needs: Iterable[tuple[int, float]], left: Sequence[SpoolLeft]
) -> tuple[Shortfall, ...]:
    """The toolheads that need more than they have, from (toolhead, grams) pairs.

    Needs are added up per toolhead first, because two slots printing from one spool take from
    the same spool, and either alone may fit where both together do not. A toolhead with no
    reading is left out: not knowing is not a shortage.
    """
    totals: dict[int, float] = {}
    for toolhead, grams in needs:
        totals[toolhead] = totals.get(toolhead, 0.0) + grams
    on_the_spool = {one.toolhead: one.grams for one in left}
    return tuple(
        Shortfall(toolhead=toolhead, needed=needed, left=on_the_spool[toolhead])
        for toolhead, needed in sorted(totals.items())
        if toolhead in on_the_spool and needed > on_the_spool[toolhead]
    )


def needs_of(job: Job) -> list[tuple[int, float]]:
    """What a waiting job will take from each toolhead, on the map it is going to start on.

    The map is the one recorded when somebody saw it. A job recorded with nothing to map runs the
    file's own numbering, slot 0 on T0, so that is what it takes from. A job with no record at all
    is waiting for somebody to confirm its map, and until then there is no telling.
    """
    if not job.slot_grams or job.toolheads_seen is None:
        return []
    if not job.toolheads_seen:
        return list(job.slot_grams)
    return needs_on([(one.slot, one.toolhead) for one in job.toolheads_seen], job.slot_grams)


def needs_on(
    pairs: Iterable[tuple[int, int]], slot_grams: Iterable[tuple[int, float]]
) -> list[tuple[int, float]]:
    """What each toolhead of a slot to toolhead map would take, from the grams per slot."""
    toolhead_of = dict(pairs)
    return [(toolhead_of[slot], grams) for slot, grams in slot_grams if slot in toolhead_of]
