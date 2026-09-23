<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Changelog

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
