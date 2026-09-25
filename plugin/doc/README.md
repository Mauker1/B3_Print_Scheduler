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
fails silently. The one thing that waits for as long as it takes is a job held for you to answer,
and the page says so on that job's own row. The rules are checked in the order below, and the order
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
| The printer shows a print that finished or was cancelled and has not been dismissed | **Held for you**, whenever that print ended. It waits on its own row until you say the bed is clear; see [The bed](#the-bed) |
| The print reports an error | **Cancelled**, with the printer's message |
| Something other than a print is running | **Retried**: a calibration started by hand is a matter of minutes |
| The file is no longer on the printer | **Cancelled** |
| No free toolhead holds the material the file needs | **Cancelled**, naming what is loaded |
| Another scheduled job started in the same tick | **Cancelled** as busy. At most one job starts per tick |
| The printer refused the start | **Cancelled**, carrying the printer's own refusal verbatim |
| The printer accepted the start and then did not run it | **Cancelled**: the start did not take |
| None of the above | **Started**, once the printer is seen to act on it |
| You cancelled it | **Cancelled**, recorded as your decision rather than as a refusal |

Four of those deserve saying out loud.

**A job never starts over a print the printer still shows.** It is held and asks you, because the
scheduler cannot see the bed, and not starting a print is always better than starting one onto a
part.

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

The scheduler cannot see the bed. Whoever schedules a job promises it will be clear, and the page
asks you to say so. What the scheduler adds on top is one rule, and it errs on the side of not
printing.

A printer that shows a finished or cancelled print may well have something on it, because clearing
the bed and dismissing the print are the same habit. So **a job never starts while the printer
shows one.** When it comes due and the printer still shows a finished or cancelled print, the job is
held, not started and not cancelled, however long ago that print ended and whether or not it was
showing when you scheduled. The promise you gave on the form was about a moment that had not come
yet, and a printer still showing a print at that moment is evidence against it.

This is a change from before 0.4.0, when a print already showing as you scheduled was taken to be
covered by your promise. That rule existed only because a finished print never clears itself, and
refusing on it could stop the scheduler until somebody walked over to the printer. There is now a
way out from the page, so the scheduler asks instead of taking the promise on trust. **Some prints
that used to start will now wait for you, on purpose.** The habit that avoids it is dismissing the
print, on the printer or on the page, when you take the part off.

Nothing here detects a part, a skirt, a purge blob or a tool left on the plate.

### When you schedule

If the printer shows a finished print when you schedule, the form says so, beside the promise
about the bed, with a button: **I've cleared the bed**. Pressing it dismisses the print on the
printer the way Mainsail's Clear button does, so the job will not be held when it comes due.

The command behind that button also stops a print that is running, so it is guarded more carefully
than anything else the page does. It is only offered for a finished or cancelled print on a printer
that is ready. When you press it, the plugin asks the printer again, right then, rather than trusting
what the page showed, because the page can be a few seconds out of date and a print somebody has
just started from the touchscreen must not be the thing it stops. If the answer has changed,
nothing is sent and the page says why. Checking and sending happen under the same lock the
scheduler holds while it starts prints, so it cannot start one in between either. A print that
ended in an error is never offered: that one deserves somebody walking over to the printer.

### When a job is held

Its row says why: **Waiting for you: the printer still shows a finished print**, with **I've
cleared the bed, start it now**. Pressing that starts the job there and then, however late it is,
because you asked. Every other check still applies, afresh:

- if something would pass by itself, such as another print running, the printer not answering or
  Klipper not ready, **nothing starts, the job stays held**, and the page says why so you can try
  again;
- if something never will, such as the file having gone or no toolhead holding the material, the
  job is cancelled with that reason, exactly as it would be at a normal start.

**Dismissing the print on the printer's own screen does not start a held job.** Somebody dismissing
a print in the evening is not asking for the morning's job to begin while they load something else.
The row keeps saying why the job did not start, and when, and offers **The bed is clear, start it
now** instead. Cancelling works as it always has.

A job held for the bed is not the same as the jobs held after a long silence, and the two are
answered separately: confirming the schedule after a silence never starts a job that is waiting
for the bed.

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

**Language** (default `en`). Which language this plugin's page starts in: `en` for English,
`pt-BR` for Brazilian Portuguese. It is the starting point for everybody who opens the page, and
anybody reading it can choose differently for their own browser without changing this. A tag
nothing on the printer can serve falls back to English and says so, the same way an unusable
number does.

## What is in your language, and what is not

**The page is.** Everything this plugin writes, including the reason a job did not run, is stored
as a key rather than as a sentence and made into words when somebody reads it. So a job that was
cancelled last week reads in whichever language you are reading today, and a reason we reword in a
later version reaches the rows that settled before it.

**The printer's own words are not.** Klipper's state, Moonraker's refusal, your filenames: those
pass through exactly as the machine said them. Translating a machine's message makes it
impossible to search for and useless in a bug report, which is the opposite of what a message like
that is for.

**The log is not.** It is always English. A log is read by whoever is debugging, who is often not
the person who owns the printer, and a Portuguese traceback in a bug report helps nobody.

**Bespok3d's own surfaces are not.** The plugin's tile, its install dialog, the labels and hints
on these settings: the platform has no way to offer a translation of any of them, so they are
English whatever this is set to. That is a limit of the platform rather than a decision here, and
it is the one place where the product is only partly in your language.

**Choosing for yourself.** When the plugin ships more than one language, the page carries a small
picker beside its title. It remembers your choice in that browser alone, on that one printer, and
nothing about it is ever sent to the printer or to anybody else. Its first entry, *Follow the
printer*, gives up your choice again and goes back to the setting above, so a choice you made once
is never a thing you cannot undo. Clearing your browser's site data has the same effect.

**Another language** is a JSON file of the same keys next to the two that are there, under
`files/lib/print_scheduler/locale/`, and a pull request. Nothing else changes: the page finds
whatever is installed. A key nobody translated shows in English rather than as a gap, and a
translation with a typo in a placeholder falls back to English rather than stopping anything,
which is deliberate: a mistake in a sentence must never be able to stop a print from being
scheduled.

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

## Reaching the page from Mainsail's sidebar

The plugin's own tile in the Bespok3d app links to the page, and `/print-scheduler/` works in any
browser on the printer's address. If you use **Mainsail**, you can also give it an entry in
Mainsail's own sidebar, next to Status and History.

**Mainsail only.** Fluidd has no equivalent: adding a side tab is its issue #472, open, with no
implementation yet. A Fluidd user reaches the page by its address or from the Bespok3d app.

**This plugin will not create that entry for you, deliberately.** Mainsail keeps its custom
navigation in one file, `navi.json`, in a `.theme` folder inside your printer's config directory.
That file is yours. A plugin writing to it would overwrite entries you added, fight any other
plugin that wanted one, and leave its own line behind after being uninstalled. So it is a snippet
to paste rather than something that happens to you.

Create or edit `.theme/navi.json` in your config directory:

```json
[
  {
    "title": "Print Scheduler",
    "href": "/print-scheduler/",
    "target": "_self",
    "position": 45,
    "icon": "M12,20A8,8 0 0,0 20,12A8,8 0 0,0 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20M12,2A10,10 0 0,1 22,12A10,10 0 0,1 12,22C6.47,22 2,17.5 2,12A10,10 0 0,1 12,2M12.5,7V12.25L17,14.92L16.25,16.15L11,13V7H12.5Z"
  }
]
```

**If you already have a `navi.json`, add this object to the array you have.** Replacing the file
loses whatever was in it.

`position` decides where the entry sits. Mainsail's own items occupy 10 to 90, so 45 puts this
one in the middle of them; move it up or down to taste. The `icon` is SVG path data, and this one
is a clock.

**One thing to expect.** With `"target": "_self"` the link leaves Mainsail, so Mainsail's sidebar
goes with it and the browser's back button brings it back. That is not a fault in the entry: the
scheduler is a separate page rather than a view inside Mainsail, which is the same reason it needs
no Mainsail version to work. If you would rather keep Mainsail where it is, use
`"target": "_blank"` and the page opens in a new tab instead.

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
