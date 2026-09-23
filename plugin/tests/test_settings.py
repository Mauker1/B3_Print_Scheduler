# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings, and what happens to a value the plugin cannot use.

The platform has no way to bound a number field, so `-1` reaches us and something has to
happen. Falling back to the default is right; doing it in silence is not, because the person
then has a printer behaving differently from the number they are looking at.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from print_scheduler import ENGLISH, Settings, say


def written(tmp_path: Path, **values: object) -> Settings:
    path = tmp_path / "user_vars.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return Settings(path)


def test_absent_is_not_invalid(tmp_path: Path) -> None:
    """A setting nobody touched, and a file the daemon has not written, say nothing.

    Complaining about those would mean a fresh install greeting its owner with two warnings
    about settings they never set, which is how people learn to ignore warnings.
    """
    nothing_there = Settings(tmp_path / "never-written.json")
    assert nothing_there.tolerance_seconds() == 5 * 60
    assert nothing_there.settled_kept() == 25
    assert nothing_there.ignored() == ()

    empty = written(tmp_path)
    assert empty.tolerance_seconds() == 5 * 60
    assert empty.ignored() == ()


def test_a_negative_is_ignored_out_loud(tmp_path: Path) -> None:
    settings = written(tmp_path, START_TOLERANCE_MINUTES=-1)
    assert settings.tolerance_seconds() == 5 * 60
    complaint = settings.ignored()[0]
    assert complaint.setting == "START_TOLERANCE_MINUTES"
    assert complaint.found == "-1"
    assert "-1" in complaint.sentence()
    assert "5 minutes" in complaint.sentence()


def test_nonsense_is_ignored_out_loud_too(tmp_path: Path) -> None:
    settings = written(tmp_path, SETTLED_JOBS_KEPT="many")
    assert settings.settled_kept() == 25
    assert [one.setting for one in settings.ignored()] == ["SETTLED_JOBS_KEPT"]


def test_both_settings_can_be_wrong_at_once(tmp_path: Path) -> None:
    # One bad setting must not hide another, which a single flag would have done.
    settings = written(tmp_path, START_TOLERANCE_MINUTES=-1, SETTLED_JOBS_KEPT=-2)
    settings.tolerance_seconds()
    settings.settled_kept()
    assert [one.setting for one in settings.ignored()] == [
        "SETTLED_JOBS_KEPT",
        "START_TOLERANCE_MINUTES",
    ]


def test_zero_is_a_real_answer_for_both(tmp_path: Path) -> None:
    settings = written(tmp_path, START_TOLERANCE_MINUTES=0, SETTLED_JOBS_KEPT=0)
    assert settings.tolerance_seconds() == 0.0
    assert settings.settled_kept() == 0
    assert settings.ignored() == ()


def test_the_log_says_it_once_and_the_page_keeps_saying_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The two channels are deliberately different, and this is the test that pins it.

    The log is a record: these settings are read on every tick and on every page poll, so a
    line per read would be thousands a day and a log nobody reads. The page is the live truth,
    because the person looking at it wants to know what is true now.
    """
    settings = written(tmp_path, START_TOLERANCE_MINUTES=-1)
    with caplog.at_level(logging.WARNING, logger="bespok3d.print_scheduler"):
        for _ in range(5):
            settings.tolerance_seconds()

    warnings = [one for one in caplog.records if one.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "START_TOLERANCE_MINUTES" in warnings[0].getMessage()
    assert len(settings.ignored()) == 1


def test_fixing_the_value_clears_the_page_warning(tmp_path: Path) -> None:
    path = tmp_path / "user_vars.json"
    path.write_text(json.dumps({"START_TOLERANCE_MINUTES": -1}), encoding="utf-8")
    settings = Settings(path)
    settings.tolerance_seconds()
    assert settings.ignored() != ()

    # Read afresh is the whole point: changing it in the app takes effect with no restart, and
    # so does the warning going away.
    path.write_text(json.dumps({"START_TOLERANCE_MINUTES": 3}), encoding="utf-8")
    assert settings.tolerance_seconds() == 3 * 60
    assert settings.ignored() == ()


def test_no_language_at_all_is_english(tmp_path: Path) -> None:
    """Absent is not invalid: a setting nobody has touched says nothing anywhere."""
    settings = written(tmp_path)
    assert settings.language() == ENGLISH
    assert settings.ignored() == ()


def test_a_language_we_ship_is_used(tmp_path: Path) -> None:
    assert written(tmp_path, LANGUAGE="pt-BR").language() == "pt-BR"


def test_a_language_nobody_ships_is_english_and_says_so(tmp_path: Path) -> None:
    """The same shape of mistake as a negative tolerance, and the same answer."""
    settings = written(tmp_path, LANGUAGE="kl")
    assert settings.language() == ENGLISH
    assert [one.setting for one in settings.ignored()] == ["LANGUAGE"]


def test_a_language_that_is_a_path_is_refused(tmp_path: Path) -> None:
    settings = written(tmp_path, LANGUAGE="../../../etc/passwd")
    assert settings.language() == ENGLISH
    assert settings.ignored() != ()


def test_the_fallback_names_itself_in_the_reader_s_language(tmp_path: Path) -> None:
    """"Using 5 minutes" in the middle of a Portuguese sentence is a half translation."""
    settings = written(tmp_path, START_TOLERANCE_MINUTES=-1)
    settings.tolerance_seconds()
    said = settings.ignored()[0].said()
    assert "5 minutes" in say(ENGLISH, said.key, said.values)
    assert "5 minutos" in say("pt-BR", said.key, said.values)
