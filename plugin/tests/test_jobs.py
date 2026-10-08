# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The job record and the filename rules.

Both filename rules come from the printer itself: the gcode parser treats `#` as a comment, and the
name is passed as a quoted parameter. Both are worth catching when a job is created rather than at
the moment it was supposed to run.
"""

from __future__ import annotations

from print_scheduler import (
    Job,
    Message,
    job_from_dict,
    new_job_id,
    reason_filename_cannot_start,
)

BENCHY = "3DBenchy_ASA_HF_48m40s.gcode"


def test_an_ordinary_name_is_startable() -> None:
    assert reason_filename_cannot_start(BENCHY) is None


def test_a_name_with_spaces_is_startable_because_the_parameter_is_quoted() -> None:
    assert reason_filename_cannot_start("06_Baby Dragon Teen_PLA_HF_4h35m.gcode") is None


def test_a_chinese_name_is_startable() -> None:
    # Verified on the printer: `M118 顶盖前靴` echoed back intact.
    assert reason_filename_cannot_start("顶盖前靴_TPU_13m5s.gcode") is None


def test_a_hash_is_refused_because_the_parser_would_truncate_the_name() -> None:
    reason = reason_filename_cannot_start("plate #2.gcode")
    assert reason is not None
    assert reason.key is Message.FILENAME_HAS_HASH
    assert "comment" in reason.in_english()


def test_a_double_quote_is_refused_because_it_would_end_the_parameter() -> None:
    reason = reason_filename_cannot_start('say "hello".gcode')
    assert reason is not None


def test_an_empty_name_is_refused() -> None:
    assert reason_filename_cannot_start("   ") is not None


def test_a_job_survives_a_round_trip_through_its_dictionary() -> None:
    job = Job(job_id=new_job_id(), filename=BENCHY, start_at=1_758_348_000.0, level_bed=True)
    assert job_from_dict(job.to_dict()) == job


def test_two_job_identifiers_differ() -> None:
    assert new_job_id() != new_job_id()
