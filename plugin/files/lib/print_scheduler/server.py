# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routing for the plugin's own web interface.

nginx strips the plugin's prefix before proxying and sends no header saying what it was, so routes
are matched against the path alone. Exactly, and with the query string discarded first, never as a
prefix: Fluidd and Mainsail append a cache-busting parameter to their requests, so a match against
the raw request target 404s in a way that looks like something else entirely.

Every endpoint that changes the schedule takes `application/json` and refuses anything else. That
is not fussiness. A cross-origin HTML form can post form-encoded or plain text without the browser
asking permission first, but it cannot post JSON, so requiring it means a page on another site
cannot quietly schedule a print on your machine.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from print_scheduler.page import render_schedule_page
from print_scheduler.service import (
    JobRequest,
    ScheduleRejectedError,
    ScheduleService,
    payload_for,
)

SERVICE_NAME = "print-scheduler"
SERVICE_VERSION = "0.1.0"

JSON_CONTENT_TYPE = "application/json"
# A schedule entry is a filename and a few flags. Anything larger is not one.
MAXIMUM_BODY_BYTES = 64 * 1024


class BadRequestError(Exception):
    """The request itself is wrong, as opposed to the schedule refusing what it asked for."""


class SchedulerServer(ThreadingHTTPServer):
    """An HTTP server that knows which schedule it is serving."""

    def __init__(self, address: tuple[str, int], service: ScheduleService) -> None:
        super().__init__(address, SchedulerRequestHandler)
        self.service = service


