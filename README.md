<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# B3 Print Scheduler

A [Bespok3d](https://github.com/Bespok3d) plugin that starts a print at a time you choose.

Pick a sliced file that is already on the printer, pick when it should start, and the printer starts
it for you. Upload in the evening, print at six.

The scheduler refuses far more often than it starts. It will not start a job on a printer that is
not idle, it will not start a job whose time has already passed, and it records a reason for every
job it did not start. It cannot see the bed, and it does not pretend to.

Bespok3d runs on stock Klipper firmware, so nothing here needs a custom firmware flash. The plugin
ships as a signed `.b3` package that the Bespok3d desktop app installs onto the printer.

## Status

Early. The manifest, the nginx location, the gate and the test layer are in place, and the plugin
installs and serves its page. Scheduling itself is not built yet.

## Layout

```text
plugin/                 the plugin, and the unit b3-builder packs
  manifest.json         the release contract; bumping its version cuts a release
  files/                the payload, mirroring where things land on the printer
    bin/                the entry point the manifest names
    lib/print_scheduler/ the service itself
    etc/nginx/locations/ the plugin's own nginx location file
  doc/                  user-facing docs, linked from the catalog entry
  tests/                runs against a stand-in Moonraker and an injected clock
scripts/check.sh        the gate
lib_bespok3d/           submodule: shared gate helpers and workspace detectors
```

## Build

```sh
npm install --prefix ~/.b3-builder github:Bespok3d/b3-builder
~/.b3-builder/node_modules/.bin/b3-builder build \
  --source ./plugin --out dist --atom-repo Mauker1/B3_Print_Scheduler
```

Install it for testing by dragging the resulting `.b3` onto the Bespok3d desktop app window. Nothing
needs to be published to test it.

## The gate

```sh
bash scripts/check.sh
```

Green before anything is done. It needs the `lib_bespok3d` submodule, so clone with
`--recurse-submodules`.

## Contributing

[CONTRIBUTING.md](CONTRIBUTING.md) has the full setup, the release path and the licence terms.
[CLAUDE.md](CLAUDE.md) is the contract for changes, for humans and for AI assistants alike.

## Licence

GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE).
