#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SSH_DIR = Path.home() / ".ssh"
KNOWN_HOSTS = SSH_DIR / "known_hosts"


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    SSH_DIR.mkdir(parents=True, exist_ok=True)
    existing = KNOWN_HOSTS.read_text(encoding="utf-8", errors="ignore") if KNOWN_HOSTS.exists() else ""
    if "github.com" in existing:
        print(f"github.com already present in {KNOWN_HOSTS}")
        return 0

    result = run(["ssh-keyscan", "github.com"])
    scanned = result.stdout.strip()
    if not scanned:
        raise SystemExit("ssh-keyscan returned no host keys for github.com")

    with KNOWN_HOSTS.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(scanned)
        handle.write("\n")

    print(f"Added github.com host keys to: {KNOWN_HOSTS}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        raise SystemExit(exc.returncode)
