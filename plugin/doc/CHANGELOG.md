<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Changelog

## 0.1.16

- **The busy refusal says what happened and stops.** It used to add that a busy printer is
  never waited for and why, which is a policy rather than anything about your job, and it is
  already in this document. A reason is read by somebody wanting to know why their print did
  not run, not to be argued with.
- **The missed refusal loses its last sentence** for the same reason. It still says how late the
  job was and what the tolerance is, because those are about your job and they are the two
  numbers worth knowing.

## 0.1.15

- **The scheduler now asks before acting on promises made before a long silence.** It can stop
  running without anybody choosing it: the Bespok3d daemon deactivates a plugin that breaks
  Klipper or Moonraker so the printer keeps working, a printer sits switched off for a
  fortnight, or somebody uninstalls it and the schedule survives because the platform keeps a
  plugin's data on purpose. In all three it comes back holding prints nobody has looked at
  since. If it was away for more than a day, everything still waiting is held, the page says so,
  and one button releases all of them.
- A held job is **not** started, and not cancelled either. Letting it quietly expire as missed
  would answer the question on your behalf. Once released it meets the ordinary rules again, so
  one whose moment has gone is then cancelled and says why.
- An upgrade takes seconds, so it never triggers this. Neither does a first install, nor an
  upgrade from a version that never recorded being alive.
- **The version shown on the page and at `/health` is now read from the manifest** rather than
  written down a second time in the service. There was never a mismatch, because the gate
  checked for one, but there was a second thing to remember at every release.

## 0.1.14

- **The schedule moved to a data directory the daemon knows about**, from
  `$BESPOK3D/var/print-scheduler/` to `$BESPOK3D/var/lib/print-scheduler/`, declared with
  `install.data`. The old location was a directory the service created at runtime and the
  daemon had never heard of.
- This does not change what an uninstall leaves behind, and cannot: declared data directories
  are exactly the ones the platform preserves, so that plugins do not throw away your work. It
  means the directory is the plugin's on the record rather than one nobody is tracking.
- **The documentation now says plainly that uninstalling does not cancel scheduled prints.**
  Cancel them in the plugin first if you want them gone.

## 0.1.13

- **Both job lists are ordered by time rather than by when the job was typed.** Scheduled is
  soonest first, so the list says what happens next; settled is most recently settled first.
  Previously a job added later but due sooner sat at the bottom of the queue, and the settled
  list was in reverse creation order, which looks like newest first often enough to be trusted
  and quietly is not.
- **Job rows carry the file's preview**, in both lists. An ordered list of near-identical
  filenames is still hard to read; a picture fixes what ordering alone does not.

## 0.1.12

- **Editing a job now loads that job's own levelling and timelapse choices.** The form used to
  keep whatever it was last set to, so editing the time on a print that levels the bed could
  silently stop it levelling, with nothing on screen to say so. *Schedule another like this*
  had the same fault, where it mattered more.
- **The setting for how many finished jobs to keep no longer affects the projection.** It was
  deciding both how many rows you see and how much history the levelling aware estimate had to
  work with, so turning the list down to a couple of rows quietly disabled the estimate. The
  scheduler now keeps enough of its own history whatever the list is set to.

## 0.1.11

- **A job is projected against prints that made the same levelling choice.** Levelling costs
  about six and a half minutes on the machine this was measured on, which is most of the
  difference between a two minute setup and a ten minute one, and averaging the two produced a
  number almost no print was near. A job that asks for levelling is now measured against prints
  that levelled, and one that does not against prints that did not.
- The labels come from this scheduler's own settled jobs joined to the printer's history,
  because **the printer records what ran and never what it was asked for**. Prints started by
  hand carry no label; they still count towards the general figure, they are just not
  partitioned. A printer that does not offer the choice at all keeps the general figure, which
  is correct rather than unfortunate.
- **Three prints of a kind before that kind is measured on its own.** One sample would collapse
  the range to a single number and the page would state a confident time from a single print,
  which is the overconfidence the range was built to remove. Below that it falls back to the
  general figure, so a fresh install behaves exactly as it did.
- **A scheduled job now shows what it asked the printer for**, levelling and timelapse, which
  was invisible once a job was scheduled. It is also the reason two rows can carry very
  different setup times, and a reader should not have to work that out.
- The overlap warning now assumes the slowest setup **of the earlier job's own kind** rather
  than the slowest of any kind.
- *Finished jobs to keep* now says in its own hint that those records are what carries the
  levelling labels, so setting it to 0 projects every job from one figure again.

## 0.1.10

- **Settled jobs can be removed, one at a time or all at once.** Clear the list means clear
  everything *settled*, and nothing scheduled is ever touched: that single property is what
  makes the button safe to press without reading it, and there is a test named after it.
