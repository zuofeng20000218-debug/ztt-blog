#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "scripts" / "blog_config.json"
DEFAULT_BRANCH = "main"
DEFAULT_REPO = "ztt-blog"
DEFAULT_GIT_NAME = "ztt"
DEFAULT_GIT_EMAIL = "ztt@users.noreply.github.com"
DEFAULT_OWNER = ""


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


def load_config() -> dict[str, str]:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def ensure_repo() -> None:
    if not (ROOT / ".git").exists():
        run(["git", "init"])


def ensure_safe_directory() -> None:
    result = run(["git", "rev-parse", "--is-inside-work-tree"], check=False)
    if result.returncode == 0:
        return
    combined = (result.stdout or "") + (result.stderr or "")
    if "detected dubious ownership" in combined:
        run(["git", "config", "--global", "--add", "safe.directory", str(ROOT)])
        verify = run(["git", "rev-parse", "--is-inside-work-tree"], check=False)
        if verify.returncode != 0:
            raise subprocess.CalledProcessError(verify.returncode, verify.args, verify.stdout, verify.stderr)


def ensure_identity(git_name: str, git_email: str) -> None:
    name = run(["git", "config", "--get", "user.name"], check=False).stdout.strip()
    email = run(["git", "config", "--get", "user.email"], check=False).stdout.strip()
    config_path = str(ROOT / ".git" / "config")
    if not name:
        run(["git", "config", "--file", config_path, "user.name", git_name])
    if not email:
        run(["git", "config", "--file", config_path, "user.email", git_email])


def ensure_branch(branch: str) -> None:
    current = run(["git", "branch", "--show-current"], check=False).stdout.strip()
    if current == branch:
        print(f"Already on {branch}")
        return

    has_head = run(["git", "rev-parse", "--verify", "HEAD"], check=False)
    if has_head.returncode != 0:
        run(["git", "checkout", "--orphan", branch])
        print(f"Created orphan branch {branch}")
        return

    run(["git", "checkout", "-B", branch])
    print(f"Checked out {branch}")


def commit_if_needed(message: str) -> None:
    run(["git", "add", "."])
    status = run(["git", "status", "--short"], check=False).stdout.strip()
    if not status:
        print("Working tree clean, nothing to commit")
        return
    run(["git", "commit", "-m", message])
    print(f'Created commit: "{message}"')


def set_remote_and_push(owner: str, repo: str, branch: str) -> None:
    repo_url = f"https://github.com/{owner}/{repo}.git"
    existing = run(["git", "remote", "get-url", "origin"], check=False).stdout.strip()
    if existing and existing != repo_url:
        run(["git", "remote", "set-url", "origin", repo_url])
        print(f"Updated origin: {repo_url}")
    elif not existing:
        run(["git", "remote", "add", "origin", repo_url])
        print(f"Added origin: {repo_url}")
    else:
        print(f"Origin already set: {repo_url}")

    run(["git", "push", "-u", "origin", branch])
    print(f"Pushed branch: {branch}")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Push the local blog project to an existing GitHub repository.")
    parser.add_argument("--owner", help="GitHub username or organization owner.")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Repository name. Defaults to ztt-blog.")
    parser.add_argument("--branch", default=DEFAULT_BRANCH, help="Branch name. Defaults to main.")
    return parser


def main() -> int:
    args = make_parser().parse_args()
    config = load_config()
    owner = args.owner or config.get("github_owner", DEFAULT_OWNER)
    repo = args.repo if args.repo != DEFAULT_REPO else config.get("github_repo", DEFAULT_REPO)
    branch = args.branch if args.branch != DEFAULT_BRANCH else config.get("git_branch", DEFAULT_BRANCH)
    git_name = config.get("git_name", DEFAULT_GIT_NAME)
    git_email = config.get("git_email", DEFAULT_GIT_EMAIL)

    if not owner:
        raise SystemExit(f"GitHub owner is missing. Set it in {CONFIG_PATH} or pass --owner.")

    print(f"Project root: {ROOT}")
    ensure_safe_directory()
    ensure_repo()
    ensure_identity(git_name=git_name, git_email=git_email)
    ensure_branch(branch)
    commit_if_needed("Initial blog scaffold")
    set_remote_and_push(owner=owner, repo=repo, branch=branch)
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
