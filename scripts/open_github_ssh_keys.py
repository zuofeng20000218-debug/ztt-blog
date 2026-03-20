#!/usr/bin/env python3
from __future__ import annotations

import webbrowser


def main() -> int:
    url = "https://github.com/settings/keys"
    opened = webbrowser.open(url)
    if opened:
        print(url)
        print("Add a new SSH key there.")
        return 0
    print(f"Open this URL manually: {url}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
