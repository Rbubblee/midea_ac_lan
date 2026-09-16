#!/usr/bin/env python3
"""Decide whether a new upstream release can be published from this fork.

The fork exists for exactly one reason: it keeps `midea-lan` pinned to a build
that carries the probe fixes for wuwentao/midea_ac_lan#658 while the library
change is being reviewed upstream (wuwentao/midea-lan#113). Everything else in
this repository tracks upstream.

This script is read-only. It looks at the newest upstream release, at the
library version that release expects, and at the fix build in the library fork,
then reports what the workflow should do:

    pin       merge upstream, re-apply the pin, publish the release
    official  upstream does not need the pin (it ships the fix, or points
              somewhere else itself), publish upstream's requirement as-is
    blocked   publishing would pair this integration with a library build that
              is older than the one upstream expects; leave the fork alone and
              open an issue instead of shipping something that may not work

Outputs are written to $GITHUB_OUTPUT when running in Actions, and printed as
JSON otherwise, so the decision can be checked locally.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

MANIFEST_PATH = "custom_components/midea_ac_lan/manifest.json"
LIBRARY_NAME = "midea-lan"
FIX_MARKER = "def build_query_fallback"
REQUEST_TIMEOUT = 30


def setting(name: str, default: str) -> str:
    """Return an environment override or the default."""
    return os.environ.get(name) or default


def gh_api(path: str) -> object | None:
    """Return the parsed JSON for an API path, or None when it is missing."""
    result = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def raw_file(url: str) -> str | None:
    """Return the text of a raw URL, or None when it cannot be fetched."""
    # Branch names may contain non-ASCII characters (the fix branch is named
    # after the appliance it targets), and those have to be percent-encoded
    # before urllib will even send the request.
    url = urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~")
    try:
        with urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None


def archive_url(repo: str, branch: str) -> str:
    """Return the source archive URL of a branch, encoded for use in a URL."""
    return (
        f"https://github.com/{repo}/archive/refs/heads/"
        f"{urllib.parse.quote(branch)}.zip"
    )


def version_key(value: str) -> tuple[int, ...]:
    """Return a sortable key for a version string (good enough for calver)."""
    digits = tuple(int(part) for part in re.findall(r"\d+", value))
    return digits or (0,)


def library_requirement(requirements: list[str]) -> str | None:
    """Return the midea-lan entry of a manifest requirements list."""
    for entry in requirements:
        name = re.split(r"\s*[=<>!\s@]", entry.strip(), maxsplit=1)[0]
        if name == LIBRARY_NAME:
            return entry.strip()
    return None


def required_version(entry: str | None) -> str | None:
    """Return the pinned version of a requirement, if it is a plain pin."""
    if entry and "==" in entry:
        return entry.split("==", 1)[1].strip()
    return None


def emit(outputs: dict[str, str], exit_code: int = 0) -> int:
    """Write the decision to $GITHUB_OUTPUT (or stdout) and exit."""
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            for key, value in outputs.items():
                handle.write(f"{key}={value}\n")
    else:
        print(json.dumps(outputs, indent=2, ensure_ascii=False))
    return exit_code


def main() -> int:
    """Report what to do about the newest upstream release."""
    fork = setting("FORK_REPO", os.environ.get("GITHUB_REPOSITORY", ""))
    upstream = setting("UPSTREAM_REPO", "wuwentao/midea_ac_lan")
    library_upstream = setting("LIB_UPSTREAM_REPO", "wuwentao/midea-lan")
    pin_repo = setting("PIN_REPO", "Rbubblee/midea-lan")
    pin_branch = setting("PIN_BRANCH", "personal/ac-probe-fallback-fix（针对星光PRO修订）")

    release = gh_api(f"repos/{upstream}/releases/latest")
    if not isinstance(release, dict) or "tag_name" not in release:
        return emit(
            {
                "skip": "true",
                "mode": "none",
                "reason": f"{upstream} has no published release to mirror",
            },
        )
    tag = release["tag_name"]

    # A forced re-pin (workflow_dispatch input) only rewrites the manifest, so
    # an already mirrored release must not make the workflow bail out.
    force_repin = (os.environ.get("FORCE_REPIN") or "").lower() in {"1", "true", "yes"}

    if gh_api(f"repos/{fork}/releases/tags/{tag}") is not None and not force_repin:
        return emit(
            {
                "skip": "true",
                "mode": "none",
                "tag": tag,
                "reason": f"release {tag} is already published in {fork}",
            },
        )

    base_outputs = {
        "skip": "false",
        "tag": tag,
        "repin_only": "true" if force_repin else "false",
    }

    manifest_text = raw_file(
        f"https://raw.githubusercontent.com/{upstream}/{tag}/{MANIFEST_PATH}",
    )
    if manifest_text is None:
        return emit(
            {
                **base_outputs,
                "skip": "true",
                "mode": "none",
                "reason": f"cannot read {MANIFEST_PATH} at {tag}",
            },
        )

    manifest = json.loads(manifest_text)
    entry = library_requirement(manifest.get("requirements", []))
    if entry is None:
        # The integration stopped depending on midea-lan at all: that changes
        # how it is packaged, so let a human look at it before publishing.
        return emit(
            {
                **base_outputs,
                "mode": "blocked",
                "reason": f"{tag} no longer depends on {LIBRARY_NAME};"
                " review the new packaging by hand",
            },
        )

    required = required_version(entry)
    if required is None:
        # Upstream already points the requirement somewhere else (a URL, a
        # range, ...): keep whatever it asks for instead of guessing.
        return emit(
            {
                **base_outputs,
                "mode": "official",
                "required": "",
                "reason": f"{tag} does not pin {LIBRARY_NAME} to a plain version"
                f" (requirement: {entry!r}); upstream's requirement is kept",
            },
        )

    base_outputs["required"] = required

    for candidate in (f"v{required}", required):
        released = raw_file(
            f"https://raw.githubusercontent.com/{library_upstream}/{candidate}"
            "/midealan/device.py",
        )
        if released and FIX_MARKER in released:
            return emit(
                {
                    **base_outputs,
                    "mode": "official",
                    "reason": f"{library_upstream} {candidate} already carries the"
                    " #658 fixes; keeping the official requirement",
                },
            )

    build_device = raw_file(
        f"https://raw.githubusercontent.com/{pin_repo}/{pin_branch}/midealan/device.py",
    )
    build_version_file = raw_file(
        f"https://raw.githubusercontent.com/{pin_repo}/{pin_branch}/midealan/version.py",
    )
    if not build_device or FIX_MARKER not in build_device:
        return emit(
            {
                **base_outputs,
                "mode": "blocked",
                "reason": f"{pin_repo}@{pin_branch} does not carry the #658 fixes",
            },
        )

    match = re.search(r'__version__\s*=\s*"([^"]+)"', build_version_file or "")
    build_base = match.group(1) if match else ""
    base_outputs["build_base"] = build_base
    if not build_base or version_key(build_base) < version_key(required):
        return emit(
            {
                **base_outputs,
                "mode": "blocked",
                "reason": f"the fix build is based on {LIBRARY_NAME} {build_base or '?'}"
                f" but {tag} expects {required}; rebase the fix branch first",
            },
        )

    return emit(
        {
            **base_outputs,
            "mode": "pin",
            "pin_url": f"{LIBRARY_NAME} @ {archive_url(pin_repo, pin_branch)}",
            "reason": f"mirror {tag} with the fix build based on {LIBRARY_NAME}"
            f" {build_base}",
        },
    )


if __name__ == "__main__":
    sys.exit(main())
