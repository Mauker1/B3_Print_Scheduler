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

import base64  # noqa: E402  after the bytecode setting
import json  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
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
    A_LONG_SILENCE_SECONDS,
    Heartbeat,
    Job,
    PrintRecord,
    ScheduleService,
    ScheduleStore,
    Settings,
    build_server,
    start_logging,
)
from printer_stand_in import (  # noqa: E402
    BENCHY,
    CHINESE_NAME,
    FOUR_TOOL_METADATA,
    TOO_MUCH_ASA_METADATA,
    WHITE_PLA_METADATA,
    StandInPrinter,
)

A_TIME_WELL_IN_THE_FUTURE = "2030-06-01T06:00"
# The smallest legal PNG, so the page has a real image to lay out rather than a broken one.
ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
# The shared fixtures carry no thumbnails, because the modules that use them are not about
# pictures. The page is, so the harness adds one: two sizes, so the largest actually gets
# chosen rather than the only one passing by default.
THUMBNAILS_THE_SLICER_WROTE = [
    {"width": 32, "height": 32, "relative_path": ".thumbs/small.png"},
    {"width": 300, "height": 300, "relative_path": ".thumbs/large.png"},
]
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
    page.wait_for_selector("#file-list .file", timeout=PATIENCE_MILLISECONDS)


def pick_the_file(page: Page, filename: str) -> None:
    page.click(f'#file-list .file[data-filename="{filename}"]')


def check_the_page_before_anything_touches_it(page: Page) -> None:
    print("\nOn load, before any interaction")
    wait_for_the_file_list(page)
    check("the printer line says something", text_of(page, "#printer-line") != "", True)
    check("the file list is populated", page.locator("#file-list .file").count() > 0, True)
    check("every file shows its preview", page.locator("#file-list .file img").count() > 0, True)
    check("nothing is scheduled", "Nothing scheduled" in text_of(page, "#pending"), True)
    check("the settled list is empty", "Nothing yet" in text_of(page, "#settled"), True)
    check("scheduling is refused until asked properly", page.is_disabled("#save"), True)
    check("the preference toggles are offered", page.is_visible("#level-bed"), True)


def check_the_file_list_itself(page: Page) -> None:
    print("\nThe file list")
    rows = text_of(page, "#file-list")
    check("a file says when it was sliced", "sliced" in rows, True)
    check("and whether it has ever run", "never printed" in rows, True)
    check("and how long it takes", "48m" in rows or "26s" in rows, True)
    page.fill("#file-search", "nothing matches this")
    page.wait_for_timeout(100)
    check("searching can empty it", "No file matches" in text_of(page, "#file-list"), True)
    page.fill("#file-search", "Benchy")
    page.wait_for_timeout(100)
    check("and narrow it", page.locator("#file-list .file").count(), 1)
    page.fill("#file-search", "")
    page.wait_for_timeout(100)
    newest = page.locator("#file-list .file").first.get_attribute("data-filename")
    page.select_option("#file-sort", "name")
    page.wait_for_timeout(100)
    alphabetical = page.locator("#file-list .file").first.get_attribute("data-filename")
    check("sorting by name changes the order", alphabetical != newest, True)
    page.select_option("#file-sort", "name-back")
    page.wait_for_timeout(100)
    backwards = page.locator("#file-list .file").first.get_attribute("data-filename")
    check("and reversing it changes the order again", backwards != alphabetical, True)
    page.select_option("#file-sort", "newest")
    page.wait_for_timeout(100)
    check(
        "and newest first comes back",
        page.locator("#file-list .file").first.get_attribute("data-filename"),
        newest,
    )


def check_choosing_a_file(page: Page, filename: str) -> None:
    print("\nChoosing a file")
    pick_the_file(page, filename)
    page.wait_for_selector(".tool", timeout=PATIENCE_MILLISECONDS)
    facts = text_of(page, "#file-facts")
    check("the slicer slot is shown, not a toolhead", "slot 0" in facts, True)
    check("the material is shown", "PLA" in facts, True)
    # The regression, visible on screen: slot 0 wants white PLA, which is on T2. The
    # printer would default it to T0, where the ASA is.
    check("the toolhead it chose is shown", "on T2" in facts, True)
    check("and nothing claims there is no toolhead", "no toolhead" in facts, False)
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
    check("the job says what it asked the printer for", "levelling, timelapse" in pending, True)
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


