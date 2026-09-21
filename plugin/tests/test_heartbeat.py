# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How long the scheduler was away, and what it does about it.

The interesting cases are the ones that must NOT read as a silence: a first install, an upgrade
from a version that never wrote a mark, and a printer whose clock has gone backwards. Each of
those would otherwise hold a schedule nobody needed held.
"""

from __future__ import annotations

from pathlib import Path

from print_scheduler import A_LONG_SILENCE_SECONDS, Heartbeat

A_MONDAY = 1_790_000_000.0


def test_a_mark_that_was_never_written_is_not_a_silence(tmp_path: Path) -> None:
    # A first install has nothing behind it, and an upgrade from a version with no heartbeat
    # looks exactly the same. Holding a schedule in either case would be inventing a reason.
    beat = Heartbeat(tmp_path / "last-seen")
    assert beat.last_seen() is None
    assert beat.silence_before(A_MONDAY) == 0.0


def test_an_unreadable_mark_is_not_a_silence_either(tmp_path: Path) -> None:
    path = tmp_path / "last-seen"
    path.write_text("half a timestamp", encoding="utf-8")
    assert Heartbeat(path).silence_before(A_MONDAY) == 0.0


def test_a_mark_comes_back_as_the_gap_since_it(tmp_path: Path) -> None:
    beat = Heartbeat(tmp_path / "last-seen")
    beat.mark(A_MONDAY)
    assert beat.silence_before(A_MONDAY + 3600) == 3600


def test_a_clock_that_went_backwards_is_not_a_silence(tmp_path: Path) -> None:
    # A printer that has just come up without a network, not evidence of anything.
    beat = Heartbeat(tmp_path / "last-seen")
    beat.mark(A_MONDAY)
    assert Heartbeat(tmp_path / "last-seen").silence_before(A_MONDAY - 9999) == 0.0


def test_the_mark_is_not_rewritten_on_every_tick(tmp_path: Path) -> None:
    """Every twenty seconds forever is four thousand writes a day to a printer's flash, for a
    number that is read against a threshold of a day."""
    path = tmp_path / "last-seen"
    beat = Heartbeat(path)
    beat.mark(A_MONDAY)
    beat.mark(A_MONDAY + 20)
    beat.mark(A_MONDAY + 40)
    assert Heartbeat(path).last_seen() == A_MONDAY

    beat.mark(A_MONDAY + A_LONG_SILENCE_SECONDS)
    assert Heartbeat(path).last_seen() == A_MONDAY + A_LONG_SILENCE_SECONDS


def test_a_mark_that_cannot_be_written_is_survivable(tmp_path: Path) -> None:
    # A directory where the file should be. Nothing about a schedule should fail because of it.
    path = tmp_path / "last-seen"
    path.mkdir()
    beat = Heartbeat(path)
    beat.mark(A_MONDAY)
    assert beat.silence_before(A_MONDAY + 10) == 0.0


def test_the_writing_file_does_not_survive_a_mark(tmp_path: Path) -> None:
    beat = Heartbeat(tmp_path / "last-seen")
    beat.mark(A_MONDAY)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["last-seen"]
