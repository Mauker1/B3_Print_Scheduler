# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scheduler page.

Two rules govern everything in this module, and both of them shipped as real defects in a sibling
plugin while every server-side test passed.

Every URL this page emits is relative. nginx publishes the plugin under a prefix and strips it
before proxying, so the service never learns what the browser called it. An absolute path here
points at the printer dashboard instead of at us, and it tests perfectly against the service port.

No form control may share a name with a property of HTMLFormElement. A named control is exposed as a
property of its own form, so a control named "action" makes form.action return that control instead
of the URL. A script reading form.action then fetches "[object HTMLButtonElement]", gets a 404, and
falls back to form.submit(), which does not include the submitter, so the fallback posts every field
except the one that mattered, and the page honestly reports that nothing was asked of it.

test_page.py asserts both as properties of the rendered HTML rather than as the strings that happen
to satisfy them today.
"""

from __future__ import annotations

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Print Scheduler</title>
<style>
:root { color-scheme: light dark; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  margin: 0 auto; max-width: 42rem; padding: 1.5rem 1rem; line-height: 1.5;
}
h1 { font-size: 1.4rem; margin: 0 0 0.25rem; }
p.lede { margin: 0 0 1.5rem; opacity: 0.75; }
section { border: 1px solid rgba(128,128,128,0.35); border-radius: 0.5rem; padding: 1rem; }
h2 { font-size: 1rem; margin: 0 0 0.5rem; }
ul { margin: 0; padding-left: 1.25rem; }
li.empty { list-style: none; margin-left: -1.25rem; opacity: 0.7; }
footer { margin-top: 1.5rem; font-size: 0.85rem; opacity: 0.6; }
</style>
</head>
<body>
<h1>Print Scheduler</h1>
<p class="lede">Scheduling is not built yet. This page confirms the plugin installed,
started, and is reachable through its own nginx location.</p>

<section>
<h2>Scheduled jobs</h2>
<ul id="job-list"><li class="empty">Loading...</li></ul>
</section>

<footer>print-scheduler __VERSION__</footer>

<script>
// Relative, always. See the module docstring: the prefix this page is served under is unknown here.
fetch("./jobs", { headers: { "Accept": "application/json" } })
  .then(function (response) {
    if (!response.ok) { throw new Error("jobs returned " + response.status); }
    return response.json();
  })
  .then(function (payload) {
    var list = document.getElementById("job-list");
    list.textContent = "";
    if (!payload.jobs || payload.jobs.length === 0) {
      var empty = document.createElement("li");
      empty.className = "empty";
      empty.textContent = "Nothing scheduled.";
      list.appendChild(empty);
      return;
    }
    payload.jobs.forEach(function (job) {
      var row = document.createElement("li");
      row.textContent = job.filename;
      list.appendChild(row);
    });
  })
  .catch(function (problem) {
    var list = document.getElementById("job-list");
    list.textContent = "";
    var failed = document.createElement("li");
    failed.className = "empty";
    failed.textContent = "Could not read the schedule: " + problem.message;
    list.appendChild(failed);
  });
</script>
</body>
</html>
"""


def render_schedule_page(service_version: str) -> str:
    """Render the scheduler page for the given service version."""
    return PAGE_TEMPLATE.replace("__VERSION__", service_version)
