# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The schedule on disk.

The interesting cases are all failures: no file yet, a file written by a half completed save, a
file nobody can parse. A printer loses power mid-write, so none of these are hypothetical.
"""

from __future__ import annotations

import json
from pathlib import Path

from print_scheduler import Attempt, Job, JobState, Refusal, ScheduleStore

CHINESE_NAME = "顶盖前靴_TPU_13m5s.gcode"


def a_job() -> Job:
    return Job(
        job_id="job-one",
        filename=CHINESE_NAME,
        start_at=1_758_348_000.0,
        typed_time="2026-09-21 06:00",
        timezone_name="Europe/Berlin",
        bed_acknowledged=True,
        level_bed=True,
        record_timelapse=False,
    )


def test_a_schedule_survives_a_round_trip(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "jobs.json")
    store.save([a_job()])
    assert store.load() == [a_job()]


def test_a_settled_job_keeps_its_reason_and_its_attempts(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "jobs.json")
    cancelled = Job(
        job_id="job-two",
        filename="Cube.gcode",
        start_at=1.0,
        state=JobState.CANCELLED,
        refusal=Refusal.BED_NOT_CLEARED,
        detail="the previous print was not dismissed",
        decided_at=2.0,
        attempts=(Attempt(1.5, "klipper reports startup"),),
    )
    store.save([cancelled])
    assert store.load() == [cancelled]


def test_a_missing_file_is_an_empty_schedule_rather_than_an_error(tmp_path: Path) -> None:
    assert ScheduleStore(tmp_path / "never-written.json").load() == []


def test_a_chinese_filename_is_stored_readably(tmp_path: Path) -> None:
    # ensure_ascii would turn it into escapes, which makes the file useless for diagnosis.
    path = tmp_path / "jobs.json"
    ScheduleStore(path).save([a_job()])
    assert CHINESE_NAME in path.read_text(encoding="utf-8")


def test_the_save_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "jobs.json")
    store.save([a_job()])
    assert [entry.name for entry in tmp_path.iterdir()] == ["jobs.json"]


def test_an_unreadable_schedule_is_set_aside_rather_than_silently_emptied(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert ScheduleStore(path).load() == []
    assert (tmp_path / "jobs.json.unreadable").exists()
    assert not path.exists()


def test_a_schedule_of_the_wrong_shape_is_set_aside_too(tmp_path: Path) -> None:
    path = tmp_path / "jobs.json"
    wrong_shape = {"version": 1, "jobs": [{"filename": "no job_id"}]}
    path.write_text(json.dumps(wrong_shape), encoding="utf-8")
    assert ScheduleStore(path).load() == []
    assert (tmp_path / "jobs.json.unreadable").exists()


def test_the_schedule_directory_is_created_on_first_save(tmp_path: Path) -> None:
    store = ScheduleStore(tmp_path / "var" / "print-scheduler" / "jobs.json")
    store.save([a_job()])
    assert store.load() == [a_job()]
