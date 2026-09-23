# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The catalogues, and the rules that stop them rotting.

Three of these tests are the gate for translation. A catalogue is a file somebody edits without
running anything, often somebody who does not read Python, so the only thing standing between a
typo and a page that says `{fileName}` at six in the morning is this file.

The fourth kind is the one that matters most: rendering never raises, whatever is missing or
malformed. A bad translation must degrade to English, and past English to the key itself, and
never to a traceback in the middle of scheduling a print.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from string import Formatter
from typing import Any

import pytest
from print_scheduler import ENGLISH, Message, Said, catalogue, known_tags, messages, say
from print_scheduler.messages import LOCALE_DIR

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "files" / "lib" / "print_scheduler"


def placeholders_in(template: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(template) if name}


def forms_of(entry: Any) -> dict[str, str]:
    """A catalogue entry as its forms, so a plain string and a plural pair compare alike."""
    return {"": entry} if isinstance(entry, str) else dict(entry)


def catalogues_besides_english() -> list[str]:
    return [tag for tag in known_tags() if tag != ENGLISH]


# How the page names a key: a `t()` call, a nested message inside one's values, one of the
# three attributes that translate the static markup, or a lookup by literal index. The page's
# keys cannot be constants the way the Python side's are, so they are read back out of it.
KEYS_IN_THE_PAGE = (
    re.compile(r'\bt\(\s*"([a-z][\w.-]*\.[\w.-]+)"'),
    re.compile(r'\bjoinedWith\(\s*"([a-z][\w.-]*\.[\w.-]+)"'),
    re.compile(r'\bmessage:\s*"([a-z][\w.-]*\.[\w.-]+)"'),
    re.compile(r'\bdata-i18n(?:-placeholder|-aria-label)?="([a-z][\w.-]*\.[\w.-]+)"'),
    re.compile(r'\["([a-z][\w.-]*\.[\w.-]+)"\]'),
)


def source_of_the_package() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PACKAGE_ROOT.rglob("*.py"))
    )


def keys_the_code_uses() -> set[str]:
    page = (PACKAGE_ROOT / "page.py").read_text(encoding="utf-8")
    from_the_page = {found for pattern in KEYS_IN_THE_PAGE for found in pattern.findall(page)}
    return {message.value for message in Message} | from_the_page


def test_english_holds_exactly_the_keys_the_code_uses() -> None:
    """No key without a sentence, and no sentence nobody says.

    The second half is the one that rots quietly: a message reworded out of the code leaves an
    entry behind, and every translator after that dutifully translates a string that will
    never be shown to anybody.

    The page's keys are read out of its own source, because a page written in JavaScript cannot
    share the enum. That is the weaker half of this check by nature: it can only see the keys
    somebody wrote as literals.
    """
    used = keys_the_code_uses()
    assert sorted(set(catalogue(ENGLISH)) - used) == []
    assert sorted(used - set(catalogue(ENGLISH))) == []


def test_every_key_the_python_declares_is_one_it_says() -> None:
    source = source_of_the_package()
    unused = sorted(
        message.value for message in Message if f"Message.{message.name}" not in source
    )
    assert unused == []


@pytest.mark.parametrize("tag", catalogues_besides_english())
def test_every_catalogue_has_exactly_english_s_keys(tag: str) -> None:
    assert set(catalogue(tag)) == set(catalogue(ENGLISH))


@pytest.mark.parametrize("tag", catalogues_besides_english())
def test_every_translation_has_english_s_placeholders(tag: str) -> None:
    english = catalogue(ENGLISH)
    for key, entry in catalogue(tag).items():
        ours, theirs = forms_of(english[key]), forms_of(entry)
        assert set(ours) == set(theirs), key
        for form, template in theirs.items():
            assert placeholders_in(template) == placeholders_in(ours[form]), (key, form)


@pytest.mark.parametrize("tag", known_tags())
def test_every_catalogue_is_json_of_strings(tag: str) -> None:
    entries = json.loads((LOCALE_DIR / f"{tag}.json").read_text(encoding="utf-8"))
    for key, entry in entries.items():
        assert isinstance(entry, (str, dict)), key
        assert all(isinstance(form, str) for form in forms_of(entry).values()), key


def test_a_language_nobody_ships_falls_back_to_english() -> None:
    assert say("xx", Message.CANCELLED_BY_YOU) == say(ENGLISH, Message.CANCELLED_BY_YOU)


