# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routing for the plugin's own web interface.

nginx strips the plugin's prefix before proxying and sends no header saying what it was, so routes
are matched against the path alone. Exactly, and with the query string discarded first, never as a
prefix: Fluidd and Mainsail append a cache-busting parameter to their requests, so a match against
the raw request target 404s in a way that looks like something else entirely.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from print_scheduler.page import render_schedule_page

SERVICE_NAME = "print-scheduler"
SERVICE_VERSION = "0.1.0"


class SchedulerRequestHandler(BaseHTTPRequestHandler):
    """Dispatches a request to the route registered for its exact path."""

    server_version = f"{SERVICE_NAME}/{SERVICE_VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802  the name belongs to BaseHTTPRequestHandler
        requested_path = urlsplit(self.path).path
        route = GET_ROUTES.get(requested_path)
        if route is None:
            not_found = {"error": "no such path", "path": requested_path}
            self.respond_json(HTTPStatus.NOT_FOUND, not_found)
            return
        route(self)

    def respond(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        """Send one complete response. Nothing this service serves is cacheable."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def respond_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        """Send a JSON response."""
        self.respond(status, json.dumps(payload).encode("utf-8"), "application/json")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # The daemon writes this service's stdout to $BESPOK3D/var/log/print-scheduler.log, which is
        # the first place to look when it does not start.
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)


def serve_schedule_page(handler: SchedulerRequestHandler) -> None:
    """Serve the scheduler page."""
    body = render_schedule_page(SERVICE_VERSION).encode("utf-8")
    handler.respond(HTTPStatus.OK, body, "text/html; charset=utf-8")


def serve_health(handler: SchedulerRequestHandler) -> None:
    """Report this service's own liveness, and nothing that needs Moonraker to answer."""
    handler.respond_json(
        HTTPStatus.OK,
        {"service": SERVICE_NAME, "version": SERVICE_VERSION, "status": "ok"},
    )


def serve_jobs(handler: SchedulerRequestHandler) -> None:
    """List scheduled jobs.

    Empty because scheduling is not built yet, not because nothing is scheduled. The endpoint exists
    from the first commit so the page, the nginx location and the authentication subrequest are all
    exercised before there is anything at stake.
    """
    handler.respond_json(HTTPStatus.OK, {"jobs": []})


GET_ROUTES: dict[str, Callable[[SchedulerRequestHandler], None]] = {
    "/": serve_schedule_page,
    "/health": serve_health,
    "/jobs": serve_jobs,
}


def build_server(bind_address: str, port: int) -> ThreadingHTTPServer:
    """Build the HTTP server without starting it, so a test can bind port 0 and ask what it got."""
    return ThreadingHTTPServer((bind_address, port), SchedulerRequestHandler)
