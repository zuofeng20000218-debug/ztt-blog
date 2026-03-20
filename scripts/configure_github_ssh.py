#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


SSH_DIR = Path.home() / ".ssh"
CONFIG_PATH = SSH_DIR / "config"
KEY_PATH = SSH_DIR / "id_ed25519_github_ztt_blog"


BLOCK = f"""Host github.com
  HostName github.com
  User git
  IdentityFile {KEY_PATH}
  IdentitiesOnly yes
"""


def main() -> int:
    SSH_DIR.mkdir(parents=True, exist_ok=True)
    existing = CONFIG_PATH.read_text(encoding="utf-8", errors="ignore") if CONFIG_PATH.exists() else ""

    if "IdentityFile" in existing and str(KEY_PATH) in existing:
        print(f"SSH config already points github.com to {KEY_PATH}")
        return 0

    with CONFIG_PATH.open("a", encoding="utf-8") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(BLOCK)
        if not BLOCK.endswith("\n"):
            handle.write("\n")

    print(f"Updated SSH config: {CONFIG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
