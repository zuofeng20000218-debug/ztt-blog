#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "scripts" / "blog_config.json"
DEFAULT_BRANCH = "main"
DEFAULT_REPO = "ztt-blog"


def load_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


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


def main() -> int:
    config = load_config()
    owner = config.get("github_owner", "").strip()
    repo = config.get("github_repo", DEFAULT_REPO).strip()
    branch = config.get("git_branch", DEFAULT_BRANCH).strip()

    if not owner:
        raise SystemExit(f"github_owner is missing in {CONFIG_PATH}")

    remote = f"git@github.com:{owner}/{repo}.git"
    existing = run(["git", "remote", "get-url", "origin"], check=False).stdout.strip()

    print(f"Project root: {ROOT}")
    print(f"SSH remote: {remote}")

    if existing and existing != remote:
        run(["git", "remote", "set-url", "origin", remote])
        print(f"Updated origin: {remote}")
    elif not existing:
        run(["git", "remote", "add", "origin", remote])
        print(f"Added origin: {remote}")
    else:
        print(f"Origin already set: {remote}")

    result = run(["git", "push", "-u", "origin", branch], check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if result.returncode != 0:
        raise SystemExit(result.returncode)

    print(f"Pushed branch: {branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
