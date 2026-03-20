#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import base64
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
DOC_PATH = ROOT / "docs" / "cloudflare-pages-deploy.md"
DEFAULT_DOMAIN = "200302.xyz"
DEFAULT_SUBDOMAIN = "www"
DEFAULT_BRANCH = "main"
DEFAULT_REPO = "ztt-blog"
DEFAULT_TOKEN_ENV = "GITHUB_TOKEN"
DEFAULT_GIT_NAME = "ztt"
DEFAULT_GIT_EMAIL = "ztt@users.noreply.github.com"


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def command_path(name: str) -> str | None:
    return shutil.which(name)


def print_section(title: str) -> None:
    print(f"\n== {title} ==")


def status_line(label: str, value: str) -> None:
    print(f"{label}: {value}")


def api_request(url: str, token: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "ztt-blog-setup",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            charset = response.headers.get_content_charset("utf-8")
            return json.loads(response.read().decode(charset))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub API error {exc.code}: {body}") from exc


def check_environment() -> int:
    print_section("Environment")
    for command in ("python", "git", "node", "npm", "gh"):
        path = command_path(command)
        status_line(command, path or "not found")

    print_section("Project")
    status_line("root", str(ROOT))
    status_line("site exists", str(SITE_DIR.exists()))
    status_line("package.json", str((SITE_DIR / "package.json").exists()))
    status_line("node_modules", str((SITE_DIR / "node_modules").exists()))
    status_line("deploy doc", str(DOC_PATH.exists()))

    if (SITE_DIR / "package.json").exists():
        package_json = json.loads((SITE_DIR / "package.json").read_text(encoding="utf-8"))
        scripts = package_json.get("scripts", {})
        print_section("NPM Scripts")
        for name in ("dev", "build", "preview"):
            status_line(name, scripts.get(name, "missing"))

    return 0


def ensure_git_identity() -> None:
    name = run(["git", "config", "--get", "user.name"], check=False).stdout.strip()
    email = run(["git", "config", "--get", "user.email"], check=False).stdout.strip()
    if name and email:
        return

    if not (ROOT / ".git").exists():
        run(["git", "init"], cwd=ROOT)

    config_path = ROOT / ".git" / "config"
    parser = configparser.RawConfigParser()
    parser.optionxform = str
    parser.read(config_path, encoding="utf-8")

    if not parser.has_section("user"):
        parser.add_section("user")

    if not parser.get("user", "name", fallback="").strip():
        parser.set("user", "name", DEFAULT_GIT_NAME)
    if not parser.get("user", "email", fallback="").strip():
        parser.set("user", "email", DEFAULT_GIT_EMAIL)

    with config_path.open("w", encoding="utf-8") as handle:
        parser.write(handle)


def ensure_site_ready() -> None:
    if not (SITE_DIR / "package.json").exists():
        raise SystemExit(f"Astro project not found: {SITE_DIR}")
    if not (SITE_DIR / "node_modules").exists():
        raise SystemExit(f"Dependencies are missing. Run: cd {SITE_DIR} && npm install")


def init_git(branch: str, commit_message: str) -> int:
    ensure_site_ready()

    print_section("Git Init")
    if not (ROOT / ".git").exists():
        run(["git", "init"], cwd=ROOT)
        print("initialized repository")
    else:
        print("repository already exists")

    ensure_git_identity()

    current_branch = run(["git", "branch", "--show-current"], cwd=ROOT, check=False).stdout.strip()
    if not current_branch:
        current_branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, check=False).stdout.strip()

    if current_branch == branch:
        print(f"already on {branch}")
    else:
        run(["git", "checkout", "-B", branch], cwd=ROOT)
        print(f"checked out {branch}")

    run(["git", "add", "."], cwd=ROOT)
    status = run(["git", "status", "--short"], cwd=ROOT).stdout.strip()
    if not status:
        print("working tree clean, nothing to commit")
        return 0

    run(["git", "commit", "-m", commit_message], cwd=ROOT)
    print(f'created commit: "{commit_message}"')
    return 0


def set_remote(repo_url: str, branch: str, push: bool) -> int:
    if not (ROOT / ".git").exists():
        raise SystemExit("Current directory is not a Git repository. Run git-init first.")

    existing = run(["git", "remote", "get-url", "origin"], cwd=ROOT, check=False).stdout.strip()
    if existing:
        if existing != repo_url:
            run(["git", "remote", "set-url", "origin", repo_url], cwd=ROOT)
            print(f"updated origin: {repo_url}")
        else:
            print(f"origin already set: {repo_url}")
    else:
        run(["git", "remote", "add", "origin", repo_url], cwd=ROOT)
        print(f"added origin: {repo_url}")

    if push:
        run(["git", "push", "-u", "origin", branch], cwd=ROOT)
        print(f"pushed branch: {branch}")
    else:
        print(f"next: git push -u origin {branch}")
    return 0


def build_site() -> int:
    ensure_site_ready()
    print_section("Build")
    result = run(["npm", "run", "build"], cwd=SITE_DIR)
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return 0


