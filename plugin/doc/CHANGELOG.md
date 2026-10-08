<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Changelog

## 0.6.1

- **A map offered on a held row now says when its spool is short**, before you accept it. A job
  waiting for its map to be confirmed, or held because a spool changed, offered the scheduler's
  map without checking how much was left on it, so it could put a long print onto a nearly empty
  spool with nothing on screen to say so.
- **Confirming a map records the grams each slot needs**, so a job scheduled before 0.6.0 warns
  about its spools from then on, like one scheduled today.

## 0.6.0

A warning when a spool has less left on it than a job needs.

- **On the form and on the waiting row.** Where the printer can say how much is left, a slot whose
  toolhead has less than the file needs says so: *T2 has about 32 g left, and this print needs
  about 40 g from it.* Two slots on one toolhead are added together. It follows the toolhead you
  pick, and the row follows the map the job will start on.
- **A warning only.** Nothing is refused or held because of it. If the printer refills or pauses
  for a new spool, that is what happens.
- **No new dependency.** It reads Spoolman through Moonraker, and which spool is in which toolhead
  from the tool macros' `spool_id`, the setup Mainsail and Fluidd describe, or from AFC's lanes. A
  printer without them sees no warning and nothing else changes, and is never asked for what it
  does not have.
- Jobs scheduled before 0.6.0 did not record the grams each slot needs, so their rows never show
  the warning.

## 0.5.1

- **Saving empties the form.** After scheduling or editing a job, the file stayed chosen with its
  details on screen, and once those details included a toolhead to pick for each slot it looked
  as if the job were still being edited. The form now starts fresh after every save. "Schedule
  another like this" on the job's row is the way back to the same file.

## 0.5.0

Choose the toolheads yourself, and a job now starts only on a map somebody saw.

- **A toolhead to choose beside every slot.** The form offers every toolhead with what it holds,
  with the scheduler's choice already picked. Change any one and the whole map is yours; **Back to
  automatic** undoes it. Edit and "Schedule another like this" carry it, and the row says
  "toolheads chosen by you".
- **A different material, if you say so.** Putting a slot on a toolhead that holds another material
  asks first, per slot, naming both, and says the file's own temperatures will be used. For when
  the printer's record of what is loaded is wrong.
- **Several slots on one toolhead**, for two of the file's colours from the same spool. The form
  says they will come out the same.
- **A file the scheduler cannot map can now be scheduled**, by choosing its toolheads yourself.
- **A job whose toolheads changed since it was scheduled is held, not started.** What each
  toolhead held is recorded when you schedule, and compared when the job comes due. If a spool was
  swapped, emptied or recoloured, the row says exactly what changed and offers the map that works
  now, with **Start it now with this map**. **This replaces two behaviours**: a job whose material
  had left the machine used to be cancelled, and a job whose spools had moved used to be mapped
  again without asking. Neither happens now without you.
- **Jobs scheduled before 0.5.0 are held as soon as it runs**, on a printer that reports what is
  loaded, because nobody ever saw the map they would start on. Each row offers it, with **This map
  is right**. On a printer that does not report what is loaded, nothing changes for them.
- **Downgrading keeps the schedule.** A job held for one of the new reasons is stored so that 0.4.1
  reads it as held for the nearest reason it knows, rather than setting the whole schedule aside as
  unreadable, which is what 0.4.1 does with a reason it has never seen.

## 0.4.1

- **A held job no longer claims a start and a finish it will not make.** Its row said "Starts" at
  its scheduled time and projected a finish from it, both untrue once the job is waiting for you:
  it starts when you answer. It now says when it was due and that it is held, and shows no finish
  until it has started.
- **A held job no longer takes part in the warning about jobs running into each other**, on either
  side. Its finish was being worked out from a start that was not going to happen.

## 0.4.0

A job no longer starts while the printer still shows a finished print. It waits for you.

- **Held, not started, whenever that print ended.** Until now a print that was already showing when
  you scheduled was taken to be covered by your promise that the bed would be clear, and the job
  started anyway. Now the job is held on its own row until you say the bed is clear. **Some prints
  that used to start will now wait for you, on purpose**: it is better not to start a print than to
  start one onto a part.
- **"I've cleared the bed, start it now", on the job itself.** It starts the job there and then,
  however late. If something would pass by itself, another print running or the printer not
  answering, nothing starts and the job keeps waiting, with the reason on screen. If something
  never will, the file gone or the material not loaded, the job is cancelled with that reason.
- **Dismissing on the printer's screen does not start a held job**, so nothing begins while you are
  standing at the printer doing something else. The row keeps saying why the job did not start.
- **The button to clear a finished print moved into the form**, beside the promise about the bed,
  where the question is being asked. It is no longer at the top of the page.

## 0.3.0

Clear a finished print without walking over to the printer.

- **"I've cleared the bed", beside the line that says the bed is presumed occupied.** When a print
  has finished or been cancelled and not been dismissed, the page now offers the way out as well as
  naming the problem. It clears the print on the printer, as Mainsail's own Clear button does.
- **It asks the printer again before it does anything.** The command behind it would stop a print
  that is running, so the page's copy of the state is never trusted: the printer is asked when you
  press the button, and if a print has started since, nothing is sent and the page tells you why.
  A print that ended in an error is never offered.
- **Two actions refused anything but JSON only by accident, and now refuse it by design.**
  Clearing the settled list and releasing the jobs held after a long silence both accepted a plain
  text request, which is the kind another website can send through your browser without it asking
  first. Every action is now checked in one place, and every one is tested, so one added later
  cannot forget.

## 0.2.1

Two things the first people to read it in Portuguese asked for.

- **The printer's line says what it is.** "Idle and ready. A job may start up to 2 minutes late."
  now begins with "Printer status:", because a sentence at the top of a page with nothing
  introducing it leaves you working out what it is about.
- **The language picker moved to the foot of the page**, beside the version. It is a control
  somebody uses once, and beside the title it was competing with the thing they came to do.

## 0.2.0

The page speaks Portuguese, and says which language it is written in.

- **Brazilian Portuguese**, alongside English. Set the language in the plugin's settings, and
  anyone reading the page can choose a different one for their own browser without changing what
  the printer serves everybody else.
- **The reason a job did not run is no longer stored as a sentence.** It is kept as what happened
  plus the details, and made into words when you read it, so a job that settled last week reads in
  the language you are reading today and a reason reworded in a later version reaches the rows that
  settled before it.
- **The page declares its language to a screen reader**, which it never did: it always claimed to
  be English. That one attribute decides how every word on it is pronounced.
- **The title finally says what the page is for.** A line under it, in your language, where there
  was nothing before.
- The printer's own words, your filenames, and the log stay exactly as they were. Bespok3d's own
  tile, install dialog and setting labels stay English, because the platform has no way to
  translate them.

## 0.1.21

First public release.

Everything before this was built and tested privately, so there is no earlier version anybody
could have upgraded from. What the plugin does is in the README rather than repeated here.