class SchedulerRequestHandler(BaseHTTPRequestHandler):
    """Dispatches a request to the route registered for its exact path."""

    server_version = f"{SERVICE_NAME}/{SERVICE_VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def schedule(self) -> ScheduleService:
        return cast(SchedulerServer, self.server).service

    def do_GET(self) -> None:  # noqa: N802  the name belongs to BaseHTTPRequestHandler
        self._dispatch(GET_ROUTES)

    def do_POST(self) -> None:  # noqa: N802  the name belongs to BaseHTTPRequestHandler
        self._dispatch(POST_ROUTES)

    def _dispatch(self, routes: dict[str, Route]) -> None:
        requested_path = urlsplit(self.path).path
        route = routes.get(requested_path)
        if route is None:
            self.respond_json(
                HTTPStatus.NOT_FOUND, {"error": "no such path", "path": requested_path}
            )
            return
        try:
            route(self)
        except (BadRequestError, ScheduleRejectedError) as refused:
            self.respond_json(HTTPStatus.BAD_REQUEST, {"error": str(refused)})
        except OSError as unreachable:
            self.respond_json(HTTPStatus.BAD_GATEWAY, {"error": str(unreachable)})

    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query)

    def json_body(self) -> dict[str, Any]:
        """Read and check the request body."""
        declared = self.headers.get("Content-Type", "").split(";")[0].strip()
        if declared != JSON_CONTENT_TYPE:
            raise BadRequestError(f"this endpoint takes {JSON_CONTENT_TYPE}")
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAXIMUM_BODY_BYTES:
            raise BadRequestError("the request needs a body, and a small one")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as unreadable:
            raise BadRequestError(f"the body is not valid JSON: {unreadable}") from unreadable
        if not isinstance(payload, dict):
            raise BadRequestError("the body must be a JSON object")
        return payload

    def respond(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        """Send one complete response. Nothing this service serves is cacheable."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def respond_json(self, status: HTTPStatus, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.respond(status, body, JSON_CONTENT_TYPE)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # The daemon writes this service's stdout to $BESPOK3D/var/log/print-scheduler.log, which is
        # the first place to look when it does not start.
        print(f"[{self.log_date_time_string()}] {format % args}", flush=True)


Route = Callable[[SchedulerRequestHandler], None]


def _job_request(payload: dict[str, Any]) -> JobRequest:
    try:
        start_at = float(payload.get("start_at", 0.0))
    except (TypeError, ValueError) as unusable:
        raise BadRequestError("start_at must be a number of seconds since the epoch") from unusable
    return JobRequest(
        filename=str(payload.get("filename", "")),
        start_at=start_at,
        typed_time=str(payload.get("typed_time", "")),
        timezone_name=str(payload.get("timezone_name", "")),
        bed_acknowledged=bool(payload.get("bed_acknowledged", False)),
        level_bed=_preference(payload.get("level_bed")),
        record_timelapse=_preference(payload.get("record_timelapse")),
    )


def _preference(value: Any) -> bool | None:
    """A preference the person did not set stays unset, and the printer keeps its own value."""
    return None if value is None else bool(value)


def serve_schedule_page(handler: SchedulerRequestHandler) -> None:
    body = render_schedule_page(SERVICE_VERSION).encode("utf-8")
    handler.respond(HTTPStatus.OK, body, "text/html; charset=utf-8")


def serve_health(handler: SchedulerRequestHandler) -> None:
    """Report this service's own liveness, and nothing that needs Moonraker to answer."""
    handler.respond_json(
        HTTPStatus.OK,
        {"service": SERVICE_NAME, "version": SERVICE_VERSION, "status": "ok"},
    )


def serve_jobs(handler: SchedulerRequestHandler) -> None:
    schedule = handler.schedule()
    handler.respond_json(
        HTTPStatus.OK, {"jobs": payload_for(schedule.jobs(), schedule.verdicts())}
    )


def serve_files(handler: SchedulerRequestHandler) -> None:
    handler.respond_json(HTTPStatus.OK, {"filenames": handler.schedule().gcode_filenames()})


def serve_file_summary(handler: SchedulerRequestHandler) -> None:
    requested = handler.query().get("filename", [""])[0]
    if not requested:
        raise BadRequestError("name a file")
    handler.respond_json(HTTPStatus.OK, handler.schedule().file_summary(requested).to_dict())


def serve_printer(handler: SchedulerRequestHandler) -> None:
    """The printer as it is right now, plus our own clock so a timezone skew is visible."""
    schedule = handler.schedule()
    snapshot = schedule.printer_snapshot()
    handler.respond_json(
        HTTPStatus.OK,
        {
            "reachable": snapshot.reachable,
            "klipper_state": snapshot.klipper_state,
            "klipper_message": snapshot.klipper_message,
            "print_state": snapshot.print_state,
            "printing_filename": snapshot.printing_filename,
            "other_gcode_running": snapshot.other_gcode_running,
            "printer_time": time.time(),
            "supports_print_preferences": schedule.supports_print_preferences(),
            "tolerance_minutes": schedule.tolerance_seconds() / 60.0,
        },
    )


def add_job(handler: SchedulerRequestHandler) -> None:
    job = handler.schedule().add(_job_request(handler.json_body()), time.time())
    handler.respond_json(HTTPStatus.OK, job.to_dict())


def update_job(handler: SchedulerRequestHandler) -> None:
    payload = handler.json_body()
    job_id = str(payload.get("job_id", ""))
    if not job_id:
        raise BadRequestError("name a job")
    job = handler.schedule().update(job_id, _job_request(payload), time.time())
    handler.respond_json(HTTPStatus.OK, job.to_dict())


def cancel_job(handler: SchedulerRequestHandler) -> None:
    job_id = str(handler.json_body().get("job_id", ""))
    if not job_id:
        raise BadRequestError("name a job")
    handler.respond_json(HTTPStatus.OK, handler.schedule().cancel(job_id, time.time()).to_dict())


GET_ROUTES: dict[str, Route] = {
    "/": serve_schedule_page,
    "/health": serve_health,
    "/jobs": serve_jobs,
    "/files": serve_files,
    "/file": serve_file_summary,
    "/printer": serve_printer,
}

POST_ROUTES: dict[str, Route] = {
    "/jobs": add_job,
    "/jobs/update": update_job,
    "/jobs/cancel": cancel_job,
}


def build_server(bind_address: str, port: int, service: ScheduleService) -> SchedulerServer:
    """Build the HTTP server without starting it, so a test can bind port 0 and ask what it got."""
    return SchedulerServer((bind_address, port), service)