def print_cloudflare(domain: str, subdomain: str, branch: str) -> int:
    fqdn = f"{subdomain}.{domain}"
    print_section("Cloudflare Pages")
    print("Framework: Astro")
    print(f"Production branch: {branch}")
    print("Root directory: site")
    print("Build command: npm run build")
    print("Build output directory: dist")
    print(f"Custom domain: {fqdn}")
    print("")
    print("Registrar DNS record:")
    print("Type:   CNAME")
    print(f"Name:   {subdomain}")
    print("Target: <your-pages-project>.pages.dev")
    if DOC_PATH.exists():
        print("")
        print(f"full checklist: {DOC_PATH}")
    return 0


def create_repo(
    repo_name: str,
    visibility: str,
    description: str,
    branch: str,
    token_env: str,
    set_origin: bool,
    push: bool,
) -> int:
    if push and not (ROOT / ".git").exists():
        raise SystemExit("Current directory is not a Git repository. Run git-init first.")

    token = os.environ.get(token_env, "").strip()
    if not token:
        raise SystemExit(
            f"Environment variable {token_env} is empty. Create a GitHub token and set it first.\n"
            f'PowerShell example: $env:{token_env} = "ghp_xxx"'
        )

    print_section("GitHub")
    me = api_request("https://api.github.com/user", token)
    owner = me["login"]
    print(f"authenticated as: {owner}")

    payload = {
        "name": repo_name,
        "description": description,
        "private": visibility == "private",
        "auto_init": False,
    }
    repo = api_request("https://api.github.com/user/repos", token, method="POST", payload=payload)
    clone_url = repo["clone_url"]
    html_url = repo["html_url"]
    print(f"created repository: {html_url}")

    if set_origin:
        set_remote(clone_url, branch, push)
    else:
        print(f"remote url: {clone_url}")
    return 0


def upload_workflow_secret(
    repo: str,
    token_env: str,
    secret_name: str,
    secret_value: str,
) -> int:
    token = os.environ.get(token_env, "").strip()
    if not token:
        raise SystemExit(
            f"Environment variable {token_env} is empty. Set it before uploading secrets."
        )

    owner = api_request("https://api.github.com/user", token)["login"]
    key_url = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/public-key"
    key_data = api_request(key_url, token)
    public_key = key_data["key"]
    key_id = key_data["key_id"]

    try:
        from nacl import encoding, public  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "PyNaCl is required to upload GitHub Actions secrets. Install it with: pip install pynacl"
        ) from exc

    public_key_obj = public.PublicKey(public_key.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(public_key_obj)
    encrypted = base64.b64encode(sealed_box.encrypt(secret_value.encode("utf-8"))).decode("utf-8")

    secret_url = f"https://api.github.com/repos/{owner}/{repo}/actions/secrets/{secret_name}"
    api_request(
        secret_url,
        token,
        method="PUT",
        payload={"encrypted_value": encrypted, "key_id": key_id},
    )
    print(f"uploaded secret: {secret_name}")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the local static blog workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Check local prerequisites and project status.")

    git_init_parser = subparsers.add_parser("git-init", help="Initialize git and create the first commit.")
    git_init_parser.add_argument("--branch", default=DEFAULT_BRANCH)
    git_init_parser.add_argument("--commit-message", default="Initial blog scaffold")

    remote_parser = subparsers.add_parser("set-remote", help="Set GitHub origin and optionally push.")
    remote_parser.add_argument("--repo", required=True, help="GitHub repository URL.")
    remote_parser.add_argument("--branch", default=DEFAULT_BRANCH)
    remote_parser.add_argument("--push", action="store_true")

    subparsers.add_parser("build", help="Run npm run build in the site directory.")

    cf_parser = subparsers.add_parser("cloudflare", help="Print Cloudflare Pages settings.")
    cf_parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    cf_parser.add_argument("--subdomain", default=DEFAULT_SUBDOMAIN)
    cf_parser.add_argument("--branch", default=DEFAULT_BRANCH)

    create_parser = subparsers.add_parser("create-repo", help="Create a GitHub repository via the GitHub API.")
    create_parser.add_argument("--repo-name", default=DEFAULT_REPO)
    create_parser.add_argument("--visibility", choices=("public", "private"), default="public")
    create_parser.add_argument("--description", default="ztt personal blog")
    create_parser.add_argument("--branch", default=DEFAULT_BRANCH)
    create_parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    create_parser.add_argument("--set-origin", action="store_true")
    create_parser.add_argument("--push", action="store_true")

    secret_parser = subparsers.add_parser("upload-secret", help="Upload a GitHub Actions repository secret.")
    secret_parser.add_argument("--repo", default=DEFAULT_REPO)
    secret_parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    secret_parser.add_argument("--name", required=True)
    secret_parser.add_argument("--value", required=True)

    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()

    if args.command == "check":
        return check_environment()
    if args.command == "git-init":
        return init_git(args.branch, args.commit_message)
    if args.command == "set-remote":
        return set_remote(args.repo, args.branch, args.push)
    if args.command == "build":
        return build_site()
    if args.command == "cloudflare":
        return print_cloudflare(args.domain, args.subdomain, args.branch)
    if args.command == "create-repo":
        return create_repo(
            repo_name=args.repo_name,
            visibility=args.visibility,
            description=args.description,
            branch=args.branch,
            token_env=args.token_env,
            set_origin=args.set_origin,
            push=args.push,
        )
    if args.command == "upload-secret":
        return upload_workflow_secret(
            repo=args.repo,
            token_env=args.token_env,
            secret_name=args.name,
            secret_value=args.value,
        )

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        raise SystemExit(exc.returncode)
