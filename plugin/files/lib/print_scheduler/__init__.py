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
from print_scheduler.history import (
    find_our_print,
    last_print_ended_at,
    start_routine_seconds,
    verdict_for,
)
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
    loaded_filaments_from_config,
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
    LoadedFilament,
    Printer,
    PrinterSnapshot,
    PrintRecord,
    StartRefusedError,
)
from print_scheduler.runner import (
    Action,
    Decision,
    Moment,
    PrinterAsSeen,
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
from print_scheduler.tool_mapping import (
    ToolAssignment,
    ToolPlan,
    normalise_colour,
    plan_tools,
)

__all__ = [
    "last_print_ended_at",
    "PrinterAsSeen",
    "GET_ROUTES",
    "KLIPPER_READY",
    "POST_ROUTES",
    "PRINT_STATE_ERROR",
    "RUNNING_PRINT_STATES",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "STATES_MEANING_OUR_PRINT_RAN",
    "UNCLEARED_BED_STATES",
    "Action",
    "Attempt",
    "Decision",
    "FileSummary",
    "Job",
    "JobRequest",
    "JobState",
    "LoadedFilament",
    "Moment",
    "MoonrakerPrinter",
    "PrintRecord",
    "Printer",
    "PrinterSnapshot",
    "Refusal",
    "ScheduleRejectedError",
    "ScheduleService",
    "ScheduleStore",
    "SchedulerRequestHandler",
    "SchedulerServer",
    "StartRefusedError",
    "ToolAssignment",
    "ToolPlan",
    "ToolUse",
    "build_argument_parser",
    "build_server",
    "build_start_script",
    "cancel_by_hand",
    "decide",
    "find_our_print",
    "is_due",
    "job_from_dict",
    "keep_ticking",
    "loaded_filaments_from_config",
    "main",
    "new_job_id",
    "normalise_colour",
    "overlapping_job_ids",
    "payload_for",
    "plan_tools",
    "print_records_from_history",
    "projected_finish",
    "read_tolerance_seconds",
    "reason_filename_cannot_start",
    "render_schedule_page",
    "run_tick",
    "snapshot_from_status",
    "start_routine_seconds",
    "split_slicer_list",
    "summarise",
    "tick_once",
    "tools_used",
    "verdict_for",
]
