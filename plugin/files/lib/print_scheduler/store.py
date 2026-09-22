# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The schedule on disk.

A printer loses power mid-write far more often than a laptop does, and it loses it at exactly the
moment a job is being settled. So the file is replaced atomically, and a file that cannot be read
is set aside under a new name rather than silently treated as an empty schedule: losing the
schedule is recoverable, not knowing it was lost is not.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from print_scheduler.jobs import Job, job_from_dict

_log = logging.getLogger("bespok3d.print_scheduler")

SCHEDULE_FORMAT_VERSION = 1


class ScheduleStore:
    """Reads and writes the whole schedule as one file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[Job]:
        """Return the stored jobs, or an empty list if there are none or the file is unreadable."""
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return [job_from_dict(entry) for entry in payload["jobs"]]
        except (OSError, ValueError, KeyError, TypeError) as unreadable:
            self._set_aside(unreadable)
            return []

    def save(self, jobs: Sequence[Job]) -> None:
        """Replace the schedule file atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": SCHEDULE_FORMAT_VERSION,
            "jobs": [job.to_dict() for job in jobs],
        }
        being_written = self.path.with_name(self.path.name + ".writing")
        with being_written.open("w", encoding="utf-8") as writing:
            # ensure_ascii=False keeps a Chinese filename readable in the file rather than escaped.
            json.dump(payload, writing, indent=2, ensure_ascii=False)
            writing.flush()
            os.fsync(writing.fileno())
        being_written.replace(self.path)

    def _set_aside(self, problem: Exception) -> None:
        spoiled = self.path.with_name(self.path.name + ".unreadable")
        try:
            self.path.replace(spoiled)
        except OSError as immovable:
            _log.error(
                "schedule at %s is unreadable (%s) and immovable (%s)",
                self.path, problem, immovable,
            )
            return
        _log.error(
            "schedule at %s could not be read (%s); moved to %s", self.path, problem, spoiled
        )
