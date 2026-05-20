#!/usr/bin/env python3
from __future__ import annotations

import html
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
POSTS_DIR = SITE_DIR / "src" / "content" / "blog"
FRIENDS_FILE = SITE_DIR / "src" / "data" / "friends.json"
ASSETS_DIR = SITE_DIR / "src" / "assets"
PREVIEW_HOST = "127.0.0.1"
PREVIEW_PORT = 4321
PANEL_HOST = "127.0.0.1"
PANEL_PORT = 8765

preview_process: subprocess.Popen[str] | None = None
preview_lock = threading.Lock()


@dataclass
class CommandResult:
    code: int
    output: str


@dataclass
class UploadedFile:
    filename: str
    content_type: str
    data: bytes


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg"}
COVER_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
HOME_FILE = SITE_DIR / "src" / "data" / "home.json"
NAVIGATION_FILE = SITE_DIR / "src" / "data" / "navigation.json"
PUBLIC_UPLOADS_DIR = SITE_DIR / "public" / "uploads"
DEFAULT_HOME: dict[str, Any] = {
    "kicker": "个人博客 / 学习记录 / 项目日志",
    "title": "把折腾过的东西，慢慢写成能回看的记录。",
    "description": "这里先放学习笔记、建站过程、项目复盘和一些日常想法。内容还在搭建中，现在的文章和图片有不少是占位，后面会逐步替换成真实记录。",
    "primaryLabel": "看文章",
    "primaryHref": "/blog/",
    "secondaryLabel": "看友链",
    "secondaryHref": "/links/",
    "panelEyebrow": "当前状态",
    "panelTitle": "Cloudflare Pages 静态部署",
    "panelText": "Astro 生成页面，Markdown/MDX 写文章。没有数据库，没有后台服务，适合低成本长期维护。",
    "heroBackground": "",
    "showLatestPosts": True,
    "showTopics": True,
    "sections": [],
}
DEFAULT_NAVIGATION: list[dict[str, Any]] = [
    {"label": "首页", "href": "/", "enabled": True},
    {"label": "文章", "href": "/blog", "enabled": True},
    {"label": "归档", "href": "/archive", "enabled": True},
    {"label": "标签", "href": "/tags", "enabled": True},
    {"label": "搜索", "href": "/search", "enabled": True},
    {"label": "友链", "href": "/links", "enabled": True},
    {"label": "关于", "href": "/about", "enabled": True},
]


def node_modules_ready() -> bool:
    return (SITE_DIR / "node_modules").is_dir()


def run_command(cmd: list[str], cwd: Path = ROOT, timeout: int = 120) -> CommandResult:
    env = os.environ.copy()
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        output = "\n".join(part for part in [exc.stdout, exc.stderr, "Command timed out."] if part)
        return CommandResult(124, output)
    except FileNotFoundError:
        return CommandResult(127, f"Command not found: {cmd[0]}")

    return CommandResult(result.returncode, "\n".join(part for part in [result.stdout, result.stderr] if part).strip())


def npm_command() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def check_requirements() -> CommandResult:
    messages: list[str] = []
    code = 0

    messages.append(f"项目目录：{ROOT}")
    messages.append(f"站点目录：{SITE_DIR}")

    for name in ["git", "node", npm_command()]:
        path = shutil.which(name)
        if path:
            messages.append(f"已找到 {name}：{path}")
        else:
            messages.append(f"未找到 {name}。请先安装 Git 和 Node.js，然后重新打开控制面板。")
            code = 1

    if node_modules_ready():
        messages.append("依赖状态：site/node_modules 已存在。")
    else:
        messages.append("依赖状态：site/node_modules 不存在。换电脑首次使用时，请点击“安装/更新依赖”。")

    result = run_command(["git", "remote", "-v"], timeout=20)
    if result.code == 0 and result.output.strip():
        messages.append("\nGit 远程仓库：")
        messages.append(result.output)
    else:
        messages.append("\nGit 远程仓库：未配置或读取失败。")

    return CommandResult(code, "\n".join(messages))


def install_dependencies() -> CommandResult:
    npm = shutil.which(npm_command())
    if not npm:
        return CommandResult(1, "没有找到 npm。请先安装 Node.js 22.12 或更新版本。")

    command = [npm_command(), "install"]
    if (SITE_DIR / "package-lock.json").exists():
        command = [npm_command(), "ci"]

    result = run_command(command, cwd=SITE_DIR, timeout=300)
    if result.code == 0:
        return CommandResult(0, "依赖安装完成。\n\n" + result.output)
    return CommandResult(result.code, result.output)


def slugify(title: str) -> str:
    text = title.strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff-]+", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or f"post-{int(time.time())}"


def yaml_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def parse_checkbox(value: str) -> bool:
    return value == "on"


def safe_filename(filename: str, fallback: str = "image") -> str:
    name = Path(filename).name.strip()
    stem = slugify(Path(name).stem or fallback)
    ext = Path(name).suffix.lower()
    return f"{stem}{ext}" if ext else stem


