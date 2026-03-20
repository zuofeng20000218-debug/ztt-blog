#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import sys
import traceback
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import setup_blog


TOKEN_ENV = "GITHUB_TOKEN"
TOKEN_FILE = SCRIPT_DIR / "github_token.txt"
DEFAULT_REPO = "ztt-blog"
LOG_FILE = SCRIPT_DIR / "create_repo_and_push.log"


def ensure_token() -> None:
    token = os.environ.get(TOKEN_ENV, "").strip()
    if token:
        print("Using token from environment.")
        return

    if TOKEN_FILE.exists():
        file_token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if file_token:
            os.environ[TOKEN_ENV] = file_token
            print(f"Using token from file: {TOKEN_FILE}")
            return

    entered = getpass.getpass("GitHub token: ").strip()
    if not entered:
        raise SystemExit("GitHub token is required.")
    os.environ[TOKEN_ENV] = entered


def main() -> int:
    print(f"Working directory: {Path.cwd()}")
    ensure_token()
    print("Running git initialization...")
    setup_blog.init_git(branch=setup_blog.DEFAULT_BRANCH, commit_message="Initial blog scaffold")
    print("Creating GitHub repository and pushing...")
    return setup_blog.create_repo(
        repo_name=DEFAULT_REPO,
        visibility="public",
        description="ztt personal blog",
        branch=setup_blog.DEFAULT_BRANCH,
        token_env=TOKEN_ENV,
        set_origin=True,
        push=True,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        trace = traceback.format_exc()
        LOG_FILE.write_text(trace, encoding="utf-8")
        print(f"Failed. Details written to: {LOG_FILE}")
        print(trace)
        raise
