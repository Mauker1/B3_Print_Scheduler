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

from dataclasses import replace

import print_scheduler
from print_scheduler import (
    Job,
    JobState,
    LoadedFilament,
    PrinterSnapshot,
    PrintRecord,
    Refusal,
    cancel_by_hand,
    run_tick,
)
from printer_stand_in import (
    BENCHY,
    CHINESE_NAME,
    IDLE,
    PRINTING_OURS,
    TOO_MUCH_ASA_METADATA,
    TWO_COLOUR_METADATA,
    WHITE_PLA_METADATA,
    StandInPrinter,
)

SIX_IN_THE_MORNING = 1_758_348_000.0
ONE_MINUTE = 60.0
FIVE_MINUTES = 5 * ONE_MINUTE
TEN_HOURS = 10 * 60 * ONE_MINUTE


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
    # STARTING, not STARTED. The printer said yes; whether it meant it is the next tick.
    assert settled.state is JobState.STARTING
    # Slot 0 wants ASA and only T0 has ASA, so that is where it is sent. Explicitly: the
    # printer defaults slot 0 to T0, and relying on that default printed into the wrong one.
    assert printer.started == [(BENCHY, True, False, ((0, 0),))]


def test_a_job_that_is_not_due_yet_is_left_alone() -> None:
    printer = StandInPrinter()
    settled = settle(a_job(), printer, now=SIX_IN_THE_MORNING - ONE_MINUTE)
    assert settled.state is JobState.SCHEDULED
    assert settled.attempts == ()
    assert printer.started == []


def test_a_chinese_filename_starts_like_any_other() -> None:
    printer = StandInPrinter()
    settled = settle(a_job(filename=CHINESE_NAME), printer)
    assert settled.state is JobState.STARTING
    assert printer.started == [(CHINESE_NAME, None, None, ((0, 0),))]


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


def test_a_paused_print_counts_as_busy_and_says_so_in_english() -> None:
    printer = StandInPrinter(
        reports=replace(IDLE, print_state="paused", printing_filename="half_done.gcode")
    )
    settled = settle(a_job(), printer)
    assert settled.refusal is Refusal.PRINTER_BUSY
    # One phrasing covering both states gives "the printer was busy paused half_done.gcode".
    assert "paused on half_done.gcode" in settled.detail


def test_the_busy_reason_says_what_happened_and_stops() -> None:
    """A reason is read by somebody at six in the morning asking why their print did not run.

    It owes them what happened. Why a busy printer is never waited for is a policy, it does not
    change with the job, and it is already in the README. The length is the test because that is
    the failure: the first version of this said what happened and then argued with the reader
    for two more lines.
    """
    printer = StandInPrinter(
        reports=replace(IDLE, print_state="printing", printing_filename="something_else.gcode")
    )
    detail = settle(a_job(), printer).detail
    assert len(detail) < 60, detail
    assert detail.count(".") == 1  # the one in the filename, and no sentence after it


def test_an_undismissed_finished_print_means_the_bed_is_presumed_occupied() -> None:
    printer = StandInPrinter(reports=replace(IDLE, print_state="complete"))
    settled = settle(a_job(), printer)
    assert settled.refusal is Refusal.BED_NOT_CLEARED
    assert printer.started == []


def test_an_undismissed_cancelled_print_means_the_same() -> None:
    printer = StandInPrinter(reports=replace(IDLE, print_state="cancelled"))
    assert settle(a_job(), printer).refusal is Refusal.BED_NOT_CLEARED


LAST_NIGHT = SIX_IN_THE_MORNING - 8 * 60 * ONE_MINUTE


def a_print_that_ended(status: str, ended_at: float) -> PrintRecord:
    return PrintRecord(
        job_id="0000BC",
        filename="something_else.gcode",
        start_time=ended_at - 100,
        status=status,
        end_time=ended_at,
    )


def test_a_cancelled_print_from_before_you_promised_does_not_block() -> None:
    # `cancelled` never clears itself. It sat for forty five minutes with nothing on screen to
    # dismiss, and would have sat for days. Read as news it stops the scheduler forever.
    printer = StandInPrinter(
        reports=replace(IDLE, print_state="cancelled"),
        remembers=(a_print_that_ended("cancelled", LAST_NIGHT),),
    )
    settled = settle(a_job(created_at=LAST_NIGHT + ONE_MINUTE), printer)
    assert settled.state is JobState.STARTING


def test_a_print_cancelled_after_you_promised_does_block() -> None:
    printer = StandInPrinter(
        reports=replace(IDLE, print_state="cancelled"),
        remembers=(a_print_that_ended("cancelled", SIX_IN_THE_MORNING - 10 * ONE_MINUTE),),
    )
    settled = settle(a_job(created_at=LAST_NIGHT), printer)
    assert settled.refusal is Refusal.BED_NOT_CLEARED
    assert "after you scheduled" in settled.detail


def test_a_finished_print_from_before_you_promised_does_not_block_either() -> None:
    printer = StandInPrinter(
        reports=replace(IDLE, print_state="complete"),
        remembers=(a_print_that_ended("completed", LAST_NIGHT),),
    )
    settled = settle(a_job(created_at=LAST_NIGHT + ONE_MINUTE), printer)
    assert settled.state is JobState.STARTING


