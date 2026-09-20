# SPDX-FileCopyrightText: Copyright (C) 2026 Mauker and the Bespok3d contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The promises that only fail after an install.

Nothing here can be caught by running the service locally: a placed file missing from the package, a
service argument naming a file that does not exist, a port declared in one place and bound in
another, an nginx location publishing a path the service does not serve. Each of these has broken a
real plugin, and each is cheap to assert before there is anything at stake.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import print_scheduler

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PLUGIN_ROOT / "manifest.json"
NGINX_PATH = PLUGIN_ROOT / "files" / "etc" / "nginx" / "locations" / "print-scheduler.conf"

MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
NGINX = NGINX_PATH.read_text(encoding="utf-8")

SERVICE: dict[str, Any] = MANIFEST["install"]["service"][0]
SERVICE_ARGS: list[str] = SERVICE["args"]
ENDPOINT_PATH: str = MANIFEST["endpoints"][0]["path"]

# Paths inside the installed plugin. The documented layout keeps the files/ segment, so what
# follows the prefix is the path relative to this directory.
INSTALLED_PREFIX = "$BESPOK3D_PLUGINS/print-scheduler/"
# Only what is under files/ is shipped. user_vars.json sits beside it under the same prefix, but
# the daemon writes that at install time, so it is not in the package and is not asserted on.
SHIPPED_SUBDIRECTORY = "files/"

LOCATION_PATTERN = re.compile(r"^\s*location\s+(=\s*)?(\S+)\s*\{", re.MULTILINE)
LOOPBACK_PROXY_PATTERN = re.compile(r"proxy_pass\s+http://127\.0\.0\.1:(\d+)")


def nginx_block(location_header: str) -> str:
    """Return the body of one location block, named by the text that follows `location `."""
    start = NGINX.index(f"location {location_header}")
    opening = NGINX.index("{", start)
    closing = NGINX.index("}", opening)
    return NGINX[opening + 1 : closing]


def nginx_exact_service_paths() -> set[str]:
    """Exact-match locations under this plugin's prefix, as the paths the service would receive."""
    paths = set()
    for exact, location in LOCATION_PATTERN.findall(NGINX):
        if not exact or not location.startswith(ENDPOINT_PATH):
            continue
        paths.add("/" + location[len(ENDPOINT_PATH) :])
    return paths


def test_the_publisher_is_left_for_the_signing_step() -> None:
    assert MANIFEST["publisher"] == "PLACEHOLDER"


def test_the_integrity_list_is_left_for_the_builder() -> None:
    assert MANIFEST["files"] == []


def test_the_manifest_version_matches_the_service() -> None:
    assert MANIFEST["version"] == print_scheduler.SERVICE_VERSION


def test_every_placed_file_is_in_the_package() -> None:
    for placement in MANIFEST["install"]["place"]:
        assert (PLUGIN_ROOT / placement["src"]).is_file(), placement["src"]


# The builder walks files/ and packs what it finds, gitignore or not, and the daemon refuses a
# package holding an archive member the manifest's files[] does not list. So a stray .pyc is a
# failed install, not a cosmetic problem. Running the tests once is enough to create one.
UNSHIPPABLE_NAMES = frozenset({"__pycache__", ".DS_Store", ".mypy_cache", ".ruff_cache"})
UNSHIPPABLE_SUFFIXES = frozenset({".pyc", ".pyo", ".orig", ".rej"})


def test_nothing_that_should_not_ship_is_under_files() -> None:
    strays = sorted(
        str(path.relative_to(PLUGIN_ROOT))
        for path in (PLUGIN_ROOT / "files").rglob("*")
        if path.name in UNSHIPPABLE_NAMES or path.suffix in UNSHIPPABLE_SUFFIXES
    )
    assert strays == []


def test_every_placed_class_carries_its_permission() -> None:
    for placement in MANIFEST["install"]["place"]:
        assert placement["class"] in MANIFEST["permissions"], placement["class"]


def test_placing_an_nginx_location_restarts_the_web_server() -> None:
    assert "web" in MANIFEST["install"]["restart"]


def test_declaring_a_supervised_service_carries_its_permission() -> None:
    assert "managed-service" in MANIFEST["permissions"]


def test_every_service_argument_naming_a_shipped_file_points_at_one() -> None:
    for argument in SERVICE_ARGS:
        if not argument.startswith(INSTALLED_PREFIX):
            continue
        relative = argument[len(INSTALLED_PREFIX) :]
        if not relative.startswith(SHIPPED_SUBDIRECTORY):
            continue
        assert (PLUGIN_ROOT / relative).is_file(), argument


def test_the_declared_port_is_the_one_the_service_is_told_to_bind() -> None:
    bound_port = int(SERVICE_ARGS[SERVICE_ARGS.index("--port") + 1])
    assert SERVICE["ports"] == [bound_port]


def test_every_service_option_is_one_the_parser_accepts() -> None:
    # The first two are the interpreter flag and the script path; the parser sees the rest.
    parsed = print_scheduler.build_argument_parser().parse_args(SERVICE_ARGS[2:])
    assert parsed.port == SERVICE["ports"][0]


def test_nginx_proxies_only_to_the_declared_port() -> None:
    proxied = {int(port) for port in LOOPBACK_PROXY_PATTERN.findall(NGINX)}
    assert proxied == set(SERVICE["ports"])


def test_the_advertised_endpoint_is_a_location_nginx_publishes() -> None:
    assert f"location {ENDPOINT_PATH} " in NGINX


def test_nginx_publishes_no_exact_path_the_service_does_not_serve() -> None:
    served = set(print_scheduler.GET_ROUTES) | set(print_scheduler.POST_ROUTES)
    assert nginx_exact_service_paths() <= served


def test_every_endpoint_that_changes_the_schedule_is_behind_the_subrequest() -> None:
    # The page itself is not, on purpose. Everything that reads or writes the schedule is.
    for path in print_scheduler.POST_ROUTES:
        assert "auth_request" in nginx_block(f"= {ENDPOINT_PATH.rstrip('/')}{path}"), path


def test_the_schedule_endpoint_is_behind_the_authentication_subrequest() -> None:
    assert "auth_request" in nginx_block(f"= {ENDPOINT_PATH}jobs")


def test_the_health_endpoint_is_not_behind_it() -> None:
    # It is what you curl when Moonraker is the thing that is broken.
    assert "auth_request" not in nginx_block(f"= {ENDPOINT_PATH}health")


def test_the_authentication_location_is_named_for_this_plugin() -> None:
    # Two placed location files defining the same location name is an nginx config error, and
    # u1-remote-screen already ships `location = /auth_check`. Both can be installed at once.
    # Match the directive, not the word: this file explains the collision in a comment.
    assert "location = /auth_check" not in NGINX
    assert "internal;" in nginx_block("= /print-scheduler-auth")


def test_every_config_key_is_also_a_declared_variable() -> None:
    # Two declarations for one value is the convention in every reference plugin, not an oversight.
    declared = {variable["name"] for variable in MANIFEST["requires"]["variables"]}
    assert {entry["key"] for entry in MANIFEST["config"]} == declared
