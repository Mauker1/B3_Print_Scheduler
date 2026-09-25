# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web layer, exercised over a real socket.

Two things here are worth a socket rather than a unit test, because both failures look like
something else entirely. A route matched against the raw request target 404s on a path that is
plainly in the table, because Fluidd and Mainsail append a cache-busting parameter. And the
content type rule is the difference between a page on another site being able to schedule a print
on your machine and not.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest
from print_scheduler import ScheduleService, ScheduleStore, Settings, build_server
from print_scheduler.server import POST_ROUTES
from printer_stand_in import BENCHY, StandInPrinter

SIX_IN_THE_MORNING = 1_758_348_000.0
FAR_FUTURE = 4_102_444_800.0


@pytest.fixture(name="served")
def fixture_served(tmp_path: Path) -> Iterator[tuple[str, ScheduleService]]:
    """Serve one schedule on an ephemeral port for the duration of one test."""
    service = ScheduleService(
        ScheduleStore(tmp_path / "jobs.json"),
        StandInPrinter(thumbnail_bytes=b"a picture"),
        Settings(tmp_path / "user_vars.json"),
    )
    server = build_server("127.0.0.1", 0, service)
    serving = threading.Thread(
        target=server.serve_forever, name="print-scheduler-test", daemon=True
    )
    serving.start()
    try:
        yield f"http://127.0.0.1:{int(server.server_address[1])}", service
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)


def get(base_url: str, path: str) -> dict:
    with urlopen(f"{base_url}{path}", timeout=5) as response:
        return dict(json.loads(response.read()))


def post(base_url: str, path: str, body: dict, content_type: str = "application/json") -> dict:
    request = Request(
        f"{base_url}{path}",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": content_type},
    )
    with urlopen(request, timeout=5) as response:
        return dict(json.loads(response.read()))


def test_the_page_is_served_at_the_root(served: tuple[str, ScheduleService]) -> None:
    with urlopen(f"{served[0]}/", timeout=5) as response:
        assert response.status == 200
        assert b"Print Scheduler" in response.read()


def test_a_cache_busting_query_string_does_not_change_the_route(
    served: tuple[str, ScheduleService],
) -> None:
    assert get(served[0], "/jobs?t=1758369600000")["jobs"] == []


def test_health_answers_without_needing_moonraker(served: tuple[str, ScheduleService]) -> None:
    assert get(served[0], "/health")["status"] == "ok"


def test_the_file_list_comes_from_the_printer(served: tuple[str, ScheduleService]) -> None:
    names = [row["filename"] for row in get(served[0], "/files")["files"]]
    assert BENCHY in names


def test_a_file_summary_is_served_for_the_name_in_the_query(
    served: tuple[str, ScheduleService],
) -> None:
    summary = get(served[0], f"/file?filename={BENCHY}")
    assert summary["filename"] == BENCHY
    assert len(summary["tools"]) == 1


def test_asking_for_a_summary_without_naming_a_file_is_a_bad_request(
    served: tuple[str, ScheduleService],
) -> None:
    with pytest.raises(HTTPError) as refused:
        get(served[0], "/file")
    assert refused.value.status == 400


def test_the_printer_endpoint_reports_our_own_clock_so_a_skew_is_visible(
    served: tuple[str, ScheduleService],
) -> None:
    printer = get(served[0], "/printer")
    assert printer["reachable"] is True
    assert printer["printer_time"] > 0
    assert printer["tolerance_minutes"] == 5


def test_a_job_can_be_scheduled_and_then_listed(served: tuple[str, ScheduleService]) -> None:
    base_url, _ = served
    created = post(base_url, "/jobs", {
        "filename": BENCHY, "start_at": FAR_FUTURE, "bed_acknowledged": True,
    })
    listed = get(base_url, "/jobs")["jobs"]
    assert [job["job_id"] for job in listed] == [created["job_id"]]
    assert listed[0]["state"] == "scheduled"


