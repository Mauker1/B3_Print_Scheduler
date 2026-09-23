# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every sentence this plugin says to a person, as a key and the values that fill it.

A scheduler records why a job did not run, and that record outlives the wording. Storing the
rendered sentence means a message reworded today never reaches a job settled yesterday, and it
means a schedule read in one language keeps its history in another. So nothing stores a
sentence: a decision stores the key and the values, and the sentence is made at the moment
somebody reads it.

**What is never translated.** The printer's own words: Klipper's state and message, Moonraker's
refusal, the filename. They arrive as values and pass through untouched, because translating a
machine's message makes it unsearchable and unreportable. Our own vocabulary, including a job's
state, is ours to say in the reader's language and is a key like any other sentence.

**Nothing here raises.** A missing key, a missing catalogue, a mistyped placeholder: each falls
back, and the last fallback is the key itself. A typo in a translation must not be able to stop
a print from being scheduled, and that rule is worth more than any sentence it protects.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_log = logging.getLogger("bespok3d.print_scheduler")

LOCALE_DIR = Path(__file__).resolve().parent / "locale"
ENGLISH = "en"

# A tag arrives from a setting somebody typed, and it is about to become a filename. Anything
# that is not a language tag never reaches the disk.
TAG_SHAPE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")

# The marker that says a value is itself a message rather than a piece of text. It is the one
# composition this design allows: a phrase like "five minutes" is a noun phrase in both
# languages, and rendering it separately keeps the number and its unit together where a
# translator can move them as one.
NESTED = "message"

SECONDS_PER_MINUTE = 60


class Message(str, Enum):
    """Every key the Python side renders. The page has its own, checked against the same file."""

    # Durations, always nested inside another sentence.
    DURATION_SECONDS = "duration.seconds"
    DURATION_MINUTES = "duration.minutes"

    # A job's own state, said the way a person would say it. Ours, so translated.
    STATE_SCHEDULED = "state.scheduled"
    STATE_STARTING = "state.starting"
    STATE_STARTED = "state.started"
    STATE_CANCELLED = "state.cancelled"

    # Why a job did not start, or what happened when it did.
    ANOTHER_JOB_STARTED = "detail.another-job-started"
    MISSED = "detail.missed"
    FILENAME_EMPTY = "detail.filename-empty"
    FILENAME_HAS_HASH = "detail.filename-has-hash"
    FILENAME_HAS_QUOTE = "detail.filename-has-quote"
    PRINTER_DID_NOT_ANSWER = "detail.printer-did-not-answer"
    KLIPPER_STARTING = "detail.klipper-starting"
    KLIPPER_NOT_READY = "detail.klipper-not-ready"
    PRINTER_WAS_PRINTING = "detail.printer-was-printing"
    PRINTER_WAS_PAUSED = "detail.printer-was-paused"
    PRINTER_WAS_BUSY = "detail.printer-was-busy"
    ANOTHER_JOB = "detail.another-job"
    BED_STATE_WITH_NO_RECORD = "detail.bed-state-with-no-record"
    BED_PRINT_AFTER_THE_PROMISE = "detail.bed-print-after-the-promise"
    THE_PRINTER_SAID = "detail.the-printer-said"
    OTHER_GCODE_RUNNING = "detail.other-gcode-running"
    FILE_GONE = "detail.file-gone"
    START_NOT_SEEN_YET = "detail.start-not-seen-yet"
    START_DID_NOT_TAKE = "detail.start-did-not-take"
    RECORDED_AS_JOB = "detail.recorded-as-job"
    RUNNING_WITH_NO_HISTORY = "detail.running-with-no-history"
    ACCEPTED_THE_START = "detail.accepted-the-start"
    ACCEPTED_THE_START_WITH_SLOTS = "detail.accepted-the-start-with-slots"
    SLOT_ON_TOOLHEAD = "detail.slot-on-toolhead"
    CANCELLED_BY_YOU = "detail.cancelled-by-you"

    # Why no toolhead will do.
    MATERIAL_UNKNOWN = "toolhead.material-unknown"
    SLOT_MATERIAL_UNKNOWN = "toolhead.slot-material-unknown"
    NONE_FREE_WITH_MATERIAL = "toolhead.none-free-with-material"
    NOT_ENOUGH_OF_MATERIAL = "toolhead.not-enough-of-material"
    CANNOT_GIVE_EACH_ITS_OWN = "toolhead.cannot-give-each-its-own"
    COULD_NOT_DESCRIBE_FILE = "toolhead.could-not-describe-file"
    LOADED_TOOLHEAD = "toolhead.loaded"
    TOOLHEAD_COUNT = "toolhead.count"
    NOTHING_LOADED = "toolhead.nothing"

    # Refused at the moment somebody asked, rather than at six in the morning.
    NO_SUCH_JOB = "refused.no-such-job"
    NOT_SETTLED_YET = "refused.not-settled-yet"
    ALREADY_UNDERWAY = "refused.already-underway"
    ALREADY_SETTLED = "refused.already-settled"
    BED_NOT_PROMISED = "refused.bed-not-promised"
    TIME_ALREADY_PASSED = "refused.time-already-passed"
    NOT_ON_THE_PRINTER = "refused.not-on-the-printer"

    # A setting that was there and could not be used.
    SETTING_IGNORED = "setting.ignored"

    # How a list of things is joined. A typographic choice, so the catalogue owns it.
    LIST_SEPARATOR = "list.separator"


