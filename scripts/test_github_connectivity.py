#!/usr/bin/env python3
from __future__ import annotations

import socket
import subprocess
import sys
import urllib.request


def check_dns(host: str) -> None:
    try:
        ip = socket.gethostbyname(host)
        print(f"DNS OK: {host} -> {ip}")
    except Exception as exc:
        print(f"DNS FAILED: {host} ({exc})")


def check_https(url: str) -> None:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            print(f"HTTPS OK: {url} ({response.status})")
    except Exception as exc:
        print(f"HTTPS FAILED: {url} ({exc})")


def check_git(url: str) -> None:
    try:
        result = subprocess.run(
            ["git", "ls-remote", url],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=True,
        )
        lines = result.stdout.strip().splitlines()
        print(f"GIT OK: {url} ({len(lines)} refs)")
    except subprocess.CalledProcessError as exc:
        print(f"GIT FAILED: {url}")
        if exc.stderr.strip():
            print(exc.stderr.strip())
        elif exc.stdout.strip():
            print(exc.stdout.strip())
    except Exception as exc:
        print(f"GIT FAILED: {url} ({exc})")


def main() -> int:
    print("Testing GitHub connectivity...")
    check_dns("github.com")
    check_https("https://github.com")
    check_https("https://api.github.com")
    check_git("https://github.com/zuofeng20000218-debug/ztt-blog.git")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
