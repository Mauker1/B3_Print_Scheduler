# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Arguments, startup and shutdown.

This is where the scheduler is armed: the tick thread started here is the only thing in the plugin
that can cause a print to begin.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from types import FrameType
from typing import TextIO

from print_scheduler.heartbeat import Heartbeat
from print_scheduler.moonraker import MoonrakerPrinter
from print_scheduler.server import SERVICE_NAME, SERVICE_VERSION, build_server
from print_scheduler.service import ScheduleService
from print_scheduler.settings import Settings
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


# The name Bespok3d's own plugins log under. Ours is a service in its own process rather than
# code running inside Klipper, so nothing configures logging for it and this module, the entry
# point rather than the library, attaches the handler.
_log = logging.getLogger("bespok3d.print_scheduler")

# Matching the shared log's own layout, so that the day a service plugin has a supported route
# into it, the lines already look like the ones beside them.
LOG_FORMAT = "%(asctime)s %(name)s: %(message)s"


def start_logging(stream: TextIO | None = None) -> None:
    """Send our log to stdout, which the daemon already captures per plugin.

    Deliberately not to `/userdata/bespok3d/var/logs/bespok3d.log`. Klipper's process appends to
    that file continuously, and a second unrelated writer with no locking is how interleaved
    lines happen. It also sits in no directory this plugin declared, and its path is one
    printer's rather than every printer's. Our stdout lands in `var/log/print-scheduler.log`,
    which the daemon set up for us, and which is where the other service plugins' output goes.

    Levels are the part worth having either way: a setting that cannot be used is a warning
    rather than a line indistinguishable from chatter.
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    ours = logging.getLogger("bespok3d")
    ours.handlers.clear()
    ours.addHandler(handler)
    ours.setLevel(logging.INFO)
    # Ours alone. Attaching to the root logger would adopt every library's output, and
    # propagating would hand our lines to a root handler nobody in this process configured.
    ours.propagate = False


def tick_once(service: ScheduleService) -> None:
    """One pass over the schedule, where a failure is reported rather than fatal."""
    try:
        service.tick(time.time())
    except Exception as problem:
        # A tick that raises must not take the loop with it. The printer being briefly odd is not a
        # reason for the scheduler to stop existing until someone notices and restarts it.
        _log.exception("tick failed: %r", problem)


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
    start_logging()
    service = ScheduleService(
        ScheduleStore(Path(arguments.state)),
        MoonrakerPrinter(arguments.moonraker),
        Settings(Path(arguments.user_vars)),
        # Beside the schedule rather than given its own argument: it is the same data
        # directory, it lives and dies with the schedule it describes, and a second path to
        # get wrong in the manifest buys nothing.
        Heartbeat(Path(arguments.state).with_name("last-seen")),
    )
    server = build_server(arguments.bind, arguments.port, service)
    stopping = threading.Event()
    ticking = threading.Thread(
        target=keep_ticking, args=(service, stopping), name="print-scheduler-tick", daemon=True
    )

    def request_shutdown(signal_number: int, _frame: FrameType | None) -> None:
        # shutdown() blocks until serve_forever returns, and a signal handler runs on the very
        # thread that is inside serve_forever, so calling it here directly deadlocks. Hand it off.
        _log.info("stopping on signal %s", signal_number)
        stopping.set()
        threading.Thread(target=server.shutdown, name="print-scheduler-shutdown").start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    _log.info(
        "%s %s listening on %s:%s, moonraker %s, schedule %s",
        SERVICE_NAME,
        SERVICE_VERSION,
        arguments.bind,
        arguments.port,
        arguments.moonraker,
        arguments.state,
    )
    ticking.start()
    try:
        server.serve_forever()
    finally:
        stopping.set()
        server.server_close()
    return 0
