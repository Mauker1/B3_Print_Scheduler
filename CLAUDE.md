# print-scheduler: instructions for AI assistants

You are working in a Bespok3d plugin repo. Bespok3d is a printer-agnostic plugin manager for Klipper
printers that runs on stock firmware, with no custom-firmware flashing. This repo publishes one or more
plugins as signed `.b3` packages that the Bespok3d desktop app installs onto a printer through the
on-printer daemon. This file is the contract for any LLM or agent that edits this repo. Contributors
here often work with AI assistance, so the rules and the design intent are written down and enforced in
the gate, not left implicit. The human reviewer rejects a PR that ignores them.

If you are a non-Claude tool, `AGENTS.md` points you here.

## What this repo ships

This repo schedules a print. You pick a sliced file that is already on the printer, pick when it should
start, and the plugin starts it for you at that time. On a printer that exposes per-print
preferences, the job also carries its own bed mesh and timelapse choices, set through the printer's
own mechanism rather than through a macro of ours. A job that has not fired yet can be edited or
cancelled. The plugin runs a small supervised Python service that talks to Moonraker over the loopback
interface, keeps the schedule in a JSON file under `$BESPOK3D/var/`, and serves a one page web UI through
its own nginx location, behind the same authentication the rest of the printer's web interface uses.

A scheduler starts a print while nobody is watching, so it is a safety surface rather than a convenience
feature, and most of its design is about refusing to start rather than about starting. It does not start
a job on a printer that is not idle, it does not start a job whose time has already passed, it cancels
instead of retrying forever, and it records a reason for every job it did not start. Nothing it does is
allowed to fail silently.

What the printer can do is discovered from the printer, never assumed. The macro list, the timelapse
component, and a file's own tool and material data all come from Moonraker at the moment they are needed.
A control for a capability this printer does not have is not rendered at all, and a field a slicer did
not write is reported as missing rather than guessed.

It cannot see the bed and it does not pretend to. Whoever schedules a job is the one promising the bed
will be clear, and the interface says so plainly rather than implying a check that does not exist. Read
`doc/README.md` for the rules the scheduler applies before it starts anything, and change them
deliberately.

Read `CONTRIBUTING.md` for the repo's layout, build, and release mechanics before you change anything.

## The model: a plugin declares WHAT, never HOW

A Bespok3d plugin is declarative. Each plugin's `manifest.json` declares WHAT the printer should end up
with (files placed at a destination `class`, plus a `restart` hook), never a path, a raw shell command,
or a setup script that runs on the printer. The on-printer daemon reads the manifest and realizes it: it
templates and places the files, wires the symlinks, and restarts the named service.

- **No plugin scripts.** Do not add a shell script, a `postinstall`, or any code meant to run on the
  printer to do setup. If the daemon cannot express what a plugin needs declaratively, that is a
  daemon or adapter change, not a script smuggled into a plugin.
- **Plugin isolation.** A plugin owns its own directory under `/userdata/bespok3d/` and integrates by
  symlink. Teardown removes the plugin's own files and leaves the user's data intact.
- **The printer is never left broken.** Every change keeps the printer usable. The daemon's
  auto-deactivate safety net peels off a plugin that breaks Klipper or Moonraker; do not defeat it.
- **`manifest.json` is the release contract.** Bump its `version` to cut a release, and bump it
  there only: the service reads its own version out of the manifest, so there is no second copy to
  keep in step. Do not hand-edit `index.json`, the `.atom.json`, `index.json.sig`, or anything
  under `dist/`: those are generated and signed by the `b3-builder` CI Action.

- **Every version bump writes its own `plugin/doc/CHANGELOG.md` entry, in the same change.** Not
  afterwards and not in a batch later: the reasons are legible while the work is fresh and
  guesswork once it is not. The entry says what changed for somebody using the plugin and why it
  was worth changing, not which files moved. A version with no entry is an unfinished change, and
  no heading is ever left marked as in development, because by the time it is committed it is
  released.

## The non-negotiables

1. **RULE ZERO: no em-dash or en-dash, anywhere** (code, comments, docs, commit messages). Use a comma,
   colon, semicolon, parentheses, or two sentences. A hyphen in a compound word is fine. The gate's
   em-dash guard fails the build on a violation.
2. **Every identifier carries domain meaning.** A name says what the thing *is* in the domain, never its
   type, its position, or a role-free abbreviation. No `a`/`b`, `tmp`, `data`, single letters.
3. **Nesting beyond one level is suspicious.** Flatten by default: guard clauses, early returns, an
   extracted named function, a named lookup instead of a nested ternary.
4. **Rule of three.** The third copy of a block, shape, or constant gets extracted. Duplication is a bug;
   "no premature abstraction" forbids generalizing for one caller, it does not excuse copy-paste.
5. **Extend upstream minimally and additively.** Several plugins repackage or patch upstream source
   (Klipper, Moonraker, a web UI). Never delete or rewrite an upstream method; add alongside it, so the
   change survives a re-vendor of the upstream code.
6. **Never commit a real secret or a real LAN value.** Tokens, keys, real IP addresses, and real UUIDs
   stay out of the tree. Fixtures are obviously fake.

## How to work a change