def test_an_uncleared_bed_with_no_record_of_when_refuses() -> None:
    # The safe direction, and the message says how to get out of it.
    printer = StandInPrinter(reports=replace(IDLE, print_state="cancelled"))
    settled = settle(a_job(created_at=LAST_NIGHT), printer)
    assert settled.refusal is Refusal.BED_NOT_CLEARED
    assert "no usable record" in settled.detail


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
    assert started.state is JobState.STARTING
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
    assert [job.state for job in settled] == [JobState.STARTING, JobState.CANCELLED]
    assert settled[1].refusal is Refusal.PRINTER_BUSY
    assert len(printer.started) == 1


def test_the_start_names_the_toolhead_that_holds_the_right_material() -> None:
    # The regression. Slot 0 of this file wants white PLA, which is on T2. Left to the printer's
    # default it would go to T0, where the ASA is, and that is what happened on hardware.
    printer = StandInPrinter(describes=dict(WHITE_PLA_METADATA))
    settled = settle(a_job(), printer)
    assert settled.state is JobState.STARTING
    assert printer.started == [(BENCHY, None, None, ((0, 2),))]
    assert "T2" in settled.attempts[-1].detail


def test_a_material_no_toolhead_holds_cancels_rather_than_printing_into_the_wrong_one() -> None:
    only_asa = (LoadedFilament(index=0, filament_type="ASA", colour="000000FF", present=True),)
    printer = StandInPrinter(describes=dict(WHITE_PLA_METADATA), loads=only_asa)
    settled = settle(a_job(), printer)
    assert settled.state is JobState.CANCELLED
    assert settled.refusal is Refusal.NO_TOOLHEAD_FOR_THE_MATERIAL
    assert printer.started == []


def test_a_printer_that_tracks_no_filament_starts_without_a_map() -> None:
    printer = StandInPrinter(loads=())
    settled = settle(a_job(), printer)
    assert settled.state is JobState.STARTING
    assert printer.started == [(BENCHY, None, None, ())]


def test_a_settled_job_is_not_touched_again() -> None:
    printer = StandInPrinter()
    confirmed = replace(a_job(), state=JobState.STARTED, printer_job_id="0000B9")
    again = settle(confirmed, printer, now=SIX_IN_THE_MORNING + ONE_MINUTE)
    assert again == confirmed
    assert printer.started == []


def test_the_tick_returns_the_whole_schedule_including_jobs_it_did_not_touch() -> None:
    printer = StandInPrinter()
    due = a_job(job_id="due")
    later = a_job(job_id="later", start_at=SIX_IN_THE_MORNING + TEN_HOURS)
    settled = run_tick([due, later], printer, SIX_IN_THE_MORNING, FIVE_MINUTES)
    assert [job.job_id for job in settled] == ["due", "later"]
    assert settled[1] == later


def a_starting_job(**overrides: object) -> Job:
    """A job the printer has accepted but not yet been seen to act on."""
    return replace(a_job(**overrides), state=JobState.STARTING, decided_at=SIX_IN_THE_MORNING)


def a_history_record(**overrides: object) -> PrintRecord:
    defaults: dict[str, object] = {
        "job_id": "0000B9",
        "filename": BENCHY,
        "start_time": SIX_IN_THE_MORNING + 2,
        "status": "in_progress",
    }
    defaults.update(overrides)
    return PrintRecord(**defaults)  # type: ignore[arg-type]


def test_a_start_is_confirmed_by_the_printers_own_history() -> None:
    printer = StandInPrinter(reports=PRINTING_OURS, remembers=(a_history_record(),))
    settled = settle(a_starting_job(), printer, now=SIX_IN_THE_MORNING + 20)
    assert settled.state is JobState.STARTED
    assert settled.printer_job_id == "0000B9"


def test_a_start_is_confirmed_by_the_live_state_when_the_history_has_not_caught_up() -> None:
    printer = StandInPrinter(reports=PRINTING_OURS)
    settled = settle(a_starting_job(), printer, now=SIX_IN_THE_MORNING + 20)
    assert settled.state is JobState.STARTED
    # No id to keep, so the page will say the printer has no record rather than invent one.
    assert settled.printer_job_id == ""


def test_a_print_short_enough_to_finish_before_the_next_tick_still_counts_as_started() -> None:
    # There is a 26 second file on the printer this was written against.
    finished = replace(IDLE, print_state="complete", printing_filename=BENCHY)
    printer = StandInPrinter(reports=finished)
    settled = settle(a_starting_job(), printer, now=SIX_IN_THE_MORNING + 20)
    assert settled.state is JobState.STARTED


def test_an_unavailable_history_falls_back_to_the_live_state() -> None:
    printer = StandInPrinter(reports=PRINTING_OURS, history_raises=OSError("no history component"))
    assert settle(a_starting_job(), printer, now=SIX_IN_THE_MORNING + 20).state is JobState.STARTED


