# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The decision table, one test per outcome.

Every test describes a situation as data: what the printer reported, which files it holds, and what
time it is. Nothing here needs a printer, a socket or real time, which is the point of the
`Printer` protocol and of passing `now` in rather than reading a clock.

The two that matter most are the ones nobody would notice going wrong until it was expensive: a job
that came due while the printer was off, and a job that came due while the printer was busy.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import print_scheduler
from print_scheduler import (
    Job,
    JobState,
    PrinterSnapshot,
    Refusal,
    StartRefusedError,
    cancel_by_hand,
    run_tick,
)

SIX_IN_THE_MORNING = 1_758_348_000.0
ONE_MINUTE = 60.0
FIVE_MINUTES = 5 * ONE_MINUTE
TEN_HOURS = 10 * 60 * ONE_MINUTE

BENCHY = "3DBenchy_ASA_HF_48m40s.gcode"
CHINESE_NAME = "顶盖前靴_TPU_13m5s.gcode"

IDLE = PrinterSnapshot(reachable=True, klipper_state="ready", print_state="standby")


@dataclass
class StandInPrinter:
    """A printer described as data.

    An entry is a state to report or, for the start call, an error to raise, so a test can describe
    a printer that is busy, or one that refuses a start, as plainly as one that works.
    """

    reports: PrinterSnapshot = IDLE
    holds: frozenset[str] = frozenset({BENCHY, CHINESE_NAME})
    refuses_start_with: str | None = None
    listing_raises: OSError | None = None
    started: list[tuple[str, bool | None, bool | None]] = field(default_factory=list)

    def snapshot(self) -> PrinterSnapshot:
        return self.reports

    def gcode_filenames(self) -> frozenset[str]:
        if self.listing_raises is not None:
            raise self.listing_raises
        return self.holds

    def start_print(
        self, filename: str, level_bed: bool | None, record_timelapse: bool | None
    ) -> None:
        if self.refuses_start_with is not None:
            raise StartRefusedError(self.refuses_start_with)
        self.started.append((filename, level_bed, record_timelapse))


def a_job(**overrides: object) -> Job:
    defaults: dict[str, object] = {
        "job_id": "job-one",
        "filename": BENCHY,
        "start_at": SIX_IN_THE_MORNING,
        "bed_acknowledged": True,
    }
    defaults.update(overrides)
    return Job(**defaults)  # type: ignore[arg-type]


def settle(
    job: Job,
    printer: StandInPrinter,
    now: float = SIX_IN_THE_MORNING,
    tolerance: float = FIVE_MINUTES,
) -> Job:
    return run_tick([job], printer, now, tolerance)[0]


def test_an_idle_printer_on_time_starts_the_print() -> None:
    printer = StandInPrinter()
    settled = settle(a_job(level_bed=True, record_timelapse=False), printer)
    assert settled.state is JobState.STARTED
    assert printer.started == [(BENCHY, True, False)]


def test_a_job_that_is_not_due_yet_is_left_alone() -> None:
    printer = StandInPrinter()
    settled = settle(a_job(), printer, now=SIX_IN_THE_MORNING - ONE_MINUTE)
    assert settled.state is JobState.SCHEDULED
    assert settled.attempts == ()
    assert printer.started == []


def test_a_chinese_filename_starts_like_any_other() -> None:
    printer = StandInPrinter()
    settled = settle(a_job(filename=CHINESE_NAME), printer)
    assert settled.state is JobState.STARTED
    assert printer.started == [(CHINESE_NAME, None, None)]


def test_a_job_past_the_tolerance_is_missed_rather_than_started_late() -> None:
    printer = StandInPrinter()
    settled = settle(a_job(), printer, now=SIX_IN_THE_MORNING + FIVE_MINUTES + ONE_MINUTE)
    assert settled.state is JobState.CANCELLED
    assert settled.refusal is Refusal.MISSED
    assert printer.started == []


