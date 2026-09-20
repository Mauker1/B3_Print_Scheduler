<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Changelog

## 0.1.1 (in development)

- **Fixed: a print could be started on the wrong toolhead.** A file numbers its filaments by
  slicer slot and the printer numbers its hardware by toolhead, and the scheduler was letting
  the printer default slot 0 to toolhead 0. On a four toolhead machine that is right only by
  luck, and on its first real run it was wrong: a file wanting white PLA went to the toolhead
  holding ASA. Each slot is now matched to a toolhead by material, the choice is shown before
  you commit to it, and it is made again at the moment the job fires rather than carried over
  from when it was scheduled.
- A job whose material no free toolhead holds is cancelled rather than started, naming what is
  loaded.
- The file picker says *slot 0* rather than *T0*, because those were never the same thing.

## 0.1.0 (in development)

First version. Not released: no tag has been pushed and nothing has been published.

- Schedules a print. Pick a file the printer already has and a time, and it starts it for you.
  A pending job can be edited or cancelled, and any job can seed another.
- The file picker shows the toolheads, materials and colours a file uses, the slicer's estimate
  and the bed temperature, and warns when a job would land inside an earlier one's run.
- Times are chosen in your own timezone and sent as an exact instant, so a printer on UTC and a
  person who is not still agree. The page shows the printer's clock beside your own.

- The plugin installs, starts a supervised service on port 8095, and serves its own page through its
  own nginx location.
- Every endpoint that reads or writes the schedule sits behind Moonraker's `/access/user`, so the
  scheduler is exactly as reachable as the rest of the printer's web interface and no more.
- `/health` is deliberately not behind it, because an endpoint that needs a working Moonraker to
  answer is useless for diagnosing a broken one.
- Every decision about whether to start is recorded with a reason, and `plugin/doc/README.md`
  lists them all. Nothing fails silently and nothing waits forever.
- A start is confirmed before it is believed. A job stays in `starting` until the printer is seen
  to act on it, and a start the printer accepted and then did not run is caught and recorded
  rather than reported as a success.
- A started job keeps the printer's own id for the print, so what became of it can be looked up
  in the printer's job history rather than tracked, guessed at, or copied.
- On a printer that offers it, a job's bed mesh and timelapse choices are carried by
  `SDCARD_PRINT_FILE_WITH_PARAMETERS`, the same command the printer's own interface uses, so a
  scheduled print behaves like one started by hand. Elsewhere, Moonraker's own print start is used
  and those choices have nothing to act on.
