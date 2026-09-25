# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scheduler page.

Three rules govern everything here, and the first two shipped as real defects in a sibling plugin
while every server-side test passed.

Every URL this page emits is relative. nginx publishes the plugin under a prefix and strips it
before proxying, so the service never learns what the browser called it. An absolute path here
points at the printer dashboard instead of at us, and it tests perfectly against the service port.

No form control may share a name with a property of HTMLFormElement. This page uses no form at all
and gives no control a `name`, which sidesteps it entirely; the test stays as a guard for whoever
adds the first one.

Nothing from the printer is ever put into innerHTML. Filenames come from a slicer and a person, and
one of the files on the machine this was written against is called `顶盖前靴_TPU_13m5s.gcode`.
Everything is set with textContent.
"""

from __future__ import annotations

import json
from typing import Any

from print_scheduler.messages import ENGLISH, catalogue, known_tags

# Raw, so that a backslash in here means what JavaScript means by it rather than what Python
# does. The page holds a regular expression and two control characters, and Python would either
# eat them or warn about them on the way past.
PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="__LANGUAGE__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Print Scheduler</title>
<style>
:root { color-scheme: light dark; --line: rgba(128,128,128,0.32); --quiet: rgba(128,128,128,0.9); }
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  margin: 0 auto; max-width: 46rem; padding: 1.25rem 1rem 3rem; line-height: 1.5;
}
h1 { font-size: 1.35rem; margin: 0 0 0.15rem; }
.tagline { margin: 0 0 0.3rem; color: var(--quiet); }
h2 { font-size: 1rem; margin: 0 0 0.6rem; }
section { border: 1px solid var(--line); border-radius: 0.6rem; padding: 1rem;
  margin-bottom: 1.1rem; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.15rem; }
select, input[type=search] { width: 100%; padding: 0.45rem;
  font: inherit; border: 1px solid var(--line); border-radius: 0.35rem; background: transparent;
  color: inherit; }
.finder { display: flex; gap: 0.4rem; }
/* The native arrow is drawn against the border box and ignores padding-right, so it ends up
   hard against the edge while the search field's own clear button sits comfortably inside.
   Turning the native one off and drawing ours is the only way to place it. currentColor keeps
   it right in both light and dark without a second rule. */
.picker { position: relative; display: inline-flex; flex: 0 0 auto; }
.picker select { width: auto; padding-right: 2rem; appearance: none; -webkit-appearance: none; }
.picker::after {
  content: ""; position: absolute; right: 0.75rem; top: 50%; pointer-events: none;
  width: 0.62rem; height: 0.36rem; transform: translateY(-50%); background: currentColor;
  clip-path: polygon(0 0, 100% 0, 50% 100%); opacity: 0.75;
}
.files { max-height: 17rem; overflow-y: auto; margin-top: 0.4rem;
  border: 1px solid var(--line); border-radius: 0.35rem; }
.file { display: flex; gap: 0.6rem; align-items: center; width: 100%; text-align: left;
  border: 0; border-top: 1px solid var(--line); border-radius: 0; padding: 0.45rem 0.6rem; }
.file:first-child { border-top: 0; }
.file[aria-pressed=true] { background: rgba(128,128,128,0.18); }
.file img, .file .noshot { width: 2.6rem; height: 2.6rem; flex: 0 0 2.6rem; border-radius: 0.3rem;
  object-fit: contain; background: rgba(128,128,128,0.12); }
.file-name { font-weight: 600; overflow-wrap: anywhere; font-size: 0.9rem; }
.row { margin-bottom: 0.8rem; }
/* The field asks for exactly its own width now that a button sits next to it, rather than
   stretching across a form it never filled meaningfully. */
.whenpick { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
/* One affordance, not two. The native indicator opens the same picker the button does, and two
   controls doing one thing in the same field reads as an accident. */
.whenpick input[type=datetime-local]::-webkit-calendar-picker-indicator { display: none; }
.whenpick button { display: inline-flex; align-items: center; gap: 0.4rem; }
.whenpick button svg { width: 1rem; height: 1rem; fill: currentColor; }
.whenpick input[type=datetime-local] { width: auto; flex: 0 0 auto; padding: 0.45rem;
  border: 1px solid var(--line); border-radius: 0.35rem; background: transparent;
  color: inherit; font: inherit; }
.check { display: flex; gap: 0.5rem; align-items: flex-start; margin-bottom: 0.5rem;
  font-size: 0.9rem; }
.check input { margin-top: 0.25rem; }
button { font: inherit; padding: 0.45rem 0.9rem; border-radius: 0.35rem;
  border: 1px solid var(--line); background: transparent; color: inherit; cursor: pointer; }
button.primary { border-color: currentColor; font-weight: 600; }
button:disabled { opacity: 0.45; cursor: not-allowed; }
button.link { border: 0; padding: 0.2rem 0.35rem; text-decoration: underline; font-size: 0.85rem; }
.quiet { color: var(--quiet); font-size: 0.85rem; }
.warn { border-left: 3px solid #d08b00; padding-left: 0.6rem; margin: 0.6rem 0;
  font-size: 0.88rem; }
.stop { border-left: 3px solid #c0392b; padding-left: 0.6rem; margin: 0.6rem 0;
  font-size: 0.88rem; }
.heading-row { display: flex; align-items: baseline; justify-content: space-between;
  gap: 0.6rem; }
.heading-row h2 { margin-bottom: 0.6rem; }
button.danger { border-color: #c0392b; color: #c0392b; }
.job { border-top: 1px solid var(--line); padding: 0.7rem 0;
  display: flex; gap: 0.6rem; align-items: flex-start; }
.job:first-child { border-top: 0; }
.job img, .job .noshot { width: 3.2rem; height: 3.2rem; flex: 0 0 3.2rem; border-radius: 0.3rem;
  object-fit: contain; background: rgba(128,128,128,0.12); }
/* Without the zero minimum a long filename refuses to wrap and pushes the row sideways. */
.job-body { flex: 1 1 auto; min-width: 0; }
.job-title { font-weight: 600; overflow-wrap: anywhere; }
.job-actions { margin-top: 0.35rem; display: flex; gap: 0.3rem; flex-wrap: wrap; }
.tools { display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 0.5rem 0; }
.tool { display: flex; align-items: center; gap: 0.35rem; font-size: 0.85rem; }
.swatch { width: 0.95rem; height: 0.95rem; border-radius: 50%; border: 1px solid var(--line); }
.facts { font-size: 0.85rem; color: var(--quiet); }
footer { font-size: 0.8rem; color: var(--quiet); display: flex; align-items: baseline;
         justify-content: space-between; flex-wrap: wrap; gap: 0.5rem 1rem; }
</style>
</head>
<body>
<h1>Print Scheduler</h1>
<p class="tagline" data-i18n="page.tagline">Start a print at a time you choose.</p>
<p class="quiet" id="printer-line" data-i18n="page.asking-the-printer">Asking the printer...</p>
<div id="clock-warning"></div>
<div id="settings-warning"></div>

<section>
<h2 id="form-heading" data-i18n="page.schedule-a-print">Schedule a print</h2>
<div class="row">
  <label for="file-search" data-i18n="page.file-on-the-printer">File already on the printer</label>
  <div class="finder">
    <input type="search" id="file-search" placeholder="Search by name" autocomplete="off"
      data-i18n-placeholder="page.search-by-name">
    <span class="picker"><select id="file-sort" aria-label="Sort the files"
      data-i18n-aria-label="page.sort-the-files">
      <option value="newest" data-i18n="page.sort-newest">Newest first</option>
      <option value="oldest" data-i18n="page.sort-oldest">Oldest first</option>
      <option value="printed" data-i18n="page.sort-printed">Last printed</option>
      <option value="name" data-i18n="page.sort-name">Name A to Z</option>
      <option value="name-back" data-i18n="page.sort-name-back">Name Z to A</option>
    </select></span>
  </div>
  <div id="file-list" class="files"><p class="quiet" data-i18n="page.loading">Loading...</p></div>
  <p class="quiet" id="file-count"></p>
</div>
<div id="file-facts"></div>
<div class="row">
  <label for="start-at" data-i18n="page.start-it-at">Start it at</label>
  <div class="whenpick">
    <input type="datetime-local" id="start-at">
    <button type="button" id="pick-time"><span data-i18n="page.pick-a-time">Pick a time</span><svg
      viewBox="0 0 24 24" aria-hidden="true"
      ><path d="M7 2v2H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6a2 2 0 0
      0-2-2h-2V2h-2v2H9V2H7zm12 7v10H5V9h14z"/></svg></button>
  </div>
  <p class="quiet" id="start-help"></p>
</div>
<div id="preferences"></div>
<div id="form-bed-warning"></div>
<div class="check">
  <input type="checkbox" id="bed-clear">
  <label for="bed-clear" data-i18n="page.bed-will-be-clear">The bed will be clear. The printer
  cannot see it, so this is your word, not a check.</label>
</div>
<div class="job-actions">
  <button class="primary" id="save" aria-describedby="save-blocked" disabled
    data-i18n="page.schedule-it">Schedule it</button>
  <button class="link" id="stop-editing" hidden data-i18n="page.stop-editing">Stop editing</button>
</div>
<p class="quiet" id="save-blocked"></p>
<div id="form-problem"></div>
</section>

<section>
<h2 data-i18n="page.scheduled">Scheduled</h2>
<div id="held-notice"></div>
<div id="pending"><p class="quiet" data-i18n="page.loading">Loading...</p></div>
</section>

<section>
<div class="heading-row">
  <h2 data-i18n="page.already-settled">Already settled</h2>
  <div id="clear-settled"></div>
</div>
<div id="settled"><p class="quiet" data-i18n="page.loading">Loading...</p></div>
</section>

<footer>
  <span>print-scheduler __VERSION__</span>
  <div id="language-pick"></div>
</footer>

<script>
// ---- what the page says ------------------------------------------------------------------------
// Every catalogue rides inside the page rather than being fetched. Two of them are a few
// kilobytes, it costs no round trip, and it is what lets one reader choose a language without
// changing what the printer serves everybody else.
var CATALOGUES = __CATALOGUES__;
var PRINTER_LANGUAGE = "__LANGUAGE__";
var ENGLISH = "en";
// Per browser, per printer, and never sent anywhere: the server does not know a reader chose.
var LANGUAGE_MEMORY = "print-scheduler.language";

function rememberedLanguage() {
  try { return window.localStorage.getItem(LANGUAGE_MEMORY) || ""; }
  catch (blocked) { return ""; }
}

// Storage can be off, full, or refused in a private window. None of that is worth an error on a
// page whose job is to start prints; the reader simply follows the printer again.
function rememberLanguage(tag) {
  try {
    if (tag) { window.localStorage.setItem(LANGUAGE_MEMORY, tag); }
    else { window.localStorage.removeItem(LANGUAGE_MEMORY); }
  } catch (blocked) { return; }
}

function languageNow() {
  var remembered = rememberedLanguage();
  if (remembered && CATALOGUES[remembered]) { return remembered; }
  return CATALOGUES[PRINTER_LANGUAGE] ? PRINTER_LANGUAGE : ENGLISH;
}

var language = languageNow();

// The same rules as messages.py, for the same reason: a missing key, a missing catalogue or a
// mistyped placeholder falls back rather than throwing. A typo in a translation must not be able
// to stop a print from being scheduled.
function t(key, values) {
  var supplied = values || {};
  var filled = {};
  for (var name in supplied) {
    if (Object.prototype.hasOwnProperty.call(supplied, name)) {
      filled[name] = renderedValue(supplied[name]);
    }
  }
  var template = templateFor(key, filled);
  if (template === null) { return String(key); }
  return template.replace(/\{(\w+)\}/g, function (whole, name) {
    return Object.prototype.hasOwnProperty.call(filled, name) ? String(filled[name]) : whole;
  });
}

// A value may be a message of its own, which is how "2 minutes" reaches the middle of a sentence
// with its number and its unit still together.
function renderedValue(value) {
  if (value && typeof value === "object" && typeof value.message === "string") {
    return t(value.message, value.values);
  }
  if (Array.isArray(value)) { return joinedWith("list.separator", value); }
  return value;
}

function joinedWith(separatorKey, items) {
  return items.map(renderedValue).join(t(separatorKey));
}

function templateFor(key, values) {
  var tags = [language, ENGLISH];
  for (var index = 0; index < tags.length; index += 1) {
    var chosen = oneOrOther((CATALOGUES[tags[index]] || {})[key], values);
    if (chosen !== null) { return chosen; }
  }
  return null;
}

function oneOrOther(entry, values) {
  if (typeof entry === "string") { return entry; }
  if (!entry || typeof entry !== "object") { return null; }
  var wanted = values.count === 1 ? "one" : "other";
  var chosen = entry[wanted] !== undefined ? entry[wanted] : entry.other;
  return typeof chosen === "string" ? chosen : null;
}

// The static half of the page is written in English in the markup and translated here. A reader
// on another language may see English for one paint, which is the accepted cost of keeping the
// page itself language neutral so that each reader can choose their own.
function applyStaticText() {
  document.documentElement.lang = language;
  eachNodeWith("data-i18n", function (node, key) { node.textContent = t(key); });
  eachNodeWith("data-i18n-placeholder", function (node, key) { node.placeholder = t(key); });
  eachNodeWith("data-i18n-aria-label", function (node, key) {
    node.setAttribute("aria-label", t(key));
  });
}

function eachNodeWith(attribute, apply) {
  var nodes = document.querySelectorAll("[" + attribute + "]");
  for (var index = 0; index < nodes.length; index += 1) {
    apply(nodes[index], nodes[index].getAttribute(attribute));
  }
}

// Relative, always. This page is published under a prefix it is never told about, so an absolute
// path here would point at the printer dashboard rather than at this plugin.
var CLOCK_SKEW_TOLERANCE_SECONDS = 120;
var REFRESH_MILLISECONDS = 10000;
var FILES_REFRESH_MILLISECONDS = 15000;

var state = { jobs: [], printer: null, summary: null, editing: null,
              files: [], chosen: "", armedToClear: false, dismissing: false };
// A long list is slow to build and pointless to read. Past this, search is the way in.
var MOST_FILES_TO_DRAW = 40;

function element(tag, className, text) {
  var made = document.createElement(tag);
  if (className) { made.className = className; }
  if (text !== undefined && text !== null) { made.textContent = String(text); }
  return made;
}

function replaceChildren(target, children) {
  target.textContent = "";
  children.forEach(function (child) { target.appendChild(child); });
}

function api(path, options) {
  return fetch(path, options).then(function (response) {
    return response.text().then(function (text) {
      var payload = {};
      try { payload = text ? JSON.parse(text) : {}; } catch (ignored) { payload = {}; }
      if (response.ok) { return payload; }
      if (response.status === 401 || response.status === 403) {
        throw new Error(t("page.sign-in-again"));
      }
      // The service sends the key and the values beside the English, so a refusal reads in the
      // reader's language rather than in the one the printer happens to be set to.
      if (payload.error_key) { throw new Error(t(payload.error_key, payload.error_values)); }
      throw new Error(payload.error || t("page.request-failed", { status: response.status }));
    });
  });
}

function postJson(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
}

function whenLocal(epochSeconds) {
  if (!epochSeconds) { return t("page.an-unknown-time"); }
  return new Date(epochSeconds * 1000).toLocaleString();
}

function howLong(seconds) {
  if (!seconds) { return null; }
  // A 26 second file exists on this printer, and "about 0m" helps nobody.
  if (seconds < 60) { return t("page.seconds-short", { count: Math.round(seconds) }); }
  var hours = Math.floor(seconds / 3600);
  var minutes = Math.round((seconds % 3600) / 60);
  return hours ? t("page.hours-and-minutes-short", { hours: hours, minutes: minutes })
               : t("page.minutes-short", { count: minutes });
}

function setupVaries(setup) {
  if (!setup) { return false; }
  var shortest = howLong(setup.shortest);
  var longest = howLong(setup.longest);
  return Boolean(shortest && longest && shortest !== longest);
}

function describeSetup(setup) {
  if (!setup) { return null; }
  if (setupVaries(setup)) {
    return t("page.setup-range",
             { shortest: howLong(setup.shortest), longest: howLong(setup.longest) });
  }
  return howLong(setup.typical);
}

function sameDay(first, second) {
  return new Date(first * 1000).toDateString() === new Date(second * 1000).toDateString();
}

function whenLocalTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString();
}

// A single clock time is a claim this printer cannot support: its setup time comes in two
// clusters nine minutes apart, so the middle of them is a moment almost no print finishes at.
// When the ends of the range read differently, both are shown.
function describeFinish(job, setup) {
  var from = job.projected_finish_from;
  var to = job.projected_finish_to;
  if (setupVaries(setup) && from && to && from !== to) {
    return t("page.finish-between",
             { from: whenLocal(from), to: sameDay(from, to) ? whenLocalTime(to) : whenLocal(to) });
  }
  // Two whole sentences rather than one with a clause bolted on: where the clause goes is a
  // decision each language makes for itself.
  var when = { when: whenLocal(job.projected_finish) };
  return setup ? t("page.finish-around", when) : t("page.finish-around-without-setup", when);
}

function showProblem(target, message) {
  replaceChildren(target, message ? [element("p", "stop", message)] : []);
}

// ---- the printer line -------------------------------------------------------------------------

function describePrinter(printer) {
  if (!printer.reachable) {
    return t("page.printer-not-answering", { message: printer.klipper_message });
  }
  if (printer.print_state === "printing") {
    return t("page.printing-now", { filename: printer.printing_filename });
  }
  if (printer.print_state === "complete") { return t("page.finished-not-dismissed"); }
  if (printer.print_state === "cancelled") { return t("page.cancelled-not-dismissed"); }
  if (printer.klipper_state !== "ready") {
    // Klipper's own word for its state, left as Klipper says it: a machine's vocabulary is
    // what somebody searches for when they go looking for what it means.
    return t("page.klipper-reports", { state: printer.klipper_state });
  }
  return t("page.idle-and-ready");
}

function renderPrinter() {
  var printer = state.printer;
  if (!printer) { return; }
  var tolerance = Math.round(printer.tolerance_minutes);
  document.getElementById("printer-line").textContent = t("page.printer-line", {
    printer: describePrinter(printer),
    tolerance: { message: "duration.minutes", values: { count: tolerance } }
  });

  renderIgnoredSettings(printer.settings_ignored || []);
  renderFormBedWarning(printer);

  var skew = Math.abs(printer.printer_time - (Date.now() / 1000));
  var warning = document.getElementById("clock-warning");
  if (skew > CLOCK_SKEW_TOLERANCE_SECONDS) {
    replaceChildren(warning, [element("p", "warn", t("page.clocks-differ", {
      apart: { message: "duration.minutes", values: { count: Math.round(skew / 60) } }
    }))]);
  } else {
    replaceChildren(warning, []);
  }
}

function showsAFinishedPrint(printer) {
  return Boolean(printer && printer.reachable && printer.klipper_state === "ready" &&
    (printer.print_state === "complete" || printer.print_state === "cancelled"));
}

// Beside the promise about the bed, because that is the moment the question matters: a job
// scheduled while the printer shows a finished print will wait for you when it is due, and the
// way to stop that is right here. The button is shown from the page's copy of the state, which
// can be seconds old, so it is only an offer: whether the printer may actually be cleared is
// asked of the printer again when it is pressed, because the command behind it stops a print
// that is running. An error is deliberately not offered: a print that failed deserves somebody
// walking over to the printer.
function renderFormBedWarning(printer) {
  if (state.dismissing) { return; }
  var target = document.getElementById("form-bed-warning");
  if (!showsAFinishedPrint(printer)) { replaceChildren(target, []); return; }
  var warning = element("div", "warn");
  warning.appendChild(element("p", null, t("page.form-bed-warning")));
  warning.appendChild(actionButton(t("page.i-cleared-the-bed"), dismissTheFinishedPrint));
  replaceChildren(target, [warning]);
}

// The label is the promise. Pressing it is saying the bed is clear, and there is no second
// click because there is nothing further to confirm: this is the person's word, and they have
// just given it.
function dismissTheFinishedPrint() {
  state.dismissing = true;
  var button = document.querySelector("#form-bed-warning button");
  if (button) { button.disabled = true; }
  postJson("./printer/dismiss", {}).then(function () {
    state.dismissing = false;
    return Promise.all([loadPrinter(), loadJobs()]);
  }).catch(function (problem) {
    state.dismissing = false;
    // Left on screen until the next poll redraws it, by which time the printer's newer state
    // says for itself what changed.
    replaceChildren(document.getElementById("form-bed-warning"),
                    [element("p", "stop", problem.message)]);
  });
}

// A setting the plugin cannot use falls back to its default, and says so here as well as in
// the log. The person who typed it is looking at the app, not at a file on the printer, and a
// printer quietly behaving differently from the number on screen is the failure to avoid.
function renderIgnoredSettings(sentences) {
  var target = document.getElementById("settings-warning");
  if (!sentences.length) { replaceChildren(target, []); return; }
  replaceChildren(target, sentences.map(function (sentence) {
    return element("p", "warn", sentence);
  }));
}

// ---- the file you picked ----------------------------------------------------------------------

// A file numbers its filaments by slicer slot; the printer numbers its hardware by
// toolhead. They are not the same, and the first scheduled print on real hardware went
// into ASA because slot 0 was assumed to mean toolhead 0.
function assignmentFor(plan, slot) {
  if (!plan || !plan.assignments) { return null; }
  for (var index = 0; index < plan.assignments.length; index += 1) {
    if (plan.assignments[index].slot === slot) { return plan.assignments[index]; }
  }
  return null;
}

// Four whole sentences rather than one built by appending, because where the weight and the
// toolhead go in a line is a decision each language makes.
//
// A toolhead is named only when one was chosen. Saying "no toolhead" where the printer does not
// report what is loaded reads as a machine with no toolhead, which is not the situation: there
// is simply nothing to choose between. Where a choice failed, the refusal says so below in its
// own words, and repeating it on every row adds nothing.
function describeSlot(tool, plan) {
  var assignment = assignmentFor(plan, tool.slot);
  var values = {
    slot: tool.slot,
    material: tool.filament_type || t("page.filament"),
    grams: tool.used_grams ? tool.used_grams.toFixed(1) : "",
    toolhead: assignment ? assignment.toolhead : ""
  };
  if (assignment && tool.used_grams) { return t("page.slot-with-grams-on-toolhead", values); }
  if (assignment) { return t("page.slot-on-toolhead", values); }
  if (tool.used_grams) { return t("page.slot-with-grams", values); }
  return t("page.slot", values);
}

function mismatchedColours(plan) {
  if (!plan || !plan.assignments) { return []; }
  // Both values, because the difference is often a typo's worth and a bare "they differ"
  // reads as a wrong spool when it is nothing of the kind.
  return plan.assignments.filter(function (one) { return one.colours_differ; })
    .map(function (one) {
      return t("page.colour-mismatch-slot", {
        slot: one.slot, toolhead: one.toolhead,
        wanted: one.wanted_colour, loaded: one.loaded_colour
      });
    });
}

function renderFileFacts() {
  var target = document.getElementById("file-facts");
  var summary = state.summary;
  if (!summary) { replaceChildren(target, []); return; }

  var parts = [];
  if (summary.tools.length) {
    var tools = element("div", "tools");
    summary.tools.forEach(function (tool) {
      var entry = element("div", "tool");
      var swatch = element("span", "swatch");
      if (tool.colour) { swatch.style.background = tool.colour; }
      entry.appendChild(swatch);
      entry.appendChild(element("span", null, describeSlot(tool, summary.plan)));
      tools.appendChild(entry);
    });
    parts.push(tools);
  } else {
    parts.push(element("p", "quiet", t("page.no-material-stated")));
  }

  var facts = [];
  var duration = howLong(summary.estimated_seconds);
  if (duration) { facts.push(t("page.about-this-long", { duration: duration })); }
  if (summary.bed_temperature) {
    facts.push(t("page.bed-temperature", { degrees: summary.bed_temperature }));
  }
  if (summary.chamber_temperature) {
    facts.push(t("page.chamber-temperature", { degrees: summary.chamber_temperature }));
  }
  if (summary.layer_count) {
    facts.push(t("page.layer-count", { count: summary.layer_count }));
  }
  if (facts.length) {
    parts.push(element("p", "facts", joinedWith("list.separator", facts)));
  }

  if (summary.plan && !summary.plan.applicable && summary.tools.length > 1) {
    parts.push(element("p", "quiet", t("page.no-toolhead-tracking")));
  }

  if (planProblem(summary.plan)) {
    parts.push(element("p", "stop", planProblem(summary.plan)));
  } else if (mismatchedColours(summary.plan).length) {
    parts.push(element("p", "warn", t("page.colour-mismatch", {
      slots: joinedWith("list.separator-clauses", mismatchedColours(summary.plan))
    })));
  }
  replaceChildren(target, parts);
}

// Why no toolhead will do, in the reader's language. The English sentence comes with it and is
// what a row written before the key existed falls back to.
function planProblem(plan) {
  if (!plan) { return ""; }
  if (plan.problem_key) { return t(plan.problem_key, plan.problem_values); }
  return plan.problem || "";
}

function renderPreferences() {
  var target = document.getElementById("preferences");
  if (!state.printer || !state.printer.supports_print_preferences) {
    replaceChildren(target, []);
    return;
  }
  if (document.getElementById("level-bed")) { return; }
  replaceChildren(target, [
    checkbox("level-bed", t("page.level-the-bed"), true),
    checkbox("record-timelapse", t("page.record-a-timelapse"), true),
    element("p", "quiet", t("page.preferences-are-the-printer-s"))
  ]);
}

function checkbox(id, labelText, checked) {
  var wrapper = element("div", "check");
  var box = document.createElement("input");
  box.type = "checkbox";
  box.id = id;
  box.checked = checked;
  var label = element("label", null, labelText);
  label.htmlFor = id;
  wrapper.appendChild(box);
  wrapper.appendChild(label);
  return wrapper;
}

function preferenceValue(id) {
  var box = document.getElementById(id);
  return box ? box.checked : null;
}

// ---- the schedule -----------------------------------------------------------------------------

function jobHeadline(job) {
  if (job.state === "scheduled") { return t("page.starts-at", { when: whenLocal(job.start_at) }); }
  if (job.state === "starting") { return t("page.starting-now"); }
  if (job.state === "started") { return t("page.started-at", { when: whenLocal(job.decided_at) }); }
  return t("page.did-not-run", { why: whyItDidNotRun(job) });
}

// The key and its values where the job has them, and the stored English where it does not. A row
// settled before this existed keeps the sentence it was written with, which is the whole reason
// there was nothing to migrate.
function whyItDidNotRun(job) {
  if (job.detail_key) { return t(job.detail_key, job.detail_values); }
  return job.detail || "";
}

// What this job asked the printer for. Invisible once a job was scheduled until now, and
// worth seeing: levelling is most of the difference between a two minute setup and a ten
// minute one, so this is the reason two rows can carry very different times.
function describeChoices(job) {
  var parts = [];
  if (job.level_bed === true) { parts.push(t("page.levelling")); }
  else if (job.level_bed === false) { parts.push(t("page.no-levelling")); }
  if (job.record_timelapse === true) { parts.push(t("page.timelapse")); }
  else if (job.record_timelapse === false) { parts.push(t("page.no-timelapse")); }
  return parts.length ? joinedWith("list.separator", parts) : null;
}

// The job payload does not carry the file's details, and asking the printer for them on every
// jobs poll would be a round trip every few seconds. The file list already knows, so a job
// borrows from it. A file that has gone from the printer since it was scheduled gets the
// placeholder, which is the honest answer to a preview nobody can produce any more.
function fileBehind(filename) {
  for (var index = 0; index < state.files.length; index += 1) {
    if (state.files[index].filename === filename) { return state.files[index]; }
  }
  return null;
}

function jobThumbnail(job) {
  var file = fileBehind(job.filename);
  if (!file || !file.has_thumbnail) { return element("span", "noshot"); }
  var picture = document.createElement("img");
  picture.loading = "lazy";
  picture.alt = "";
  picture.src = "./thumbnail?filename=" + encodeURIComponent(job.filename);
  return picture;
}

function renderJob(job) {
  var card = element("div", "job");
  card.appendChild(jobThumbnail(job));
  // Everything else goes beside the picture rather than under it.
  var body = element("div", "job-body");
  card.appendChild(body);
  body.appendChild(element("div", "job-title", job.filename));
  body.appendChild(element("div", "quiet", jobHeadline(job)));

  var choices = describeChoices(job);
  if (choices) { body.appendChild(element("div", "quiet", choices)); }

  if (job.state === "scheduled" && job.projected_finish) {
    var printing = howLong(job.estimated_seconds);
    var setup = describeSetup(job.setup);
    if (setup && printing) {
      body.appendChild(element("div", "facts",
        t("page.setup-then-printing", { setup: setup, printing: printing })));
    }
    body.appendChild(element("div", "facts", describeFinish(job, job.setup)));
  }
  // Only a job that is still scheduled can be waiting on you. A settled row carrying the flag
  // is either history from before it was cleared at cancellation, or a bug; either way saying
  // "waiting for your confirmation" about a job that already ran is worse than saying nothing.
  if (job.hold === "long-silence" && job.state === "scheduled") {
    // Short on purpose. The banner above the list has already said that nothing starts until
    // you confirm; this marker exists for a list long enough that the banner has scrolled away,
    // and saying it twice in three lines is how a warning stops being read.
    body.appendChild(element("p", "warn", t("page.waiting-for-your-confirmation")));
  }
  if (job.hold === "bed-not-confirmed" && job.state === "scheduled") {
    body.appendChild(heldForTheBed(job));
  }
  if (job.overlaps_with) {
    body.appendChild(element("p", "warn", t("page.overlaps-with-an-earlier-job")));
  }
  if (job.printer_says) {
    // The printer's own words, passed through: translating a machine's message makes it
    // unsearchable and unreportable.
    body.appendChild(
      element("div", "facts", t("page.the-printer-says", { what: job.printer_says })));
  } else if (job.state === "started") {
    body.appendChild(element("div", "facts", t("page.no-record-of-how-it-went")));
  }

  var actions = element("div", "job-actions");
  if (job.state === "started" || job.state === "cancelled") {
    actions.appendChild(actionButton(t("page.remove"), function () { forgetJob(job); }));
  }
  if (job.state === "scheduled") {
    actions.appendChild(actionButton(t("page.edit"), function () { startEditing(job); }));
    actions.appendChild(actionButton(t("page.cancel"), function () { cancelJob(job); }));
  }
  actions.appendChild(
    actionButton(t("page.schedule-another-like-this"), function () { copyInto(job); }));
  body.appendChild(actions);
  return card;
}

// Why the job did not start, said even once the reason has gone. A job that waits after the bed
// was dismissed on the printer's screen is doing what it was designed to do, since nothing
// starts on a screen dismissal, and with no reason on screen it would read as a bug.
function heldForTheBed(job) {
  // Until the printer has answered, the stronger question: asking somebody to clear a bed that
  // is already clear costs a glance, telling them it was dismissed when it was not costs a part.
  var stillShowing = !state.printer || showsAFinishedPrint(state.printer);
  var held = element("div", "warn");
  held.appendChild(element("p", null, stillShowing
    ? t("page.held-for-the-bed")
    : t("page.held-for-the-bed-since-dismissed", { when: whenLocal(job.held_at) })));
  // Two literal calls rather than one with a chosen key, so the catalogue check can see both.
  held.appendChild(actionButton(
    stillShowing ? t("page.cleared-start-now") : t("page.bed-clear-start-now"),
    function () { startNow(job); }));
  return held;
}

function startNow(job) {
  postJson("./jobs/start-now", { job_id: job.job_id })
    .then(function () { return Promise.all([loadJobs(), loadPrinter()]); })
    .catch(function (problem) {
      showProblem(document.getElementById("form-problem"), problem.message);
    });
}

function actionButton(label, whenClicked) {
  var button = element("button", "link", label);
  button.type = "button";
  button.addEventListener("click", whenClicked);
  return button;
}

// Both lists were in the order jobs happened to be created, which is not what either list is
// for. The scheduled one existed to say what happens next and put a job re-created after a
// failure at the bottom although it was due first. The settled one reversed that, which looks
// like newest first often enough to be trusted and then quietly is not.
function byJobId(a, b) {
  return a.job_id < b.job_id ? -1 : (a.job_id > b.job_id ? 1 : 0);
}

function bySoonestFirst(a, b) { return a.start_at - b.start_at || byJobId(a, b); }

// When a job settled: when it started, or for one that never did, when it was due. This is
// deliberately the same key the service trims on, so the row that disappears when the list is
// capped is always the one at the bottom of what you can see.
function whenItSettled(job) { return job.decided_at || job.start_at; }

function byNewestSettledFirst(a, b) {
  return whenItSettled(b) - whenItSettled(a) || byJobId(b, a);
}

function renderJobs() {
  var pending = state.jobs.filter(function (job) {
    return job.state === "scheduled" || job.state === "starting";
  }).sort(bySoonestFirst);
  var settled = state.jobs.filter(function (job) {
    return job.state === "started" || job.state === "cancelled";
  }).sort(byNewestSettledFirst);

  // Only the long silence belongs in the banner. A job waiting for the bed asks its own
  // question on its own row, and "the scheduler was not running" would be untrue about it.
  renderHeldNotice(pending.filter(function (job) { return job.hold === "long-silence"; }));
  replaceChildren(document.getElementById("pending"),
    pending.length ? pending.map(renderJob)
                   : [element("p", "quiet", t("page.nothing-scheduled"))]);
  replaceChildren(document.getElementById("settled"),
    settled.length ? settled.map(renderJob)
                   : [element("p", "quiet", t("page.nothing-settled-yet"))]);
  renderClearButton(settled.length);
}

// ---- the form ---------------------------------------------------------------------------------

function refreshSaveButton() {
  var chosen = state.chosen;
  var when = document.getElementById("start-at").value;
  var acknowledged = document.getElementById("bed-clear").checked;
  // The one thing that makes a file unschedulable is that its slots cannot be given
  // toolheads. The service refuses it too; this is so the button says so first.
  var unplannable = Boolean(state.summary && planProblem(state.summary.plan));
  document.getElementById("save").disabled =
    !chosen || !when || !acknowledged || Boolean(unplannable);
  sayWhyTheButtonIsOff(chosen, when, acknowledged, unplannable);
}

// A button that is disabled and silent about it is a puzzle. This one had four separate
// reasons to be off and named none of them, so the answer was to go and read the source.
function sayWhyTheButtonIsOff(chosen, when, acknowledged, unplannable) {
  var target = document.getElementById("save-blocked");
  if (unplannable) {
    // Already spelled out in full above the button, so this points rather than repeats.
    target.textContent = t("page.cannot-be-scheduled-see-above");
    return;
  }
  var missing = [];
  if (!chosen) { missing.push(t("page.a-file")); }
  if (!when) { missing.push(t("page.a-time")); }
  if (!acknowledged) { missing.push(t("page.your-promise-about-the-bed")); }
  target.textContent = missing.length ? t("page.still-needed", { things: inPlainList(missing) })
                                      : "";
}

// Both the separator and the word before the last item come from the catalogue: "a and b" is
// not how every language ends a list.
function inPlainList(items) {
  if (items.length === 1) { return items[0]; }

  return items.slice(0, -1).join(t("list.separator")) + t("list.last-separator") +
    items[items.length - 1];
}

function startEditing(job) {
  state.editing = job.job_id;
  document.getElementById("form-heading").textContent = t("page.edit-this-job");
  document.getElementById("save").textContent = t("page.save-changes");
  document.getElementById("stop-editing").hidden = false;
  fillForm(job, true);
}

function copyInto(job) {
  stopEditing();
  fillForm(job, false);
}

function stopEditing() {
  state.editing = null;
  document.getElementById("form-heading").textContent = t("page.schedule-a-print");
  document.getElementById("save").textContent = t("page.schedule-it");
  document.getElementById("stop-editing").hidden = true;
  showProblem(document.getElementById("form-problem"), null);
}

function fillForm(job, keepTime) {
  state.chosen = job.filename;
  renderFiles();
  // Changing the file or the time clears the promise about the bed, because the promise was about
  // a particular moment and a particular thing on the plate.
  document.getElementById("bed-clear").checked = false;
  document.getElementById("start-at").value = keepTime ? localInputValue(job.start_at) : "";
  // The bed promise is the only thing that does not carry over. Everything else has to, because
  // a form left at its last state is a job quietly changing its mind: edit the time on a
  // levelled job while these sit unchecked and it stops levelling with nothing on screen to
  // say so. "Schedule another like this" has the same duty, and a stronger claim to it.
  setPreference("level-bed", job.level_bed);
  setPreference("record-timelapse", job.record_timelapse);
  loadSummary(job.filename);
  refreshSaveButton();
  document.getElementById("form-heading").scrollIntoView({ block: "start" });
}

function setPreference(id, value) {
  var box = document.getElementById(id);
  // Absent on a printer that does not offer the choice, where there is nothing to carry.
  if (!box) { return; }
  // A job scheduled before the printer offered the choice carries null. A fresh form starts
  // both on, so that is what a job which never made a choice is shown.
  box.checked = value === null || value === undefined ? true : Boolean(value);
}

function localInputValue(epochSeconds) {
  var when = new Date(epochSeconds * 1000);
  var pad = function (value) { return String(value).padStart(2, "0"); };
  return when.getFullYear() + "-" + pad(when.getMonth() + 1) + "-" + pad(when.getDate()) +
    "T" + pad(when.getHours()) + ":" + pad(when.getMinutes());
}

function chosenInstant() {
  var typed = document.getElementById("start-at").value;
  return { typed: typed, epoch: new Date(typed).getTime() / 1000 };
}

function save() {
  var chosen = chosenInstant();
  var body = {
    filename: state.chosen,
    start_at: chosen.epoch,
    typed_time: chosen.typed,
    timezone_name: Intl.DateTimeFormat().resolvedOptions().timeZone,
    bed_acknowledged: document.getElementById("bed-clear").checked,
    level_bed: preferenceValue("level-bed"),
    record_timelapse: preferenceValue("record-timelapse")
  };
  if (state.editing) { body.job_id = state.editing; }
  var path = state.editing ? "./jobs/update" : "./jobs";

  document.getElementById("save").disabled = true;
  postJson(path, body).then(function () {
    stopEditing();
    document.getElementById("start-at").value = "";
    document.getElementById("bed-clear").checked = false;
    refreshSaveButton();
    return loadJobs();
  }).catch(function (problem) {
    showProblem(document.getElementById("form-problem"), problem.message);
    refreshSaveButton();
  });
}

function forgetJob(job) {
  // Ours to forget, not the printer's: its own record of what it printed is untouched.
  postJson("./jobs/forget", { job_id: job.job_id })
    .then(loadJobs)
    .catch(function (problem) {
      showProblem(document.getElementById("form-problem"), problem.message);
    });
}

// Two clicks, with the button saying what the second one will do. A browser confirm() would
// block the browser harness this page is tested with, and a dialog for a list of finished jobs
// is heavier than the thing deserves.
var DISARM_AFTER_MILLISECONDS = 6000;
var disarmTimer = null;

function armTheClear() {
  state.armedToClear = true;
  renderJobs();
  if (disarmTimer) { clearTimeout(disarmTimer); }
  disarmTimer = setTimeout(function () {
    state.armedToClear = false;
    renderJobs();
  }, DISARM_AFTER_MILLISECONDS);
}

function clearTheSettledList() {
  state.armedToClear = false;
  if (disarmTimer) { clearTimeout(disarmTimer); disarmTimer = null; }
  postJson("./jobs/forget-settled", {})
    .then(loadJobs)
    .catch(function (problem) {
      showProblem(document.getElementById("form-problem"), problem.message);
    });
}

// The scheduler can stop running without anybody deciding that it should: the daemon
// deactivates a plugin that breaks Klipper or Moonraker, a printer sits switched off for a
// fortnight, somebody uninstalls and the schedule survives because the platform keeps a
// plugin's data on purpose. In all three it comes back holding promises nobody has looked at
// since, so it asks once rather than acting on them.
function renderHeldNotice(held) {
  var target = document.getElementById("held-notice");
  if (!held.length) { replaceChildren(target, []); return; }
  var notice = element("div", "warn");
  notice.appendChild(element("p", null, t("page.held", { count: held.length })));
  notice.appendChild(element("p", "quiet", t("page.held-note")));
  notice.appendChild(
    actionButton(t("page.held-still-stands", { count: held.length }), releaseTheHeldJobs));
  replaceChildren(target, [notice]);
}

function releaseTheHeldJobs() {
  postJson("./jobs/release", {})
    .then(loadJobs)
    .catch(function (problem) {
      showProblem(document.getElementById("form-problem"), problem.message);
    });
}

function renderClearButton(howMany) {
  var target = document.getElementById("clear-settled");
  if (!howMany) { replaceChildren(target, []); state.armedToClear = false; return; }
  var button = state.armedToClear
    ? actionButton(t("page.really-remove", { count: howMany }), clearTheSettledList)
    : actionButton(t("page.clear-the-list"), armTheClear);
  if (state.armedToClear) { button.className = "danger"; }
  replaceChildren(target, [button]);
}

function cancelJob(job) {
  postJson("./jobs/cancel", { job_id: job.job_id })
    .then(loadJobs)
    .catch(function (problem) {
      showProblem(document.getElementById("form-problem"), problem.message);
    });
}

// ---- loading ----------------------------------------------------------------------------------

function loadJobs() {
  return api("./jobs").then(function (payload) {
    state.jobs = payload.jobs || [];
    renderJobs();
  }).catch(function (problem) {
    replaceChildren(document.getElementById("pending"), [element("p", "stop", problem.message)]);
  });
}

function loadPrinter() {
  return api("./printer").then(function (payload) {
    state.printer = payload;
    renderPrinter();
    renderPreferences();
    // A job held for the bed says different things depending on what the printer shows, and
    // the two requests land in whichever order they land in. Redrawn here so a row is never a
    // poll behind the printer it describes.
    renderJobs();
  }).catch(function (problem) {
    document.getElementById("printer-line").textContent = problem.message;
  });
}

function loadFiles() {
  return api("./files").then(function (payload) {
    var arrived = payload.files || [];
    // Redrawing a list somebody is scrolling loses their place and makes every lazy thumbnail
    // request itself again. On a poll that is nearly always a no-op, so the list is only
    // rebuilt when it has actually changed, and the common case disturbs nothing at all.
    if (state.files.length && signatureOf(arrived) === signatureOf(state.files)) {
      state.files = arrived;
      return;
    }
    state.files = arrived;
    renderFiles();
    // The job rows take their pictures from this list, and the two requests land in whichever
    // order they land in, so the jobs are redrawn once the files are known.
    renderJobs();
  }).catch(function (problem) {
    showProblem(document.getElementById("form-problem"), problem.message);
  });
}

// Everything the list draws from, and nothing else: a thumbnail appearing or a file being
// reprinted should redraw, the order of two unrelated fields should not.
function signatureOf(files) {
  return files.map(function (file) {
    return [file.filename, file.modified, file.last_printed, file.estimated_seconds,
            file.has_thumbnail].join("\u0001");
  }).join("\u0002");
}

function whenDay(epochSeconds) {
  if (!epochSeconds) { return null; }
  var moment = new Date(epochSeconds * 1000);
  var today = new Date();
  var sameDay = moment.toDateString() === today.toDateString();
  return sameDay ? moment.toLocaleTimeString() : moment.toLocaleDateString();
}

function describeFile(file) {
  var parts = [];
  var sliced = whenDay(file.modified);
  if (sliced) { parts.push(t("page.sliced", { when: sliced })); }
  var printed = whenDay(file.last_printed);
  // Said out loud rather than left blank: on a page that starts prints unattended, a file
  // nobody has ever run is worth knowing about before six in the morning.
  parts.push(printed ? t("page.printed", { when: printed }) : t("page.never-printed"));
  var duration = howLong(file.estimated_seconds);
  if (duration) { parts.push(duration); }
  return joinedWith("list.separator-dot", parts);
}

function renderFileRow(file) {
  var row = element("button", "file");
  row.type = "button";
  row.setAttribute("aria-pressed", file.filename === state.chosen ? "true" : "false");
  row.dataset.filename = file.filename;
  if (file.has_thumbnail) {
    var picture = document.createElement("img");
    picture.loading = "lazy";
    picture.alt = "";
    picture.src = "./thumbnail?filename=" + encodeURIComponent(file.filename);
    row.appendChild(picture);
  } else {
    row.appendChild(element("span", "noshot"));
  }
  var lines = element("span");
  lines.appendChild(element("span", "file-name", file.filename));
  lines.appendChild(element("div", "quiet", describeFile(file)));
  row.appendChild(lines);
  row.addEventListener("click", function () { chooseFile(file.filename); });
  return row;
}

// Every order breaks its ties on the name, so the same list always comes out the same way and
// nothing shuffles under you between refreshes.
var HOW_TO_SORT = {
  newest: function (a, b) { return b.modified - a.modified || byName(a, b); },
  oldest: function (a, b) { return a.modified - b.modified || byName(a, b); },
  // Never printed is zero, which lands at the bottom of this one, where it belongs.
  printed: function (a, b) { return b.last_printed - a.last_printed || byName(a, b); },
  name: byName,
  "name-back": function (a, b) { return byName(b, a); }
};

function byName(a, b) {
  return a.filename.localeCompare(b.filename);
}

function matchingFiles() {
  var needle = document.getElementById("file-search").value.trim().toLowerCase();
  var chosen = HOW_TO_SORT[document.getElementById("file-sort").value] || HOW_TO_SORT.newest;
  var matching = needle
    ? state.files.filter(function (file) {
        return file.filename.toLowerCase().indexOf(needle) >= 0;
      })
    : state.files.slice();
  return matching.sort(chosen);
}

function renderFiles() {
  var matching = matchingFiles();
  var drawn = matching.slice(0, MOST_FILES_TO_DRAW);
  replaceChildren(document.getElementById("file-list"),
    drawn.length ? drawn.map(renderFileRow)
                 : [element("p", "quiet", t("page.no-file-matches"))]);
  var count = document.getElementById("file-count");
  count.textContent = matching.length > drawn.length
    ? t("page.showing-some-files", { drawn: drawn.length, total: matching.length })
    : "";
}

function chooseFile(filename) {
  state.chosen = filename;
  renderFiles();
  loadSummary(filename);
  refreshSaveButton();
}

function loadSummary(filename) {
  if (!filename) { state.summary = null; renderFileFacts(); refreshSaveButton(); return; }
  api("./file?filename=" + encodeURIComponent(filename)).then(function (payload) {
    state.summary = payload;
    renderFileFacts();
    refreshSaveButton();
  }).catch(function () {
    state.summary = null;
    renderFileFacts();
  });
}

// showPicker throws when the browser decides the call was not user activated, and it is absent
// on anything older, so both are handled rather than left to become a console error.
document.getElementById("pick-time").addEventListener("click", function () {
  var when = document.getElementById("start-at");
  if (typeof when.showPicker !== "function") { when.focus(); return; }
  try { when.showPicker(); } catch (unavailable) { when.focus(); }
});

document.getElementById("file-search").addEventListener("input", renderFiles);
document.getElementById("file-sort").addEventListener("change", renderFiles);
document.getElementById("start-at").addEventListener("input", refreshSaveButton);
document.getElementById("bed-clear").addEventListener("change", refreshSaveButton);
document.getElementById("save").addEventListener("click", save);
document.getElementById("stop-editing").addEventListener("click", stopEditing);

function renderStartHelp() {
  document.getElementById("start-help").textContent =
    t("page.start-help", { zone: Intl.DateTimeFormat().resolvedOptions().timeZone });
}

// Only drawn when there is a choice to make. One language installed is not a choice, and a
// select with a single entry is furniture.
function renderLanguagePicker() {
  var target = document.getElementById("language-pick");
  var tags = Object.keys(CATALOGUES);
  if (tags.length < 2) { replaceChildren(target, []); return; }
  var label = element("label", "quiet", t("page.language"));
  label.htmlFor = "language";
  var select = document.createElement("select");
  select.id = "language";
  // First, and the way back: picking it forgets the choice, so the printer's own setting
  // reaches this reader again the next time somebody changes it.
  select.appendChild(anOption("", t("page.follow-the-printer", {
    language: languageCalledInItself(PRINTER_LANGUAGE)
  })));
  tags.forEach(function (tag) { select.appendChild(anOption(tag, languageCalledInItself(tag))); });
  select.value = rememberedLanguage();
  select.addEventListener("change", function () {
    rememberLanguage(select.value);
    language = languageNow();
    redrawEverything();
  });
  var wrapper = element("span", "picker");
  wrapper.appendChild(select);
  replaceChildren(target, [label, wrapper]);
}

function anOption(value, text) {
  var option = document.createElement("option");
  option.value = value;
  option.textContent = text;
  return option;
}

// Each language names itself, in itself, so the list reads the same whatever the page is in.
function languageCalledInItself(tag) {
  var named = (CATALOGUES[tag] || {})["language.name"];
  return typeof named === "string" ? named : tag;
}

// Everything that holds text, after a language changes. The checkboxes are rebuilt rather than
// relabelled, so their state is carried over by hand; losing a levelling choice to a change of
// language would be a quiet way to ruin a print.
function redrawEverything() {
  var levelling = preferenceValue("level-bed");
  var timelapse = preferenceValue("record-timelapse");
  applyStaticText();
  replaceChildren(document.getElementById("preferences"), []);
  renderPreferences();
  setPreference("level-bed", levelling);
  setPreference("record-timelapse", timelapse);
  if (state.editing) {
    document.getElementById("form-heading").textContent = t("page.edit-this-job");
    document.getElementById("save").textContent = t("page.save-changes");
  }
  renderStartHelp();
  renderLanguagePicker();
  renderPrinter();
  renderFiles();
  renderFileFacts();
  renderJobs();
  refreshSaveButton();
}

applyStaticText();
renderStartHelp();
renderLanguagePicker();

loadPrinter();
loadFiles();
loadJobs();
// Only the lists and the printer line are redrawn, never the form, so a refresh cannot swallow
// what someone is halfway through typing.
setInterval(function () { loadPrinter(); loadJobs(); }, REFRESH_MILLISECONDS);
// Slower than the other two, because a directory read costs the printer more than a status
// query, and skipped entirely while the tab is hidden: a page left open all day should not ask
// a printer to walk its gcode directory four times a minute for nobody to look at.
setInterval(function () {
  if (document.visibilityState === "hidden") { return; }
  loadFiles();
}, FILES_REFRESH_MILLISECONDS);
// And caught up the moment somebody comes back to the tab, so returning to it never shows a
// list that is a poll behind.
document.addEventListener("visibilitychange", function () {
  if (document.visibilityState === "visible") { loadFiles(); }
});
</script>
</body>
</html>
"""


def render_schedule_page(service_version: str, language: str = ENGLISH) -> str:
    """Render the scheduler page, carrying every catalogue and starting in one of them.

    Every catalogue goes into the page rather than being fetched: they are a few kilobytes, it
    saves a round trip, and it is what lets a reader choose a language for themselves without
    the printer serving a different page to everybody else. They are read here rather than at
    import time, so editing one over SSH shows up on the next reload.
    """
    catalogues = {tag: catalogue(tag) for tag in known_tags()}
    chosen = language if language in catalogues else ENGLISH
    return (
        PAGE_TEMPLATE.replace("__VERSION__", service_version)
        .replace("__CATALOGUES__", _inside_a_script(catalogues))
        .replace("__LANGUAGE__", chosen)
    )


def _inside_a_script(value: Any) -> str:
    """JSON that cannot end the script element it sits in, whatever a translator wrote."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")
