<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Print Scheduler

Pick a sliced file that is already on the printer, pick when it should start, and the printer starts
it for you at that time.

Most slicers can upload a file without printing it. This plugin is the other half: it decides when
that file runs. Upload in the evening, print at six, without getting up to press start.

## What works today

The plugin installs, starts, and serves its page at **Print scheduler** in the Bespok3d app, or at
`/print-scheduler/` on the printer's own web address. Scheduling is not built yet. The page shows an
empty list because there is nothing to list.

Everything below describes how the scheduler behaves once it starts a job, and it is written down
first on purpose: the rules are the feature, and changing one is a change to what the printer will
do while nobody is watching.

## The rules it applies before starting anything

A scheduled job reaches exactly one outcome, and every outcome is recorded with a reason. Nothing
fails silently and nothing waits forever.

| What the printer reports when the job comes due | What happens |
| --- | --- |
| Idle and ready, file present, on time | **Started** |
| Printing or paused | **Cancelled**, naming the file it was busy with. It does not wait |
| A finished print not yet cleared (`complete`) | **Cancelled**: the bed is presumed occupied |
| A cancelled print not yet cleared (`cancelled`) | **Cancelled**, same reason |
| Klipper in error | **Cancelled**, with the printer's own message |
| Klipper not ready, or Moonraker unreachable | Retried each tick, every attempt logged, until the tolerance runs out, then **cancelled** |
| Due time passed by more than the tolerance | **Cancelled**: missed. This is also what a job that came due while the printer was off meets at startup |
| The file is no longer on the printer | **Cancelled** |
| You cancelled it | **Cancelled** |

Two of those deserve saying out loud.

**A busy printer is never waited for.** If something else is running when your job comes due, the
job is cancelled there and then. Starting a print hours late, unattended, is a surprise that moves a
hot nozzle.

**A job whose time has passed does not start.** Powering the printer on should never begin a print
from last Tuesday.

## The bed

The scheduler cannot see the bed. It has one proxy and it is honest about being a proxy: a printer
that reports a finished or cancelled print is treated as having something on it, because clearing
the bed and dismissing the print on the screen are the same habit. Past that, whoever schedules a
job is the one promising the bed will be clear, and the page asks you to say so.

Nothing here detects a part, a skirt, a purge blob or a tool left on the plate.

## Time

Times are stored as an absolute instant, never as a wall clock plus a guess about which zone it
belongs to. Your browser resolves the time you pick using its own timezone, so a printer set to UTC
and a person set to something else still agree. The page shows the printer's own clock beside your
own, so a skew is visible rather than silent.

This matters more than it sounds. The printer this was written against runs on UTC.

## Settings

**Minutes a job may start late** (default 5). This is a retry budget, not permission to start late.
A tick is not instantaneous, Moonraker can be briefly unreachable while the printer comes up, and
Klipper can sit in startup for a few seconds. All three are worth another try or two. A printer that
is busy is never waited for, whatever this is set to.

## What it does not do yet

- **Recurring schedules.** One-shot jobs only.
- **Multi tool files.** On a tool changer the printer needs a tool assignment that this plugin does
  not yet know how to make, and making it wrong wastes the whole print. Those files are refused at
  schedule time, with the reason shown.
- **Print preferences.** On printers that expose them, a bed mesh or a timelapse can be chosen per
  job. That is coming, and until it lands a scheduled print inherits whatever the printer was last
  told.
