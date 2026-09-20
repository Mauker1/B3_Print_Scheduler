# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Arguments, startup and shutdown."""

from __future__ import annotations

import argparse
import signal
import threading
from collections.abc import Sequence
from types import FrameType

from print_scheduler.server import SERVICE_NAME, SERVICE_VERSION, build_server


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


def main(argv: Sequence[str]) -> int:
    """Serve until a signal asks us to stop."""
    arguments = build_argument_parser().parse_args(argv)
    server = build_server(arguments.bind, arguments.port)

    def request_shutdown(signal_number: int, _frame: FrameType | None) -> None:
        # shutdown() blocks until serve_forever returns, and a signal handler runs on the very
        # thread that is inside serve_forever, so calling it here directly deadlocks. Hand it off.
        print(f"{SERVICE_NAME} stopping on signal {signal_number}", flush=True)
        threading.Thread(target=server.shutdown, name="print-scheduler-shutdown").start()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    print(
        f"{SERVICE_NAME} {SERVICE_VERSION} listening on {arguments.bind}:{arguments.port}, "
        f"moonraker {arguments.moonraker}, state {arguments.state}",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0
