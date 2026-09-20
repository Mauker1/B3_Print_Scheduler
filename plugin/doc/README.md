<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Print Scheduler

Pick a sliced file that is already on the printer, pick when it should start, and the printer starts
it for you at that time.

Most slicers can upload a file without printing it. This plugin is the other half: it decides when
that file runs. Upload in the evening, print at six, without getting up to press start.

## How it works

Open **Print scheduler** in the Bespok3d app, or `/print-scheduler/` on the printer's own web
address. Pick a file the printer already has, pick when it should start, promise the bed will be
clear, and it is scheduled. A job that has not fired yet can be edited or cancelled, and any job
can be used as the starting point for another.

Picking a file shows what it will use: which toolheads, which material and colour in each, how
long the slicer thinks it will take, and what it will heat the bed to. If an earlier job is
projected to still be printing when this one is due, the page says so while you are still looking
at it, rather than letting it become a cancellation at six in the morning.

The page needs JavaScript. It is a printer's web interface, and so is everything else on the
machine.

## The rules it applies before starting anything

A scheduled job reaches exactly one outcome, and every outcome is recorded with a reason. Nothing
fails silently and nothing waits forever. The rules are checked in the order below, and the order
is part of the design: lateness is checked before the printer is, so a job whose moment has passed
does not start however healthy the printer looks.

| What is true when the job comes due | What happens |
| --- | --- |
| Its time passed by more than the tolerance | **Cancelled**: missed. This is also what a job that came due while the printer was off meets on the way back up |
| The filename cannot be passed to the printer | **Cancelled**, naming the character and why |
| Moonraker did not answer | **Retried**, every attempt recorded, until the tolerance runs out |
| Klipper is still starting up | **Retried**, same budget |
| Klipper is shut down or in error | **Cancelled**, with Klipper's own message. It will not fix itself, and waiting would only replace the real reason with "missed" |
| A print is running or paused | **Cancelled**, naming the file it was busy with. It does not wait |
| A finished or cancelled print has not been dismissed | **Cancelled**: the bed is presumed occupied |
| The print reports an error | **Cancelled**, with the printer's message |
| Something other than a print is running | **Retried**: a calibration started by hand is a matter of minutes |
| The file is no longer on the printer | **Cancelled** |
| Another scheduled job started in the same tick | **Cancelled** as busy. At most one job starts per tick |
| The printer refused the start | **Cancelled**, carrying the printer's own refusal verbatim |
| The printer accepted the start and then did not run it | **Cancelled**: the start did not take |
| None of the above | **Started**, once the printer is seen to act on it |
| You cancelled it | **Cancelled**, recorded as your decision rather than as a refusal |

Three of those deserve saying out loud.

**A busy printer is never waited for.** If a print is running when your job comes due, the job is
cancelled there and then. Starting a print hours late, unattended, is a surprise that moves a hot
nozzle.

**A job whose time has passed does not start.** Powering the printer on should never begin a print
from last Tuesday.

**Waiting is only for things that fix themselves.** An unreachable Moonraker and a Klipper still
booting get the retry budget. A Klipper that has shut down does not, because the tolerance would
expire and the recorded reason would be "missed" when the truth was an MCU error.

## Started means the printer was seen to act on it

Telling the printer to start and being told "ok" is not the same as the print running. A job
sits in **starting** until the printer is actually seen to have taken it, either as an entry in
its own job history or as the file it is running right now. Only then does it become
**started**. If a minute passes with no sign of it, the job is cancelled and says so, rather
than sitting there claiming a success nobody would question until morning.

## Did the print work?

That question belongs to the printer, and the page answers it by asking the printer rather than
by keeping its own opinion. A started job records the printer's own id for the print, and the
outcome shown beside it, completed or cancelled or whatever the printer calls it, is read from
the printer's job history when you look. So the row tells you two things with two owners: what
the scheduler did, and what the printer says became of it.

The scheduler never watches a print to its end. That is fifteen hours of polling to duplicate a
record the printer already keeps, and it would mean reporting on a power cut the scheduler had
nothing to do with. If the printer no longer remembers the print, the row says so.

## Filenames the printer cannot take

Two characters are refused, when you schedule the job rather than when it runs:

- **`#`**, because the printer's gcode parser treats it as the start of a comment and the name
  would be truncated.
- **`"`**, because the name is passed as a quoted parameter and a double quote would end it early.

Spaces are fine, and so are Chinese filenames; both were checked against the printer rather than
assumed.

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
- **Thumbnails.** The file picker shows filament colours rather than a preview of the model.
