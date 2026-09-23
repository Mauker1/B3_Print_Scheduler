# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The settings the person chose, read from the daemon's file.

Read afresh on every use rather than once at startup, so changing a setting in the app takes
effect without restarting the service. That is the whole reason this is a class holding a path
rather than a few values read at boot.

**A value that cannot be used is said out loud.** The platform has no way to bound a number
field: the manifest's `config` block has `type`, `default`, `hint` and so on, and nothing for a
minimum, so `-1` reaches us and something has to happen. Falling back to the default is the
right behaviour and doing it in silence is not, because the person then has a printer quietly
behaving differently from the number they are looking at.

Absent is not invalid. A setting nobody has touched, or a file the daemon has not written yet,
is the default and says nothing. Only a value that is *there* and unusable is worth a word.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from print_scheduler.messages import ENGLISH, Message, Said, a_duration, known_tags

# The name Bespok3d's own plugins log under. Ours is a service in its own process rather than
# code inside Klipper, so nothing configures logging for us and the entry point attaches the
# handler; see `cli.py`. Named to match the convention so that the day the platform offers
# service plugins a route into the shared log, we are already calling ourselves the right thing.
_log = logging.getLogger("bespok3d.print_scheduler")

TOLERANCE_VARIABLE = "START_TOLERANCE_MINUTES"
SETTLED_KEPT_VARIABLE = "SETTLED_JOBS_KEPT"
LANGUAGE_VARIABLE = "LANGUAGE"

DEFAULT_TOLERANCE_MINUTES = 5.0
DEFAULT_SETTLED_KEPT = 25
SECONDS_PER_MINUTE = 60.0


@dataclass(frozen=True)
class Ignored:
    """One setting that was there, could not be used, and was replaced by its default."""

    setting: str
    found: str
    # What is being used instead, which may be a message rather than a string: "5 minutes" is
    # a phrase in English and a different one in Portuguese, and a fallback that names itself
    # in the wrong language is exactly the kind of half translation this project is avoiding.
    using: Any

    def said(self) -> Said:
        return Said(
            Message.SETTING_IGNORED,
            {"setting": self.setting, "found": self.found, "using": self.using},
        )

    def sentence(self) -> str:
        """The English sentence, which is what the log keeps and what the page falls back to."""
        return self.said().in_english()


class Settings:
    """Every setting, read fresh, with a memory of what it has already complained about."""

    def __init__(self, path: Path) -> None:
        self.path = path
        # Said once per process per setting, as agreed: a log is a record rather than a live
        # monitor, and these are read on every tick and on every page poll, so complaining on
        # each read would be thousands of identical lines a day and a log nobody reads.
        self._said: set[str] = set()
        # The page gets the live truth instead, so fixing the value clears the warning on the
        # next poll without waiting for a restart. That is the difference between the two
        # channels, and it is deliberate.
        self._ignored: dict[str, Ignored] = {}

    def ignored(self) -> tuple[Ignored, ...]:
        """What is being ignored right now, for the page to show the person who typed it."""
        return tuple(self._ignored[name] for name in sorted(self._ignored))

    def tolerance_seconds(self) -> float:
        """How late a job may still start, in seconds.

        Zero is a real answer and a deliberate one: tolerate no lateness at all. Since the
        schedule is looked at every twenty seconds rather than continuously, that cancels
        nearly every job, which is documented rather than prevented. A negative is not an
        answer to anything.
        """
        minutes = self._number(
            TOLERANCE_VARIABLE,
            DEFAULT_TOLERANCE_MINUTES,
            a_duration(DEFAULT_TOLERANCE_MINUTES * SECONDS_PER_MINUTE),
        )
        return minutes * SECONDS_PER_MINUTE

    def settled_kept(self) -> int:
        """How many settled jobs to show. A display preference, and only that."""
        return int(self._number(SETTLED_KEPT_VARIABLE, float(DEFAULT_SETTLED_KEPT), "25"))

    def language(self) -> str:
        """Which language the page starts in, for every reader who has not chosen their own.

        A tag nobody ships is the same shape of mistake as a negative tolerance: it is there,
        it cannot be used, and saying so beats quietly serving English to somebody who asked
        for something else. The page decides what to do with it from there.
        """
        raw = self._raw(LANGUAGE_VARIABLE)
        if raw is None:
            self._ignored.pop(LANGUAGE_VARIABLE, None)
            return ENGLISH
        tag = str(raw).strip()
        if tag in known_tags():
            self._ignored.pop(LANGUAGE_VARIABLE, None)
            return tag
        self._complain(LANGUAGE_VARIABLE, repr(raw), ENGLISH)
        return ENGLISH

    def _number(self, name: str, default: float, said_as: Any) -> float:
        raw = self._raw(name)
        if raw is None:
            self._ignored.pop(name, None)
            return default
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return self._fall_back(name, repr(raw), said_as, default)
        if value < 0:
            return self._fall_back(name, f"{value:g}", said_as, default)
        self._ignored.pop(name, None)
        return value

    def _raw(self, name: str) -> Any:
        """The value as written, or None when there is nothing there to judge."""
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return values.get(name) if isinstance(values, dict) else None

    def _fall_back(self, name: str, found: str, said_as: Any, default: float) -> float:
        self._complain(name, found, said_as)
        return default

    def _complain(self, name: str, found: str, said_as: Any) -> None:
        """Say it on the page for as long as it is true, and in the log once, in English."""
        self._ignored[name] = Ignored(setting=name, found=found, using=said_as)
        if name not in self._said:
            self._said.add(name)
            in_english = said_as.in_english() if isinstance(said_as, Said) else said_as
            _log.warning(
                "%s is set to %s, which cannot be used; falling back to %s",
                name,
                found,
                in_english,
            )