def test_a_job_that_came_due_while_the_printer_was_off_does_not_start_on_the_way_back_up() -> None:
    # The printer is perfectly healthy now. That is exactly the case this refuses.
    printer = StandInPrinter()
    settled = settle(a_job(), printer, now=SIX_IN_THE_MORNING + TEN_HOURS)
    assert settled.refusal is Refusal.MISSED
    assert printer.started == []


def test_lateness_is_checked_before_the_printer_is() -> None:
    # Both rules would fire. Missed wins, because a job whose moment has passed must not start
    # however the printer looks.
    printer = StandInPrinter(reports=replace(IDLE, print_state="printing"))
    settled = settle(a_job(), printer, now=SIX_IN_THE_MORNING + TEN_HOURS)
    assert settled.refusal is Refusal.MISSED


def test_a_printer_part_way_through_a_print_cancels_rather_than_waits() -> None:
    printer = StandInPrinter(
        reports=replace(IDLE, print_state="printing", printing_filename="something_else.gcode")
    )
    settled = settle(a_job(), printer)
    assert settled.refusal is Refusal.PRINTER_BUSY
    assert "something_else.gcode" in settled.detail
    assert printer.started == []


def test_a_paused_print_counts_as_busy() -> None:
    printer = StandInPrinter(reports=replace(IDLE, print_state="paused"))
    assert settle(a_job(), printer).refusal is Refusal.PRINTER_BUSY


def test_an_undismissed_finished_print_means_the_bed_is_presumed_occupied() -> None:
    printer = StandInPrinter(reports=replace(IDLE, print_state="complete"))
    settled = settle(a_job(), printer)
    assert settled.refusal is Refusal.BED_NOT_CLEARED
    assert printer.started == []


def test_an_undismissed_cancelled_print_means_the_same() -> None:
    printer = StandInPrinter(reports=replace(IDLE, print_state="cancelled"))
    assert settle(a_job(), printer).refusal is Refusal.BED_NOT_CLEARED


def test_a_printer_in_error_cancels_with_the_printers_own_message() -> None:
    printer = StandInPrinter(
        reports=replace(
            IDLE, print_state="error", klipper_message="Probe triggered prior to movement"
        )
    )
    settled = settle(a_job(), printer)
    assert settled.refusal is Refusal.PRINTER_IN_ERROR
    assert "Probe triggered" in settled.detail


def test_an_unreachable_printer_is_retried_rather_than_cancelled() -> None:
    printer = StandInPrinter(reports=PrinterSnapshot(reachable=False, klipper_message="timed out"))
    settled = settle(a_job(), printer)
    assert settled.state is JobState.SCHEDULED
    assert settled.refusal is None
    assert len(settled.attempts) == 1
    assert "timed out" in settled.attempts[0].detail


def test_klipper_still_starting_is_retried() -> None:
    printer = StandInPrinter(reports=replace(IDLE, klipper_state="startup"))
    settled = settle(a_job(), printer)
    assert settled.state is JobState.SCHEDULED
    assert len(settled.attempts) == 1


def test_a_shut_down_klipper_cancels_rather_than_waiting_out_the_tolerance() -> None:
    # Waiting would replace the real reason with "missed" five minutes later.
    printer = StandInPrinter(
        reports=replace(
            IDLE, klipper_state="shutdown", klipper_message="MCU protocol error"
        )
    )
    settled = settle(a_job(), printer)
    assert settled.state is JobState.CANCELLED
    assert settled.refusal is Refusal.PRINTER_IN_ERROR
    assert "MCU protocol error" in settled.detail


def test_a_calibration_someone_started_by_hand_is_waited_for_not_cancelled() -> None:
    # Unlike a print, this is a matter of minutes, so it gets the retry budget.
    printer = StandInPrinter(reports=replace(IDLE, other_gcode_running=True))
    settled = settle(a_job(), printer)
    assert settled.state is JobState.SCHEDULED