- The clearing takes two clicks, and the button says what the second one will do: *Really
  remove 12?*. It disarms itself after six seconds. No browser dialog, which would block the
  harness this page is tested with and is heavier than a list of finished jobs deserves.
- **A new setting, Finished jobs to keep**, default 25. The list is trimmed to that many
  whenever the schedule is written, so it does not grow forever without anyone clicking
  anything. Jobs that have not run are never trimmed, whatever the cap says. Zero is a real
  answer, meaning keep nothing once a job has settled. It is not a required setting, so an
  upgrade does not interrogate anyone.
- Removing a job removes **our** record of what the scheduler decided. The printer's own
  history of what it printed is untouched and was always the authority on that.
- **Fixed: a POST whose handler ignored its body broke the next request on that connection.**
  An unread body stays in a kept-alive socket, so the following request was parsed starting
  from the leftover bytes and came back as `501 Unsupported method ('{}GET')`. The body is now
  read once before any route runs, so no handler can reintroduce it by not caring about its
  own body.
- **The sort control's arrow no longer sits against the edge of its box.** Chrome draws a
  native dropdown arrow against the border box and ignores `padding-right`, so padding
  moved the text and left the arrow where it was. The native one is off now and the arrow
  is drawn in CSS, in `currentColor`, so it sits where the search field's own clear button
  sits and is right in both light and dark.

## 0.1.9

- **The file list can be sorted.** Newest first stays the default, with oldest first, last
  printed, and name either way round beside it. Every order breaks its ties on the name, so the
  same list always comes out the same way and nothing shuffles between refreshes. A file nobody
  has printed sorts to the bottom of *last printed*, where it belongs.
- Sorting happens in the page rather than on the printer, so it is instant and costs the
  printer nothing. The choice is not remembered between visits; newest first is the right
  default often enough that it did not seem worth storing.

## 0.1.8

- **The file picker is a list rather than a dropdown.** An alphabetical `<select>` put the file
  you sliced a minute ago wherever its name happened to fall, which on a printer holding a
  hundred and fifty of them is nowhere useful. Files are now listed newest first, with the
  slicer's thumbnail, when the file was sliced, when it last printed, and how long it takes.
- **A file nobody has ever printed says so**, rather than leaving a blank that reads as missing
  data. On a page that starts prints unattended, a file that has never run is worth knowing
  about.
- **A search box**, and at most forty rows drawn at once, so a long list stays quick on a
  printer's own hardware and search is the way into it.
- All of that costs **one extra request**: a single directory read returns the metadata for
  every file at once. Files kept in subfolders are listed with a name and a date rather than
  hidden, since the listing reaches into them and the description does not.
- **Thumbnails are passed through this plugin** rather than linked straight at Moonraker.
  Linking would mean an absolute URL to a host that is only Moonraker's on a printer, and the
  service also runs on a laptop pointed at one; passing them through keeps every URL the page
  emits relative, and keeps the picture behind the same authentication as the schedule.
- The authentication subrequest now forwards the cookie as well as the header, because an
  `<img>` cannot set a header. A browser logged into Moonraker authenticates the same way for
  an image as for a fetch, and on a trusted client nothing changes.

## 0.1.7

- **A file's material, colour and temperature are read on printers that are not the one this
  was written against.** Moonraker writes a standard set of metadata fields for any slicer, and
  the Snapmaker firmware adds a parallel set under different names with more detail per slot.
  Every field the file picker shows was being read from the second set only, so on a mainline
  Klipper the picker said *this file does not say what material it needs* about a file that
  says so perfectly clearly. Each field now prefers the detailed name and falls back to
  Moonraker's own.
- The preference order is deliberate, not tidiness. On the U1 the plural `filament_colors` is
  the spools currently in the machine rather than the file's colours, so reading it first would
  compare the machine against itself. It is only read where the singular field does not exist,
  which is where it is the file's own.
- On a printer that reports no per slot extrusion, the slot count comes from whatever per slot
  lists the file carries, and a slot weighing nothing is treated as unused, weight being the
  only usage figure such a printer offers.
- Proven on a real second printer, an Ender 2 Pro Max on mainline Klipper, Moonraker and
  OrcaSlicer, whose metadata is now a test fixture. A job scheduled there started on time
  through Moonraker's own print start, was seen to take, and had its outcome read back from
  that printer's history.
- **A slot no longer claims there is no toolhead.** On a printer that does not report what is
  loaded there is a toolhead; what there is not is a choice to make, and *(no toolhead)* read as
  a machine missing one. A toolhead is named only where one was chosen. Where a choice failed,
  the refusal already says so in its own words below.
- A multi slot file on such a printer says once, quietly, that the file's own tool numbering is
  used as it was sliced, which is the one case where a reader might reasonably wonder.

## 0.1.6

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

## 0.1.5

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

## 0.1.4

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

## 0.1.3

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

## 0.1.2

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

## 0.1.1

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

## 0.1.0

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
