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

The file list is newest first, because the file you want is almost always the one you just
sliced. Each row carries the slicer's own thumbnail, when the file was sliced, when it last
printed, and how long it takes, and a file nobody has ever printed says so rather than leaving a
blank. There is a search box and a sort control, and a long list draws its first forty rows and asks
you to narrow it. Newest first is the default; oldest first, last printed, and name either way
round are there when you want them, and each breaks its ties on the name so the order never
shuffles under you.

Picking a file shows what it will use: which toolheads, which material and colour in each, how
long the slicer thinks the printing takes, and what it will heat the bed to. A scheduled job then
shows the whole thing, setup time included, because the two are not the same and only one of them
is in the file. If an earlier job is projected to still be printing when this one is due, the page
says so while you are still looking at it, rather than letting it become a cancellation at six in
the morning.

The page needs JavaScript. It is a printer's web interface, and so is everything else on the
machine.

## Which toolhead it uses

A gcode file numbers its filaments by slicer slot. Your printer numbers its hardware by
toolhead. They are not the same thing, and there is no sensible default: left alone, a
printer sends slot 0 to toolhead 0, which on a four toolhead machine is right only by luck.

So the scheduler chooses. Each slot goes to a toolhead loaded with the material that slot
needs, and the page shows the choice before you commit to it: *slot 0 PLA on T2*. A file using
several slots gets several toolheads, one each, and the page lists every one of them. If
nothing loaded has the right material for a slot, or two slots want a material only one
toolhead holds, nothing starts and the page says what is loaded instead.

Colour decides between toolheads of the same material, and it does so by nearness rather than
by exact match, the same way the slicer does when you press *Upload and print*. A colour one
digit out is a typo, not a different filament, and it should still find its spool. When the
nearest is not the same, the page says so and prints anyway, showing both values, because
knowing that #5343B7 went to a toolhead holding #5E43B7 is a different fact from knowing that
purple went to navy.

Material is never traded away for colour. If nothing loaded has the right material for a slot,
nothing starts.

On a printer that does not report what each toolhead holds, there is no choice to make: the page
lists the file's slots without naming toolheads, and the file's own tool numbering runs as it was
sliced.

The mapping is chosen as a whole rather than a slot at a time. Taking each slot's own best
toolhead in turn is the obvious approach and it is wrong: slot 0 can take the toolhead slot 1
needed far more, when slot 0 had an almost as good second choice. What is minimised is the
total across every slot.

The choice is made again at the moment the job fires, never carried over from when it was
scheduled. You can set a job at ten at night and change a spool at midnight.

## How long it will take

A slicer's estimate is how long the printing takes. It is not how long the job takes, because
before the first line of plastic your printer heats a bed, heats a nozzle, probes a mesh, picks up
a toolhead and purges. On the machine this was written against that is eight to ten minutes,
which made the old projection for a short print wrong by a factor of twenty three.

So the page adds it, and the number is your printer's, not anybody else's. It is read out of the
printer's own job history and re-read every time the page refreshes. A job says what it is made
of:

> about 3m to 10m of setup, then 26s of printing
> should finish between 6:03:55 and 6:10:24

**Each job is measured against prints like itself.** Levelling costs about six and a half
minutes on the printer this was written against, so a job that asks for it and a job that does
not have nothing to learn from each other's timings. Where there are at least three prints of
the relevant kind, that job is projected from those; otherwise from everything. Which is why two
jobs scheduled on the same page can honestly carry very different numbers, and why each row says
what it asked the printer for.

Only prints this scheduler started carry that label, because the printer's history records what
ran and never what it was asked for. Prints you started by hand still count towards the general
figure. They simply cannot be sorted into one pile or the other.

**Why a range and not a time.** On the printer this was written against, setup time does not
have a middle. It arrives in two clusters, one around two or three minutes and one around ten,
and what decides which is not yet understood. A median between them is a value almost no print
is near: one such projection was six minutes out on a job that lasted five and a half. The range
around it contained the truth. So the page publishes what it actually knows, which is both ends.

When the prints it measured from agree, both ends read the same and it collapses back to one
time. A printer with a consistent start routine sees a single figure and a single clock time.

A printer that has not finished a print yet has nothing to measure at all. It gets the slicer
estimate alone, labelled *not counting the printer's setup*, rather than a number from somebody
else's machine.

The overlap warning is the one place that deliberately assumes the worst, using the slowest
setup the printer has managed. A warning about a collision that might not happen costs you a
glance; a collision nobody warned about costs a print.

That matters more than it sounds at six in the morning: two jobs an hour apart can still collide
once the setup time is counted, and a warning that only appears afterwards is not a warning.

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
| A print finished or was cancelled after you scheduled this job, and has not been dismissed | **Cancelled**: something may be on the bed that you could not have known about when you promised it would be clear. One that was already showing when you scheduled the job does not block it |
| The print reports an error | **Cancelled**, with the printer's message |
| Something other than a print is running | **Retried**: a calibration started by hand is a matter of minutes |
| The file is no longer on the printer | **Cancelled** |
| No free toolhead holds the material the file needs | **Cancelled**, naming what is loaded |
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

The scheduler cannot see the bed. Whoever schedules a job is the one promising it will be clear,
and the page asks you to say so. What the scheduler adds on top is narrow, and worth stating
precisely, because the obvious version of it is wrong.