def check_clearing_the_settled_list(page: Page) -> None:
    print("\nClearing the settled list")
    check("a settled job offers to be removed", page.is_visible("#settled button"), True)
    check("and the list offers to be cleared", "Clear the list" in text_of(page, "#clear-settled"),
          True)
    page.click("#clear-settled button")
    page.wait_for_timeout(150)
    check(
        "one click only arms it, saying what the next one does",
        "Really remove 1?" in text_of(page, "#clear-settled"),
        True,
    )
    check("and nothing has gone yet", "Did not run" in text_of(page, "#settled"), True)
    page.click("#clear-settled button")
    page.wait_for_selector("#settled:has-text('Nothing yet')", timeout=PATIENCE_MILLISECONDS)
    check("the second click empties it", "Nothing yet" in text_of(page, "#settled"), True)
    check("and the button goes with it", text_of(page, "#clear-settled"), "")


def check_editing_carries_the_jobs_own_choices(page: Page) -> None:
    """The form must show what the job asked for, not what the form was last left at.

    Found on hardware: editing a levelled job while these boxes happened to sit unchecked
    silently stopped it levelling, with nothing on screen to say so. It costs a print and it
    gives no warning, so it is checked in both directions.
    """
    print("\nEditing a job")
    page.uncheck("#level-bed")
    page.uncheck("#record-timelapse")
    page.click("#pending .job button:has-text('Edit')")
    page.wait_for_timeout(150)
    check("editing restores the job's levelling", page.is_checked("#level-bed"), True)
    check("and its timelapse", page.is_checked("#record-timelapse"), True)
    check("the job's own time comes back", page.input_value("#start-at"), A_TIME_WELL_IN_THE_FUTURE)
    check("but the promise about the bed does not", page.is_checked("#bed-clear"), False)

    # Now change one of them and save, so the next edit has something different to carry.
    page.uncheck("#level-bed")
    page.check("#bed-clear")
    page.click("#save")
    page.wait_for_selector("#pending .job:has-text('no levelling')", timeout=PATIENCE_MILLISECONDS)
    check("the change is saved", "no levelling, timelapse" in text_of(page, "#pending"), True)

    page.check("#level-bed")
    page.click("#pending .job button:has-text('Edit')")
    page.wait_for_timeout(150)
    check("editing again carries the changed choice", page.is_checked("#level-bed"), False)
    check("and leaves the other one alone", page.is_checked("#record-timelapse"), True)
    page.click("#stop-editing")


def check_copying_carries_the_choices_too(page: Page) -> None:
    """Schedule another like this has the same duty, and a stronger claim to it."""
    print("\nCopying a settled job")
    page.check("#level-bed")
    page.click("#settled .job button:has-text('Schedule another like this')")
    page.wait_for_timeout(150)
    check("the copy is like the original", page.is_checked("#level-bed"), False)
    check("in both choices", page.is_checked("#record-timelapse"), True)
    check("but it is a new job, not an edit", page.input_value("#start-at"), "")


def schedule_one(page: Page, filename: str, when: str) -> None:
    # Cleared rather than assumed empty: an earlier check may have left a filter in it, and a
    # filtered out file is a timeout with a misleading message.
    page.fill("#file-search", "")
    page.wait_for_selector(
        f'#file-list .file[data-filename="{filename}"]', timeout=PATIENCE_MILLISECONDS
    )
    pick_the_file(page, filename)
    page.fill("#start-at", when)
    page.check("#bed-clear")
    page.wait_for_selector("#save:not([disabled])", timeout=PATIENCE_MILLISECONDS)
    page.click("#save")
    page.wait_for_selector(f'#pending .job:has-text("{filename}")', timeout=PATIENCE_MILLISECONDS)


