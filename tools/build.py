"""Package addon/ as dist/swarmAccess-<version>.nvda-addon.

An .nvda-addon file is a zip with manifest.ini at its root.  Run from the
repository root with any Python 3:

    python tools/build.py
"""

import pathlib
import re
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADDON = ROOT / "addon"
DIST = ROOT / "dist"


def main() -> None:
    manifest = (ADDON / "manifest.ini").read_text(encoding="utf-8")
    name = re.search(r"^name\s*=\s*(\S+)", manifest, re.M).group(1)
    version = re.search(r"^version\s*=\s*(\S+)", manifest, re.M).group(1)
    DIST.mkdir(exist_ok=True)
    target = DIST / f"{name}-{version}.nvda-addon"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(ADDON.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            bundle.write(path, path.relative_to(ADDON).as_posix())
    print(f"Built {target.relative_to(ROOT)}")
    with zipfile.ZipFile(target) as bundle:
        for info in bundle.infolist():
            print(f"  {info.filename}")


if __name__ == "__main__":
    main()
