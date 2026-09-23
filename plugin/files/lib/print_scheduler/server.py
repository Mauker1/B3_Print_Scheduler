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
import logging
import time
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from print_scheduler.page import render_schedule_page
from print_scheduler.service import (
    JobRequest,
    ScheduleRejectedError,
    ScheduleService,
)

_log = logging.getLogger("bespok3d.print_scheduler")

SERVICE_NAME = "print-scheduler"

# Four levels up is the plugin root, in this repo and on the printer alike:
# <plugin>/files/lib/print_scheduler/server.py
MANIFEST_PATH = Path(__file__).resolve().parents[3] / "manifest.json"


def version_in(manifest_path: Path) -> str:
    """The plugin's version, or "unknown" when the manifest is not where it should be.

    Read rather than copied. The manifest is the release contract, so a second copy here would
    be a second thing to remember at a moment nobody is thinking about it, and it is the copy
    that gets forgotten: nothing breaks when it goes stale, it just starts lying quietly.

    It takes a path so the missing case can be tested, and that case is worth testing. A
    service running from outside its plugin tree should say it does not know rather than
    invent a number: a wrong version in a bug report costs more than a missing one.
    """
    try:
        return str(json.loads(manifest_path.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"


SERVICE_VERSION = version_in(MANIFEST_PATH)

JSON_CONTENT_TYPE = "application/json"
# A schedule entry is a filename and a few flags. Anything larger is not one.
MAXIMUM_BODY_BYTES = 64 * 1024


def _why_it_was_refused(refused: Exception) -> dict[str, Any]:
    """The refusal as JSON: English, plus the key and values when there are any.

    A `BadRequestError` carries no key on purpose. It means the request itself was malformed,
    which is a programming mistake in whatever sent it rather than something a person did, and
    a caller that cannot form a request is not helped by reading about it in Portuguese.
    """
    payload: dict[str, Any] = {"error": str(refused)}
    said = getattr(refused, "said", None)
    if said is not None:
        payload["error_key"] = said.key.value
        payload["error_values"] = said.wire_values()
    return payload


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

    # Whatever arrived with a POST, read off the socket once before any route sees it.
    _body: bytes = b""

    def schedule(self) -> ScheduleService:
        return cast(SchedulerServer, self.server).service

    def do_GET(self) -> None:  # noqa: N802  the name belongs to BaseHTTPRequestHandler
        self._dispatch(GET_ROUTES)

    def do_POST(self) -> None:  # noqa: N802  the name belongs to BaseHTTPRequestHandler
        # Drained here, before the route runs, and never in the route itself. This connection
        # is kept alive, so a body left unread stays in the socket and the next request on the
        # same connection is parsed starting from it: the server answered a real POST and then
        # rejected the following GET as an unsupported method called `{}GET`. Reading it once
        # here means no handler can reintroduce that by not caring about its body.
        self._body = self._read_the_body()
        self._dispatch(POST_ROUTES)

    def _read_the_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(min(length, MAXIMUM_BODY_BYTES))

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
            self.respond_json(HTTPStatus.BAD_REQUEST, _why_it_was_refused(refused))
        except OSError as unreachable:
            self.respond_json(HTTPStatus.BAD_GATEWAY, {"error": str(unreachable)})

    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query)

    def json_body(self) -> dict[str, Any]:
        """Check the request body, which was already read off the socket by do_POST."""
        declared = self.headers.get("Content-Type", "").split(";")[0].strip()
        if declared != JSON_CONTENT_TYPE:
            raise BadRequestError(f"this endpoint takes {JSON_CONTENT_TYPE}")
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0 or length > MAXIMUM_BODY_BYTES:
            raise BadRequestError("the request needs a body, and a small one")
        try:
            payload = json.loads(self._body.decode("utf-8"))
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
        # Every request, so INFO rather than anything louder, and through the same logger as the
        # rest of us. The daemon writes this service's output to
        # $BESPOK3D/var/log/print-scheduler.log, which is the first place to look when it does
        # not start. BaseHTTPRequestHandler would otherwise write straight to stderr, unformatted
        # and outside every level we set.
        _log.info(format, *args)


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
    handler.respond_json(HTTPStatus.OK, handler.schedule().schedule_payload())


def serve_files(handler: SchedulerRequestHandler) -> None:
    rows = handler.schedule().files_on_the_printer()
    handler.respond_json(HTTPStatus.OK, {"files": [row.to_dict() for row in rows]})


def serve_thumbnail(handler: SchedulerRequestHandler) -> None:
    """The picture a slicer left in the file, passed through rather than linked to.

    Linking the browser straight at Moonraker would mean an absolute URL to a host that is only
    Moonraker's on a printer, and the service also runs on a laptop pointed at one. Passing it
    through keeps every URL the page emits relative and keeps the image behind the same
    authentication as the rest of the schedule.
    """
    requested = handler.query().get("filename", [""])[0]
    if not requested:
        raise BadRequestError("name a file")
    found = handler.schedule().thumbnail(requested)
    if found is None:
        handler.respond_json(HTTPStatus.NOT_FOUND, {"error": "no thumbnail for that file"})
        return
    picture, content_type = found
    handler.respond(HTTPStatus.OK, picture, content_type)


def serve_file_summary(handler: SchedulerRequestHandler) -> None:
    requested = handler.query().get("filename", [""])[0]
    if not requested:
        raise BadRequestError("name a file")
    schedule = handler.schedule()
    summary = schedule.file_summary(requested)
    payload = summary.to_dict()
    payload["plan"] = schedule.tool_plan(summary).to_dict()
    handler.respond_json(HTTPStatus.OK, payload)


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
            # Shown on the page as well as logged, because the person who typed a value the
            # plugin cannot use is looking at the app, not at a file on the printer.
            "settings_ignored": [one.sentence() for one in schedule.settings().ignored()],
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


def forget_job(handler: SchedulerRequestHandler) -> None:
    """Remove one settled job from our list.

    Ours, not the printer's: its own history of what it printed is untouched and always was
    the authority on that. This list is a record of what the scheduler decided.
    """
    job_id = str(handler.json_body().get("job_id", ""))
    if not job_id:
        raise BadRequestError("name a job")
    handler.schedule().forget(job_id)
    handler.respond_json(HTTPStatus.OK, {"forgotten": job_id})


def forget_settled_jobs(handler: SchedulerRequestHandler) -> None:
    """Empty the settled list. Nothing scheduled is touched, which is what makes it safe."""
    gone = handler.schedule().forget_every_settled_job()
    handler.respond_json(HTTPStatus.OK, {"forgotten": gone})


def release_held_jobs(handler: SchedulerRequestHandler) -> None:
    """Let jobs held after a long silence stand again, all of them at once."""
    released = handler.schedule().release_held_jobs()
    handler.respond_json(HTTPStatus.OK, {"released": released})


GET_ROUTES: dict[str, Route] = {
    "/": serve_schedule_page,
    "/health": serve_health,
    "/jobs": serve_jobs,
    "/files": serve_files,
    "/thumbnail": serve_thumbnail,
    "/file": serve_file_summary,
    "/printer": serve_printer,
}

POST_ROUTES: dict[str, Route] = {
    "/jobs": add_job,
    "/jobs/update": update_job,
    "/jobs/cancel": cancel_job,
    "/jobs/forget": forget_job,
    "/jobs/forget-settled": forget_settled_jobs,
    "/jobs/release": release_held_jobs,
}


def build_server(bind_address: str, port: int, service: ScheduleService) -> SchedulerServer:
    """Build the HTTP server without starting it, so a test can bind port 0 and ask what it got."""
    return SchedulerServer((bind_address, port), service)
