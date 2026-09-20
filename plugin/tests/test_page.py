# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two cheap assertions standing in for a browser the gate does not have.

Both correspond to a defect that shipped in a sibling plugin and that every server-side test passed
straight through. They are written as properties of the rendered page rather than as the strings
that happen to satisfy them today, so they keep their value as the page grows.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

import print_scheduler

PAGE = print_scheduler.render_schedule_page("0.0.0-test")

URL_ATTRIBUTES = frozenset({"href", "src", "action", "formaction", "data", "poster"})

CONTROL_TAGS = frozenset({"button", "fieldset", "input", "object", "output", "select", "textarea"})

# A named form control is exposed as a property of its own form, so any of these names shadows the
# real property. See the module docstring of print_scheduler.page for what that costs.
FORM_ELEMENT_PROPERTIES = frozenset({
    "accept-charset", "acceptcharset", "action", "autocomplete", "checkvalidity", "elements",
    "encoding", "enctype", "length", "method", "name", "novalidate", "rel", "rellist",
    "reportvalidity", "requestsubmit", "reset", "submit", "target",
})

FETCH_BY_ABSOLUTE_PATH = re.compile(r"""fetch\(\s*["']/""")


class PageInspector(HTMLParser):
    """Collects the URLs a page emits and the names of its form controls."""

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []
        self.control_names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name: value for name, value in attrs if value is not None}
        for attribute in URL_ATTRIBUTES & attributes.keys():
            self.urls.append(attributes[attribute])
        control_name = attributes.get("name")
        if tag in CONTROL_TAGS and control_name is not None:
            self.control_names.append(control_name)


def inspect_page() -> PageInspector:
    inspector = PageInspector()
    inspector.feed(PAGE)
    return inspector


def test_the_page_emits_no_absolute_path_of_its_own() -> None:
    # nginx strips the prefix this page is published under and never tells the service what it was,
    # so an absolute path points at the printer dashboard. It tests perfectly against the service
    # port, which is exactly why this assertion is here and not in a browser.
    assert [url for url in inspect_page().urls if url.startswith("/")] == []


def test_the_page_script_fetches_nothing_by_absolute_path() -> None:
    assert FETCH_BY_ABSOLUTE_PATH.search(PAGE) is None


def test_no_form_control_shadows_a_property_of_its_form() -> None:
    shadowing = [
        name for name in inspect_page().control_names if name.lower() in FORM_ELEMENT_PROPERTIES
    ]
    assert shadowing == []


def test_the_page_reports_the_service_version() -> None:
    assert "0.0.0-test" in PAGE
    assert "__VERSION__" not in PAGE
