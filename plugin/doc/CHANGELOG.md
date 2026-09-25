<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Changelog

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
