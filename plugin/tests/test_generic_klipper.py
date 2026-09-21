# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The plugin on a printer that is not the one it was written against.

Every U1 specific thing the scheduler does is meant to be asked for rather than assumed: the
parameterised start command, what is loaded in each toolhead, and which filenames the gcode
parser can take. This module is the whole of that claim, exercised against a printer that
answers no to all three.

It has never been run on such a machine. That is stated in `plugin/doc/README.md` and it stays
stated until it has. What these tests buy is that the generic path is exercised on every gate
run rather than being reasoned about once and left.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from print_scheduler import (
    JobRequest,
    JobState,
    ScheduleRejectedError,
    ScheduleService,
    ScheduleStore,
    reason_filename_cannot_start,
    run_tick,
)
from printer_stand_in import BENCHY, MAINLINE_METADATA, a_generic_klipper

SIX_IN_THE_MORNING = 1_758_348_000.0
LAST_NIGHT = SIX_IN_THE_MORNING - 8 * 3600
AWKWARD_NAME = "bracket #2 rev\"b\".gcode"


def a_service(tmp_path: Path, printer: object) -> ScheduleService:
    return ScheduleService(
        ScheduleStore(tmp_path / "jobs.json"),
        printer,  # type: ignore[arg-type]
        tmp_path / "user_vars.json",
    )


def a_request(**overrides: object) -> JobRequest:
    base = JobRequest(filename=BENCHY, start_at=SIX_IN_THE_MORNING, bed_acknowledged=True)
    return JobRequest(**{**base.__dict__, **overrides})


def test_a_name_the_gcode_parser_would_mangle_is_fine_when_no_gcode_is_used() -> None:
    # Both refusals exist because of the gcode command. Moonraker's own print start takes the
    # name as a URL parameter, so refusing these on such a printer refuses files it can print.
    assert reason_filename_cannot_start(AWKWARD_NAME, starts_by_gcode=False) is None
    assert reason_filename_cannot_start(AWKWARD_NAME, starts_by_gcode=True) is not None


def test_an_empty_name_is_refused_on_any_printer() -> None:
    assert reason_filename_cannot_start("   ", starts_by_gcode=False) is not None


def test_such_a_file_can_actually_be_scheduled(tmp_path: Path) -> None:
    printer = a_generic_klipper(holds=frozenset({AWKWARD_NAME}))
    job = a_service(tmp_path, printer).add(a_request(filename=AWKWARD_NAME), LAST_NIGHT)
    assert job.state is JobState.SCHEDULED


def test_and_on_the_u1_the_same_file_is_still_refused_at_schedule_time(tmp_path: Path) -> None:
    printer = a_generic_klipper(holds=frozenset({AWKWARD_NAME}), offers_preferences=True)
    with pytest.raises(ScheduleRejectedError, match="#"):
        a_service(tmp_path, printer).add(a_request(filename=AWKWARD_NAME), LAST_NIGHT)


def test_it_starts_with_no_map_table_and_no_preferences(tmp_path: Path) -> None:
    printer = a_generic_klipper(holds=frozenset({AWKWARD_NAME}))
    service = a_service(tmp_path, printer)
    job = service.add(a_request(filename=AWKWARD_NAME), LAST_NIGHT)
    settled = run_tick([job], printer, SIX_IN_THE_MORNING, 300.0)
    assert settled[0].state is JobState.STARTING
    assert printer.started == [(AWKWARD_NAME, None, None, ())]


def test_a_file_that_says_almost_nothing_about_itself_still_schedules(tmp_path: Path) -> None:
    # No filament lists, no colours, no bed temperature. On the U1 a file with no material
    # would be refused, because there a map has to be chosen and cannot be. Here there is no
    # map to choose, so there is nothing to refuse over.
    service = a_service(tmp_path, a_generic_klipper())
    job = service.add(a_request(), LAST_NIGHT)
    assert job.state is JobState.SCHEDULED
    assert service.file_summary(BENCHY).tools == ()
    assert not service.tool_plan(service.file_summary(BENCHY)).applicable


def test_a_real_mainline_file_shows_its_material_without_a_map(tmp_path: Path) -> None:
    # The file that actually came off the second printer. Its slot is described, so the page
    # has something to show, and there is nothing loaded to map it onto, so nothing is
    # refused for the lack of a map. Both halves matter: showing blanks would be a bug, and
    # refusing the job would be a worse one.
    printer = a_generic_klipper(describes=dict(MAINLINE_METADATA))
    service = a_service(tmp_path, printer)
    summary = service.file_summary(BENCHY)
    assert len(summary.tools) == 1
    assert summary.tools[0].filament_type == "PLA"
    assert summary.tools[0].colour == "#FF8040"
    plan = service.tool_plan(summary)
    assert plan.problem is None
    assert not plan.applicable
    assert service.add(a_request(), LAST_NIGHT).state is JobState.SCHEDULED