def test_a_tag_that_is_a_path_reads_no_file() -> None:
    """A setting somebody typed is about to become a filename. It never leaves the locale dir."""
    assert say("../../../etc/passwd", Message.CANCELLED_BY_YOU) == say(
        ENGLISH, Message.CANCELLED_BY_YOU
    )
    assert catalogue("../en") == {}


def test_a_key_nobody_wrote_renders_as_itself() -> None:
    assert say(ENGLISH, "detail.nothing-like-this") == "detail.nothing-like-this"


def test_a_placeholder_nobody_supplied_stays_visible() -> None:
    assert say(ENGLISH, Message.FILE_GONE) == "{filename} is no longer on the printer"


def test_one_and_many_are_not_the_same_word() -> None:
    assert say(ENGLISH, Message.DURATION_MINUTES, {"count": 1}) == "1 minute"
    assert say(ENGLISH, Message.DURATION_MINUTES, {"count": 4}) == "4 minutes"


def test_a_message_inside_a_message_is_rendered_in_the_same_language() -> None:
    sentence = say(
        ENGLISH,
        Message.MISSED,
        {
            "lateness": Said(Message.DURATION_MINUTES, {"count": 2}),
            "tolerance": Said(Message.DURATION_SECONDS, {"count": 30}),
        },
    )
    assert sentence == "Its time passed 2 minutes ago, beyond a tolerance of 30 seconds"


def test_a_list_is_joined_with_the_catalogue_s_own_separator() -> None:
    said = Said(
        Message.CANNOT_GIVE_EACH_ITS_OWN,
        {
            "loaded": (
                Said(Message.LOADED_TOOLHEAD, {"index": 0, "material": "PLA"}),
                Said(Message.LOADED_TOOLHEAD, {"index": 1, "material": "ASA"}),
            )
        },
    )
    assert "T0 PLA, T1 ASA" in said.in_english()


def test_the_values_a_reader_gets_are_json() -> None:
    """The browser renders these, so whatever a message carries has to survive the wire."""
    said = Said(
        Message.MISSED,
        {
            "lateness": Said(Message.DURATION_MINUTES, {"count": 2}),
            "tolerance": Said(Message.DURATION_SECONDS, {"count": 30}),
        },
    )
    assert json.loads(json.dumps(said.wire_values())) == {
        "lateness": {"message": "duration.minutes", "values": {"count": 2}},
        "tolerance": {"message": "duration.seconds", "values": {"count": 30}},
    }


@pytest.fixture
def a_catalogue_of_our_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str, str], None]:
    """Write a catalogue somewhere harmless and have the module read from there.

    Never into the package's own locale directory: the builder packs `files/` verbatim, so a
    test that leaves a file behind there is a failed install rather than untidiness.
    """
    monkeypatch.setattr(messages, "LOCALE_DIR", tmp_path)
    monkeypatch.setattr(messages, "_loaded", {})
    (tmp_path / f"{ENGLISH}.json").write_text(
        json.dumps({Message.CANCELLED_BY_YOU.value: "You cancelled it"}), encoding="utf-8"
    )

    def write(tag: str, text: str) -> None:
        (tmp_path / f"{tag}.json").write_text(text, encoding="utf-8")

    return write


def test_a_key_nobody_translated_falls_back_to_english(
    a_catalogue_of_our_own: Callable[[str, str], None],
) -> None:
    """A half finished translation shows English, never a gap and never an error."""
    a_catalogue_of_our_own("zz", json.dumps({"detail.file-gone": "nada aqui"}))
    assert say("zz", Message.CANCELLED_BY_YOU) == "You cancelled it"


def test_a_catalogue_that_is_not_json_falls_back_rather_than_raising(
    a_catalogue_of_our_own: Callable[[str, str], None],
) -> None:
    a_catalogue_of_our_own("zz", "{not json at all")
    assert say("zz", Message.CANCELLED_BY_YOU) == "You cancelled it"


def test_a_catalogue_that_is_not_an_object_falls_back_rather_than_raising(
    a_catalogue_of_our_own: Callable[[str, str], None],
) -> None:
    a_catalogue_of_our_own("zz", '["a list of things"]')
    assert say("zz", Message.CANCELLED_BY_YOU) == "You cancelled it"


def test_a_template_with_a_malformed_placeholder_renders_as_written(
    a_catalogue_of_our_own: Callable[[str, str], None],
) -> None:
    a_catalogue_of_our_own("zy", json.dumps({Message.CANCELLED_BY_YOU.value: "{"}))
    assert say("zy", Message.CANCELLED_BY_YOU) == "{"
