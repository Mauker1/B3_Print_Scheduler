# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How long the scheduler was away.

A schedule is a list of promises to move a hot nozzle, and this plugin can stop running without
anybody deciding that it should. The daemon deactivates a plugin that breaks Klipper or Moonraker,
so that the printer keeps working; the printer itself gets switched off for a fortnight; somebody
uninstalls the plugin and the schedule survives, because the platform keeps a plugin's data on
purpose so that nobody loses their work.

In every one of those the plugin comes back and finds promises nobody has looked at since. Acting
on them is the failure this whole project is built to avoid, and the printer cannot tell us which
of the three happened, so the question worth asking is not *why* we were away but *how long*. That
is all this file measures.

The mark is deliberately coarse. A schedule is judged against a silence of a day, so a timestamp
written every few minutes is precise to well under a percent of the thing it measures, and the
printer's flash is spared four thousand writes a day for a number nobody reads at that resolution.
"""

from __future__ import annotations

from pathlib import Path

# Long enough that a printer switched off overnight, or a plugin upgraded between two breaths,
# says nothing at all. Short enough that a forgotten uninstall or a quiet deactivation is caught
# well before the print it would have started.
A_LONG_SILENCE_SECONDS = 24 * 60 * 60

# How often the mark is rewritten while the service is up. See the note above about flash.
MARK_NO_MORE_OFTEN_THAN_SECONDS = 5 * 60


class Heartbeat:
    """A single timestamp on disk: the last moment the scheduler is known to have been running."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._marked_at: float | None = None

    def last_seen(self) -> float | None:
        """When the scheduler was last running, or None if it has never recorded being alive.

        None is the honest answer for a first install, and it is also the answer after an
        upgrade from a version that never wrote one. Both must read as no silence at all: an
        install with nothing behind it has no stale promises, and an upgrade takes seconds.
        """
        try:
            return float(self.path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def silence_before(self, now: float) -> float:
        """How long the scheduler was away before this moment, as far as it can tell.

        Zero when it cannot tell, and zero when the clock has gone backwards. A printer whose
        clock jumps is usually one that has just come up without a network, and inventing a
        silence out of that would be reading noise as evidence.
        """
        seen = self.last_seen()
        if seen is None:
            return 0.0
        return max(0.0, now - seen)

    def mark(self, now: float) -> None:
        """Record being alive, at most every few minutes, and never fatally.

        A mark that cannot be written is worth no more than a note. The cost of failing here is
        that a later silence reads as longer than it was, which errs towards asking, which is
        the safe direction.
        """
        if self._marked_at is not None and now - self._marked_at < MARK_NO_MORE_OFTEN_THAN_SECONDS:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            being_written = self.path.with_name(self.path.name + ".writing")
            being_written.write_text(f"{now:.0f}\n", encoding="utf-8")
            being_written.replace(self.path)
        except OSError as unwritable:
            print(f"could not record being alive at {self.path}: {unwritable}", flush=True)
            return
        self._marked_at = now