A printer that reports a finished or cancelled print may well have something on it, because
clearing the bed and dismissing the print on the screen are the same habit. But that state is a
latch, not a reading: this printer keeps saying `cancelled` until someone dismisses it, for hours
or for days, and treating it as a fact would mean one cancelled print silently stops every job you
schedule afterwards.

So the state is judged by when it arrived. A print that ended **before** you scheduled the job is
something you could see when you made the promise, and the promise covers it. A print that ended
**after** is something you could not have known about, and it wins: the job is cancelled and says
so. Editing a job re-asks for the promise, which re-dates it, so a job you touch after clearing the
bed is unblocked by the act of touching it.

When the printer reports an undismissed print but gives no usable end time for it, there is nothing
to compare against and the job is cancelled, saying exactly that.

Nothing here detects a part, a skirt, a purge blob or a tool left on the plate.

## Time

Times are stored as an absolute instant, never as a wall clock plus a guess about which zone it
belongs to. Your browser resolves the time you pick using its own timezone, so a printer set to UTC
and a person set to something else still agree. The page shows the printer's own clock beside your
own, so a skew is visible rather than silent.

This matters more than it sounds. The printer this was written against runs on UTC.

## The list of settled jobs

A job that has run or been cancelled stays in the list so you can see what happened. Each one
can be removed, and the whole settled list can be cleared in two clicks, the second of which
says how many will go.

Clearing means clearing what has **settled**. Nothing you have scheduled is ever removed by it,
whatever else is going on, because a list of promises about the future is the one thing this
page must not quietly forget.

The list also trims itself to the newest few, so it does not grow forever without anyone
clicking anything. How many it keeps is a setting.

What goes is our record of what the scheduler decided. The printer's own history of what it
printed is untouched, and was always the authority on that.

## Settings

**Minutes a job may start late** (default 5). This is a retry budget, not permission to start late.
A tick is not instantaneous, Moonraker can be briefly unreachable while the printer comes up, and
Klipper can sit in startup for a few seconds. All three are worth another try or two. A printer that
is busy is never waited for, whatever this is set to.

A value this plugin cannot use, such as a negative number or a word where a number belongs,
falls back to the default rather than stopping anything. It does not do so silently: the page
says which setting was ignored, what it was set to, and what is being used instead, and the
same is recorded once in the log. Fix the setting and the warning goes away on its own, without
restarting anything.

Zero is allowed and means exactly what it says: no lateness at all is tolerated. Because the
scheduler looks at the schedule every twenty seconds rather than continuously, a job is almost
never seen at the precise second it is due, so zero cancels nearly every job as missed. It is a
real setting rather than a mistake, and it is the quickest way to see what a missed job looks
like, but it is not a way to make prints start punctually. A negative number is not an answer to
anything and reads as the default.

**Finished jobs to keep** (default 25). The settled list is trimmed to this many, newest first,
whenever the schedule changes. Jobs that have not run yet are never trimmed. Zero keeps nothing
once a job has settled. It only changes how many rows you see: the scheduler keeps enough
history of its own to tell a levelled print's setup time from an unlevelled one whatever this is
set to.

## Coming back after a long time away

The scheduler can stop running without you deciding that it should. The Bespok3d daemon
deactivates a plugin that breaks Klipper or Moonraker, so that your printer keeps working. A
printer gets switched off for a fortnight. The plugin gets uninstalled and the schedule outlives
it, for the reason in the next section.

In all of those it comes back holding prints nobody has looked at since, and starting one of
those unattended is the thing this plugin is most careful about. So if it was away for more than
a day, everything still waiting is held: the page says the scheduler was not running for a
while, and one button confirms that the schedule still says what you want. Nothing starts until
you press it.

A held job is not cancelled either, because letting it quietly expire would answer the question
for you. Once released it meets the ordinary rules again, so one whose moment has already gone
is then cancelled and tells you so.

An upgrade takes seconds, so it never triggers this, and neither does a fresh install.

## Uninstalling does not cancel scheduled prints

Uninstalling removes the plugin, its settings and its web page. It does not remove your
schedule. The schedule lives in a data directory, and the Bespok3d daemon preserves those across
an uninstall on purpose, so that a plugin cannot throw away your data. Reinstall, and the
schedule is there again.

If you want a scheduled print gone, cancel it in the plugin before uninstalling. If you
reinstall much later, the section above applies: everything waiting is held until you confirm
it.

## What has been tested, and where

Everything here is exercised against a Snapmaker U1, which is the machine it was written on, and
every printer specific thing it does is asked for rather than assumed: whether the printer offers
the parameterised start command, what each toolhead has loaded, and which filenames its gcode
parser can take. A printer that answers no to all three gets Moonraker's own print start, no
toolhead map, no preference toggles, and no filename refusals it does not need.

That path has now run on a second machine, an Ender 2 Pro Max on mainline Klipper and Moonraker,
end to end: a job was scheduled, it started on time through Moonraker's own print start, the
scheduler saw the printer take it, and the outcome came back from that printer's history. No
toolhead was chosen and no preferences were offered, both correctly, because that machine reports
neither.

One thing there is still only tested on a Snapmaker U1: **installing the package**. The service
was run directly against that printer rather than installed on it, since Bespok3d does not run
there. The install classes are mapped to real paths by each printer's own adapter, so a second
adapter remains a thing this plugin has never met.

## What it does not do yet

- **Recurring schedules.** One-shot jobs only.
- **Choosing the toolheads yourself.** The mapping is worked out from what is loaded and shown
  to you, but it cannot be overridden. When two slots want a material whose colours are not
  loaded, that choice is arbitrary and you can only cancel, not correct it.
