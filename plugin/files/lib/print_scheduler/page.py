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

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
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
h2 { font-size: 1rem; margin: 0 0 0.6rem; }
section { border: 1px solid var(--line); border-radius: 0.6rem; padding: 1rem;
  margin-bottom: 1.1rem; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.15rem; }
select, input[type=datetime-local] { width: 100%; padding: 0.45rem; font: inherit;
  border: 1px solid var(--line); border-radius: 0.35rem; background: transparent; color: inherit; }
.row { margin-bottom: 0.8rem; }
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
.job { border-top: 1px solid var(--line); padding: 0.7rem 0; }
.job:first-child { border-top: 0; }
.job-title { font-weight: 600; overflow-wrap: anywhere; }
.job-actions { margin-top: 0.35rem; display: flex; gap: 0.3rem; flex-wrap: wrap; }
.tools { display: flex; gap: 0.6rem; flex-wrap: wrap; margin: 0.5rem 0; }
.tool { display: flex; align-items: center; gap: 0.35rem; font-size: 0.85rem; }
.swatch { width: 0.95rem; height: 0.95rem; border-radius: 50%; border: 1px solid var(--line); }
.facts { font-size: 0.85rem; color: var(--quiet); }
footer { font-size: 0.8rem; color: var(--quiet); }
</style>
</head>
<body>
<h1>Print Scheduler</h1>
<p class="quiet" id="printer-line">Asking the printer...</p>
<div id="clock-warning"></div>

<section>
<h2 id="form-heading">Schedule a print</h2>
<div class="row">
  <label for="file-choice">File already on the printer</label>
  <select id="file-choice"><option value="">Loading...</option></select>
</div>
<div id="file-facts"></div>
<div class="row">
  <label for="start-at">Start it at</label>
  <input type="datetime-local" id="start-at">
  <p class="quiet" id="start-help"></p>
</div>
<div id="preferences"></div>
<div class="check">
  <input type="checkbox" id="bed-clear">
  <label for="bed-clear">The bed will be clear. The printer cannot see it, so this is your word,
  not a check.</label>
</div>
<div class="job-actions">
  <button class="primary" id="save" disabled>Schedule it</button>
  <button class="link" id="stop-editing" hidden>Stop editing</button>
</div>
<div id="form-problem"></div>
</section>

<section>
<h2>Scheduled</h2>
<div id="pending"><p class="quiet">Loading...</p></div>
</section>

<section>
<h2>Already settled</h2>
<div id="settled"><p class="quiet">Loading...</p></div>
</section>

<footer>print-scheduler __VERSION__</footer>

<script>
// Relative, always. This page is published under a prefix it is never told about, so an absolute
// path here would point at the printer dashboard rather than at this plugin.
var CLOCK_SKEW_TOLERANCE_SECONDS = 120;
var REFRESH_MILLISECONDS = 10000;

var state = { jobs: [], printer: null, summary: null, editing: null, setup: null };

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
        throw new Error("The printer did not accept this request. Sign in to the printer's web " +
                        "interface in another tab, then reload this page.");
      }
      throw new Error(payload.error || ("the request failed with status " + response.status));
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
  if (!epochSeconds) { return "an unknown time"; }
  return new Date(epochSeconds * 1000).toLocaleString();
}

function howLong(seconds) {
  if (!seconds) { return null; }
  // A 26 second file exists on this printer, and "about 0m" helps nobody.
  if (seconds < 60) { return Math.round(seconds) + "s"; }
  var hours = Math.floor(seconds / 3600);
  var minutes = Math.round((seconds % 3600) / 60);
  return hours ? (hours + "h " + minutes + "m") : (minutes + "m");
}

function setupVaries(setup) {
  if (!setup) { return false; }
  var shortest = howLong(setup.shortest);
  var longest = howLong(setup.longest);
  return Boolean(shortest && longest && shortest !== longest);
}

function describeSetup(setup) {
  if (!setup) { return null; }
  if (setupVaries(setup)) { return howLong(setup.shortest) + " to " + howLong(setup.longest); }
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
    return "should finish between " + whenLocal(from) + " and " +
      (sameDay(from, to) ? whenLocalTime(to) : whenLocal(to));
  }
  return "should finish around " + whenLocal(job.projected_finish) +
    (setup ? "" : ", not counting the printer's setup");
}

function showProblem(target, message) {
  replaceChildren(target, message ? [element("p", "stop", message)] : []);
}

// ---- the printer line -------------------------------------------------------------------------

function describePrinter(printer) {
  if (!printer.reachable) { return "The printer is not answering: " + printer.klipper_message; }
  if (printer.print_state === "printing") { return "Printing " + printer.printing_filename; }
  if (printer.print_state === "complete") {
    return "A finished print has not been dismissed, so the bed is presumed occupied.";
  }
  if (printer.print_state === "cancelled") {
    return "A cancelled print has not been dismissed, so the bed is presumed occupied.";
  }
  if (printer.klipper_state !== "ready") { return "Klipper reports " + printer.klipper_state; }
  return "Idle and ready.";
}

