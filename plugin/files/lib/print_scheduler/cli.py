# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Arguments, startup and shutdown.

This is where the scheduler is armed: the tick thread started here is the only thing in the plugin
that can cause a print to begin.
"""

from __future__ import annotations

import argparse
import signal
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

from print_scheduler.moonraker import MoonrakerPrinter
from print_scheduler.server import SERVICE_NAME, SERVICE_VERSION, build_server
from print_scheduler.service import ScheduleService
from print_scheduler.store import ScheduleStore

# A job that takes nine hours does not need a tighter loop than this, and a loop that wakes rarely
# is a loop that survives a clock that jumps.
TICK_SECONDS = 20.0


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Every option here is one the manifest's service entry passes, and test_manifest.py asserts that
    correspondence in both directions, because a rename on one side alone is a service that fails to
    start on the printer and nowhere else.
    """
    parser = argparse.ArgumentParser(
        prog=SERVICE_NAME,
        description="Start a print at a time you choose.",
    )
    parser.add_argument("--bind", default="127.0.0.1", help="Address to listen on.")
    parser.add_argument("--port", type=int, default=8095, help="Port to listen on.")
    parser.add_argument(
        "--moonraker",
        default="http://127.0.0.1:7125",
        help="Base URL of the printer's Moonraker instance.",
    )
    parser.add_argument("--state", required=True, help="Path to the schedule's JSON file.")
    parser.add_argument(
        "--user-vars",
        required=True,
        help="Path to the daemon's user_vars.json for this plugin, re-read on every tick.",
    )
    return parser


def tick_once(service: ScheduleService) -> None:
    """One pass over the schedule, where a failure is reported rather than fatal."""
    try:
        service.tick(time.time())
    except Exception as problem:
        # A tick that raises must not take the loop with it. The printer being briefly odd is not a
        # reason for the scheduler to stop existing until someone notices and restarts it.
        print(f"{SERVICE_NAME} tick failed: {problem!r}", flush=True)


def keep_ticking(
    service: ScheduleService, stopping: threading.Event, interval_seconds: float = TICK_SECONDS
) -> None:
    """Settle the schedule now, and again every interval until asked to stop.

    Now first, deliberately: a job that came due while the printer was off should be dealt with as
    the service comes up rather than twenty seconds later.
    """
    while True:
        tick_once(service)
        if stopping.wait(interval_seconds):
            return


def main(argv: Sequence[str]) -> int:
    """Serve, and tick, until a signal asks us to stop."""
    arguments = build_argument_parser().parse_args(argv)
    service = ScheduleService(
        ScheduleStore(Path(arguments.state)),
        MoonrakerPrinter(arguments.moonraker),
        Path(arguments.user_vars),
    )
    server = build_server(arguments.bind, arguments.port, service)
    stopping = threading.Event()
    ticking = threading.Thread(
        target=keep_ticking, args=(service, stopping), name="print-scheduler-tick", daemon=True
    )

    def request_shutdown(signal_number: int, _frame: FrameType | None) -> None:
        # shutdown() blocks until serve_forever returns, and a signal handler runs on the very
        # thread that is inside serve_forever, so calling it here directly deadlocks. Hand it off.
        print(f"{SERVICE_NAME} stopping on signal {signal_number}", flush=True)
        stopping.set()
        threading.Thread(target=server.shutdown, name="print-scheduler-shutdown").start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    print(
        f"{SERVICE_NAME} {SERVICE_VERSION} listening on {arguments.bind}:{arguments.port}, "
        f"moonraker {arguments.moonraker}, schedule {arguments.state}",
        flush=True,
    )
    ticking.start()
    try:
        server.serve_forever()
    finally:
        stopping.set()
        server.server_close()
    return 0