def test_a_start_with_no_sign_of_it_yet_is_given_the_confirmation_window() -> None:
    printer = StandInPrinter(reports=IDLE)
    settled = settle(a_starting_job(), printer, now=SIX_IN_THE_MORNING + 20)
    assert settled.state is JobState.STARTING
    assert len(settled.attempts) == 1


def test_a_start_the_printer_accepted_and_then_never_ran_is_caught() -> None:
    # The hole this state exists for: an ok that meant nothing, found in the morning otherwise.
    printer = StandInPrinter(reports=IDLE)
    settled = settle(a_starting_job(), printer, now=SIX_IN_THE_MORNING + 90)
    assert settled.state is JobState.CANCELLED
    assert settled.refusal is Refusal.START_DID_NOT_TAKE


def test_a_print_of_a_different_file_does_not_confirm_our_start() -> None:
    elsewhere = replace(IDLE, print_state="printing", printing_filename="somebody_elses.gcode")
    somebody_elses = a_history_record(filename="other.gcode")
    printer = StandInPrinter(reports=elsewhere, remembers=(somebody_elses,))
    assert settle(a_starting_job(), printer, now=SIX_IN_THE_MORNING + 90).refusal is (
        Refusal.START_DID_NOT_TAKE
    )


def test_a_job_due_while_another_is_being_confirmed_cancels_as_busy() -> None:
    printer = StandInPrinter(reports=PRINTING_OURS, remembers=(a_history_record(),))
    settled = run_tick(
        [a_starting_job(job_id="first"), a_job(job_id="second")],
        printer,
        SIX_IN_THE_MORNING + 20,
        FIVE_MINUTES,
    )
    assert settled[0].state is JobState.STARTED
    assert settled[1].refusal is Refusal.PRINTER_BUSY


def test_cancelling_by_hand_is_not_a_refusal_by_the_printer() -> None:
    cancelled = cancel_by_hand(a_job(), SIX_IN_THE_MORNING)
    assert cancelled.state is JobState.CANCELLED
    assert cancelled.refusal is Refusal.CANCELLED_BY_YOU


def test_every_refusal_reason_is_reachable_from_the_rules_or_by_hand() -> None:
    # A new way to refuse cannot be added without a test and a row in plugin/doc/README.md.
    assert len(print_scheduler.Refusal) == 12


def test_a_two_colour_print_sends_both_pairs_and_neither_is_the_identity() -> None:
    # Slot 0 wants the white PLA, which is on T2. Slot 1 wants the purple, which is on T3.
    # A printer sent no map defaults to slot 0 on T0 and slot 1 on T1, which here is two
    # wrong toolheads rather than one.
    printer = StandInPrinter(describes=dict(TWO_COLOUR_METADATA))
    settled = settle(a_job(), printer)
    assert settled.state is JobState.STARTING
    assert printer.started == [(BENCHY, None, None, ((0, 2), (1, 3)))]


def test_a_multi_tool_job_whose_material_left_the_machine_overnight_is_cancelled() -> None:
    # Scheduled when three ASA slots had somewhere to go, fired when they do not. The check
    # that counts is this one, at the moment of starting, not the one at scheduling.
    printer = StandInPrinter(describes=dict(TOO_MUCH_ASA_METADATA))
    settled = settle(a_job(), printer)
    assert settled.state is JobState.CANCELLED
    assert settled.refusal is Refusal.NO_TOOLHEAD_FOR_THE_MATERIAL
    assert printer.started == []


def test_a_job_seconds_late_says_seconds_rather_than_zero_minutes() -> None:
    """The reason a tolerance of zero was unusable, and it was the wording, not the behaviour.

    Flooring to whole minutes turned a job cancelled seven seconds late into "its time passed
    0 minutes ago, beyond a tolerance of 0 minutes", which reads as a bug in the plugin rather
    than as the setting somebody typed.
    """
    settled = settle(a_job(), StandInPrinter(), now=SIX_IN_THE_MORNING + 7, tolerance=0.0)
    assert settled.refusal is Refusal.MISSED
    assert settled.detail == "Its time passed 7 seconds ago, beyond a tolerance of 0 seconds"


def test_a_tolerance_of_zero_still_starts_a_job_that_is_not_late() -> None:
    # Zero means no lateness is tolerated, not that nothing may ever run.
    settled = settle(a_job(), StandInPrinter(), now=SIX_IN_THE_MORNING, tolerance=0.0)
    assert settled.state is JobState.STARTING


def test_minutes_are_still_minutes_once_there_is_a_minute_to_report() -> None:
    settled = settle(
        a_job(), StandInPrinter(), now=SIX_IN_THE_MORNING + 400, tolerance=FIVE_MINUTES
    )
    assert settled.detail == "Its time passed 6 minutes ago, beyond a tolerance of 5 minutes"


def test_one_of_a_unit_is_singular() -> None:
    settled = settle(a_job(), StandInPrinter(), now=SIX_IN_THE_MORNING + 1, tolerance=0.0)
    assert "1 second ago" in settled.detail
    settled = settle(a_job(), StandInPrinter(), now=SIX_IN_THE_MORNING + 121, tolerance=60.0)
    assert "2 minutes ago, beyond a tolerance of 1 minute" in settled.detail
