# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The routing rule, exercised over a real socket.

The rule is worth a socket rather than a unit test because the failure it prevents looks like
something else entirely: Fluidd and Mainsail append a cache-busting parameter to their requests, so
a route matched against the raw request target 404s on a path that is plainly in the table.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from urllib.error import HTTPError
from urllib.request import urlopen

import print_scheduler
import pytest


@pytest.fixture(name="base_url")
def fixture_base_url() -> Iterator[str]:
    """Serve on an ephemeral port for the duration of one test."""
    server = print_scheduler.build_server("127.0.0.1", 0)
    serving = threading.Thread(
        target=server.serve_forever, name="print-scheduler-test", daemon=True
    )
    serving.start()
    try:
        yield f"http://127.0.0.1:{int(server.server_address[1])}"
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)


def test_the_page_is_served_at_the_root(base_url: str) -> None:
    with urlopen(f"{base_url}/", timeout=5) as response:
        assert response.status == 200
        assert b"Print Scheduler" in response.read()


def test_a_cache_busting_query_string_does_not_change_the_route(base_url: str) -> None:
    with urlopen(f"{base_url}/jobs?t=1758369600000", timeout=5) as response:
        assert response.status == 200
        assert json.loads(response.read()) == {"jobs": []}


def test_health_answers_without_needing_moonraker(base_url: str) -> None:
    with urlopen(f"{base_url}/health", timeout=5) as response:
        assert json.loads(response.read())["status"] == "ok"


def test_an_unknown_path_answers_with_json_rather_than_an_html_error_page(base_url: str) -> None:
    with pytest.raises(HTTPError) as refused:
        urlopen(f"{base_url}/not-a-route", timeout=5)
    assert refused.value.status == 404
    assert json.loads(refused.value.read())["path"] == "/not-a-route"
