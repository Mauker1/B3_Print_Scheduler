# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The print scheduler service.

Everything public is re-exported here so the suite can take the package as one namespace and ask it
for names rather than importing files. That is what lets these modules be split, renamed or moved
later without a single test changing.
"""

from print_scheduler.cli import build_argument_parser, keep_ticking, main, tick_once
from print_scheduler.gcode_files import (
    FileSummary,
    ToolUse,
    split_slicer_list,
    summarise,
    tools_used,
)
from print_scheduler.history import find_our_print, verdict_for
from print_scheduler.jobs import (
    Attempt,
    Job,
    JobState,
    Refusal,
    job_from_dict,
    new_job_id,
    reason_filename_cannot_start,
)
from print_scheduler.moonraker import (
    MoonrakerPrinter,
    build_start_script,
    print_records_from_history,
    snapshot_from_status,
)
from print_scheduler.page import render_schedule_page
from print_scheduler.printer import (
    KLIPPER_READY,
    PRINT_STATE_ERROR,
    RUNNING_PRINT_STATES,
    STATES_MEANING_OUR_PRINT_RAN,
    UNCLEARED_BED_STATES,
    Printer,
    PrinterSnapshot,
    PrintRecord,
    StartRefusedError,
)
from print_scheduler.runner import (
    Action,
    Decision,
    Moment,
    cancel_by_hand,
    decide,
    is_due,
    run_tick,
)
from print_scheduler.server import (
    GET_ROUTES,
    POST_ROUTES,
    SERVICE_NAME,
    SERVICE_VERSION,
    SchedulerRequestHandler,
    SchedulerServer,
    build_server,
)
from print_scheduler.service import (
    JobRequest,
    ScheduleRejectedError,
    ScheduleService,
    overlapping_job_ids,
    payload_for,
    projected_finish,
    read_tolerance_seconds,
)
from print_scheduler.store import ScheduleStore

__all__ = [
    "tools_used",
    "tick_once",
    "summarise",
    "split_slicer_list",
    "read_tolerance_seconds",
    "projected_finish",
    "payload_for",
    "overlapping_job_ids",
    "keep_ticking",
    "ToolUse",
    "SchedulerServer",
    "ScheduleService",
    "ScheduleRejectedError",
    "JobRequest",
    "FileSummary",
    "POST_ROUTES",
    "GET_ROUTES",
    "KLIPPER_READY",
    "PRINT_STATE_ERROR",
    "RUNNING_PRINT_STATES",
    "STATES_MEANING_OUR_PRINT_RAN",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "UNCLEARED_BED_STATES",
    "Action",
    "Attempt",
    "Decision",
    "Job",
    "JobState",
    "Moment",
    "MoonrakerPrinter",
    "PrintRecord",
    "Printer",
    "PrinterSnapshot",
    "Refusal",
    "ScheduleStore",
    "SchedulerRequestHandler",
    "StartRefusedError",
    "build_argument_parser",
    "build_server",
    "build_start_script",
    "cancel_by_hand",
    "decide",
    "find_our_print",
    "is_due",
    "job_from_dict",
    "main",
    "new_job_id",
    "print_records_from_history",
    "reason_filename_cannot_start",
    "render_schedule_page",
    "run_tick",
    "snapshot_from_status",
    "verdict_for",
]
