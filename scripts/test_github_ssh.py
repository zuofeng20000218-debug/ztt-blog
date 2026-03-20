#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    result = subprocess.run(
        ["ssh", "-T", "git@github.com"],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
