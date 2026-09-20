# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The print scheduler service.

Everything public is re-exported here so the suite can take the package as one namespace and ask it
for names rather than importing files. That is what lets these modules be split, renamed or moved
later without a single test changing.
"""

from print_scheduler.cli import build_argument_parser, main
from print_scheduler.page import render_schedule_page
from print_scheduler.server import (
    GET_ROUTES,
    SERVICE_NAME,
    SERVICE_VERSION,
    SchedulerRequestHandler,
    build_server,
)

__all__ = [
    "GET_ROUTES",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "SchedulerRequestHandler",
    "build_argument_parser",
    "build_server",
    "main",
    "render_schedule_page",
]
