#!/usr/bin/env python3
"""Build the release asset HACS downloads for this integration.

hacs.json asks for a zip release (`"zip_release": true`) named
`midea_ac_lan.zip`, so the asset -- not the source archive -- is what HACS
installs. Upstream builds it with `zip -r ../midea_ac_lan.zip ./*` from inside
`custom_components/midea_ac_lan`, i.e. the integration files sit at the root of
the archive; this reproduces that layout without needing the zip binary.
"""

from __future__ import annotations

import pathlib
import sys
import zipfile

SOURCE = pathlib.Path("custom_components/midea_ac_lan")
DEFAULT_OUTPUT = pathlib.Path("/tmp/midea_ac_lan.zip")


def main() -> int:
    """Write the integration files into the release asset."""
    output = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    files = sorted(
        path
        for path in SOURCE.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    if not files:
        print(f"no files found under {SOURCE}", file=sys.stderr)
        return 1
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(SOURCE).as_posix())
    print(f"wrote {output} with {len(files)} entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