def test_a_job_can_be_cancelled_through_the_endpoint(
    served: tuple[str, ScheduleService],
) -> None:
    base_url, _ = served
    created = post(base_url, "/jobs", {
        "filename": BENCHY, "start_at": FAR_FUTURE, "bed_acknowledged": True,
    })
    cancelled = post(base_url, "/jobs/cancel", {"job_id": created["job_id"]})
    assert cancelled["state"] == "cancelled"
    assert cancelled["refusal"] == "cancelled-by-you"


def test_a_refused_job_answers_with_the_reason_rather_than_a_stack_trace(
    served: tuple[str, ScheduleService],
) -> None:
    with pytest.raises(HTTPError) as refused:
        post(served[0], "/jobs", {"filename": BENCHY, "start_at": FAR_FUTURE})
    assert refused.value.status == 400
    assert "promise" in json.loads(refused.value.read())["error"]


def test_a_form_encoded_post_is_refused(served: tuple[str, ScheduleService]) -> None:
    # A page on another site can post a form without the browser asking permission first, but it
    # cannot post JSON. Requiring JSON is what stops it scheduling a print on your machine.
    with pytest.raises(HTTPError) as refused:
        post(
            served[0],
            "/jobs",
            {"filename": BENCHY},
            content_type="application/x-www-form-urlencoded",
        )
    assert refused.value.status == 400
    assert "application/json" in json.loads(refused.value.read())["error"]


def test_an_unknown_path_answers_with_json_rather_than_an_html_error_page(
    served: tuple[str, ScheduleService],
) -> None:
    with pytest.raises(HTTPError) as refused:
        get(served[0], "/not-a-route")
    assert refused.value.status == 404
    assert json.loads(refused.value.read())["path"] == "/not-a-route"


def test_a_thumbnail_comes_back_as_an_image(served: tuple[str, ScheduleService]) -> None:
    with urlopen(f"{served[0]}/thumbnail?filename={quote(BENCHY)}", timeout=5) as response:
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        assert response.read() == b"a picture"


def test_a_file_with_no_thumbnail_is_a_clean_miss_rather_than_a_broken_image(
    served: tuple[str, ScheduleService],
) -> None:
    try:
        with urlopen(f"{served[0]}/thumbnail?filename=nothing.gcode", timeout=5):
            raise AssertionError("expected a 404")
    except HTTPError as missing:
        assert missing.code == 404


def test_a_post_whose_handler_ignores_the_body_does_not_poison_the_connection(
    served: tuple[str, ScheduleService],
) -> None:
    """The bug this guards: a body left unread stays in a kept-alive socket.

    The next request on that connection is then parsed starting from the leftover bytes, and
    the server answered a real POST and then rejected the following GET as an unsupported
    method called `{}GET`. One connection, two requests, in that order, is the whole test.
    """
    from http.client import HTTPConnection
    host = served[0].removeprefix("http://")
    connection = HTTPConnection(host, timeout=5)
    connection.request(
        "POST", "/jobs/forget-settled", body=b"{}",
        headers={"Content-Type": "application/json"},
    )
    assert connection.getresponse().read() is not None
    connection.request("GET", "/health")
    second = connection.getresponse()
    assert second.status == 200
    connection.close()


@pytest.mark.parametrize("path", sorted(POST_ROUTES))
def test_every_endpoint_that_changes_something_refuses_anything_but_json(
    served: tuple[str, ScheduleService], path: str
) -> None:
    """A plain text POST is what another website can send without the browser asking first.

    Enforced in one place for every route, and tested for every route, because two of them had
    quietly accepted it: clearing the settled list and releasing held jobs. A route added later
    is covered by this without anybody remembering to add it.
    """
    with pytest.raises(HTTPError) as refused:
        post(served[0], path, {}, content_type="text/plain")
    assert refused.value.code == 400
    assert "application/json" in json.loads(refused.value.read())["error"]
