#!/usr/bin/env python3
"""Write the `midea-lan` requirement this fork needs into manifest.json.

The fork is upstream plus one line: `midea-lan` points at the fork build that
carries the #658 probe fixes instead of the release on PyPI. Merging upstream
replaces that line with upstream's own pin, so the workflow re-applies it here.

`--mode pin` needs `--url` (the requirement entry to write). `--mode official`
keeps whatever upstream asks for and is a no-op, used when upstream already
ships the fixes (see plan_sync.py).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

MANIFEST = pathlib.Path("custom_components/midea_ac_lan/manifest.json")
LIBRARY_NAME = "midea-lan"


def requirement_name(entry: str) -> str:
    """Return the distribution name of a requirement entry."""
    return re.split(r"\s*[=<>!\s@]", entry.strip(), maxsplit=1)[0]


def main() -> int:
    """Apply the requested requirement to the manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pin", "official"), required=True)
    parser.add_argument("--url", help="requirement entry to write with --mode pin")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    requirements = manifest.get("requirements", [])

    if args.mode == "official":
        print(f"keeping upstream's requirements as-is: {requirements!r}")
        return 0

    if not args.url or not args.url.startswith(LIBRARY_NAME):
        print("--mode pin needs --url starting with 'midea-lan'", file=sys.stderr)
        return 2

    for index, entry in enumerate(requirements):
        if requirement_name(entry) == LIBRARY_NAME:
            requirements[index] = args.url
            break
    else:
        # Upstream stopped depending on midea-lan at all. That is a real change
        # in how the integration is packaged, so refuse to guess rather than
        # publishing a release with an unexpected dependency set.
        print(f"manifest.json has no {LIBRARY_NAME} requirement to pin", file=sys.stderr)
        return 1

    manifest["requirements"] = requirements
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"pinned {LIBRARY_NAME} -> {args.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