function renderPrinter() {
  var printer = state.printer;
  if (!printer) { return; }
  var tolerance = Math.round(printer.tolerance_minutes);
  document.getElementById("printer-line").textContent =
    describePrinter(printer) + " A job may start up to " + tolerance +
    (tolerance === 1 ? " minute" : " minutes") + " late.";

  var skew = Math.abs(printer.printer_time - (Date.now() / 1000));
  var warning = document.getElementById("clock-warning");
  if (skew > CLOCK_SKEW_TOLERANCE_SECONDS) {
    replaceChildren(warning, [element("p", "warn",
      "This device's clock and the printer's differ by about " + Math.round(skew / 60) +
      " minutes. Times you pick are sent as an exact instant, so scheduling still works, but one " +
      "of the two clocks is wrong.")]);
  } else {
    replaceChildren(warning, []);
  }
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

function describeSlot(tool, plan) {
  var assignment = assignmentFor(plan, tool.slot);
  var text = "slot " + tool.slot + " " + (tool.filament_type || "filament");
  if (tool.used_grams) { text += " " + tool.used_grams.toFixed(1) + " g"; }
  // A toolhead is named only when one was chosen. Saying "no toolhead" where the printer does
  // not report what is loaded reads as a machine with no toolhead, which is not the situation:
  // there is simply nothing to choose between. Where a choice failed, the refusal says so
  // below in its own words, and repeating it on every row adds nothing.
  return assignment ? text + " on T" + assignment.toolhead : text;
}

function mismatchedColours(plan) {
  if (!plan || !plan.assignments) { return []; }
  // Both values, because the difference is often a typo's worth and a bare "they differ"
  // reads as a wrong spool when it is nothing of the kind.
  return plan.assignments.filter(function (one) { return one.colours_differ; })
    .map(function (one) {
      return "slot " + one.slot + " on T" + one.toolhead +
        " (#" + one.wanted_colour + " against #" + one.loaded_colour + ")";
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
    parts.push(element("p", "quiet", "This file does not say what material it needs."));
  }

  var facts = [];
  var duration = howLong(summary.estimated_seconds);
  if (duration) { facts.push("about " + duration); }
  if (summary.bed_temperature) { facts.push("bed " + summary.bed_temperature + "C"); }
  if (summary.chamber_temperature) { facts.push("chamber " + summary.chamber_temperature + "C"); }
  if (summary.layer_count) { facts.push(summary.layer_count + " layers"); }
  if (facts.length) { parts.push(element("p", "facts", facts.join(", "))); }

  if (summary.plan && !summary.plan.applicable && summary.tools.length > 1) {
    parts.push(element("p", "quiet",
      "This printer does not report what each toolhead holds, so the file's own tool numbering " +
      "is used as it was sliced."));
  }

  if (summary.plan && summary.plan.problem) {
    parts.push(element("p", "stop", summary.plan.problem));
  } else if (mismatchedColours(summary.plan).length) {
    parts.push(element("p", "warn",
      "The nearest colour loaded is not the colour this file was sliced for: " +
      mismatchedColours(summary.plan).join("; ") +
      ". The material matches, so it will print."));
  }
  replaceChildren(target, parts);
}

function renderPreferences() {
  var target = document.getElementById("preferences");
  if (!state.printer || !state.printer.supports_print_preferences) {
    replaceChildren(target, []);
    return;
  }
  if (document.getElementById("level-bed")) { return; }
  replaceChildren(target, [
    checkbox("level-bed", "Level the bed before this print", true),
    checkbox("record-timelapse", "Record a timelapse", true),
    element("p", "quiet", "These are the printer's own per-print settings, the same ones its app " +
            "asks about. A plugin that forces one will override the choice made here.")
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
  if (job.state === "scheduled") { return "Starts " + whenLocal(job.start_at); }
  if (job.state === "starting") { return "Starting now, waiting for the printer to pick it up"; }
  if (job.state === "started") { return "Started " + whenLocal(job.decided_at); }
  return "Did not run. " + (job.detail || "");
}

function renderJob(job) {
  var card = element("div", "job");
  card.appendChild(element("div", "job-title", job.filename));
  card.appendChild(element("div", "quiet", jobHeadline(job)));

  if (job.state === "scheduled" && job.projected_finish) {
    var printing = howLong(job.estimated_seconds);
    var setup = describeSetup(state.setup);
    if (setup && printing) {
      card.appendChild(element("div", "facts",
        "about " + setup + " of setup, then " + printing + " of printing"));
    }
    card.appendChild(element("div", "facts", describeFinish(job, state.setup)));
  }
  if (job.overlaps_with) {
    card.appendChild(element("p", "warn",
      "An earlier job is projected to still be printing when this one is due, so this one " +
      "would be cancelled as busy."));
  }
  if (job.printer_says) {
    card.appendChild(element("div", "facts", "The printer says: " + job.printer_says));
  } else if (job.state === "started") {
    card.appendChild(element("div", "facts", "The printer has no record of how it went."));
  }

  var actions = element("div", "job-actions");
  if (job.state === "scheduled") {
    actions.appendChild(actionButton("Edit", function () { startEditing(job); }));
    actions.appendChild(actionButton("Cancel", function () { cancelJob(job); }));
  }
  actions.appendChild(actionButton("Schedule another like this", function () { copyInto(job); }));
  card.appendChild(actions);
  return card;
}

function actionButton(label, whenClicked) {
  var button = element("button", "link", label);
  button.type = "button";
  button.addEventListener("click", whenClicked);
  return button;
}

function renderJobs() {
  var pending = state.jobs.filter(function (job) {
    return job.state === "scheduled" || job.state === "starting";
  });
  var settled = state.jobs.filter(function (job) {
    return job.state === "started" || job.state === "cancelled";
  }).reverse();

  replaceChildren(document.getElementById("pending"),
    pending.length ? pending.map(renderJob) : [element("p", "quiet", "Nothing scheduled.")]);
  replaceChildren(document.getElementById("settled"),
    settled.length ? settled.map(renderJob) : [element("p", "quiet", "Nothing yet.")]);
}

// ---- the form ---------------------------------------------------------------------------------

function refreshSaveButton() {
  var chosen = document.getElementById("file-choice").value;
  var when = document.getElementById("start-at").value;
  var acknowledged = document.getElementById("bed-clear").checked;
  // The one thing that makes a file unschedulable is that its slots cannot be given
  // toolheads. The service refuses it too; this is so the button says so first.
  var unplannable = state.summary && state.summary.plan && state.summary.plan.problem;
  document.getElementById("save").disabled =
    !chosen || !when || !acknowledged || Boolean(unplannable);
}

function startEditing(job) {
  state.editing = job.job_id;
  document.getElementById("form-heading").textContent = "Edit this job";
  document.getElementById("save").textContent = "Save changes";
  document.getElementById("stop-editing").hidden = false;
  fillForm(job, true);
}

function copyInto(job) {
  stopEditing();
  fillForm(job, false);
}

function stopEditing() {
  state.editing = null;
  document.getElementById("form-heading").textContent = "Schedule a print";
  document.getElementById("save").textContent = "Schedule it";
  document.getElementById("stop-editing").hidden = true;
  showProblem(document.getElementById("form-problem"), null);
}

function fillForm(job, keepTime) {
  document.getElementById("file-choice").value = job.filename;
  // Changing the file or the time clears the promise about the bed, because the promise was about
  // a particular moment and a particular thing on the plate.
  document.getElementById("bed-clear").checked = false;
  document.getElementById("start-at").value = keepTime ? localInputValue(job.start_at) : "";
  loadSummary(job.filename);
  refreshSaveButton();
  document.getElementById("form-heading").scrollIntoView({ block: "start" });
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
    filename: document.getElementById("file-choice").value,
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
    state.setup = payload.setup || null;
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
  }).catch(function (problem) {
    document.getElementById("printer-line").textContent = problem.message;
  });
}

function loadFiles() {
  return api("./files").then(function (payload) {
    var choice = document.getElementById("file-choice");
    var options = [element("option", null, "Choose a file")];
    options[0].value = "";
    (payload.filenames || []).forEach(function (filename) {
      var option = element("option", null, filename);
      option.value = filename;
      options.push(option);
    });
    replaceChildren(choice, options);
  }).catch(function (problem) {
    showProblem(document.getElementById("form-problem"), problem.message);
  });
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

document.getElementById("file-choice").addEventListener("change", function (event) {
  loadSummary(event.target.value);
});
document.getElementById("start-at").addEventListener("input", refreshSaveButton);
document.getElementById("bed-clear").addEventListener("change", refreshSaveButton);
document.getElementById("save").addEventListener("click", save);
document.getElementById("stop-editing").addEventListener("click", stopEditing);

document.getElementById("start-help").textContent =
  "Read in this device's timezone, " + Intl.DateTimeFormat().resolvedOptions().timeZone +
  ", and sent to the printer as an exact instant.";

loadPrinter();
loadFiles();
loadJobs();
// Only the lists and the printer line are redrawn, never the form, so a refresh cannot swallow
// what someone is halfway through typing.
setInterval(function () { loadPrinter(); loadJobs(); }, REFRESH_MILLISECONDS);
</script>
</body>
</html>
"""


def render_schedule_page(service_version: str) -> str:
    """Render the scheduler page for the given service version."""
    return PAGE_TEMPLATE.replace("__VERSION__", service_version)
