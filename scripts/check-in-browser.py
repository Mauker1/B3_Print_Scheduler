#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the real page in a headless browser, against a stand-in printer.

The gate covers the plugin's Python. It cannot cover whether a button does anything, and in a
sibling plugin that gap shipped two bugs: a control whose name shadowed a form property, and a
fallback that dropped the button that was pressed. Both passed every server-side test.

Two rules came out of that experience and both are followed here.

Measure the page before anything touches it. A page that only paints on interaction looks perfect
to any test that interacts, so the first checks below assert what is on screen after load and
before a single click.

Do not confuse this with the prefix test. This harness serves the page at the root, so a relative
URL and an absolute one both work here. That the page emits no absolute path is asserted in
`plugin/tests/test_page.py` instead, where it cannot pass by accident.

Not in the gate: it needs a browser download, which is a lot to ask of someone working on a
printer plugin.

    pip install playwright && playwright install chromium
    python3 scripts/check-in-browser.py
"""

from __future__ import annotations

import sys

# Before importing the plugin. It lives under plugin/files/, which the builder packs verbatim,
# and the daemon refuses a package holding a member the manifest's files[] does not list, so a
# .pyc dropped here is a failed install. The gate sets this for its own runs; this harness runs
# outside the gate and has to set it for itself.
sys.dont_write_bytecode = True

import tempfile  # noqa: E402  after the bytecode setting
import threading  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(REPO_ROOT / "plugin" / "files" / "lib"))
sys.path.append(str(REPO_ROOT / "plugin" / "tests"))

try:
    from playwright.sync_api import Page, sync_playwright  # noqa: E402  the paths come first
except ModuleNotFoundError:  # pragma: no cover  the message is the point
    sys.exit(
        "This harness needs a browser, which the gate deliberately does not, so playwright is\n"
        "not installed for you. Either:\n"
        "    pip install playwright && playwright install chromium\n"
        "or, if your python refuses to install into itself, which most managed ones now do:\n"
        "    python3 -m venv .venv\n"
        "    .venv/bin/pip install playwright\n"
        "    .venv/bin/playwright install chromium\n"
        "    .venv/bin/python scripts/check-in-browser.py"
    )
from print_scheduler import (  # noqa: E402
    PrintRecord,
    ScheduleService,
    ScheduleStore,
    build_server,
)
from printer_stand_in import (  # noqa: E402
    BENCHY,
    FOUR_TOOL_METADATA,
    TOO_MUCH_ASA_METADATA,
    WHITE_PLA_METADATA,
    StandInPrinter,
)

A_TIME_WELL_IN_THE_FUTURE = "2030-06-01T06:00"
MULTI_TOOL_FILE = "04_XYZ_Cali_PLA_14m25s.gcode"
SLOTS_IN_THE_MULTI_TOOL_FILE = 4
PATIENCE_MILLISECONDS = 5000

# The durations are the printer's own, off jobs 0000BE and 0000BF, so the page has a real setup
# time to quote rather than a round number that would hide an off by a factor mistake. The two
# differ because one had levelling on and the other did not, which is exactly the spread the
# page has to be able to say out loud.
PRINTS_THAT_FINISHED = (
    PrintRecord(
        job_id="0000C0",
        filename=BENCHY,
        start_time=1789930000.00,
        status="completed",
        end_time=1789930338.41,
        total_duration=338.41,
        print_duration=128.60,
    ),
    PrintRecord(
        job_id="0000BF",
        filename=BENCHY,
        start_time=1789928000.00,
        status="completed",
        end_time=1789928499.14,
        total_duration=499.14,
        print_duration=39.64,
    ),
    PrintRecord(
        job_id="0000BE",
        filename=BENCHY,
        start_time=1789925226.45,
        status="completed",
        end_time=1789925865.19,
        total_duration=638.67,
        print_duration=40.03,
    ),
)

failures: list[str] = []
complaints: list[str] = []


def check(description: str, actual: object, expected: object) -> None:
    outcome = "ok" if actual == expected else "FAIL"
    print(f"  {description:<62} {outcome}")
    if actual != expected:
        failures.append(f"{description}: expected {expected!r}, got {actual!r}")


def text_of(page: Page, selector: str) -> str:
    return (page.text_content(selector) or "").strip()


def wait_for_the_file_list(page: Page) -> None:
    # Attached, not visible: an option inside a closed select is never "visible".
    page.wait_for_selector(
        "#file-choice option[value$='.gcode']", state="attached", timeout=PATIENCE_MILLISECONDS
    )


def check_the_page_before_anything_touches_it(page: Page) -> None:
    print("\nOn load, before any interaction")
    wait_for_the_file_list(page)
    check("the printer line says something", text_of(page, "#printer-line") != "", True)
    check("the file list is populated", page.locator("#file-choice option").count() > 1, True)
    check("nothing is scheduled", "Nothing scheduled" in text_of(page, "#pending"), True)
    check("the settled list is empty", "Nothing yet" in text_of(page, "#settled"), True)
    check("scheduling is refused until asked properly", page.is_disabled("#save"), True)
    check("the preference toggles are offered", page.is_visible("#level-bed"), True)


def check_choosing_a_file(page: Page, filename: str) -> None:
    print("\nChoosing a file")
    page.select_option("#file-choice", filename)
    page.wait_for_selector(".tool", timeout=PATIENCE_MILLISECONDS)
    facts = text_of(page, "#file-facts")
    check("the slicer slot is shown, not a toolhead", "slot 0" in facts, True)
    check("the material is shown", "PLA" in facts, True)
    # The regression, visible on screen: slot 0 wants white PLA, which is on T2. The
    # printer would default it to T0, where the ASA is.
    check("the toolhead it chose is shown", "on T2" in facts, True)
    check("the estimate is shown", "about 26s" in facts, True)
    check("the bed temperature is shown", "bed 45" in facts, True)
    check("a file alone is not enough to schedule", page.is_disabled("#save"), True)


def check_the_bed_promise_is_required(page: Page) -> None:
    print("\nThe promise about the bed")
    page.fill("#start-at", A_TIME_WELL_IN_THE_FUTURE)
    check("a time alone is still not enough", page.is_disabled("#save"), True)
    page.check("#bed-clear")
    check("promising the bed is clear enables it", page.is_enabled("#save"), True)


def check_scheduling(page: Page) -> None:
    print("\nScheduling")
    page.click("#save")
    page.wait_for_selector("#pending .job", timeout=PATIENCE_MILLISECONDS)
    pending = text_of(page, "#pending")
    check("the job is listed", "3DBenchy" in pending, True)
    check("it says when it starts", "Starts" in pending, True)
    check("it projects a finish", "should finish" in pending, True)
    check("it names the setup time", "of setup, then" in pending, True)
    check("and quotes it as a range when the printer varies", "3m to 10m" in pending, True)
    check("the finish is a range too", "should finish between" in pending, True)
    check(
        "and does not warn about a setup time it knows",
        "not counting the printer's setup" in pending,
        False,
    )
    check("the time is cleared for the next one", page.input_value("#start-at"), "")
    check("the promise is not reused", page.is_checked("#bed-clear"), False)
    check("and scheduling is refused again", page.is_disabled("#save"), True)


def check_cancelling(page: Page) -> None:
    print("\nCancelling")
    page.click("#pending .job button:has-text('Cancel')")
    page.wait_for_selector("#settled .job", timeout=PATIENCE_MILLISECONDS)
    check("it leaves the pending list", "Nothing scheduled" in text_of(page, "#pending"), True)
    check("it says it did not run", "Did not run" in text_of(page, "#settled"), True)
    check("and why", "you cancelled it" in text_of(page, "#settled"), True)


def check_a_multi_tool_file(page: Page, printer: StandInPrinter) -> None:
    print("\nA multi tool file")
    printer.holds = frozenset({*printer.holds, MULTI_TOOL_FILE})
    printer.describes = dict(FOUR_TOOL_METADATA)
    page.reload()
    wait_for_the_file_list(page)
    page.select_option("#file-choice", MULTI_TOOL_FILE)
    page.wait_for_selector("#file-facts .tools", timeout=PATIENCE_MILLISECONDS)
    facts = text_of(page, "#file-facts")
    check(
        "every slot is listed",
        facts.count("slot ") >= SLOTS_IN_THE_MULTI_TOOL_FILE,
        True,
    )
    check(
        "each one names its toolhead",
        facts.count(" on T") >= SLOTS_IN_THE_MULTI_TOOL_FILE,
        True,
    )
    check("nothing refuses it", "#file-facts .stop" not in facts, True)
    page.fill("#start-at", A_TIME_WELL_IN_THE_FUTURE)
    page.check("#bed-clear")
    check("and it can be scheduled", page.is_enabled("#save"), True)


def check_a_file_whose_material_is_not_loaded(page: Page, printer: StandInPrinter) -> None:
    print("\nA file wanting more of a material than the machine holds")
    printer.describes = dict(TOO_MUCH_ASA_METADATA)
    page.reload()
    wait_for_the_file_list(page)
    page.select_option("#file-choice", MULTI_TOOL_FILE)
    page.wait_for_selector("#file-facts .stop", timeout=PATIENCE_MILLISECONDS)
    facts = text_of(page, "#file-facts")
    check("it says how many short it is", "needs 3 toolheads with ASA" in facts, True)
    check("and what the printer has instead", "The printer reports" in facts, True)
    page.fill("#start-at", A_TIME_WELL_IN_THE_FUTURE)
    page.check("#bed-clear")
    check("and scheduling is refused", page.is_disabled("#save"), True)


def watch_for_complaints(page: Page) -> None:
    """A console error is a failure here, not noise."""
    page.on("pageerror", lambda problem: complaints.append(f"page error: {problem}"))
    page.on(
        "console",
        lambda message: complaints.append(f"console error: {message.text}")
        if message.type == "error"
        else None,
    )


def run_every_check(page: Page, printer: StandInPrinter, base_url: str) -> None:
    page.goto(base_url)
    check_the_page_before_anything_touches_it(page)
    check_choosing_a_file(page, sorted(printer.holds)[0])
    check_the_bed_promise_is_required(page)
    check_scheduling(page)
    check_cancelling(page)
    check_a_multi_tool_file(page, printer)
    check_a_file_whose_material_is_not_loaded(page, printer)


def serve(scratch: Path, printer: StandInPrinter) -> tuple[str, Any]:
    service = ScheduleService(
        ScheduleStore(scratch / "jobs.json"), printer, scratch / "user_vars.json"
    )
    server = build_server("127.0.0.1", 0, service)
    threading.Thread(target=server.serve_forever, name="check-in-browser", daemon=True).start()
    return f"http://127.0.0.1:{int(server.server_address[1])}/", server


def report() -> int:
    print("")
    for complaint in complaints:
        print(f"  browser complained: {complaint}")
    for failure in failures:
        print(f"  {failure}")
    if failures or complaints:
        print(f"\n{len(failures)} failed, {len(complaints)} browser complaints")
        return 1
    print("The page works.")
    return 0


def main() -> int:
    printer = StandInPrinter(
        describes=dict(WHITE_PLA_METADATA), remembers=PRINTS_THAT_FINISHED
    )
    with tempfile.TemporaryDirectory() as scratch:
        base_url, server = serve(Path(scratch), printer)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            watch_for_complaints(page)
            run_every_check(page, printer, base_url)
            browser.close()
        server.shutdown()
    return report()


if __name__ == "__main__":
    sys.exit(main())