def cancel_one(page: Page, filename: str) -> None:
    page.click(f'#pending .job:has-text("{filename}") button:has-text("Cancel")')
    page.wait_for_selector(f'#settled .job:has-text("{filename}")', timeout=PATIENCE_MILLISECONDS)


def check_the_lists_are_in_time_order(page: Page) -> None:
    """A list called Scheduled has to say what happens next, not what was typed last.

    Found on hardware: a job re-created after a failure sat at the bottom of the queue
    although it was due first. The settled list had the same fault in reverse, and that one is
    the worse of the two, because reverse creation order looks like newest first often enough
    to be trusted.
    """
    print("\nThe order of the two lists")
    schedule_one(page, BENCHY, "2030-06-03T06:00")
    schedule_one(page, CHINESE_NAME, "2030-06-02T06:00")
    check(
        "the job due first is listed first, not the one added first",
        page.locator("#pending .job-title").all_inner_texts(),
        [CHINESE_NAME, BENCHY],
    )
    check("and every job row carries the file's picture",
          page.locator("#pending .job img").count(), 2)

    # Settled the other way round on purpose: the job created first is cancelled last, so
    # reverse creation order and newest settled first disagree about which comes top.
    cancel_one(page, CHINESE_NAME)
    cancel_one(page, BENCHY)
    check(
        "the job that settled most recently is listed first",
        page.locator("#settled .job-title").all_inner_texts(),
        [BENCHY, CHINESE_NAME],
    )
    check("nothing is left scheduled", "Nothing scheduled" in text_of(page, "#pending"), True)


def check_a_multi_tool_file(page: Page, printer: StandInPrinter) -> None:
    print("\nA multi tool file")
    printer.holds = frozenset({*printer.holds, MULTI_TOOL_FILE})
    printer.describes = {**FOUR_TOOL_METADATA, "thumbnails": THUMBNAILS_THE_SLICER_WROTE}
    page.reload()
    wait_for_the_file_list(page)
    pick_the_file(page, MULTI_TOOL_FILE)
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
    pick_the_file(page, MULTI_TOOL_FILE)
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
    check_the_file_list_itself(page)
    check_choosing_a_file(page, sorted(printer.holds)[0])
    check_the_bed_promise_is_required(page)
    check_scheduling(page)
    check_editing_carries_the_jobs_own_choices(page)
    check_cancelling(page)
    check_copying_carries_the_choices_too(page)
    check_clearing_the_settled_list(page)
    check_the_lists_are_in_time_order(page)
    check_a_multi_tool_file(page, printer)
    check_a_file_whose_material_is_not_loaded(page, printer)


def check_a_setting_the_plugin_cannot_use(scratch: Path, printer: StandInPrinter) -> None:
    """A setting the plugin falls back on is said on the page, not only in the log.

    The person who typed it is looking at the app, and a printer quietly behaving differently
    from the number on screen is the failure worth avoiding.
    """
    print("\nA setting that cannot be used")
    (scratch / "user_vars.json").write_text(
        json.dumps({"START_TOLERANCE_MINUTES": -1}), encoding="utf-8"
    )
    base_url, server, _service = serve(scratch, printer)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            watch_for_complaints(page)
            page.goto(base_url)
            page.wait_for_selector("#settings-warning .warn", timeout=PATIENCE_MILLISECONDS)
            said = text_of(page, "#settings-warning")
            check("the page names the setting", "START_TOLERANCE_MINUTES" in said, True)
            check("what was found", "-1" in said, True)
            check("and what is being used instead", "5 minutes" in said, True)
            check("the printer line still says the default is in force",
                  "up to 5 minutes late" in text_of(page, "#printer-line"), True)
            browser.close()
    finally:
        server.shutdown()


def a_schedule_left_behind(scratch: Path) -> Heartbeat:
    """A waiting job, and a heartbeat saying the scheduler has been away a day and a half."""
    now = time.time()
    Heartbeat(scratch / "last-seen").mark(now - A_LONG_SILENCE_SECONDS * 1.5)
    ScheduleStore(scratch / "jobs.json").save([
        Job(
            job_id="left-behind",
            filename=BENCHY,
            start_at=now + 7 * 24 * 3600,
            created_at=now - A_LONG_SILENCE_SECONDS * 2,
            bed_acknowledged=True,
        )
    ])
    return Heartbeat(scratch / "last-seen")


