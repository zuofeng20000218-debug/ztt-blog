#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MESSAGE = "update blog"


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def print_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Commit and push blog updates to GitHub.")
    parser.add_argument("-m", "--message", default=DEFAULT_MESSAGE, help="Commit message.")
    parser.add_argument("--no-push", action="store_true", help="Commit only, do not push.")
    args = parser.parse_args()

    print(f"Project root: {ROOT}")

    status = run(["git", "status", "--short"], check=False)
    if not status.stdout.strip():
        print("No changes to commit.")
        return 0

    print("Staging changes...")
    print_output(run(["git", "add", "."]))

    print("Creating commit...")
    print_output(run(["git", "commit", "-m", args.message]))

    if args.no_push:
        print("Commit created. Push skipped.")
        return 0

    print("Pushing to origin/main...")
    print_output(run(["git", "push"]))
    print("Update complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {' '.join(exc.cmd)}", file=sys.stderr)
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        raise SystemExit(exc.returncode)