def unique_path(directory: Path, filename: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = directory / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{int(time.time())}{suffix}"


def save_public_image(upload: UploadedFile | None, folder: str, fallback: str = "image") -> str | None:
    if not upload or not upload.filename or not upload.data:
        return None
    filename = safe_filename(upload.filename, fallback)
    if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("图片只支持 jpg、jpeg、png、webp、avif、gif、svg。")
    target_dir = PUBLIC_UPLOADS_DIR / folder
    target = unique_path(target_dir, filename)
    target.write_bytes(upload.data)
    return "/" + str(target.relative_to(SITE_DIR / "public")).replace("\\", "/")


def save_asset_image(upload: UploadedFile | None, folder: str, fallback: str = "image") -> tuple[Path, str] | None:
    if not upload or not upload.filename or not upload.data:
        return None
    filename = safe_filename(upload.filename, fallback)
    if Path(filename).suffix.lower() not in COVER_IMAGE_EXTENSIONS:
        raise ValueError("封面图只支持 jpg、jpeg、png、webp、avif。")
    target_dir = ASSETS_DIR / folder
    target = unique_path(target_dir, filename)
    target.write_bytes(upload.data)
    return target, str(target.relative_to(ROOT))


def asset_path_for_post(asset: Path, post_path: Path) -> str:
    return Path(os.path.relpath(asset, post_path.parent)).as_posix()


def read_home() -> dict[str, Any]:
    data = DEFAULT_HOME.copy()
    if HOME_FILE.exists():
        loaded = json.loads(HOME_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    sections = data.get("sections", [])
    data["sections"] = sections if isinstance(sections, list) else []
    return data


def write_home(data: dict[str, Any]) -> None:
    HOME_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOME_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_navigation() -> list[dict[str, Any]]:
    if NAVIGATION_FILE.exists():
        loaded = json.loads(NAVIGATION_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            items = [item for item in loaded if isinstance(item, dict)]
            if items:
                return items
    return [item.copy() for item in DEFAULT_NAVIGATION]


def write_navigation(items: list[dict[str, Any]]) -> None:
    NAVIGATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    NAVIGATION_FILE.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def split_post_file(path: Path) -> tuple[dict[str, Any], str]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")

    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end == -1:
        return {}, text

    frontmatter = parse_frontmatter(path)
    body = text[end + len("\n---") :].lstrip("\r\n")
    return frontmatter, body


def post_path_from_rel(rel_file: str) -> Path | None:
    if not rel_file:
        return None
    path = (ROOT / rel_file).resolve()
    try:
        path.relative_to(POSTS_DIR.resolve())
    except ValueError:
        return None
    if not path.is_file() or path.suffix.lower() not in {".md", ".mdx"}:
        return None
    return path


def parse_frontmatter(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")

    if not text.startswith("---"):
        return {}

    end = text.find("\n---", 3)
    if end == -1:
        return {}

    data: dict[str, Any] = {}
    for raw_line in text[3:end].splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip().strip("\"'")
        if value.lower() == "true":
            data[key.strip()] = True
        elif value.lower() == "false":
            data[key.strip()] = False
        elif value.startswith("[") and value.endswith("]"):
            data[key.strip()] = [
                item.strip().strip("\"'")
                for item in value[1:-1].split(",")
                if item.strip()
            ]
        else:
            data[key.strip()] = value
    return data


def list_posts() -> list[dict[str, Any]]:
    posts = []
    for path in sorted(POSTS_DIR.glob("**/*")):
        if path.suffix.lower() not in {".md", ".mdx"}:
            continue
        data = parse_frontmatter(path)
        posts.append(
            {
                "file": str(path.relative_to(ROOT)),
                "name": path.name,
                "title": data.get("title", path.stem),
                "date": data.get("pubDate", ""),
                "draft": bool(data.get("draft", False)),
                "tags": data.get("tags", []),
            }
        )
    return sorted(posts, key=lambda item: str(item["date"]), reverse=True)


def get_post_for_edit(rel_file: str) -> dict[str, Any] | None:
    path = post_path_from_rel(rel_file)
    if not path:
        return None

    data, body = split_post_file(path)
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        tags = []

    return {
        "file": str(path.relative_to(ROOT)),
        "name": path.name,
        "title": data.get("title", path.stem),
        "description": data.get("description", ""),
        "tags": ", ".join(str(tag) for tag in tags),
        "draft": bool(data.get("draft", False)),
        "pubDate": data.get("pubDate", ""),
        "updatedDate": data.get("updatedDate", ""),
        "heroImage": data.get("heroImage", ""),
        "body": body,
    }


def read_friends() -> list[dict[str, str]]:
    if not FRIENDS_FILE.exists():
        return []
    data = json.loads(FRIENDS_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def write_friends(friends: list[dict[str, str]]) -> None:
    FRIENDS_FILE.write_text(
        json.dumps(friends, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, UploadedFile]]:
    marker = "boundary="
    if marker not in content_type:
        return {}, {}
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    delimiter = ("--" + boundary).encode("utf-8")
    form: dict[str, str] = {}
    files: dict[str, UploadedFile] = {}

    for part in body.split(delimiter):
        part = part.strip(b"\r\n")
        if not part or part == b"--" or b"\r\n\r\n" not in part:
            continue
        raw_headers, payload = part.split(b"\r\n\r\n", 1)
        payload = payload.rstrip(b"\r\n")
        headers = raw_headers.decode("utf-8", errors="replace").split("\r\n")
        disposition = ""
        part_type = ""
        for header in headers:
            key, _, value = header.partition(":")
            if key.lower() == "content-disposition":
                disposition = value.strip()
            elif key.lower() == "content-type":
                part_type = value.strip()
        name_match = re.search(r'name="([^"]+)"', disposition)
        if not name_match:
            continue
        field_name = name_match.group(1)
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        if filename_match:
            filename = filename_match.group(1)
            if filename and payload:
                files[field_name] = UploadedFile(filename, part_type, payload)
        else:
            form[field_name] = payload.decode("utf-8", errors="replace")
    return form, files


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def get_git_status() -> str:
    result = run_command(["git", "status", "--short"], timeout=20)
    if result.code != 0:
        return result.output or "Git status failed."
    return result.output or "工作区干净。"


def create_post(form: dict[str, str]) -> CommandResult:
    title = form.get("title", "").strip()
    if not title:
        return CommandResult(1, "请先填写文章标题。")

    description = form.get("description", "").strip() or "这是一篇新的博客文章。"
    tags = [tag.strip() for tag in re.split(r"[,，]", form.get("tags", "")) if tag.strip()]
    draft = form.get("draft", "on") == "on"
    pub_date = form.get("pubDate", "").strip() or date.today().isoformat()
    suffix = ".mdx" if form.get("format") == "mdx" else ".md"
    filename = f"{pub_date}-{slugify(title)}{suffix}"
    path = POSTS_DIR / filename

    if path.exists():
        return CommandResult(1, f"文章已存在：{path.relative_to(ROOT)}")

    tag_text = "[" + ", ".join(yaml_quote(tag) for tag in tags) + "]"
    body = f"""---
title: {yaml_quote(title)}
description: {yaml_quote(description)}
tags: {tag_text}
draft: {'true' if draft else 'false'}
pubDate: {yaml_quote(pub_date)}
heroImage: '../../assets/blog-placeholder-1.jpg'
---

这里先写正文。

## 提纲

- 想说明的问题
- 过程中的记录
- 最后的总结
"""
    path.write_text(body, encoding="utf-8")
    return CommandResult(0, f"已创建文章：{path.relative_to(ROOT)}")


def publish_post(form: dict[str, str]) -> CommandResult:
    rel_file = form.get("file", "").strip()
    if not rel_file:
        return CommandResult(1, "请选择要发布的文章。")
    path = (ROOT / rel_file).resolve()
    if not path.is_file() or POSTS_DIR not in path.parents:
        return CommandResult(1, "文章路径无效。")

    text = path.read_text(encoding="utf-8")
    if re.search(r"(?m)^draft:\s*true\s*$", text):
        text = re.sub(r"(?m)^draft:\s*true\s*$", "draft: false", text, count=1)
    elif not re.search(r"(?m)^draft:", text):
        text = text.replace("---\n", "---\ndraft: false\n", 1)
    path.write_text(text, encoding="utf-8")
    return CommandResult(0, f"已标记为发布：{path.relative_to(ROOT)}")


def save_post(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "文章路径无效。")

    title = form.get("title", "").strip()
    if not title:
        return CommandResult(1, "请填写文章标题。")

    description = form.get("description", "").strip()
    pub_date = form.get("pubDate", "").strip() or date.today().isoformat()
    updated_date = form.get("updatedDate", "").strip()
    hero_image = form.get("heroImage", "").strip()
    body = form.get("body", "").replace("\r\n", "\n").strip()
    tags = [tag.strip() for tag in re.split(r"[,，]", form.get("tags", "")) if tag.strip()]
    draft = parse_checkbox(form.get("draft", ""))

    try:
        cover_upload = save_asset_image((files or {}).get("heroImageFile"), "covers", slugify(title))
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if cover_upload:
        hero_image = asset_path_for_post(cover_upload[0], path)

    lines = [
        "---",
        f"title: {yaml_quote(title)}",
        f"description: {yaml_quote(description)}",
        "tags: [" + ", ".join(yaml_quote(tag) for tag in tags) + "]",
        f"draft: {'true' if draft else 'false'}",
        f"pubDate: {yaml_quote(pub_date)}",
    ]
    if updated_date:
        lines.append(f"updatedDate: {yaml_quote(updated_date)}")
    if hero_image:
        lines.append(f"heroImage: {yaml_quote(hero_image)}")
    lines.extend(["---", "", body, ""])

    path.write_text("\n".join(lines), encoding="utf-8")
    return CommandResult(0, f"已保存文章：{path.relative_to(ROOT)}")


def insert_post_image(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "请选择要插入图片的文章。")

    upload = (files or {}).get("image")
    if not upload or not upload.filename:
        return CommandResult(1, "请选择一张图片。")

    alt = form.get("alt", "").strip() or Path(upload.filename).stem
    try:
        image_path = save_public_image(upload, "posts", slugify(alt))
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if not image_path:
        return CommandResult(1, "图片保存失败。")

    markdown = f"\n\n![{alt}]({image_path})\n"
    with path.open("a", encoding="utf-8") as file:
        file.write(markdown)
    return CommandResult(0, f"已把图片插入到文章末尾：{image_path}\n\nMarkdown：![{alt}]({image_path})")


def update_home_settings(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    home = read_home()
    for key in [
        "kicker",
        "title",
        "description",
        "primaryLabel",
        "primaryHref",
        "secondaryLabel",
        "secondaryHref",
        "panelEyebrow",
        "panelTitle",
        "panelText",
    ]:
        home[key] = form.get(key, "").strip()
    home["showLatestPosts"] = parse_checkbox(form.get("showLatestPosts", ""))
    home["showTopics"] = parse_checkbox(form.get("showTopics", ""))

    try:
        background = save_public_image((files or {}).get("heroBackgroundFile"), "home", "home-background")
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if background:
        home["heroBackground"] = background
    elif parse_checkbox(form.get("clearHeroBackground", "")):
        home["heroBackground"] = ""
    else:
        home["heroBackground"] = form.get("heroBackground", "").strip()

    sections = home.get("sections", [])
    current = sections[0] if sections and isinstance(sections[0], dict) else {}
    if parse_checkbox(form.get("deleteSection", "")):
        home["sections"] = []
    else:
        section = {
            "id": current.get("id", "custom-section"),
            "enabled": parse_checkbox(form.get("sectionEnabled", "")),
            "eyebrow": form.get("sectionEyebrow", "").strip(),
            "title": form.get("sectionTitle", "").strip(),
            "body": form.get("sectionBody", "").strip(),
            "linkLabel": form.get("sectionLinkLabel", "").strip(),
            "linkHref": form.get("sectionLinkHref", "").strip(),
        }
        home["sections"] = [section] if section["title"] or section["body"] else []
    write_home(home)
    return CommandResult(0, "首页设置已保存。启动预览或构建后就能看到效果。")


def update_navigation(form: dict[str, str]) -> CommandResult:
    items = read_navigation()
    updated: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        if parse_checkbox(form.get(f"delete_{index}", "")):
            continue
        label = form.get(f"label_{index}", "").strip()
        href = form.get(f"href_{index}", "").strip()
        if not label or not href:
            continue
        try:
            order = int(form.get(f"order_{index}", str(index + 1)))
        except ValueError:
            order = index + 1
        updated.append(
            {
                "label": label,
                "href": href,
                "enabled": parse_checkbox(form.get(f"enabled_{index}", "")),
                "_order": order,
            }
        )

    new_label = form.get("new_label", "").strip()
    new_href = form.get("new_href", "").strip()
    if new_label and new_href:
        try:
            new_order = int(form.get("new_order", str(len(updated) + 1)))
        except ValueError:
            new_order = len(updated) + 1
        updated.append(
            {
                "label": new_label,
                "href": new_href,
                "enabled": parse_checkbox(form.get("new_enabled", "on")),
                "_order": new_order,
            }
        )

    updated.sort(key=lambda item: item.get("_order", 999))
    for item in updated:
        item.pop("_order", None)
    if not updated:
        return CommandResult(1, "导航栏至少保留一个栏目。")
    write_navigation(updated)
    return CommandResult(0, "导航栏目已保存。刷新预览即可看到变化。")


def add_friend(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    name = form.get("name", "").strip()
    url = form.get("url", "").strip()
    description = form.get("description", "").strip()
    avatar = form.get("avatar", "").strip() or "/favicon.svg"
    if not name or not url:
        return CommandResult(1, "友链名称和链接必填。")

    try:
        uploaded_avatar = save_public_image((files or {}).get("avatarFile"), "avatars", slugify(name))
    except ValueError as exc:
        return CommandResult(1, str(exc))
    if uploaded_avatar:
        avatar = uploaded_avatar

    friends = read_friends()
    friends.append(
        {
            "name": name,
            "url": url,
            "description": description or "新的朋友站点。",
            "avatar": avatar,
        }
    )
    write_friends(friends)
    return CommandResult(0, f"已添加友链：{name}")


def delete_friend(form: dict[str, str]) -> CommandResult:
    url = form.get("url", "").strip()
    friends = read_friends()
    kept = [friend for friend in friends if friend.get("url") != url]
    if len(kept) == len(friends):
        return CommandResult(1, "没有找到这条友链。")
    write_friends(kept)
    return CommandResult(0, "已删除友链。")


def start_preview() -> CommandResult:
    global preview_process
    with preview_lock:
        if not shutil.which(npm_command()):
            return CommandResult(1, "没有找到 npm。请先安装 Node.js 22.12 或更新版本。")
        if not node_modules_ready():
            return CommandResult(1, "还没有安装依赖。请先点击“安装/更新依赖”。")
        if preview_process and preview_process.poll() is None:
            return CommandResult(0, f"预览服务已在 http://{PREVIEW_HOST}:{PREVIEW_PORT}/ 运行。")
        if is_port_open(PREVIEW_HOST, PREVIEW_PORT):
            return CommandResult(0, f"端口 {PREVIEW_PORT} 已有服务运行。")
        npm = npm_command()
        env = os.environ.copy()
        env["ASTRO_TELEMETRY_DISABLED"] = "1"
        preview_process = subprocess.Popen(
            [npm, "run", "dev", "--", "--host", PREVIEW_HOST, "--port", str(PREVIEW_PORT)],
            cwd=str(SITE_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    return CommandResult(0, f"已启动预览：http://{PREVIEW_HOST}:{PREVIEW_PORT}/")


def stop_preview() -> CommandResult:
    global preview_process
    with preview_lock:
        if preview_process and preview_process.poll() is None:
            preview_process.terminate()
            try:
                preview_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                preview_process.kill()
            preview_process = None
            return CommandResult(0, "已停止预览服务。")
    return CommandResult(0, "当前没有由面板启动的预览服务。")


def build_site() -> CommandResult:
    if not shutil.which(npm_command()):
        return CommandResult(1, "没有找到 npm。请先安装 Node.js 22.12 或更新版本。")
    if not node_modules_ready():
        return CommandResult(1, "还没有安装依赖。请先点击“安装/更新依赖”。")
    return run_command([npm_command(), "run", "build"], cwd=SITE_DIR, timeout=180)


def update_blog(form: dict[str, str]) -> CommandResult:
    message = form.get("message", "").strip() or "update blog"
    build = build_site()
    if build.code != 0:
        return CommandResult(build.code, "构建失败，已取消提交。\n\n" + build.output)
    result = run_command(
        [sys.executable, str(ROOT / "scripts" / "update_blog.py"), "-m", message, "--skip-build"],
        timeout=180,
    )
    return CommandResult(result.code, "构建已通过。\n\n" + result.output)


def html_escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def render_page(message: CommandResult | None = None, edit_file: str = "") -> str:
    posts = list_posts()
    friends = read_friends()
    home = read_home()
    navigation = read_navigation()
    home_section = home["sections"][0] if home.get("sections") else {}
    git_status = get_git_status()
    preview_running = is_port_open(PREVIEW_HOST, PREVIEW_PORT)
    deps_ready = node_modules_ready()
    drafts = [post for post in posts if post["draft"]]
    edit_post = get_post_for_edit(edit_file)

    message_html = ""
    if message:
        status_class = "ok" if message.code == 0 else "bad"
        message_html = f"""
        <section class="panel result {status_class}">
          <h2>操作结果</h2>
          <pre>{html_escape(message.output or '完成。')}</pre>
        </section>
        """

    post_options = "\n".join(
        f'<option value="{html_escape(post["file"])}">{html_escape(post["title"])} ({html_escape(post["name"])})</option>'
        for post in drafts
    )
    edit_options = "\n".join(
        f'<option value="{html_escape(post["file"])}" {"selected" if edit_post and post["file"] == edit_post["file"] else ""}>{html_escape(post["title"])} ({html_escape(post["name"])})</option>'
        for post in posts
    )
    friend_rows = "\n".join(
        f"""
        <tr>
          <td>{html_escape(friend.get('name', ''))}</td>
          <td><a href="{html_escape(friend.get('url', ''))}" target="_blank">{html_escape(friend.get('url', ''))}</a></td>
          <td>{html_escape(friend.get('description', ''))}</td>
          <td>
            <form method="post" action="/action/delete_friend">
              <input type="hidden" name="url" value="{html_escape(friend.get('url', ''))}">
              <button class="ghost" type="submit">删除</button>
            </form>
          </td>
        </tr>
        """
        for friend in friends
    )
    navigation_rows = "\n".join(
        f"""
        <tr>
          <td><input name="order_{index}" type="number" min="1" value="{index + 1}"></td>
          <td><input name="label_{index}" required value="{html_escape(item.get('label', ''))}"></td>
          <td><input name="href_{index}" required value="{html_escape(item.get('href', ''))}" placeholder="/blog"></td>
          <td><label class="compact"><input type="checkbox" name="enabled_{index}" {'checked' if item.get('enabled', True) else ''}> 显示</label></td>
          <td><label class="compact"><input type="checkbox" name="delete_{index}"> 删除</label></td>
        </tr>
        """
        for index, item in enumerate(navigation)
    )
    edit_form_html = ""
    if edit_file and not edit_post:
        edit_form_html = """
      <div class="panel wide result bad">
        <h2>编辑文章</h2>
        <pre>没有找到要编辑的文章。</pre>
      </div>
        """
    elif edit_post:
        edit_form_html = f"""
      <div class="panel wide" id="edit-post">
        <h2>编辑文章</h2>
        <form method="post" action="/action/save_post" enctype="multipart/form-data">
          <input type="hidden" name="file" value="{html_escape(edit_post['file'])}">
          <label>标题</label>
          <input name="title" required value="{html_escape(edit_post['title'])}">
          <label>摘要</label>
          <textarea name="description">{html_escape(edit_post['description'])}</textarea>
          <label>标签（用逗号分隔）</label>
          <input name="tags" value="{html_escape(edit_post['tags'])}">
          <label>发布日期</label>
          <input name="pubDate" type="date" value="{html_escape(edit_post['pubDate'])}">
          <label>更新日期（可选）</label>
          <input name="updatedDate" type="date" value="{html_escape(edit_post['updatedDate'])}">
          <label>封面图路径</label>
          <input name="heroImage" value="{html_escape(edit_post['heroImage'])}">
          <label>上传新封面图（jpg、png、webp、avif）</label>
          <input name="heroImageFile" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,image/jpeg,image/png,image/webp,image/avif">
          <label><input style="width:auto" type="checkbox" name="draft" {'checked' if edit_post['draft'] else ''}> 保存为草稿</label>
          <label>正文</label>
          <textarea name="body" class="body-editor">{html_escape(edit_post['body'])}</textarea>
          <div class="actions">
            <button type="submit">保存文章</button>
            <a class="button secondary" href="/">关闭编辑</a>
          </div>
        </form>
      </div>
        """
    post_rows = "\n".join(
        f"""
        <tr>
          <td>{'草稿' if post['draft'] else '已发布'}</td>
          <td>{html_escape(post['title'])}</td>
          <td>{html_escape(post['date'])}</td>
          <td>{html_escape(', '.join(post['tags']))}</td>
          <td>{html_escape(post['file'])}</td>
          <td><a class="button ghost" href="/?edit={quote(post['file'])}#edit-post">编辑</a></td>
        </tr>
        """
        for post in posts
    )
    image_post_options = "\n".join(
        f'<option value="{html_escape(post["file"])}">{html_escape(post["title"])} ({html_escape(post["name"])})</option>'
        for post in posts
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>博客控制面板</title>
  <style>
    :root {{ --accent:#2563eb; --ink:#111827; --muted:#64748b; --line:#e2e8f0; --bg:#f8fafc; --surface:#fff; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:"Microsoft YaHei", system-ui, sans-serif; line-height:1.6; }}
    header {{ position:sticky; top:0; background:rgba(255,255,255,.94); border-bottom:1px solid var(--line); backdrop-filter:blur(12px); z-index:2; }}
    .wrap {{ width:min(1180px, calc(100% - 32px)); margin:0 auto; }}
    header .wrap {{ display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 0; }}
    main.wrap {{ padding:28px 0 48px; }}
    h1,h2,h3 {{ margin:0 0 10px; line-height:1.25; }}
    p {{ margin:0 0 12px; }}
    a {{ color:var(--accent); }}
    .status {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:18px; }}
    .metric, .panel {{ border:1px solid var(--line); background:var(--surface); border-radius:10px; padding:16px; box-shadow:0 8px 28px rgba(15,23,42,.05); }}
    .metric strong {{ display:block; font-size:1.6rem; }}
    .metric span, .muted {{ color:var(--muted); }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; align-items:start; }}
    label {{ display:block; color:var(--muted); font-size:.92rem; margin:10px 0 4px; }}
    input, select, textarea {{ width:100%; border:1px solid var(--line); border-radius:8px; padding:10px 12px; font:inherit; background:#fff; }}
    input[type="number"] {{ min-width:72px; }}
    textarea {{ min-height:84px; resize:vertical; }}
    .body-editor {{ min-height:420px; font-family:Consolas, "Microsoft YaHei", monospace; line-height:1.55; }}
    .hint {{ display:block; margin-top:4px; color:var(--muted); font-size:.86rem; }}
    .compact {{ display:flex; align-items:center; gap:6px; margin:0; color:var(--ink); white-space:nowrap; }}
    .compact input {{ width:auto; }}
    button, .button {{ display:inline-flex; align-items:center; justify-content:center; min-height:38px; border:0; border-radius:8px; background:var(--accent); color:#fff; padding:8px 14px; font-weight:700; text-decoration:none; cursor:pointer; }}
    button.secondary, .button.secondary {{ background:#111827; }}
    button.ghost, .button.ghost {{ background:#eef2ff; color:#1e40af; min-height:32px; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }}
    pre {{ white-space:pre-wrap; overflow:auto; background:#0f172a; color:#e5e7eb; border-radius:8px; padding:12px; max-height:360px; }}
    .result.ok {{ border-color:#86efac; }}
    .result.bad {{ border-color:#fca5a5; }}
    table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
    th,td {{ border-bottom:1px solid var(--line); text-align:left; padding:10px; vertical-align:top; }}
    .wide {{ grid-column:1 / -1; }}
    @media (max-width: 900px) {{ .status, .grid {{ grid-template-columns:1fr; }} header .wrap {{ align-items:flex-start; flex-direction:column; }} }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div>
        <h1>博客控制面板</h1>
        <p class="muted">本地工具，只操作 D:\\Blog 里的静态博客文件。</p>
      </div>
      <div class="actions">
        <a class="button" href="http://{PREVIEW_HOST}:{PREVIEW_PORT}/" target="_blank">打开预览</a>
        <a class="button secondary" href="/" aria-current="page">刷新面板</a>
      </div>
    </div>
  </header>
  <main class="wrap">
    <section class="status">
      <div class="metric"><strong>{len(posts)}</strong><span>文章总数</span></div>
      <div class="metric"><strong>{len(drafts)}</strong><span>草稿</span></div>
      <div class="metric"><strong>{len(friends)}</strong><span>友链</span></div>
      <div class="metric"><strong>{'运行中' if preview_running else '未启动'}</strong><span>本地预览</span></div>
      <div class="metric"><strong>{'已安装' if deps_ready else '未安装'}</strong><span>项目依赖</span></div>
    </section>
    {message_html}
    <section class="grid">
      <div class="panel">
        <h2>新建文章</h2>
        <form method="post" action="/action/create_post">
          <label>标题</label>
          <input name="title" required placeholder="例如：今天把博客控制面板做起来">
          <label>摘要</label>
          <textarea name="description" placeholder="一句话说明这篇文章写什么"></textarea>
          <label>标签（用逗号分隔）</label>
          <input name="tags" placeholder="建站, 记录">
          <label>发布日期</label>
          <input name="pubDate" type="date" value="{date.today().isoformat()}">
          <label>格式</label>
          <select name="format"><option value="md">Markdown</option><option value="mdx">MDX</option></select>
          <label><input style="width:auto" type="checkbox" name="draft" checked> 先保存为草稿</label>
          <div class="actions"><button type="submit">创建文章</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>发布草稿</h2>
        <p class="muted">把选中的文章从 draft: true 改成 draft: false。</p>
        <form method="post" action="/action/publish_post">
          <label>选择草稿</label>
          <select name="file" {'disabled' if not drafts else ''}>{post_options or '<option>暂无草稿</option>'}</select>
          <div class="actions"><button type="submit" {'disabled' if not drafts else ''}>发布这篇</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>编辑已有文章</h2>
        <form method="get" action="/">
          <label>选择文章</label>
          <select name="edit" {'disabled' if not posts else ''}>{edit_options or '<option>暂无文章</option>'}</select>
          <div class="actions"><button type="submit" {'disabled' if not posts else ''}>打开编辑</button></div>
        </form>
      </div>
      {edit_form_html}
      <div class="panel wide" id="navigation">
        <h2>导航栏目</h2>
        <form method="post" action="/action/update_navigation">
          <table>
            <thead><tr><th>顺序</th><th>名称</th><th>链接</th><th>显示</th><th>删除</th></tr></thead>
            <tbody>{navigation_rows}</tbody>
          </table>
          <h3>新增栏目</h3>
          <label>名称</label>
          <input name="new_label" placeholder="例如：作品">
          <label>链接</label>
          <input name="new_href" placeholder="/projects">
          <label>顺序</label>
          <input name="new_order" type="number" min="1" value="{len(navigation) + 1}">
          <label class="compact"><input type="checkbox" name="new_enabled" checked> 新栏目立即显示</label>
          <span class="hint">链接可以填站内路径，比如 /blog、/about，也可以填完整外链。改完后启动预览刷新页面即可看到导航变化。</span>
          <div class="actions"><button type="submit">保存导航栏目</button></div>
        </form>
      </div>
      <div class="panel wide" id="home-design">
        <h2>首页设计</h2>
        <form method="post" action="/action/update_home" enctype="multipart/form-data">
          <label>首页小标题</label>
          <input name="kicker" value="{html_escape(home.get('kicker', ''))}">
          <label>首页大标题</label>
          <input name="title" value="{html_escape(home.get('title', ''))}">
          <label>首页说明</label>
          <textarea name="description">{html_escape(home.get('description', ''))}</textarea>
          <label>主按钮文字</label>
          <input name="primaryLabel" value="{html_escape(home.get('primaryLabel', ''))}">
          <label>主按钮链接</label>
          <input name="primaryHref" value="{html_escape(home.get('primaryHref', ''))}">
          <label>副按钮文字</label>
          <input name="secondaryLabel" value="{html_escape(home.get('secondaryLabel', ''))}">
          <label>副按钮链接</label>
          <input name="secondaryHref" value="{html_escape(home.get('secondaryHref', ''))}">
          <label>右侧信息小标题</label>
          <input name="panelEyebrow" value="{html_escape(home.get('panelEyebrow', ''))}">
          <label>右侧信息标题</label>
          <input name="panelTitle" value="{html_escape(home.get('panelTitle', ''))}">
          <label>右侧信息说明</label>
          <textarea name="panelText">{html_escape(home.get('panelText', ''))}</textarea>
          <label>当前首页背景图路径</label>
          <input name="heroBackground" value="{html_escape(home.get('heroBackground', ''))}" placeholder="/uploads/home/background.webp">
          <label>上传首页背景图（jpg、png、webp、avif、gif、svg）</label>
          <input name="heroBackgroundFile" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif,.svg,image/*">
          <label><input style="width:auto" type="checkbox" name="clearHeroBackground"> 清空首页背景图</label>
          <label><input style="width:auto" type="checkbox" name="showLatestPosts" {'checked' if home.get('showLatestPosts') else ''}> 显示“最近文章”栏目</label>
          <label><input style="width:auto" type="checkbox" name="showTopics" {'checked' if home.get('showTopics') else ''}> 显示“正在整理的主题”栏目</label>
          <h3>自定义首页栏目</h3>
          <label><input style="width:auto" type="checkbox" name="sectionEnabled" {'checked' if home_section.get('enabled') else ''}> 显示这个栏目</label>
          <label><input style="width:auto" type="checkbox" name="deleteSection"> 删除这个自定义栏目</label>
          <label>栏目小标题</label>
          <input name="sectionEyebrow" value="{html_escape(home_section.get('eyebrow', ''))}" placeholder="Now">
          <label>栏目标题</label>
          <input name="sectionTitle" value="{html_escape(home_section.get('title', ''))}" placeholder="正在整理的方向">
          <label>栏目内容</label>
          <textarea name="sectionBody">{html_escape(home_section.get('body', ''))}</textarea>
          <label>栏目链接文字</label>
          <input name="sectionLinkLabel" value="{html_escape(home_section.get('linkLabel', ''))}" placeholder="了解更多">
          <label>栏目链接</label>
          <input name="sectionLinkHref" value="{html_escape(home_section.get('linkHref', ''))}" placeholder="/about/">
          <span class="hint">背景图会保存到 site/public/uploads/home/，支持 jpg、jpeg、png、webp、avif、gif、svg；更推荐 webp/jpg/png。</span>
          <div class="actions"><button type="submit">保存首页设置</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>给文章插入图片</h2>
        <form method="post" action="/action/insert_post_image" enctype="multipart/form-data">
          <label>选择文章</label>
          <select name="file" {'disabled' if not posts else ''}>{image_post_options or '<option>暂无文章</option>'}</select>
          <label>图片说明（会作为 alt 文本）</label>
          <input name="alt" placeholder="例如：控制面板截图">
          <label>选择图片（jpg、png、webp、avif、gif、svg）</label>
          <input name="image" required type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif,.svg,image/*">
          <span class="hint">保存后会自动把 Markdown 图片语法追加到文章末尾，你也可以打开文章编辑区，把那一行移动到正文中想放的位置。</span>
          <div class="actions"><button type="submit" {'disabled' if not posts else ''}>上传并插入</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>首次准备</h2>
        <p class="muted">换电脑下载仓库后，先检查环境，再安装依赖。密钥仍然只保存在本机，不会上传到 GitHub。</p>
        <div class="actions">
          <form method="post" action="/action/check_requirements"><button type="submit">检查环境</button></form>
          <form method="post" action="/action/install_dependencies"><button class="secondary" type="submit">安装/更新依赖</button></form>
        </div>
      </div>
      <div class="panel">
        <h2>预览和构建</h2>
        <p class="muted">预览用于本地查看，构建用于上线前检查。</p>
        <div class="actions">
          <form method="post" action="/action/start_preview"><button type="submit">启动预览</button></form>
          <form method="post" action="/action/stop_preview"><button class="secondary" type="submit">停止预览</button></form>
          <form method="post" action="/action/build"><button type="submit">构建检查</button></form>
        </div>
      </div>
      <div class="panel">
        <h2>提交并发布</h2>
        <p class="muted">会先运行构建；构建通过后才 git add、commit、push。</p>
        <form method="post" action="/action/update_blog">
          <label>提交说明</label>
          <input name="message" value="update blog">
          <div class="actions"><button type="submit">构建并推送</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>添加友链</h2>
        <form method="post" action="/action/add_friend" enctype="multipart/form-data">
          <label>名称</label>
          <input name="name" required>
          <label>链接</label>
          <input name="url" required placeholder="https://">
          <label>简介</label>
          <input name="description">
          <label>头像</label>
          <input name="avatar" placeholder="/favicon.svg 或 https://...">
          <label>上传头像（推荐本地保存，避免外链失效）</label>
          <input name="avatarFile" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif,.svg,image/*">
          <span class="hint">上传头像会保存到 site/public/uploads/avatars/，友链页会自动使用 /favicon.svg 作为加载失败兜底。</span>
          <div class="actions"><button type="submit">添加友链</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>Git 状态</h2>
        <pre>{html_escape(git_status)}</pre>
      </div>
      <div class="panel wide">
        <h2>文章列表</h2>
        <table>
          <thead><tr><th>状态</th><th>标题</th><th>日期</th><th>标签</th><th>文件</th><th>操作</th></tr></thead>
          <tbody>{post_rows}</tbody>
        </table>
      </div>
      <div class="panel wide">
        <h2>友链列表</h2>
        <table>
          <thead><tr><th>名称</th><th>链接</th><th>简介</th><th>操作</th></tr></thead>
          <tbody>{friend_rows}</tbody>
        </table>
      </div>
    </section>
  </main>
</body>
</html>"""


class BlogPanelHandler(BaseHTTPRequestHandler):
    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_html(render_page(), include_body=False)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        edit_file = parse_qs(parsed.query).get("edit", [""])[-1]
        self.send_html(render_page(edit_file=edit_file))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        content_type = self.headers.get("Content-Type", "")
        raw_body = self.rfile.read(length)
        files: dict[str, UploadedFile] = {}
        if content_type.startswith("multipart/form-data"):
            form, files = parse_multipart(raw_body, content_type)
        else:
            body = raw_body.decode("utf-8", errors="replace")
            form = {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}

        actions = {
            "/action/check_requirements": lambda _: check_requirements(),
            "/action/install_dependencies": lambda _: install_dependencies(),
            "/action/create_post": create_post,
            "/action/publish_post": publish_post,
            "/action/save_post": lambda data: save_post(data, files),
            "/action/insert_post_image": lambda data: insert_post_image(data, files),
            "/action/update_home": lambda data: update_home_settings(data, files),
            "/action/update_navigation": update_navigation,
            "/action/add_friend": lambda data: add_friend(data, files),
            "/action/delete_friend": delete_friend,
            "/action/start_preview": lambda _: start_preview(),
            "/action/stop_preview": lambda _: stop_preview(),
            "/action/build": lambda _: build_site(),
            "/action/update_blog": update_blog,
        }
        action = actions.get(parsed.path)
        if not action:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_html(render_page(action(form)))

    def send_html(self, content: str, include_body: bool = True) -> None:
        payload = content.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if include_body:
            self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local blog control panel.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--port", type=int, default=PANEL_PORT, help="Panel port, default: 8765.")
    args = parser.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    FRIENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    HOME_FILE.parent.mkdir(parents=True, exist_ok=True)
    NAVIGATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not FRIENDS_FILE.exists():
        write_friends([])
    if not HOME_FILE.exists():
        write_home(DEFAULT_HOME)
    if not NAVIGATION_FILE.exists():
        write_navigation(DEFAULT_NAVIGATION)

    server = ThreadingHTTPServer((PANEL_HOST, args.port), BlogPanelHandler)
    url = f"http://{PANEL_HOST}:{args.port}/"
    print(f"Blog panel is running: {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping panel...")
    finally:
        stop_preview()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
