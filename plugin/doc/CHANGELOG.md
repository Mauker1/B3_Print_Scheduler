<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Changelog

## 0.1.6 (in development)

- **The projected finish is a range, not a time.** Twenty runs off the printer show setup time
  arriving in two clusters, one around two or three minutes and one around ten, with nothing in
  between. A median of that is a value almost no print is near, and it showed: one projection
  was six minutes out on a job lasting five and a half, while the range around it contained the
  truth. The page now says *should finish between 6:03:55 and 6:10:24*, and collapses back to a
  single time when the prints it measured from agree.
- The overlap warning now assumes the slowest setup the printer has managed rather than a
  typical one. A warning about a collision that might not happen costs a glance; a collision
  nobody warned about costs a print.

- **Colour now chooses by nearness rather than by exact match**, the same way the slicer does
  on *Upload and print*. Found on the hardware before it cost a print: a file asking for
  `#5343B7` against a spool holding `#5E43B7`, a typo's worth apart, matched nothing and fell
  back to the lowest numbered toolhead of the right material, which was a navy about ninety
  units away rather than the purple eleven units away. Material is still never traded for
  colour.
- **The mapping is chosen as a whole rather than a slot at a time.** Choosing greedily, slot 0
  can take the toolhead slot 1 needed far more while having an almost as good second choice of
  its own. The total across every slot is what is minimised now, searched exhaustively, which
  at these sizes is better than being clever. Ties break on the lowest toolhead number so the
  same file always maps the same way.
- A colour that could not be matched exactly names the slot, the toolhead, and both values,
  because a near miss and a wrong spool used to read identically.
- Not enough toolheads of one material now says how many the file needs and how many the
  printer has, rather than reporting the first slot that found nowhere to go.

## 0.1.5 (in development)

- **Multi tool files can be scheduled.** They were refused because a wrong tool assignment wastes
  the whole print, and until 0.1.1 the scheduler had no way to make a right one. It has since,
  and the printer's own source settles the rest: the start command hands its parameters straight
  to `SET_PRINT_TASK_PARAMETERS`, which rebuilds the toolhead map from `MAP_TABLE` and then marks
  exactly those toolheads used. Every slot the file extrudes from gets its own toolhead, listed
  on the page before you commit to it.
- Two slots wanting a material only one toolhead holds is refused, naming what is loaded, rather
  than doubling two slots onto one nozzle.
- **Fixed: filenames were refused on printers that could have printed them.** A name containing
  `#` or `"` is unusable in a gcode command, which is how this printer starts a print. A printer
  without that command is sent its filename as a URL parameter instead and takes both characters
  without complaint. The refusal now asks the printer first, at scheduling and again at starting,
  so a printer that answers differently later cancels the job with a reason rather than sending
  a name its parser would truncate.

## 0.1.4 (in development)

- **The setup time is quoted as a range when the printer varies.** It was being shown as a single
  figure, which reads as a promise: *about 10m of setup*. It is a median over prints made under
  different conditions, and on the machine this was measured on those conditions span 459 to 614
  seconds. Levelling costs time, and so does a bed cooling from the last print's temperature to
  this one's. A job now says *about 8m to 10m of setup, then 26s of printing*, and collapses back
  to one figure when the ends of the range would read the same anyway.
- The extremes are trimmed once there are five measurements or more, so one print somebody
  paused for an hour no longer widens the range either. Below five there is nothing to trim.
- **Corrected in the docs: levelling and timelapse do cost time.** An earlier note said they did
  not. That was inferred from two uncontrolled runs agreeing to within fifteen seconds, and a
  third run with both preferences off came in 139 seconds faster. The measurement stands, the
  claim did not.
- The projected finish and the overlap warning still use the middle of the range rather than the
  worst case, so the clock time on the page is one number rather than two.

## 0.1.3 (in development)

- **Fixed: a projected finish that ignored the printer's own setup time.** The page was quoting
  the slicer's estimate as a finish time. The slicer measures printing; it knows nothing about
  heating a bed, probing a mesh, picking up a toolhead or purging, and this printer spends eight
  to ten minutes on that before the first extrusion. A 26 second print was projected to be done
  in 26 seconds and took ten and a half minutes.
- The setup time is now measured from the printer's own job history, as the median of what the
  last few finished prints spent not printing, and re-read whenever the page refreshes. It is
  never a number written into the source, because it belongs to a machine rather than to this
  plugin. A scheduled job says what it is made of: *about 10m of setup, then 26s of printing*.
- A printer with no finished print to measure is told apart from one that takes no time. It gets
  the slicer estimate labelled *not counting the printer's setup* rather than a borrowed figure.
- **The overlap warning inherits the same correction**, which is the half of this that mattered:
  two jobs an hour apart can collide once setup is counted, and that warning used to arrive only
  after the second job had been cancelled as busy.
- Prints cancelled during the start routine are left out of the measurement. They record a
  printing time of exactly zero, so counting them would have read a 32 second cancellation as a
  32 second setup and dragged the figure to a third of the truth.
- The schedule endpoint reads the printer's history once per request instead of twice.

## 0.1.2 (in development)

- **Fixed: one cancelled print stopped every job scheduled after it.** The printer reports a
  finished or cancelled print until somebody dismisses it on the screen, and the scheduler was
  reading that as "there is something on the bed". It is a latch, not a reading, so the first
  print anyone cancelled blocked the scheduler indefinitely. The state is now judged by when it
  arrived: a print that ended before you scheduled the job is one you could see when you promised
  the bed would be clear, so the promise covers it, and only a print that ended afterwards stops
  the job. Editing a job re-dates the promise.
- A job now records when its promise was made, and the tick reads the printer's history once and
  uses it both to date the bed and to confirm a start.
- **Dropped two dead commands from the start.** `SET_PRINT_EXTRUDER_MAP` and
  `SET_PRINT_USED_EXTRUDERS` were being sent ahead of the start. The printer's own source settles
  what happens next: `SDCARD_PRINT_FILE_WITH_PARAMETERS` calls `SET_PRINT_TASK_PARAMETERS` with
  the same arguments, and that resets both the toolhead map and the used list unconditionally
  before applying its own `MAP_TABLE`. The two commands were overwritten a moment after being
  sent, which is worse than useless: it is dead code that reads as live, and the next person to
  debug a bad toolhead would have started there. The start is one command now.

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
