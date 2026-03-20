#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"


def main() -> int:
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm not found in PATH.")

    print(f"Project root: {ROOT}")
    print(f"Site directory: {SITE_DIR}")
    print("Starting Astro dev server...")

    result = subprocess.run(
        [npm, "run", "dev"],
        cwd=str(SITE_DIR),
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