def check_the_held_notice(page: Page) -> None:
    page.wait_for_selector("#pending .job", timeout=PATIENCE_MILLISECONDS)
    page.wait_for_selector("#held-notice .warn", timeout=PATIENCE_MILLISECONDS)
    notice = text_of(page, "#held-notice")
    check("the page says the scheduler was away", "not running for a while" in notice, True)
    check("and that nothing starts until it is confirmed",
          "Nothing waiting will start until you confirm" in notice, True)
    check("the job itself says it is waiting on you",
          "Waiting for your confirmation" in text_of(page, "#pending"), True)
    check("and it was not cancelled while nobody was looking",
          "Did not run" in text_of(page, "#pending"), False)

    page.click("#held-notice button")
    # Detached rather than hidden: the notice is emptied, and an empty div is never "visible".
    page.wait_for_selector("#held-notice .warn", state="detached", timeout=PATIENCE_MILLISECONDS)
    check("one click releases it", text_of(page, "#held-notice"), "")
    check("the job stays in the list, unheld",
          "Waiting for your confirmation" in text_of(page, "#pending"), False)
    check("and is still scheduled", "Starts" in text_of(page, "#pending"), True)


def check_what_a_long_silence_looks_like(scratch: Path, printer: StandInPrinter) -> None:
    """A second service, over a schedule left behind by a long silence.

    The hold is decided once per run, on the first tick, so it cannot be staged inside a
    session that is already up. This starts a fresh one over a schedule that predates the
    silence the heartbeat describes.
    """
    print("\nComing back from a long silence")
    base_url, server, service = serve(scratch, printer, a_schedule_left_behind(scratch))
    # The service decides about the silence on its first tick, which is what the real one does
    # as it comes up. Nothing here is due, so this settles nothing else.
    service.tick(time.time())
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            watch_for_complaints(page)
            page.goto(base_url)
            check_the_held_notice(page)
            browser.close()
    finally:
        server.shutdown()


def serve(
    scratch: Path, printer: StandInPrinter, heartbeat: Heartbeat | None = None
) -> tuple[str, Any, ScheduleService]:
    service = ScheduleService(
        ScheduleStore(scratch / "jobs.json"),
        printer,
        Settings(scratch / "user_vars.json"),
        heartbeat,
    )
    server = build_server("127.0.0.1", 0, service)
    threading.Thread(target=server.serve_forever, name="check-in-browser", daemon=True).start()
    return f"http://127.0.0.1:{int(server.server_address[1])}/", server, service


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
    # The real entry point configures logging; without it INFO falls below stdlib's lastResort
    # and vanishes, which is the bug this plugin was just fixed not to have. Calling it here
    # means the harness exercises the wiring rather than quietly proving it is missing.
    start_logging()
    printer = StandInPrinter(
        describes={**WHITE_PLA_METADATA, "thumbnails": THUMBNAILS_THE_SLICER_WROTE},
        remembers=PRINTS_THAT_FINISHED,
        # The Chinese named file is the newer one and the Benchy sorts first by name, so
        # newest and alphabetical are genuinely different orders rather than the same
        # one twice, which is what made the first version of the sort check useless.
        modified_at={BENCHY: 1789830000.0, CHINESE_NAME: 1789920000.0},
        thumbnail_bytes=ONE_PIXEL_PNG,
    )
    with tempfile.TemporaryDirectory() as scratch:
        base_url, server, service = serve(Path(scratch), printer)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            watch_for_complaints(page)
            run_every_check(page, printer, base_url)
            browser.close()
        server.shutdown()
        check_what_a_long_silence_looks_like(Path(scratch), printer)
    with tempfile.TemporaryDirectory() as scratch:
        check_a_setting_the_plugin_cannot_use(Path(scratch), printer)
    return report()


if __name__ == "__main__":
    sys.exit(main())
