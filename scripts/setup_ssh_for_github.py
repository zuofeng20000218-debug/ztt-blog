#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "scripts" / "blog_config.json"
SSH_DIR = Path.home() / ".ssh"
KEY_PATH = SSH_DIR / "id_ed25519_github_ztt_blog"
PUB_PATH = SSH_DIR / "id_ed25519_github_ztt_blog.pub"


def load_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


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
    config = load_config()
    email = config.get("git_email", "ztt@users.noreply.github.com")

    SSH_DIR.mkdir(parents=True, exist_ok=True)

    if not KEY_PATH.exists():
        print(f"Generating SSH key: {KEY_PATH}")
        run([
            "ssh-keygen",
            "-t",
            "ed25519",
            "-C",
            email,
            "-f",
            str(KEY_PATH),
            "-N",
            "",
        ])
    else:
        print(f"SSH key already exists: {KEY_PATH}")

    if PUB_PATH.exists():
        print("")
        print("Public key:")
        print(PUB_PATH.read_text(encoding="utf-8").strip())
        print("")
        print(f"Saved at: {PUB_PATH}")

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