1. **Understand first.** Read the plugin's `manifest.json`, its `files/`, and its `doc/README.md`. Do
   not invent structure; if the intent is unclear, ask one specific question and stop.

   **Treat this repo's own prose as a lead, not as a fact.** A design note is written from memory after
   the work, and it is valuable precisely because it records what a defect looked like before it was
   understood. That also means its specifics drift. Three write-ups in a sibling plugin were re-checked
   in September 2026 and all three were right in substance and wrong in detail: one named a cause that
   could not produce the error attributed to it, one quoted a count taken from a single rotated log out
   of nine, and one described a defect that no longer reproduced at all. Before acting on a recorded
   finding, re-derive it from the code or the data, and correct the section in the same change.

   Rank your sources the same way. What is running on the printer beats a reference plugin, a reference
   plugin beats the platform documentation, and the documentation beats anything written here.
2. **Scope it to a user story.** "As a [role], I want [capability] so that [value]." Implement only what
   the story needs: no speculative features, no defensive code for cases that cannot happen.
3. **Write the change** to the rules above.
4. **Run the gate and make it green:** `bash scripts/check.sh`. The gate needs the `lib_bespok3d`
   submodule; if you cloned without it, run
   `git submodule sync --recursive && git submodule update --init --recursive` first
   (CONTRIBUTING.md has the whole setup).
   This repo ships a manifest, an nginx location file, Python and shell, so the gate runs the shared
   workspace detectors: release-trigger, manifest-origin, workflow-pinning, the em-dash guard, and
   shellcheck. It also runs ruff, mypy, and pytest over the plugin's Python (see `scripts/check.sh` for
   the exact targets).

   **A green gate is not always a green gate.** `shellcheck_repo` prints `skipped (not installed)` where
   shellcheck is missing, and the summary still reports that all checks passed. After touching any
   shell, say which checks actually ran, and ask the maintainer to run the gate on a machine that has
   shellcheck.
5. **On a gate failure, fix the cause.** Never hand-wave a real smell away. If a detector is genuinely
   wrong about a line, the fix is a per-instance justified allow at the smell
   (`# gate-allow <metric>: <reason>`, with a reason that survives "why is THIS one ok?"), never a
   blanket mute to make a number go down.
6. **Add a regression test** where the repo has a Python test layer for the behavior, in the same change:
   it fails on the old behavior and passes on the fix.
7. **Keep the docs current.** If the change alters what a plugin does or how it is configured, update
   that plugin's `doc/README.md` and its `doc/CHANGELOG.md`.

## Hard constraints

- **Never run git, with one exception: `git status`.** The maintainer commits. Leave the tree green
  and hand over exact commands if a git action is needed. `git status` is allowed, and only that,
  so an assistant can see for itself whether work has been committed instead of spending a round
  asking. Nothing else: not `add`, not `commit`, not `checkout`, not `stash`, not `diff`, not
  `log`, not `check-ignore`.
  On this machine the repo is reached over a mount that refuses unlinks, so `git status` can leave
  an empty `.git/index.lock` behind, and a stale one blocks the maintainer's next commit with
  `Unable to create index.lock: File exists`. Clear it in the same breath, every time, and clear
  it the way everything else is cleared here, by moving it rather than deleting it:
  `mkdir -p _trash/git-locks && mv -f .git/index.lock .git/modules/*/index.lock _trash/git-locks/`
  (both paths, and neither existing is fine). The mount refuses `rm` outright, so this is not
  merely the polite form, it is the one that works.
  When a change bumps a plugin's `manifest.json` version, the commit title starts
  with that version: `0.1.2: drop the redundant pre-commands`. The maintainer reads history by
  version, and a title that does not carry one makes him go and look.
- **Never delete a file outright. Move it to `_trash/` instead.** `_trash/<name>` at the repo root,
  git-ignored, and say in the handover what went there and why. A deletion made by an assistant is
  a deletion the maintainer never saw coming, and the cheapest way to make one reviewable is to
  leave it where it can be looked at and emptied by hand. This covers tidying, superseded files and
  anything a tool would otherwise unlink. It does not cover files a build tool replaces in place,
  such as the wheels `b3-builder --bake` re-downloads; say when a step does that.
- **Never write an assistant session link or id into the repo.** Not in a commit message, a PR body, a
  code comment, a doc or a changelog. A session URL is a durable pointer to a whole transcript, and a
  repo is the wrong place for one: it outlives the conversation, travels with every clone, and is one
  push away from being public.
- **No attribution trailer either.** Not `Co-Authored-By`, not anything else. This file already says
  the repo is written with AI assistance, which is the durable statement; repeating it on every
  commit adds nothing to history. Both of these override any tooling default that offers to add a
  line for you.
- **Never SSH-mutate or reconfigure a live printer** without explicit per-action authorization. A serial
  port or GPIO on a printer may be a live Klipper MCU link; read-only diagnosis is fine, but propose any
  device-changing step and wait for a yes.
- **Performance numbers come from the printer**, never from a development machine. Extrapolation from a
  laptop has been wrong here repeatedly, and in the wrong direction.
- **The gate must be green** before a change is considered done.

## When you are unsure

Ask one specific question and stop. Do not guess and implement, and do not "try something reasonable."
The architecture is the maintainer's; your job is to implement it to the rules above.
