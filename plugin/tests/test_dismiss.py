# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clearing a finished print from the page.

The command behind this is `SDCARD_RESET_FILE`, whose own help text says it stops a print if
necessary. So most of this file is about the one number that matters most: how many times the
command reached a printer that was not finished, which must always be zero.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from print_scheduler import (
    ENGLISH,
    Message,
    PrinterSnapshot,
    ScheduleRejectedError,
    ScheduleService,
    ScheduleStore,
    Settings,
    build_server,
    say,
)
from printer_stand_in import IDLE, StandInPrinter

FINISHED = replace(IDLE, print_state="complete", printing_filename="cube.gcode")
CANCELLED = replace(IDLE, print_state="cancelled", printing_filename="cube.gcode")


def a_service(tmp_path: Path, printer: StandInPrinter) -> ScheduleService:
    return ScheduleService(
        ScheduleStore(tmp_path / "jobs.json"), printer, Settings(tmp_path / "user_vars.json")
    )


@pytest.mark.parametrize("ended", [FINISHED, CANCELLED])
def test_a_print_that_ended_is_cleared(tmp_path: Path, ended: PrinterSnapshot) -> None:
    printer = StandInPrinter(reports=ended)
    a_service(tmp_path, printer).dismiss_finished_print()
    assert printer.dismissed == 1
    assert printer.reports.print_state == "standby"


@pytest.mark.parametrize(
    "state",
    [
        # The one that matters: the command stops a running print.
        replace(IDLE, print_state="printing", printing_filename="somebody-else.gcode"),
        replace(IDLE, print_state="paused", printing_filename="somebody-else.gcode"),
        IDLE,
        # A failed print is for somebody to walk over and look at, not to clear from a phone.
        replace(IDLE, print_state="error"),
        replace(FINISHED, klipper_state="startup"),
        replace(FINISHED, klipper_state="shutdown"),
        PrinterSnapshot(reachable=False, klipper_message="connection refused"),
    ],
)
def test_nothing_else_is_ever_sent_the_command(tmp_path: Path, state: PrinterSnapshot) -> None:
    printer = StandInPrinter(reports=state)
    with pytest.raises(ScheduleRejectedError):
        a_service(tmp_path, printer).dismiss_finished_print()
    assert printer.dismissed == 0


def test_the_printer_is_asked_again_when_the_button_is_pressed(tmp_path: Path) -> None:
    """The page offered the button while the print was finished. Since then, somebody started
    another one from the touchscreen. The page's copy of the state is not what decides."""
    printer = StandInPrinter(reports=FINISHED)
    service = a_service(tmp_path, printer)
    printer.reports = replace(IDLE, print_state="printing", printing_filename="started-by-hand")
    with pytest.raises(ScheduleRejectedError) as refused:
        service.dismiss_finished_print()
    assert printer.dismissed == 0
    assert refused.value.said.key is Message.NOTHING_TO_DISMISS
    assert "printing" in str(refused.value)


def test_the_printer_s_own_refusal_is_passed_on_in_its_own_words(tmp_path: Path) -> None:
    printer = StandInPrinter(reports=FINISHED, refuses_dismiss_with="Must home axis first")
    with pytest.raises(ScheduleRejectedError) as refused:
        a_service(tmp_path, printer).dismiss_finished_print()
    assert str(refused.value) == "Must home axis first"


def test_the_refusal_reads_in_the_reader_s_language(tmp_path: Path) -> None:
    printer = StandInPrinter(reports=IDLE)
    with pytest.raises(ScheduleRejectedError) as refused:
        a_service(tmp_path, printer).dismiss_finished_print()
    said = refused.value.said
    assert "nothing to dismiss" in say(ENGLISH, said.key, said.values)
    assert "nada para dispensar" in say("pt-BR", said.key, said.values)


@pytest.fixture(name="served")
def fixture_served(tmp_path: Path) -> Iterator[tuple[str, StandInPrinter]]:
    printer = StandInPrinter(reports=FINISHED)
    server = build_server("127.0.0.1", 0, a_service(tmp_path, printer))
    serving = threading.Thread(target=server.serve_forever, name="dismiss-test", daemon=True)
    serving.start()
    try:
        yield f"http://127.0.0.1:{int(server.server_address[1])}", printer
    finally:
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)


def post(base_url: str, body: dict[str, object], content_type: str = "application/json") -> dict:
    request = Request(
        f"{base_url}/printer/dismiss",
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": content_type},
    )
    with urlopen(request, timeout=5) as response:
        return dict(json.loads(response.read()))


def test_the_endpoint_clears_a_finished_print(served: tuple[str, StandInPrinter]) -> None:
    base_url, printer = served
    assert post(base_url, {}) == {"dismissed": True}
    assert printer.dismissed == 1


def test_the_endpoint_refuses_in_keys_the_page_can_translate(
    served: tuple[str, StandInPrinter],
) -> None:
    base_url, printer = served
    printer.reports = IDLE
    with pytest.raises(HTTPError) as refused:
        post(base_url, {})
    payload = json.loads(refused.value.read())
    assert refused.value.code == 400
    assert payload["error_key"] == Message.NOTHING_TO_DISMISS.value
    assert printer.dismissed == 0


def test_the_endpoint_takes_json_and_nothing_else(served: tuple[str, StandInPrinter]) -> None:
    """A form post from another site cannot reach it, which is why every changing endpoint
    insists on a content type a plain HTML form cannot send."""
    base_url, printer = served
    with pytest.raises(HTTPError) as refused:
        post(base_url, {}, content_type="text/plain")
    assert refused.value.code == 400
    assert printer.dismissed == 0
