<!--
SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Contributing

Thanks for working on a Bespok3d plugin. Bespok3d is a printer-agnostic plugin manager for Klipper
printers that runs on stock firmware, with no custom-firmware flashing. This repo publishes the
`print-scheduler` plugin as a signed `.b3` package that the desktop app installs onto a printer through
the on-printer daemon.

The plugin lets you pick a sliced file that is already on the printer and a time for it to start, and
starts it for you at that time. It refuses far more often than it starts, and every refusal is recorded
with a reason.

## Before you write code

Read [CLAUDE.md](CLAUDE.md). It is the contract for changes here: the plugin model (a plugin declares
WHAT the printer should end up with, never a script that runs on the printer), the non-negotiables
(RULE ZERO: no em-dash or en-dash; every identifier carries domain meaning; nesting beyond one level
is suspicious; rule of three; extend upstream additively; never commit a real secret or LAN value),
and the working procedure. If you use an AI assistant (many contributors do), point it at that file;
`AGENTS.md` sends non-Claude tools there too.

**Writing a plugin of your own?** The full plugin documentation lives with the build tool:
[Bespok3d/b3-builder/doc](https://github.com/Bespok3d/b3-builder/tree/main/doc). It covers the
anatomy of a plugin, its manifest and its `.b3` package, the six kinds of plugin, signing, the
release Action, channels, local testing and publishing.

## Quick start: from clone to pull request

Six steps. A change is ready for review when all six are done and the gate is green.

### 1. Install the tools

| Tool | Why | macOS | Linux |
| --- | --- | --- | --- |
| git 2.23 or newer | `git switch` and cloning submodules in one pass | preinstalled, or `brew install git` | `sudo apt install git` |
| Python 3.11 | the printer's runtime; the gate pins it and refuses to run on another version | `brew install python@3.11`, or `brew install uv` | install `uv` (`curl -LsSf https://astral.sh/uv/install.sh \| sh`) and the gate provisions 3.11 itself |
| Node 20 or newer | runs the shared detectors (the em-dash guard, workflow pinning) | `brew install node` | `nvm install 20`; distro packages are usually older than 20 |
| shellcheck | lints this repo's shell scripts | `brew install shellcheck` | `sudo apt install shellcheck` |
| GitHub CLI (optional) | opens the pull request from the terminal | `brew install gh` | see [cli.github.com](https://cli.github.com) |

You also need an SSH key on your GitHub account (`ssh -T git@github.com` should greet you by name).
This repo is private, and so is `Bespok3d/lib_bespok3d`, which it carries as a submodule. Ask the
maintainer for read access to both before you clone: access to one does not imply access to the other,
because this repo lives in a personal namespace and the shared gate library lives in the Bespok3d org.

The gate builds its own Python tool venv under `lib_bespok3d/tooling/` the first time you run it.
Nothing is installed into your system Python.

**This plugin has no runtime dependencies.** It is written against the Python standard library only, so
there is nothing to `pip install` before the tests will run, no `requirements.txt`, no baked wheels, and
no arm64 wheel to go looking for. Keep it that way: a dependency here has to earn a venv on the printer,
and so far none has.

### 2. Clone with the submodule

`lib_bespok3d` carries the shared gate helpers and the workspace detectors, and nothing in this repo
checks out green without it. Changes are made on `dev`, so clone that branch:

```sh
git clone --recurse-submodules --branch dev git@github.com:Mauker1/B3_Print_Scheduler.git
cd B3_Print_Scheduler
```

Already cloned, or seeing `lib_bespok3d/tooling/gate-lib.sh: No such file or directory`? Run this
once from the repo root:

```sh
git submodule sync --recursive && git submodule update --init --recursive
```

The submodule is pinned to an absolute SSH URL, `git@github.com:Bespok3d/lib_bespok3d.git`, rather
than to the relative `../lib_bespok3d.git` that sibling repos use. A relative URL resolves against this
repo's origin, and this repo is not in the Bespok3d org, so it would look for the gate library in the
wrong namespace and fail with a confusing "Repository not found".

The practical consequence is that you should clone this repo over SSH. Cloning over HTTPS still fetches
the submodule over SSH and stops on a permission error. The fix is either to use SSH, or to tell git to
rewrite the protocol for you:

```sh
git config --global url."https://github.com/".insteadOf "git@github.com:"
```

### 3. Branch off `dev`

```sh
git switch dev && git pull
git switch -c <short-name-for-your-change>
```

### 4. Make the change

Only what your user story needs. Keep `plugin/doc/README.md` and `plugin/doc/CHANGELOG.md` current when
behavior or config changes, and add a regression test in the same change. The rules the reviewer applies
are in [CLAUDE.md](CLAUDE.md), and RULE ZERO (no em-dash, no en-dash) covers your commit message too.

Two things specific to this plugin are easy to get wrong:

- **Every URL the page emits must be relative.** nginx publishes the plugin under a prefix, strips it
  before proxying, and never tells the service what it was. An absolute path such as a `Location: /`
  redirect sends the user to the printer dashboard, and it tests perfectly against the service port.
- **What the printer can do is read from the printer.** Macro names, the timelapse component, and a
  file's tool and material data are fetched from Moonraker when they are needed. Do not hardcode a macro
  name, and do not render a control for a capability that was not found.

### 5. Run the gate until it is green

```sh
bash scripts/check.sh
```

It runs the shared workspace detectors (release-trigger, manifest-origin, workflow pinning, the em-dash
guard, shellcheck) plus ruff, mypy and pytest over the plugin's Python. On a failure, fix the cause. If a
detector is genuinely wrong about one line, justify that one line at the smell
(`# gate-allow <metric>: <reason>`); never mute a check to make a number go down.

**Check that shellcheck actually ran.** Where it is not installed, `shellcheck_repo` prints
`skipped (not installed)` and the summary still says all checks passed, with a check count that quietly
differs from the one the maintainer sees. If you touched any shell, confirm the line in the output.

### 6. Commit, push and open the pull request

```sh
git commit -am "<what changed and why>"
git push -u origin <your-branch>
gh pr create --base dev --fill      # or open the link that git push prints
```

The pull request targets `dev`. CI runs this same `scripts/check.sh` on it, so a red gate is not
reviewable and blocks the release.

## Tests

Tests live in `plugin/tests/` and run against a stand-in Moonraker and an injected clock, so no printer
is needed and no test waits on real time. A test describes a situation as data: what the printer
reported, what the file's metadata said, and what time it is.

Three kinds of test carry most of the weight here.

- **Manifest tests**, for the promises that only fail after an install: every placed file exists, every
  service argument naming a plugin file points at a real one, the declared port is the one the service
  is told to bind, and every path in the router is a path the nginx location actually serves.
- **Decision tests**, one per outcome in the table in `plugin/doc/README.md`. A job either starts or is
  cancelled with a reason, and there is a test for each reason, including the two that matter most: a
  job that came due while the printer was off, and a job that came due while the printer was busy.
- **Page tests**, which are cheap assertions on the rendered HTML and stand in for a browser the gate
  does not have. The page must emit no absolute path of its own, and no form control may share a name
  with a property of `HTMLFormElement`. Both of those shipped as real bugs in a sibling plugin and both
  passed every server-side test.

A fix ships with a regression test in the same change: one that fails on the old behaviour and passes on
the new.

## Checking the page in a browser

The gate covers the plugin's Python. It cannot cover whether a button does anything, and in a
sibling plugin that gap shipped two bugs that every server-side test passed.

```sh
pip install playwright && playwright install chromium
python3 scripts/check-in-browser.py
```

Most managed Python installations now refuse to install into themselves, so if that first line is
rejected, put it in a virtualenv instead. `.venv` at the repo root is already ignored:

```sh
python3 -m venv .venv
.venv/bin/pip install playwright
.venv/bin/playwright install chromium
.venv/bin/python scripts/check-in-browser.py
```

It serves the real page against a stand-in printer and drives it in headless Chromium: that the
file list, the tool display and the estimate are on screen before anything is clicked, that
scheduling is refused until a file, a time and the promise about the bed are all there, that
scheduling and cancelling actually change the lists, and that a multi tool file explains itself
and stays refused. It fails on a console error too.

Run it after touching the page. Nothing runs it for you, and it is not in the gate because a
browser download is a lot to ask of someone working on a printer plugin. The two rules it taught a
sibling plugin are in the suite instead, as cheap assertions on the rendered HTML: no form control
may share a name with a property of HTMLFormElement, and the page may not emit an absolute path.
That second one cannot be checked by this harness, which serves the page at the root where a
relative URL and an absolute one both happen to work.

## Building locally

The builder is installed into its own prefix. Do not use `npx b3-builder`: it resolves to whatever copy
npm cached earlier, which silently builds against an out of date manifest schema. And do not run a plain
`npm install` here: with no `package.json` in this repo it installs into the nearest one above it.

```sh
npm install --prefix ~/.b3-builder github:Bespok3d/b3-builder
~/.b3-builder/node_modules/.bin/b3-builder build \
  --source ./plugin --out dist --atom-repo Mauker1/B3_Print_Scheduler
```

No `--bake` is needed while the plugin has no Python dependencies. Check what you produced before
installing it:

```sh
unzip -l dist/print-scheduler-<version>.b3
unzip -p dist/print-scheduler-<version>.b3 manifest.json | jq '.files[].path'
```

Nothing may be in the archive that is not in `files[]`: the daemon refuses a package with an unlisted
member, so a stray `.DS_Store` is a failed install, not a cosmetic problem.

Install it for testing by dragging the `.b3` onto the Bespok3d desktop app window. Nothing needs to be
published to test it. Bump the patch version on every build you test, so you are never wondering which
one is installed.

## Release

Bump `version` in `plugin/manifest.json` and push a tag naming this plugin and that exact number:

```sh
git tag plugin-print-scheduler-v<version>
git push origin <branch> --tags
```

A push to a branch publishes nothing. CI runs the `b3-builder` Action, which packs and signs the `.b3`,
cuts a release, and registers the atom in the org index. Do not hand-edit `index.json`, the
`.atom.json`, `index.json.sig`, or anything under `dist/`: those are generated and signed by CI.

## What a good change looks like

- Scoped to a clear user story; only what the story needs.
- Follows the rules in CLAUDE.md; passes the gate green.
- Ships a regression test in the same change.
- Keeps `plugin/doc/README.md` and `plugin/doc/CHANGELOG.md` current when it changes behavior or config.

## Constraints

- The maintainer owns git history and releases; submit changes as a pull request against `dev`.
- Never SSH-mutate or reconfigure a live printer without explicit authorization; a serial port on a
  printer may be a live Klipper MCU link. Read-only diagnosis is fine.
- This plugin starts prints. Anything that widens what it will start, or narrows what it refuses, is a
  change to a safety surface and needs the reasoning written down in the pull request, not just the
  code.

## Signing off your work

Every commit must carry a `Signed-off-by` line. It is your statement that you wrote the change, or
that you otherwise have the right to contribute it, under the terms of the Developer Certificate of
Origin (<https://developercertificate.org/>). Git writes the line for you:

```sh
git commit -s -m "your message"
```

A pull request whose commits are not signed off cannot be merged.

## Licence

This repository is under the GNU Affero General Public License, version 3 or later. The full text is in
[LICENSE](LICENSE).

By contributing you agree that your contribution is licensed under those same terms. You keep the
copyright in what you write. There is no copyright assignment and no contributor licence agreement to
sign.