# What a placeholder may be filled with. A plain value, another message, or a sequence of
# either, which the reader's own separator joins.
Value = Any


@dataclass(frozen=True)
class Said:
    """One message, ready to be rendered in whatever language the reader wants.

    A value may itself be a `Said`, which is how a duration reaches the middle of a sentence
    without its number and its unit being torn apart.
    """

    key: Message
    values: Mapping[str, Any] = field(default_factory=dict)

    def in_english(self) -> str:
        """The English sentence, which is what the log and the stored record keep."""
        return say(ENGLISH, self.key, self.values)

    def wire_values(self) -> dict[str, Any]:
        """The values as JSON, with any nested message left as a message for the reader."""
        return {name: _as_json(value) for name, value in self.values.items()}


def _as_json(value: Any) -> Any:
    if isinstance(value, Said):
        return {NESTED: value.key.value, "values": value.wire_values()}
    if isinstance(value, (list, tuple)):
        return [_as_json(one) for one in value]
    return value


def a_duration(seconds: float) -> Said:
    """A length of time in the largest unit that does not round it away.

    Flooring to whole minutes reported anything under a minute as "0 minutes", and a reason
    that reads as nonsense sends the reader looking for a bug in the plugin rather than at the
    setting they typed.
    """
    if seconds < SECONDS_PER_MINUTE:
        return Said(Message.DURATION_SECONDS, {"count": int(seconds)})
    return Said(Message.DURATION_MINUTES, {"count": int(seconds // SECONDS_PER_MINUTE)})


def known_tags() -> tuple[str, ...]:
    """Every catalogue on disk, English first and the rest in alphabetical order."""
    try:
        found = sorted(path.stem for path in LOCALE_DIR.glob("*.json"))
    except OSError:
        return (ENGLISH,)
    rest = [tag for tag in found if tag != ENGLISH and TAG_SHAPE.match(tag)]
    return (ENGLISH, *rest)


_loaded: dict[str, tuple[float, dict[str, Any]]] = {}


def catalogue(tag: str) -> dict[str, Any]:
    """The catalogue for one language tag, read afresh whenever the file on disk changes.

    Re-reading means an edit over SSH shows up on the next page load, the same way the
    tolerance does, and the stat call it costs is nothing beside the request it serves.
    """
    if not TAG_SHAPE.match(tag or ""):
        return {}
    path = LOCALE_DIR / f"{tag}.json"
    try:
        changed_at = path.stat().st_mtime
    except OSError:
        return {}
    remembered = _loaded.get(tag)
    if remembered is not None and remembered[0] == changed_at:
        return remembered[1]
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as unreadable:
        _log.warning("could not read the %s catalogue, falling back: %s", tag, unreadable)
        entries = {}
    if not isinstance(entries, dict):
        _log.warning("the %s catalogue is not an object of keys, falling back", tag)
        entries = {}
    _loaded[tag] = (changed_at, entries)
    return entries


def say(tag: str, key: str, values: Mapping[str, Any] | None = None) -> str:
    """Render one message in one language, whatever is missing or malformed.

    The fallback chain is the whole point: this language, then English, then the key itself. A
    reader seeing a bare key knows something is wrong; a reader seeing a traceback does not get
    to read anything at all.
    """
    wanted = _key_text(key)
    filled = {name: _rendered(tag, value) for name, value in dict(values or {}).items()}
    template = _template(tag, wanted, filled)
    if template is None:
        return wanted
    try:
        return template.format_map(_WhateverIsMissing(filled))
    except (IndexError, KeyError, ValueError):
        return template


def _key_text(key: str) -> str:
    """The key as it is spelled in the catalogue.

    `str()` on a member of a string enum gives "Message.MISSED" rather than the value, which
    looks up nothing and prints as nonsense. This is the one place that has to know.
    """
    return key.value if isinstance(key, Message) else str(key)


def _rendered(tag: str, value: Any) -> Any:
    """One placeholder's value, with a message rendered and a sequence joined.

    Joining translated pieces is normally the mistake this whole module exists to avoid. It is
    allowed here because every piece is a noun phrase, never a fragment of a sentence, and
    because the separator is itself a catalogue entry rather than a comma we chose for
    everybody.
    """
    if isinstance(value, Said):
        return say(tag, value.key, value.values)
    if isinstance(value, dict) and NESTED in value:
        return say(tag, str(value[NESTED]), value.get("values") or {})
    if isinstance(value, (list, tuple)):
        separator = say(tag, Message.LIST_SEPARATOR)
        return separator.join(str(_rendered(tag, one)) for one in value)
    return value


def _template(tag: str, key: str, values: Mapping[str, Any]) -> str | None:
    for entry in (catalogue(tag).get(key), catalogue(ENGLISH).get(key)):
        chosen = _one_or_other(entry, values)
        if chosen is not None:
            return chosen
    return None


def _one_or_other(entry: Any, values: Mapping[str, Any]) -> str | None:
    """Pick the singular or the plural, for the entries that have both.

    Both languages this ships with count the same way, so the choice is one against everything
    else. A language that divides the world differently needs more than this, and needs it
    here rather than in every call site.
    """
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return None
    count = values.get("count")
    wanted = "one" if count == 1 else "other"
    chosen = entry.get(wanted, entry.get("other"))
    return chosen if isinstance(chosen, str) else None


class _WhateverIsMissing(dict[str, Any]):
    """A placeholder nobody supplied is left visible rather than being an error."""

    def __missing__(self, name: str) -> str:
        return "{" + name + "}"