def test_retrying_accumulates_attempts_and_then_starts_when_the_printer_comes_back() -> None:
    offline = PrinterSnapshot(reachable=False, klipper_message="refused")
    unreachable = StandInPrinter(reports=offline)
    waited_once = settle(a_job(), unreachable, now=SIX_IN_THE_MORNING)
    waited_twice = settle(waited_once, unreachable, now=SIX_IN_THE_MORNING + 20)
    assert len(waited_twice.attempts) == 2

    recovered = StandInPrinter()
    started = settle(waited_twice, recovered, now=SIX_IN_THE_MORNING + 40)
    assert started.state is JobState.STARTED
    assert len(started.attempts) == 3


def test_retrying_stops_at_the_tolerance_and_cancels() -> None:
    printer = StandInPrinter(reports=PrinterSnapshot(reachable=False, klipper_message="refused"))
    waited = settle(a_job(), printer, now=SIX_IN_THE_MORNING + ONE_MINUTE)
    gave_up = settle(waited, printer, now=SIX_IN_THE_MORNING + FIVE_MINUTES + ONE_MINUTE)
    assert gave_up.state is JobState.CANCELLED
    assert gave_up.refusal is Refusal.MISSED
    # The attempts survive the cancellation, so the retry history is readable afterwards.
    assert len(gave_up.attempts) == 2


def test_a_file_that_vanished_between_scheduling_and_firing_cancels() -> None:
    printer = StandInPrinter(holds=frozenset())
    settled = settle(a_job(), printer)
    assert settled.refusal is Refusal.FILE_GONE
    assert BENCHY in settled.detail


def test_a_file_listing_that_fails_is_treated_as_an_unreachable_printer() -> None:
    # Not as a printer whose files have all vanished, which would cancel every pending job at once.
    printer = StandInPrinter(listing_raises=OSError("connection reset"))
    settled = settle(a_job(), printer)
    assert settled.state is JobState.SCHEDULED


def test_a_filename_the_gcode_parser_cannot_carry_cancels() -> None:
    printer = StandInPrinter(holds=frozenset({"plate #2.gcode"}))
    settled = settle(a_job(filename="plate #2.gcode"), printer)
    assert settled.refusal is Refusal.FILENAME_NOT_STARTABLE
    assert printer.started == []


def test_a_printer_that_refuses_the_start_cancels_with_its_own_words() -> None:
    printer = StandInPrinter(
        refuses_start_with='{"coded": "0003-0531-0000-0021", "msg": "auto feeding batch"}'
    )
    settled = settle(a_job(), printer)
    assert settled.state is JobState.CANCELLED
    assert settled.refusal is Refusal.START_REFUSED
    assert "auto feeding batch" in settled.detail


def test_at_most_one_job_starts_in_a_tick() -> None:
    printer = StandInPrinter()
    first = a_job(job_id="first")
    second = a_job(job_id="second")
    settled = run_tick([first, second], printer, SIX_IN_THE_MORNING, FIVE_MINUTES)
    assert [job.state for job in settled] == [JobState.STARTED, JobState.CANCELLED]
    assert settled[1].refusal is Refusal.PRINTER_BUSY
    assert len(printer.started) == 1


def test_a_settled_job_is_not_touched_again() -> None:
    printer = StandInPrinter()
    started = settle(a_job(), printer)
    again = settle(started, printer, now=SIX_IN_THE_MORNING + ONE_MINUTE)
    assert again == started
    assert len(printer.started) == 1


def test_the_tick_returns_the_whole_schedule_including_jobs_it_did_not_touch() -> None:
    printer = StandInPrinter()
    due = a_job(job_id="due")
    later = a_job(job_id="later", start_at=SIX_IN_THE_MORNING + TEN_HOURS)
    settled = run_tick([due, later], printer, SIX_IN_THE_MORNING, FIVE_MINUTES)
    assert [job.job_id for job in settled] == ["due", "later"]
    assert settled[1] == later


def test_cancelling_by_hand_is_not_a_refusal_by_the_printer() -> None:
    cancelled = cancel_by_hand(a_job(), SIX_IN_THE_MORNING)
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.refusal is Refusal.CANCELLED_BY_YOU


def test_every_refusal_reason_is_reachable_from_the_rules_or_by_hand() -> None:
    # A new way to refuse cannot be added without a test and a row in plugin/doc/README.md.
    assert len(print_scheduler.Refusal) == 10
