#!/usr/bin/env python3
from __future__ import annotations

import html
import argparse
import json
import mimetypes
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
POST_TEMPLATES_DIR = ROOT / "scripts" / "post_templates"
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
FONT_EXTENSIONS = {".woff2", ".woff", ".ttf", ".otf"}
POST_EXTENSIONS = {".md", ".mdx"}
EDITABLE_EXTENSIONS = {
    ".astro",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mdx",
    ".mjs",
    ".ps1",
    ".py",
    ".svg",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
EDIT_EXCLUDED_PARTS = {".git", ".astro", ".wrangler", "__pycache__", "dist", "node_modules"}
EDIT_EXCLUDED_NAMES = {"github_token.txt"}
HOME_FILE = SITE_DIR / "src" / "data" / "home.json"
NAVIGATION_FILE = SITE_DIR / "src" / "data" / "navigation.json"
FOOTER_FILE = SITE_DIR / "src" / "data" / "footer.json"
CONSTS_FILE = SITE_DIR / "src" / "consts.ts"
THEME_FILE = SITE_DIR / "src" / "data" / "theme.json"
PUBLIC_UPLOADS_DIR = SITE_DIR / "public" / "uploads"
PUBLIC_FONTS_DIR = SITE_DIR / "public" / "fonts"
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
    "heroOverlayStart": 0.72,
    "heroOverlayEnd": 0.42,
    "heroPanelOpacity": 0.82,
    "primaryButtonOpacity": 1.0,
    "secondaryButtonOpacity": 0.86,
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
DEFAULT_FOOTER: dict[str, Any] = {
    "copyright": "© {year} ztt. All rights reserved.",
    "description": "ztt 的网站 使用 Astro 构建，托管在 Cloudflare Pages。",
    "rssLabel": "RSS",
    "rssHref": "/rss.xml",
    "showRss": True,
    "douyinHref": "",
    "bilibiliHref": "",
}
DEFAULT_THEME: dict[str, Any] = {
    "bodyFont": "default",
    "headingFont": "default",
    "navFont": "default",
    "homeTitleFont": "default",
    "homeTextFont": "default",
    "postTitleFont": "default",
    "postBodyFont": "default",
    "footerFont": "default",
    "customFonts": [],
}
BUILTIN_FONT_OPTIONS: list[dict[str, str]] = [
    {"id": "default", "label": "默认 Atkinson + 中文系统字体"},
    {"id": "serif", "label": "文艺宋体"},
    {"id": "wenkai", "label": "温和文楷"},
    {"id": "sans", "label": "现代黑体"},
    {"id": "system", "label": "系统界面字体"},
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


def parse_opacity(value: str, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return round(min(1.0, max(0.0, parsed)), 2)


def safe_filename(filename: str, fallback: str = "image") -> str:
    name = Path(filename).name.strip()
    stem = slugify(Path(name).stem or fallback)
    ext = Path(name).suffix.lower()
    return f"{stem}{ext}" if ext else stem


def font_format(ext: str) -> str:
    return {
        ".woff2": "woff2",
        ".woff": "woff",
        ".ttf": "truetype",
        ".otf": "opentype",
    }.get(ext.lower(), "woff2")


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


def save_font_file(upload: UploadedFile | None, fallback: str = "font") -> tuple[str, str, str] | None:
    if not upload or not upload.filename or not upload.data:
        return None
    filename = safe_filename(upload.filename, fallback)
    ext = Path(filename).suffix.lower()
    if ext not in FONT_EXTENSIONS:
        raise ValueError("字体只支持 woff2、woff、ttf、otf。")
    target_dir = PUBLIC_FONTS_DIR / "custom"
    target = unique_path(target_dir, filename)
    target.write_bytes(upload.data)
    url = "/" + str(target.relative_to(SITE_DIR / "public")).replace("\\", "/")
    return url, font_format(ext), target.stem


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


def read_footer() -> dict[str, Any]:
    data = DEFAULT_FOOTER.copy()
    if FOOTER_FILE.exists():
        loaded = json.loads(FOOTER_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    return data


def write_footer(data: dict[str, Any]) -> None:
    FOOTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOOTER_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_theme() -> dict[str, Any]:
    data = DEFAULT_THEME.copy()
    if THEME_FILE.exists():
        loaded = json.loads(THEME_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data.update(loaded)
    if not isinstance(data.get("customFonts"), list):
        data["customFonts"] = []
    return data


def write_theme(data: dict[str, Any]) -> None:
    THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
    THEME_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
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
    if not path.is_file() or path.suffix.lower() not in POST_EXTENSIONS:
        return None
    return path


def relative_to_root(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def safe_root_file(rel_file: str, *, must_exist: bool = True) -> Path | None:
    if not rel_file:
        return None
    raw = rel_file.replace("\\", "/").lstrip("/")
    path = (ROOT / raw).resolve()
    try:
        relative = path.relative_to(ROOT.resolve())
    except ValueError:
        return None
    if any(part in EDIT_EXCLUDED_PARTS for part in relative.parts):
        return None
    if path.name in EDIT_EXCLUDED_NAMES:
        return None
    if path.suffix.lower() not in EDITABLE_EXTENSIONS:
        return None
    if must_exist and not path.is_file():
        return None
    return path


def list_editable_files() -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for current, dirs, names in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in EDIT_EXCLUDED_PARTS]
        current_path = Path(current)
        for name in names:
            path = current_path / name
            if name in EDIT_EXCLUDED_NAMES or path.suffix.lower() not in EDITABLE_EXTENSIONS:
                continue
            try:
                relative = path.relative_to(ROOT)
            except ValueError:
                continue
            rel = relative.as_posix()
            files.append({"file": rel, "name": rel, "kind": path.suffix.lower().lstrip(".") or "text"})
    return sorted(files, key=lambda item: item["file"])


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def page_file_for_href(href: str) -> str | None:
    clean_href = href.strip()
    if not clean_href or clean_href.startswith(("http://", "https://", "mailto:", "#")):
        return None
    path_part = clean_href.split("?", 1)[0].split("#", 1)[0].strip("/")
    candidates: list[Path]
    if not path_part:
        candidates = [SITE_DIR / "src" / "pages" / "index.astro"]
    else:
        candidates = [
            SITE_DIR / "src" / "pages" / f"{path_part}.astro",
            SITE_DIR / "src" / "pages" / path_part / "index.astro",
        ]
    for candidate in candidates:
        if candidate.is_file() and safe_root_file(relative_to_root(candidate)):
            return relative_to_root(candidate)
    return None


def route_for_page_file(path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to((SITE_DIR / "src" / "pages").resolve())
    except ValueError:
        return None
    if path.suffix.lower() != ".astro":
        return None
    if any(part.startswith("[") for part in relative.parts):
        return None

    parts = list(relative.parts)
    filename = parts.pop()
    stem = Path(filename).stem
    if stem != "index":
        parts.append(stem)
    route = "/" + "/".join(parts)
    return route.rstrip("/") + "/" if route != "/" else "/"


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


def parse_frontmatter_text(text: str) -> dict[str, Any]:
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


def new_post_path_from_source(content: str, suffix: str) -> tuple[Path | None, str | None]:
    data = parse_frontmatter_text(content)
    title = str(data.get("title", "")).strip()
    if not title:
        return None, "新文章源码 frontmatter 里需要有 title。"
    pub_date = str(data.get("pubDate", "")).strip() or date.today().isoformat()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", pub_date):
        pub_date = date.today().isoformat()
    extension = ".mdx" if suffix == ".mdx" else ".md"
    path = POSTS_DIR / f"{pub_date}-{slugify(title)}{extension}"
    if path.exists():
        return None, f"文章已存在：{relative_to_root(path)}"
    return path, None


def template_path_from_rel(rel_file: str) -> Path | None:
    if not rel_file:
        return None
    raw = rel_file.replace("\\", "/").lstrip("/")
    path = (POST_TEMPLATES_DIR / raw).resolve()
    try:
        path.relative_to(POST_TEMPLATES_DIR.resolve())
    except ValueError:
        return None
    if not path.is_file() or path.suffix.lower() not in POST_EXTENSIONS:
        return None
    return path


def list_post_templates() -> list[dict[str, str]]:
    templates: list[dict[str, str]] = []
    if not POST_TEMPLATES_DIR.exists():
        return templates
    for path in sorted(POST_TEMPLATES_DIR.glob("*")):
        if path.suffix.lower() not in POST_EXTENSIONS:
            continue
        data = parse_frontmatter(path)
        templates.append(
            {
                "file": path.relative_to(POST_TEMPLATES_DIR).as_posix(),
                "name": path.name,
                "title": str(data.get("title", path.stem)),
                "kind": path.suffix.lower().lstrip("."),
            }
        )
    return templates


def source_from_template(template_rel: str, title: str, description: str, tags: list[str], draft: bool, pub_date: str) -> tuple[str, str]:
    path = template_path_from_rel(template_rel)
    if not path:
        return default_post_source(title, description, tags, draft, pub_date), ".md"

    text = read_text_file(path)
    suffix = path.suffix.lower() if path.suffix.lower() in POST_EXTENSIONS else ".md"
    tag_text = "[" + ", ".join(yaml_quote(tag) for tag in tags) + "]"
    replacements = {
        "title": yaml_quote(title),
        "description": yaml_quote(description),
        "tags": tag_text,
        "draft": "true" if draft else "false",
        "pubDate": yaml_quote(pub_date),
    }
    for key, value in replacements.items():
        if re.search(rf"(?m)^{key}:\s*.*$", text):
            text = re.sub(rf"(?m)^{key}:\s*.*$", f"{key}: {value}", text, count=1)
        elif text.startswith("---\n"):
            text = text.replace("---\n", f"---\n{key}: {value}\n", 1)
    return text, suffix


def save_post_as_template(form: dict[str, str]) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "文章路径无效，无法保存为模板。")
    data = parse_frontmatter(path)
    title = str(data.get("title", path.stem)).strip() or path.stem
    filename = f"{slugify(title)}{path.suffix.lower() if path.suffix.lower() in POST_EXTENSIONS else '.md'}"
    target = unique_path(POST_TEMPLATES_DIR, filename)
    text = read_text_file(path)
    if re.search(r"(?m)^draft:\s*(true|false)\s*$", text):
        text = re.sub(r"(?m)^draft:\s*(true|false)\s*$", "draft: true", text, count=1)
    elif text.startswith("---\n"):
        text = text.replace("---\n", "---\ndraft: true\n", 1)
    target.write_text(text, encoding="utf-8")
    return CommandResult(0, f"已保存为模板：{target.relative_to(ROOT)}")


def initialize_post_templates() -> None:
    POST_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if any(POST_TEMPLATES_DIR.glob("*.md")) or any(POST_TEMPLATES_DIR.glob("*.mdx")):
        return
    for post in list_posts()[:6]:
        path = post_path_from_rel(post["file"])
        if not path:
            continue
        target = POST_TEMPLATES_DIR / f"{slugify(str(post['title']))}{path.suffix.lower()}"
        if target.exists():
            continue
        text = read_text_file(path)
        if re.search(r"(?m)^draft:\s*(true|false)\s*$", text):
            text = re.sub(r"(?m)^draft:\s*(true|false)\s*$", "draft: true", text, count=1)
        elif text.startswith("---\n"):
            text = text.replace("---\n", "---\ndraft: true\n", 1)
        target.write_text(text, encoding="utf-8")


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


def parse_multipart_multi(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, list[UploadedFile]]]:
    marker = "boundary="
    if marker not in content_type:
        return {}, {}
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    delimiter = ("--" + boundary).encode("utf-8")
    form: dict[str, str] = {}
    files: dict[str, list[UploadedFile]] = {}

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
                files.setdefault(field_name, []).append(UploadedFile(filename, part_type, payload))
        else:
            form[field_name] = payload.decode("utf-8", errors="replace")
    return form, files


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, UploadedFile]]:
    form, multi_files = parse_multipart_multi(body, content_type)
    return form, {key: values[-1] for key, values in multi_files.items() if values}


def is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def get_git_status() -> str:
    result = run_command(["git", "status", "--short"], timeout=20)
    if result.code != 0:
        return result.output or "Git status failed."
    return result.output or "工作区干净。"


def get_site_url() -> str:
    if CONSTS_FILE.exists():
        text = read_text_file(CONSTS_FILE)
        match = re.search(r"export\s+const\s+SITE_URL\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            return match.group(1).rstrip("/")
    return "https://www.200302.xyz"


def default_post_source(title: str, description: str, tags: list[str], draft: bool, pub_date: str) -> str:
    tag_text = "[" + ", ".join(yaml_quote(tag) for tag in tags) + "]"
    return f"""---
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


def create_post(form: dict[str, str]) -> CommandResult:
    title = form.get("title", "").strip()
    if not title:
        return CommandResult(1, "请先填写文章标题。")

    description = form.get("description", "").strip() or "这是一篇新的博客文章。"
    tags = [tag.strip() for tag in re.split(r"[,，]", form.get("tags", "")) if tag.strip()]
    draft = form.get("draft", "") == "on"
    pub_date = form.get("pubDate", "").strip() or date.today().isoformat()
    suffix = ".mdx" if form.get("format") == "mdx" else ".md"
    filename = f"{pub_date}-{slugify(title)}{suffix}"
    path = POSTS_DIR / filename

    if path.exists():
        return CommandResult(1, f"文章已存在：{path.relative_to(ROOT)}")

    path.write_text(default_post_source(title, description, tags, draft, pub_date), encoding="utf-8")
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


def set_post_visibility(form: dict[str, str]) -> CommandResult:
    path = post_path_from_rel(form.get("file", "").strip())
    if not path:
        return CommandResult(1, "文章路径无效。")
    visible = form.get("visible", "true") == "true"
    text = read_text_file(path)
    draft_line = f"draft: {'false' if visible else 'true'}"
    if re.search(r"(?m)^draft:\s*(true|false)\s*$", text):
        text = re.sub(r"(?m)^draft:\s*(true|false)\s*$", draft_line, text, count=1)
    elif text.startswith("---\n"):
        text = text.replace("---\n", f"---\n{draft_line}\n", 1)
    else:
        text = f"---\n{draft_line}\n---\n\n{text}"
    path.write_text(text, encoding="utf-8")
    return CommandResult(0, f"已{'显示' if visible else '隐藏'}文章：{relative_to_root(path)}")


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


def save_source_file(form: dict[str, str]) -> CommandResult:
    rel_file = form.get("file", "").strip()
    content = form.get("content", "").replace("\r\n", "\n")
    if rel_file == "__new_post__":
        suffix = form.get("suffix", ".md")
        path, error = new_post_path_from_source(content, suffix)
        if not path:
            return CommandResult(1, error or "无法创建新文章。")
    else:
        path = safe_root_file(rel_file)
        if not path:
            return CommandResult(1, "文件路径无效，或这个文件类型不允许在面板里编辑。")
    path.write_text(content, encoding="utf-8")
    return CommandResult(0, f"已保存：{relative_to_root(path)}")


def upload_editor_images(multi_files: dict[str, list[UploadedFile]]) -> CommandResult:
    uploads = multi_files.get("images", [])
    if not uploads:
        return CommandResult(1, "请选择至少一张图片。")

    snippets: list[str] = []
    for upload in uploads:
        alt = Path(upload.filename).stem or "image"
        try:
            image_path = save_public_image(upload, "posts", slugify(alt))
        except ValueError as exc:
            return CommandResult(1, str(exc))
        if image_path:
            snippets.append(f"![{alt}]({image_path})")

    if not snippets:
        return CommandResult(1, "图片保存失败。")
    return CommandResult(0, "\n\n".join(snippets))


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
    home["heroOverlayStart"] = parse_opacity(form.get("heroOverlayStart", ""), 0.72)
    home["heroOverlayEnd"] = parse_opacity(form.get("heroOverlayEnd", ""), 0.42)
    home["heroPanelOpacity"] = parse_opacity(form.get("heroPanelOpacity", ""), 0.82)
    home["primaryButtonOpacity"] = parse_opacity(form.get("primaryButtonOpacity", ""), 1.0)
    home["secondaryButtonOpacity"] = parse_opacity(form.get("secondaryButtonOpacity", ""), 0.86)

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


def update_footer(form: dict[str, str]) -> CommandResult:
    footer = {
        "copyright": form.get("copyright", "").strip() or DEFAULT_FOOTER["copyright"],
        "description": form.get("description", "").strip(),
        "rssLabel": form.get("rssLabel", "").strip() or "RSS",
        "rssHref": form.get("rssHref", "").strip() or "/rss.xml",
        "showRss": parse_checkbox(form.get("showRss", "")),
        "douyinHref": form.get("douyinHref", "").strip(),
        "bilibiliHref": form.get("bilibiliHref", "").strip(),
    }
    write_footer(footer)
    return CommandResult(0, "底部信息已保存。刷新预览即可看到变化。")


def update_theme(form: dict[str, str], files: dict[str, UploadedFile] | None = None) -> CommandResult:
    theme = read_theme()
    custom_fonts = [font for font in theme.get("customFonts", []) if isinstance(font, dict)]

    family = form.get("fontFamily", "").strip()
    upload = (files or {}).get("fontFile")
    if upload and upload.filename:
        if not family:
            family = Path(upload.filename).stem
        try:
            url, fmt, stem = save_font_file(upload, slugify(family or "custom-font"))
        except ValueError as exc:
            return CommandResult(1, str(exc))
        font_id = f"custom-{slugify(family or stem)}-{int(time.time())}"
        custom_fonts.append(
            {
                "id": font_id,
                "label": family,
                "family": family,
                "url": url,
                "format": fmt,
                "weight": form.get("fontWeight", "").strip() or "400",
            }
        )
        if parse_checkbox(form.get("applyUploadedToBody", "")):
            theme["bodyFont"] = font_id
        if parse_checkbox(form.get("applyUploadedToHeading", "")):
            theme["headingFont"] = font_id

    available_ids = {item["id"] for item in BUILTIN_FONT_OPTIONS}
    available_ids.update(str(font.get("id")) for font in custom_fonts)
    for key in [
        "bodyFont",
        "headingFont",
        "navFont",
        "homeTitleFont",
        "homeTextFont",
        "postTitleFont",
        "postBodyFont",
        "footerFont",
    ]:
        value = form.get(key, "").strip()
        if value in available_ids:
            theme[key] = value

    theme["customFonts"] = custom_fonts
    write_theme(theme)
    return CommandResult(0, "字体设置已保存。构建并发布后，访客会加载网站托管的字体文件。")


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


def base_panel_css() -> str:
    return """
    :root { --accent:#2563eb; --ink:#111827; --muted:#64748b; --line:#e2e8f0; --bg:#f8fafc; --surface:#fff; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font-family:"Microsoft YaHei", system-ui, sans-serif; line-height:1.6; }
    header { position:sticky; top:0; background:rgba(255,255,255,.94); border-bottom:1px solid var(--line); backdrop-filter:blur(12px); z-index:2; }
    .wrap { width:min(1180px, calc(100% - 32px)); margin:0 auto; }
    header .wrap { display:flex; justify-content:space-between; align-items:center; gap:16px; padding:16px 0; }
    main.wrap { padding:28px 0 48px; }
    h1,h2,h3 { margin:0 0 10px; line-height:1.25; }
    p { margin:0 0 12px; }
    a { color:var(--accent); }
    .status { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:18px; }
    .metric, .panel { border:1px solid var(--line); background:var(--surface); border-radius:10px; padding:16px; box-shadow:0 8px 28px rgba(15,23,42,.05); }
    .metric strong { display:block; font-size:1.6rem; }
    .metric span, .muted { color:var(--muted); }
    .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; align-items:start; }
    label { display:block; color:var(--muted); font-size:.92rem; margin:10px 0 4px; }
    input, select, textarea { width:100%; border:1px solid var(--line); border-radius:8px; padding:10px 12px; font:inherit; background:#fff; }
    input[type="number"] { min-width:72px; }
    input[type="range"] { padding:0; }
    textarea { min-height:84px; resize:vertical; }
    .body-editor { min-height:420px; font-family:Consolas, "Microsoft YaHei", monospace; line-height:1.55; }
    .hint { display:block; margin-top:4px; color:var(--muted); font-size:.86rem; }
    .compact { display:flex; align-items:center; gap:6px; margin:0; color:var(--ink); white-space:nowrap; }
    .compact input { width:auto; }
    .field-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px 16px; }
    .range-line { display:grid; grid-template-columns:minmax(0,1fr) 4.5rem; gap:10px; align-items:center; }
    button, .button { display:inline-flex; align-items:center; justify-content:center; min-height:38px; border:0; border-radius:8px; background:var(--accent); color:#fff; padding:8px 14px; font-weight:700; text-decoration:none; cursor:pointer; }
    button.secondary, .button.secondary { background:#111827; }
    button.ghost, .button.ghost { background:#eef2ff; color:#1e40af; min-height:32px; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
    pre { white-space:pre-wrap; overflow:auto; background:#0f172a; color:#e5e7eb; border-radius:8px; padding:12px; max-height:360px; }
    .result.ok { border-color:#86efac; }
    .result.bad { border-color:#fca5a5; }
    table { width:100%; border-collapse:collapse; font-size:.92rem; }
    th,td { border-bottom:1px solid var(--line); text-align:left; padding:10px; vertical-align:top; }
    .wide { grid-column:1 / -1; }
    @media (max-width: 900px) { .status, .grid { grid-template-columns:1fr; } header .wrap { align-items:flex-start; flex-direction:column; } }
    """


def render_editor_page(
    *,
    rel_file: str,
    content: str,
    kind: str,
    title: str,
    site_route: str = "",
    suffix: str = "",
    is_new_post: bool = False,
    message: CommandResult | None = None,
) -> str:
    status_html = ""
    if message:
        status_html = html_escape(message.output or "完成。")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)} | 博客控制面板</title>
  <style>
    {base_panel_css()}
    body {{ height:100vh; overflow:hidden; }}
    header {{ position:static; }}
    .editor-shell {{ display:grid; grid-template-columns:minmax(0,1fr) minmax(360px,.9fr); height:calc(100vh - 86px); }}
    .editor-pane, .preview-pane {{ min-width:0; min-height:0; display:flex; flex-direction:column; }}
    .editor-pane {{ border-right:1px solid var(--line); background:#0f172a; }}
    .editor-toolbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:10px; padding:12px 14px; border-bottom:1px solid rgba(226,232,240,.18); background:#111827; color:#e5e7eb; }}
    .editor-toolbar code {{ color:#bfdbfe; }}
    .editor-toolbar input[type="file"] {{ width:auto; max-width:260px; border-color:#334155; background:#0f172a; color:#e5e7eb; }}
    .editor-toolbar .button, .editor-toolbar button {{ min-height:34px; }}
    .editor-status {{ margin-left:auto; color:#cbd5e1; font-size:.92rem; }}
    #source-editor {{ flex:1; width:100%; min-height:0; border:0; border-radius:0; background:#0f172a; color:#e5e7eb; padding:18px; font:15px/1.6 Consolas, "Cascadia Mono", "Microsoft YaHei", monospace; resize:none; outline:none; tab-size:2; }}
    .preview-pane {{ background:#fff; }}
    .preview-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:12px 18px; border-bottom:1px solid var(--line); }}
    .preview-body {{ flex:1; overflow:auto; padding:24px; }}
    .preview-body img {{ max-width:100%; border-radius:8px; }}
    .article-preview {{ max-width:760px; margin:0 auto; }}
    .article-cover {{ width:100%; aspect-ratio:2 / 1; object-fit:cover; margin-bottom:22px; box-shadow:0 12px 36px rgba(15,23,42,.12); }}
    .article-title {{ font-size:clamp(2rem, 5vw, 3.6rem); line-height:1.1; margin-bottom:10px; text-align:center; }}
    .article-meta, .article-description {{ color:var(--muted); text-align:center; }}
    .article-tags {{ display:flex; flex-wrap:wrap; justify-content:center; gap:8px; margin:14px 0 24px; }}
    .article-tag {{ border-radius:999px; background:#dbeafe; color:#1e40af; padding:2px 10px; font-size:.9rem; }}
    .article-divider {{ border:0; border-top:1px solid var(--line); margin:22px 0; }}
    .preview-body pre {{ max-height:none; }}
    .preview-body iframe {{ width:100%; min-height:70vh; border:1px solid var(--line); border-radius:8px; background:#fff; }}
    .site-preview-frame {{ height:100%; min-height:0 !important; border:0 !important; border-radius:0 !important; }}
    .preview-body table {{ margin:1rem 0; }}
    .preview-body blockquote {{ margin:1rem 0; padding-left:1rem; border-left:4px solid var(--accent); color:var(--muted); }}
    @media (max-width: 980px) {{
      body {{ height:auto; overflow:auto; }}
      .editor-shell {{ grid-template-columns:1fr; height:auto; }}
      #source-editor {{ min-height:54vh; }}
      .editor-pane {{ border-right:0; }}
      .preview-pane {{ min-height:60vh; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div>
        <h1>{html_escape(title)}</h1>
        <p class="muted">{html_escape(rel_file if rel_file != "__new_post__" else "新文章，首次保存后会生成文件")}</p>
      </div>
      <div class="actions">
        <a class="button secondary" href="/">返回面板</a>
        <a class="button" href="http://{PREVIEW_HOST}:{PREVIEW_PORT}/" target="_blank">打开预览</a>
      </div>
    </div>
  </header>
  <main class="editor-shell">
    <section class="editor-pane">
      <div class="editor-toolbar">
        <button id="save-button" type="button">保存</button>
        <label class="compact">
          <input id="image-upload" type="file" accept=".jpg,.jpeg,.png,.webp,.avif,.gif,.svg,image/*" multiple>
        </label>
        <button class="ghost" id="upload-button" type="button">插入图片</button>
        <span>类型：<code id="file-kind">{html_escape(kind)}</code></span>
        <span class="editor-status" id="editor-status">{status_html}</span>
      </div>
      <textarea id="source-editor" spellcheck="false">{html_escape(content)}</textarea>
    </section>
    <section class="preview-pane">
      <div class="preview-head">
        <h2>预览</h2>
        <span class="muted" id="preview-kind">{html_escape(kind)}</span>
      </div>
      <div class="preview-body" id="preview"></div>
    </section>
  </main>
  <script>
    let currentFile = {json.dumps(rel_file, ensure_ascii=False)};
    const suffix = {json.dumps(suffix, ensure_ascii=False)};
    const kind = {json.dumps(kind, ensure_ascii=False)};
    const siteRoute = {json.dumps(site_route, ensure_ascii=False)};
    const previewBase = {json.dumps(f"http://{PREVIEW_HOST}:{PREVIEW_PORT}", ensure_ascii=False)};
    const isNewPost = {json.dumps(is_new_post)};
    const editor = document.getElementById('source-editor');
    const preview = document.getElementById('preview');
    const status = document.getElementById('editor-status');
    const fileKind = document.getElementById('file-kind');

    function escapeHtml(value) {{
      return String(value).replace(/[&<>"']/g, (char) => ({{
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      }}[char]));
    }}

    function inlineMarkdown(value) {{
      let text = escapeHtml(value);
      text = text.replace(/!\\[([^\\]]*)\\]\\(([^)]+)\\)/g, '<img src="$2" alt="$1">');
      text = text.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
      text = text.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
      return text;
    }}

    function parseFrontmatter(source) {{
      const match = source.match(/^---\\s*\\n([\\s\\S]*?)\\n---\\s*/);
      if (!match) return {{ data: {{}}, body: source }};
      const data = {{}};
      for (const rawLine of match[1].split('\\n')) {{
        const index = rawLine.indexOf(':');
        if (index === -1) continue;
        const key = rawLine.slice(0, index).trim();
        let value = rawLine.slice(index + 1).trim();
        value = value.replace(/^['"]|['"]$/g, '');
        if (value.startsWith('[') && value.endsWith(']')) {{
          data[key] = value.slice(1, -1).split(',').map((item) => item.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
        }} else {{
          data[key] = value;
        }}
      }}
      return {{ data, body: source.slice(match[0].length) }};
    }}

    function resolvePreviewPath(path) {{
      if (!path) return '';
      if (/^(https?:)?\\/\\//.test(path) || path.startsWith('/')) return path;
      if (!currentFile || currentFile === '__new_post__') return path;
      const stack = currentFile.split('/').slice(0, -1);
      for (const part of path.split('/')) {{
        if (!part || part === '.') continue;
        if (part === '..') stack.pop();
        else stack.push(part);
      }}
      return '/preview_asset/' + stack.join('/');
    }}

    function renderMarkdownBody(body) {{
      const lines = body.split('\\n');
      const html = [];
      let inCode = false;
      let codeLines = [];
      let inList = false;
      for (const line of lines) {{
        if (line.trim().startsWith('```')) {{
          if (inCode) {{
            html.push('<pre><code>' + escapeHtml(codeLines.join('\\n')) + '</code></pre>');
            codeLines = [];
            inCode = false;
          }} else {{
            if (inList) {{ html.push('</ul>'); inList = false; }}
            inCode = true;
          }}
          continue;
        }}
        if (inCode) {{
          codeLines.push(line);
          continue;
        }}
        if (/^\\s*-\\s+/.test(line)) {{
          if (!inList) {{ html.push('<ul>'); inList = true; }}
          html.push('<li>' + inlineMarkdown(line.replace(/^\\s*-\\s+/, '')) + '</li>');
          continue;
        }}
        if (inList) {{ html.push('</ul>'); inList = false; }}
        if (!line.trim()) {{
          html.push('');
        }} else if (line.startsWith('### ')) {{
          html.push('<h3>' + inlineMarkdown(line.slice(4)) + '</h3>');
        }} else if (line.startsWith('## ')) {{
          html.push('<h2>' + inlineMarkdown(line.slice(3)) + '</h2>');
        }} else if (line.startsWith('# ')) {{
          html.push('<h1>' + inlineMarkdown(line.slice(2)) + '</h1>');
        }} else if (line.startsWith('> ')) {{
          html.push('<blockquote>' + inlineMarkdown(line.slice(2)) + '</blockquote>');
        }} else {{
          html.push('<p>' + inlineMarkdown(line) + '</p>');
        }}
      }}
      if (inList) html.push('</ul>');
      if (inCode) html.push('<pre><code>' + escapeHtml(codeLines.join('\\n')) + '</code></pre>');
      return html.join('\\n');
    }}

    function renderMarkdown(source) {{
      const parsed = parseFrontmatter(source);
      const data = parsed.data;
      const title = data.title || '未命名文章';
      const description = data.description || '';
      const pubDate = data.pubDate || '';
      const updatedDate = data.updatedDate || '';
      const tags = Array.isArray(data.tags) ? data.tags : [];
      const heroImage = resolvePreviewPath(data.heroImage || '');
      const cover = heroImage ? '<img class="article-cover" src="' + escapeHtml(heroImage) + '" alt="' + escapeHtml(title) + ' 封面">' : '';
      const tagHtml = tags.length ? '<div class="article-tags">' + tags.map((tag) => '<span class="article-tag">' + escapeHtml(tag) + '</span>').join('') + '</div>' : '';
      const updatedHtml = updatedDate ? ' · 更新于 ' + escapeHtml(updatedDate) : '';
      preview.innerHTML = `
        <article class="article-preview">
          ${{cover}}
          <p class="article-meta">${{escapeHtml(pubDate)}}${{updatedHtml}}</p>
          <h1 class="article-title">${{escapeHtml(title)}}</h1>
          ${{description ? '<p class="article-description">' + escapeHtml(description) + '</p>' : ''}}
          ${{tagHtml}}
          <hr class="article-divider">
          <div class="article-body">${{renderMarkdownBody(parsed.body)}}</div>
        </article>
      `;
    }}

    function renderPreview() {{
      const source = editor.value;
      if (siteRoute) {{
        const url = previewBase + siteRoute + (siteRoute.includes('?') ? '&' : '?') + 'panelPreview=' + Date.now();
        preview.innerHTML = `
          <iframe class="site-preview-frame" src="${{url}}"></iframe>
          <p class="muted">这里显示的是 Astro 本地预览服务。如果没有画面，请先回到控制面板点击“启动预览”。</p>
        `;
        return;
      }}
      if (['md', 'mdx'].includes(kind)) {{
        renderMarkdown(source);
        return;
      }}
      if (kind === 'json') {{
        try {{
          preview.innerHTML = '<pre><code>' + escapeHtml(JSON.stringify(JSON.parse(source), null, 2)) + '</code></pre>';
        }} catch (error) {{
          preview.innerHTML = '<pre><code>' + escapeHtml(error.message + '\\n\\n' + source) + '</code></pre>';
        }}
        return;
      }}
      if (['html', 'svg'].includes(kind)) {{
        preview.innerHTML = '<iframe sandbox="allow-same-origin" srcdoc="' + escapeHtml(source) + '"></iframe>';
        return;
      }}
      preview.innerHTML = '<pre><code>' + escapeHtml(source) + '</code></pre>';
    }}

    function insertAtCursor(text) {{
      const start = editor.selectionStart ?? editor.value.length;
      const end = editor.selectionEnd ?? editor.value.length;
      const before = editor.value.slice(0, start);
      const after = editor.value.slice(end);
      const insertion = (before && !before.endsWith('\\n') ? '\\n\\n' : '') + text + (after && !text.endsWith('\\n') ? '\\n\\n' : '');
      editor.value = before + insertion + after;
      const cursor = before.length + insertion.length;
      editor.focus();
      editor.setSelectionRange(cursor, cursor);
      renderPreview();
    }}

    async function saveSource() {{
      status.textContent = '保存中...';
      const body = new URLSearchParams();
      body.set('file', currentFile);
      body.set('content', editor.value);
      body.set('suffix', suffix);
      const response = await fetch('/action/save_source', {{ method: 'POST', body }});
      const text = await response.text();
      status.textContent = text;
      const match = text.match(/^已保存：(.+)$/);
      if (match) {{
        currentFile = match[1];
        if (fileKind) fileKind.textContent = currentFile.split('.').pop() || kind;
        const editPath = currentFile.startsWith('site/src/content/blog/') ? '/post/edit' : '/file/edit';
        history.replaceState(null, '', editPath + '?file=' + encodeURIComponent(currentFile));
        if (siteRoute) renderPreview();
      }}
    }}

    async function uploadImages() {{
      const input = document.getElementById('image-upload');
      if (!input.files.length) {{
        status.textContent = '请选择图片。';
        return;
      }}
      status.textContent = '上传中...';
      const body = new FormData();
      for (const file of input.files) body.append('images', file);
      const response = await fetch('/action/upload_editor_images', {{ method: 'POST', body }});
      const text = await response.text();
      if (!response.ok || !text.startsWith('![')) {{
        status.textContent = text;
        return;
      }}
      insertAtCursor(text);
      input.value = '';
      status.textContent = '图片已插入到光标位置。';
    }}

    document.getElementById('save-button').addEventListener('click', saveSource);
    document.getElementById('upload-button').addEventListener('click', uploadImages);
    editor.addEventListener('input', renderPreview);
    editor.addEventListener('keydown', (event) => {{
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {{
        event.preventDefault();
        saveSource();
      }}
      if (event.key === 'Tab') {{
        event.preventDefault();
        insertAtCursor('  ');
      }}
    }});
    renderPreview();
  </script>
</body>
</html>"""


def render_page(message: CommandResult | None = None, edit_file: str = "") -> str:
    posts = list_posts()
    friends = read_friends()
    home = read_home()
    navigation = read_navigation()
    footer = read_footer()
    theme = read_theme()
    templates = list_post_templates()
    editable_files = list_editable_files()
    home_section = home["sections"][0] if home.get("sections") else {}
    git_status = get_git_status()
    preview_running = is_port_open(PREVIEW_HOST, PREVIEW_PORT)
    deps_ready = node_modules_ready()
    site_url = get_site_url()
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
    template_options = "\n".join(
        f'<option value="{html_escape(template["file"])}">{html_escape(template["title"])} ({html_escape(template["kind"].upper())})</option>'
        for template in templates
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
    navigation_row_parts: list[str] = []
    for index, item in enumerate(navigation):
        page_file = page_file_for_href(str(item.get("href", "")))
        edit_link = (
            f'<a class="button ghost" href="/file/edit?file={quote(page_file)}">编辑页面</a>'
            if page_file
            else '<span class="muted">无对应页面</span>'
        )
        navigation_row_parts.append(
            f"""
        <tr>
          <td><input name="order_{index}" type="number" min="1" value="{index + 1}"></td>
          <td><input name="label_{index}" required value="{html_escape(item.get('label', ''))}"></td>
          <td><input name="href_{index}" required value="{html_escape(item.get('href', ''))}" placeholder="/blog"></td>
          <td><label class="compact"><input type="checkbox" name="enabled_{index}" {'checked' if item.get('enabled', True) else ''}> 显示</label></td>
          <td>{edit_link}</td>
          <td><label class="compact"><input type="checkbox" name="delete_{index}"> 删除</label></td>
        </tr>
        """
        )
    navigation_rows = "\n".join(navigation_row_parts)
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
    post_row_parts: list[str] = []
    for post in posts:
        share_url = f"{site_url}/blog/{post['name'].rsplit('.', 1)[0]}/"
        visibility_button = (
            f"""
            <form method="post" action="/action/set_post_visibility">
              <input type="hidden" name="file" value="{html_escape(post['file'])}">
              <input type="hidden" name="visible" value="true">
              <button class="ghost" type="submit">显示</button>
            </form>
            """
            if post["draft"]
            else f"""
            <form method="post" action="/action/set_post_visibility">
              <input type="hidden" name="file" value="{html_escape(post['file'])}">
              <input type="hidden" name="visible" value="false">
              <button class="ghost" type="submit">取消发布</button>
            </form>
            """
        )
        share_cell = (
            f"""
            <a class="button ghost" href="{html_escape(share_url)}" target="_blank" rel="noopener noreferrer">打开</a>
            <button class="ghost copy-link" type="button" data-url="{html_escape(share_url)}">复制</button>
            """
            if not post["draft"]
            else '<span class="muted">隐藏后不能分享</span>'
        )
        post_row_parts.append(
            f"""
        <tr>
          <td>{'草稿' if post['draft'] else '已发布'}</td>
          <td>{html_escape(post['title'])}</td>
          <td>{html_escape(post['date'])}</td>
          <td>{html_escape(', '.join(post['tags']))}</td>
          <td>{html_escape(post['file'])}</td>
          <td><div class="actions">{visibility_button}<a class="button ghost" href="/post/edit?file={quote(post['file'])}">编辑</a><form method="post" action="/action/save_post_template"><input type="hidden" name="file" value="{html_escape(post['file'])}"><button class="ghost" type="submit">存为模板</button></form></div></td>
          <td><div class="actions">{share_cell}</div></td>
        </tr>
        """
        )
    post_rows = "\n".join(post_row_parts)
    image_post_options = "\n".join(
        f'<option value="{html_escape(post["file"])}">{html_escape(post["title"])} ({html_escape(post["name"])})</option>'
        for post in posts
    )
    file_options = "\n".join(
        f'<option value="{html_escape(item["file"])}">{html_escape(item["file"])}</option>'
        for item in editable_files
    )
    font_choices = BUILTIN_FONT_OPTIONS + [
        {
            "id": str(font.get("id", "")),
            "label": f"自定义：{font.get('label') or font.get('family') or font.get('id')}",
        }
        for font in theme.get("customFonts", [])
        if isinstance(font, dict) and font.get("id")
    ]
    def font_options(selected: Any) -> str:
        return "\n".join(
            f'<option value="{html_escape(item["id"])}" {"selected" if item["id"] == selected else ""}>{html_escape(item["label"])}</option>'
            for item in font_choices
        )

    body_font_options = font_options(theme.get("bodyFont"))
    heading_font_options = font_options(theme.get("headingFont"))
    nav_font_options = font_options(theme.get("navFont", theme.get("bodyFont")))
    home_title_font_options = font_options(theme.get("homeTitleFont", theme.get("headingFont")))
    home_text_font_options = font_options(theme.get("homeTextFont", theme.get("bodyFont")))
    post_title_font_options = font_options(theme.get("postTitleFont", theme.get("headingFont")))
    post_body_font_options = font_options(theme.get("postBodyFont", theme.get("bodyFont")))
    footer_font_options = font_options(theme.get("footerFont", theme.get("bodyFont")))
    custom_font_rows = "\n".join(
        f'<li>{html_escape(font.get("label") or font.get("family") or font.get("id"))} <span class="muted">{html_escape(font.get("url", ""))}</span></li>'
        for font in theme.get("customFonts", [])
        if isinstance(font, dict)
    )
    douyin_preview_class = "" if footer.get("douyinHref") else " is-empty"
    douyin_preview_href = html_escape(footer.get("douyinHref") or "#")
    bilibili_preview_class = "" if footer.get("bilibiliHref") else " is-empty"
    bilibili_preview_href = html_escape(footer.get("bilibiliHref") or "#")
    preview_url = f"http://{PREVIEW_HOST}:{PREVIEW_PORT}/"
    embedded_preview_html = (
        f'<iframe src="{preview_url}" title="网站实时预览"></iframe>'
        if preview_running
        else '<div class="preview-placeholder">预览服务还没启动。点击上面的“启动预览”后，这里会显示网站首页。</div>'
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>博客控制面板</title>
  <style>
    :root {{ --accent:#2563eb; --accent-2:#0f766e; --ink:#111827; --muted:#64748b; --line:#e2e8f0; --bg:#f8fafc; --surface:#fff; }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior:smooth; }}
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
    .panel-nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:0 0 16px; padding:8px; border:1px solid var(--line); border-radius:999px; background:rgba(255,255,255,.82); box-shadow:0 10px 30px rgba(15,23,42,.06); }}
    .panel-nav a {{ flex:1 1 120px; border-radius:999px; padding:9px 14px; color:#334155; text-align:center; text-decoration:none; font-weight:700; }}
    .panel-nav a:hover {{ background:#e0f2fe; color:#075985; }}
    .quick-actions {{ margin-bottom:18px; background:linear-gradient(135deg,#fff 0%,#eff6ff 58%,#ecfdf5 100%); }}
    .quick-actions-head {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; margin-bottom:10px; }}
    .quick-actions form {{ margin:0; }}
    .commit-line {{ display:grid; grid-template-columns:minmax(220px,1fr) auto; gap:10px; align-items:end; margin-top:12px; }}
    .dashboard-preview {{ margin-bottom:18px; overflow:hidden; padding:0; }}
    .dashboard-preview-head {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding:14px 16px; border-bottom:1px solid var(--line); }}
    .dashboard-preview-head h2 {{ margin:0; }}
    .dashboard-preview iframe {{ display:block; width:100%; min-height:520px; border:0; background:#fff; }}
    .preview-placeholder {{ min-height:220px; display:grid; place-items:center; padding:28px; color:var(--muted); text-align:center; background:linear-gradient(135deg,#f8fafc,#eef2ff); }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; align-items:start; }}
    .section-title {{ grid-column:1 / -1; padding:18px 4px 2px; }}
    .section-title h2 {{ margin:0; font-size:1.45rem; }}
    .section-title p {{ margin:0; color:var(--muted); }}
    label {{ display:block; color:var(--muted); font-size:.92rem; margin:10px 0 4px; }}
    input, select, textarea {{ width:100%; border:1px solid var(--line); border-radius:8px; padding:10px 12px; font:inherit; background:#fff; }}
    input[type="number"] {{ min-width:72px; }}
    input[type="range"] {{ padding:0; }}
    textarea {{ min-height:84px; resize:vertical; }}
    .body-editor {{ min-height:420px; font-family:Consolas, "Microsoft YaHei", monospace; line-height:1.55; }}
    .hint {{ display:block; margin-top:4px; color:var(--muted); font-size:.86rem; }}
    .compact {{ display:flex; align-items:center; gap:6px; margin:0; color:var(--ink); white-space:nowrap; }}
    .compact input {{ width:auto; }}
    .field-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px 16px; }}
    .range-line {{ display:grid; grid-template-columns:minmax(0,1fr) 4.5rem; gap:10px; align-items:center; }}
    button, .button {{ display:inline-flex; align-items:center; justify-content:center; min-height:38px; border:0; border-radius:8px; background:var(--accent); color:#fff; padding:8px 14px; font-weight:700; text-decoration:none; cursor:pointer; }}
    button.secondary, .button.secondary {{ background:#111827; }}
    button.ghost, .button.ghost {{ background:#eef2ff; color:#1e40af; min-height:32px; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }}
    .footer-icon-preview {{ display:flex; align-items:center; gap:12px; margin:14px 0 4px; padding:14px; border:1px dashed #cbd5e1; border-radius:12px; background:#f8fafc; }}
    .footer-icon-preview strong {{ margin-right:auto; color:#334155; }}
    .panel-social {{ width:36px; height:36px; display:inline-flex; align-items:center; justify-content:center; border:1px solid #dbe4ef; border-radius:999px; background:#fff; color:#23304b; text-decoration:none; transition:transform .18s ease, box-shadow .18s ease; }}
    .panel-social:hover {{ transform:translateY(-1px); box-shadow:0 8px 22px rgba(15,23,42,.12); }}
    .panel-social.is-empty {{ opacity:.38; filter:grayscale(1); pointer-events:none; }}
    .panel-social svg {{ width:18px; height:18px; display:block; }}
    .panel-social.douyin {{ color:#111827; }}
    .panel-social.bilibili {{ color:#00aeec; }}
    pre {{ white-space:pre-wrap; overflow:auto; background:#0f172a; color:#e5e7eb; border-radius:8px; padding:12px; max-height:360px; }}
    .result.ok {{ border-color:#86efac; }}
    .result.bad {{ border-color:#fca5a5; }}
    table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
    th,td {{ border-bottom:1px solid var(--line); text-align:left; padding:10px; vertical-align:top; }}
    .wide {{ grid-column:1 / -1; }}
    @media (max-width: 900px) {{ .status, .grid, .commit-line {{ grid-template-columns:1fr; }} header .wrap, .quick-actions-head, .dashboard-preview-head {{ align-items:flex-start; flex-direction:column; }} .panel-nav {{ border-radius:18px; }} .dashboard-preview iframe {{ min-height:420px; }} }}
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
    <section class="panel quick-actions" id="quick-actions">
      <div class="quick-actions-head">
        <div>
          <h2>预览、构建和发布</h2>
          <p class="muted">最常用的启动预览、构建检查、推送上线都放在这里，打开控制面板就能直接操作。</p>
        </div>
        <a class="button ghost" href="http://{PREVIEW_HOST}:{PREVIEW_PORT}/" target="_blank">打开网站预览</a>
      </div>
      <div class="actions">
        <form method="post" action="/action/check_requirements"><button class="ghost" type="submit">检查环境</button></form>
        <form method="post" action="/action/install_dependencies"><button class="secondary" type="submit">安装/更新依赖</button></form>
        <form method="post" action="/action/start_preview"><button type="submit">启动预览</button></form>
        <form method="post" action="/action/stop_preview"><button class="secondary" type="submit">停止预览</button></form>
        <form method="post" action="/action/build"><button type="submit">构建检查</button></form>
      </div>
      <form method="post" action="/action/update_blog" class="commit-line">
        <div>
          <label>提交说明</label>
          <input name="message" value="update blog">
        </div>
        <button type="submit">构建并推送</button>
      </form>
    </section>
    {message_html}
    <nav class="panel-nav" aria-label="控制面板分区">
      <a href="#quick-actions">预览发布</a>
      <a href="#writing-section">文章写作</a>
      <a href="#pages-section">页面导航</a>
      <a href="#appearance-section">外观底部</a>
      <a href="#data-section">友链数据</a>
    </nav>
    <section class="status">
      <div class="metric"><strong>{len(posts)}</strong><span>文章总数</span></div>
      <div class="metric"><strong>{len(drafts)}</strong><span>草稿</span></div>
      <div class="metric"><strong>{len(friends)}</strong><span>友链</span></div>
      <div class="metric"><strong>{'运行中' if preview_running else '未启动'}</strong><span>本地预览</span></div>
      <div class="metric"><strong>{'已安装' if deps_ready else '未安装'}</strong><span>项目依赖</span></div>
    </section>
    <section class="panel dashboard-preview" id="site-preview">
      <div class="dashboard-preview-head">
        <div>
          <h2>网站预览</h2>
          <p class="muted">这里直接嵌入本地预览首页，方便你保存设置后马上对照效果。</p>
        </div>
        <a class="button ghost" href="{preview_url}" target="_blank">新窗口打开</a>
      </div>
      {embedded_preview_html}
    </section>
    <section class="grid">
      <div class="section-title" id="writing-section">
        <h2>文章写作</h2>
        <p>新建、编辑、发布、插图和文章显示控制都在这一组。</p>
      </div>
      <div class="panel">
        <h2>新建文章</h2>
        <form method="get" action="/post/new">
          <label>标题</label>
          <input name="title" required placeholder="例如：今天把博客控制面板做起来">
          <label>摘要</label>
          <textarea name="description" placeholder="一句话说明这篇文章写什么"></textarea>
          <label>标签（用逗号分隔）</label>
          <input name="tags" placeholder="建站, 记录">
          <label>发布日期</label>
          <input name="pubDate" type="date" value="{date.today().isoformat()}">
          <label>文章模板</label>
          <select name="template">
            <option value="">空白模板</option>
            {template_options}
          </select>
          <span class="hint">模板来自 scripts/post_templates。第一次启动面板会自动用当前几篇文章生成模板；也可以在文章列表里点“存为模板”。</span>
          <label>格式</label>
          <select name="format"><option value="md">Markdown</option><option value="mdx">MDX</option></select>
          <span class="hint">选择模板时会优先使用模板自己的 md/mdx 格式。</span>
          <label><input style="width:auto" type="checkbox" name="draft"> 先隐藏，不在网站显示</label>
          <div class="actions"><button type="submit">进入编辑器</button></div>
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
        <h2>当前模板</h2>
        <p class="muted">新建文章时可以从这些模板起步，打开编辑器后再改标题、正文和图片。</p>
        <ul>{''.join(f'<li>{html_escape(template["title"])} <span class="muted">{html_escape(template["name"])}</span></li>' for template in templates) or '<li class="muted">暂无模板，重启控制面板会从当前文章自动生成。</li>'}</ul>
      </div>
      <div class="panel">
        <h2>编辑已有文章</h2>
        <form method="get" action="/post/edit">
          <label>选择文章</label>
          <select name="file" {'disabled' if not posts else ''}>{edit_options or '<option>暂无文章</option>'}</select>
          <div class="actions"><button type="submit" {'disabled' if not posts else ''}>进入编辑器</button></div>
        </form>
      </div>
      <div class="panel">
        <h2>编辑常用文件</h2>
        <form method="get" action="/file/edit">
          <label>选择文件</label>
          <select name="file" {'disabled' if not editable_files else ''}>{file_options or '<option>暂无可编辑文件</option>'}</select>
          <div class="actions"><button type="submit" {'disabled' if not editable_files else ''}>打开文件</button></div>
        </form>
      </div>
      {edit_form_html}
      <div class="section-title" id="pages-section">
        <h2>页面导航</h2>
        <p>这里管理导航栏显示、链接顺序，以及“关于我”等独立页面的编辑入口。</p>
      </div>
      <div class="panel wide" id="navigation">
        <h2>导航栏目</h2>
        <form method="post" action="/action/update_navigation">
          <table>
            <thead><tr><th>顺序</th><th>名称</th><th>链接</th><th>显示</th><th>页面内容</th><th>删除</th></tr></thead>
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
      <div class="section-title" id="appearance-section">
        <h2>外观、字体和底部</h2>
        <p>首页文案背景、各区域字体、网站底部和社交图标集中放在这里。</p>
      </div>
      <div class="panel wide" id="footer-settings">
        <h2>底部信息</h2>
        <form method="post" action="/action/update_footer">
          <label>版权行</label>
          <input name="copyright" value="{html_escape(footer.get('copyright', ''))}" placeholder="© {{year}} ztt. All rights reserved.">
          <span class="hint">可以使用 {{year}}，页面会自动替换成当前年份。</span>
          <label>说明文字</label>
          <input name="description" value="{html_escape(footer.get('description', ''))}">
          <label class="compact"><input type="checkbox" name="showRss" {'checked' if footer.get('showRss') else ''}> 显示 RSS 链接</label>
          <div class="field-grid">
            <div>
              <label>RSS 文字</label>
              <input name="rssLabel" value="{html_escape(footer.get('rssLabel', ''))}">
            </div>
            <div>
              <label>RSS 链接</label>
              <input name="rssHref" value="{html_escape(footer.get('rssHref', ''))}">
            </div>
          </div>
          <div class="field-grid">
            <div>
              <label>抖音主页链接</label>
              <input name="douyinHref" value="{html_escape(footer.get('douyinHref', ''))}" placeholder="https://www.douyin.com/user/...">
            </div>
            <div>
              <label>Bilibili 主页链接</label>
              <input name="bilibiliHref" value="{html_escape(footer.get('bilibiliHref', ''))}" placeholder="https://space.bilibili.com/...">
            </div>
          </div>
          <span class="hint">链接为空时不会显示对应图标；填写后底部会显示小图标并跳转到你的主页。</span>
          <div class="footer-icon-preview" aria-label="底部社交图标预览">
            <strong>图标预览</strong>
            <a class="panel-social douyin{douyin_preview_class}" href="{douyin_preview_href}" target="_blank" rel="noopener noreferrer" title="抖音">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path fill="currentColor" d="M14.4 3c.3 2.7 1.8 4.6 4.6 4.8v3.1a8 8 0 0 1-4.5-1.3v5.8c0 3.4-2.5 5.6-5.7 5.6A5.5 5.5 0 0 1 3 15.5c0-3.5 3-6 6.8-5.4v3.2c-2-.5-3.6.4-3.6 2.1 0 1.3 1 2.3 2.4 2.3 1.6 0 2.5-.9 2.5-2.8V3h3.3Z"/>
              </svg>
            </a>
            <a class="panel-social bilibili{bilibili_preview_class}" href="{bilibili_preview_href}" target="_blank" rel="noopener noreferrer" title="bilibili">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path fill="currentColor" d="M8.1 4.2 10 6.1h4l1.9-1.9a1 1 0 0 1 1.4 1.4L16.9 6H18a3 3 0 0 1 3 3v7.2a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V9a3 3 0 0 1 3-3h1.1L6.7 5.6a1 1 0 1 1 1.4-1.4ZM6 8.7c-.4 0-.8.4-.8.8v6.2c0 .5.4.8.8.8h12c.4 0 .8-.3.8-.8V9.5c0-.4-.4-.8-.8-.8H6Zm2.4 2.7c.6 0 1 .5 1 1v1.1a1 1 0 0 1-2 0v-1.1c0-.5.4-1 1-1Zm7.2 0c.6 0 1 .5 1 1v1.1a1 1 0 0 1-2 0v-1.1c0-.5.4-1 1-1Z"/>
              </svg>
            </a>
          </div>
          <span class="hint">灰色表示链接还没填；保存链接后，预览和正式网站底部都会显示可点击图标。</span>
          <div class="actions"><button type="submit">保存底部信息</button></div>
        </form>
      </div>
      <div class="panel wide" id="theme-fonts">
        <h2>字体设置</h2>
        <form method="post" action="/action/update_theme" enctype="multipart/form-data">
          <p class="muted">普通选项使用字体栈：访客电脑有这个字体就显示，没有就自动回退到可用字体。只有上传自定义字体时，字体文件才会跟着网站发布。</p>
          <div class="field-grid">
            <div>
              <label>全站正文字体</label>
              <select name="bodyFont">{body_font_options}</select>
            </div>
            <div>
              <label>标题字体</label>
              <select name="headingFont">{heading_font_options}</select>
            </div>
            <div>
              <label>导航栏字体</label>
              <select name="navFont">{nav_font_options}</select>
            </div>
            <div>
              <label>首页大标题字体</label>
              <select name="homeTitleFont">{home_title_font_options}</select>
            </div>
            <div>
              <label>首页说明文字字体</label>
              <select name="homeTextFont">{home_text_font_options}</select>
            </div>
            <div>
              <label>文章标题字体</label>
              <select name="postTitleFont">{post_title_font_options}</select>
            </div>
            <div>
              <label>文章正文字体</label>
              <select name="postBodyFont">{post_body_font_options}</select>
            </div>
            <div>
              <label>底部字体</label>
              <select name="footerFont">{footer_font_options}</select>
            </div>
          </div>
          <h3>上传自定义字体</h3>
          <label>字体名称</label>
          <input name="fontFamily" placeholder="例如：霞鹜文楷">
          <label>字体粗细</label>
          <select name="fontWeight">
            <option value="400">常规 400</option>
            <option value="500">中等 500</option>
            <option value="700">粗体 700</option>
          </select>
          <label>字体文件</label>
          <input name="fontFile" type="file" accept=".woff2,.woff,.ttf,.otf,font/*">
          <span class="hint">推荐上传 woff2 或 woff。中文字体可能有几 MB 到几十 MB，只在需要特殊字体时上传。</span>
          <label class="compact"><input type="checkbox" name="applyUploadedToBody"> 上传后应用到全站正文</label>
          <label class="compact"><input type="checkbox" name="applyUploadedToHeading"> 上传后应用到全站标题</label>
          <div class="actions"><button type="submit">保存字体设置</button></div>
        </form>
        <h3>已上传字体</h3>
        <ul>{custom_font_rows or '<li class="muted">暂无自定义字体</li>'}</ul>
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
          <h3>透明度</h3>
          <div class="field-grid">
            <div>
              <label>背景左侧白色遮罩</label>
              <div class="range-line">
                <input name="heroOverlayStart" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayStart', 0.72))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayStart', 0.72))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='heroOverlayStart'">
              </div>
            </div>
            <div>
              <label>背景右侧白色遮罩</label>
              <div class="range-line">
                <input name="heroOverlayEnd" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayEnd', 0.42))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('heroOverlayEnd', 0.42))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='heroOverlayEnd'">
              </div>
            </div>
            <div>
              <label>当前状态白色遮罩</label>
              <div class="range-line">
                <input name="heroPanelOpacity" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('heroPanelOpacity', 0.82))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('heroPanelOpacity', 0.82))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='heroPanelOpacity'">
              </div>
            </div>
            <div>
              <label>主按钮透明度</label>
              <div class="range-line">
                <input name="primaryButtonOpacity" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('primaryButtonOpacity', 1.0))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('primaryButtonOpacity', 1.0))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='primaryButtonOpacity'">
              </div>
            </div>
            <div>
              <label>副按钮透明度</label>
              <div class="range-line">
                <input name="secondaryButtonOpacity" type="range" min="0" max="1" step="0.01" value="{html_escape(home.get('secondaryButtonOpacity', 0.86))}" oninput="this.nextElementSibling.value=this.value">
                <input type="number" min="0" max="1" step="0.01" value="{html_escape(home.get('secondaryButtonOpacity', 0.86))}" oninput="this.previousElementSibling.value=this.value; this.previousElementSibling.name='secondaryButtonOpacity'">
              </div>
            </div>
          </div>
          <span class="hint">数值越低越透明。背景遮罩太低会影响文字可读性，建议左侧 0.55-0.8、右侧 0.25-0.55。</span>
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
      <div class="section-title" id="data-section">
        <h2>友链、列表和状态</h2>
        <p>友链维护、Git 状态、文章显示/分享入口放在最后，方便检查。</p>
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
        <p class="muted">“显示”的文章会出现在网站并可以分享；“隐藏”的文章不会出现在公开页面里，别人打开线上链接也看不到。</p>
        <table>
          <thead><tr><th>状态</th><th>标题</th><th>日期</th><th>标签</th><th>文件</th><th>操作</th><th>分享</th></tr></thead>
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
  <script>
    document.querySelectorAll('.copy-link').forEach((button) => {{
      button.addEventListener('click', async () => {{
        const url = button.dataset.url || '';
        try {{
          await navigator.clipboard.writeText(url);
          button.textContent = '已复制';
        }} catch (error) {{
          window.prompt('复制这条链接：', url);
        }}
      }});
    }});
  </script>
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
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            edit_file = query.get("edit", [""])[-1]
            self.send_html(render_page(edit_file=edit_file))
            return
        if parsed.path == "/post/new":
            title = query.get("title", [""])[-1].strip() or "新文章"
            description = query.get("description", [""])[-1].strip() or "这是一篇新的博客文章。"
            tags = [tag.strip() for tag in re.split(r"[,，]", query.get("tags", [""])[-1]) if tag.strip()]
            pub_date = query.get("pubDate", [""])[-1].strip() or date.today().isoformat()
            draft = query.get("draft", [""])[-1] == "on"
            template_rel = query.get("template", [""])[-1]
            requested_suffix = ".mdx" if query.get("format", ["md"])[-1] == "mdx" else ".md"
            content, template_suffix = source_from_template(template_rel, title, description, tags, draft, pub_date)
            suffix = template_suffix if template_rel else requested_suffix
            self.send_html(
                render_editor_page(
                    rel_file="__new_post__",
                    content=content,
                    kind=suffix.lstrip("."),
                    title="新建文章",
                    suffix=suffix,
                    is_new_post=True,
                )
            )
            return
        if parsed.path == "/post/edit":
            rel_file = query.get("file", [""])[-1]
            path = post_path_from_rel(rel_file)
            if not path:
                self.send_html(render_page(CommandResult(1, "没有找到要编辑的文章。")))
                return
            self.send_html(
                render_editor_page(
                    rel_file=relative_to_root(path),
                    content=read_text_file(path),
                    kind=path.suffix.lower().lstrip("."),
                    title=f"编辑文章：{path.name}",
                )
            )
            return
        if parsed.path == "/file/edit":
            rel_file = query.get("file", [""])[-1]
            path = safe_root_file(rel_file)
            if not path:
                self.send_html(render_page(CommandResult(1, "文件路径无效，或这个文件类型不允许在面板里编辑。")))
                return
            site_route = route_for_page_file(path) or ""
            if site_route:
                start_preview()
            self.send_html(
                render_editor_page(
                    rel_file=relative_to_root(path),
                    content=read_text_file(path),
                    kind=path.suffix.lower().lstrip(".") or "text",
                    title=f"编辑文件：{path.name}",
                    site_route=site_route,
                )
            )
            return
        if parsed.path.startswith("/uploads/") or parsed.path in {"/favicon.svg", "/favicon.ico"}:
            public_path = (SITE_DIR / "public" / parsed.path.lstrip("/")).resolve()
            try:
                public_path.relative_to((SITE_DIR / "public").resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not public_path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file(public_path)
            return
        if parsed.path.startswith("/preview_asset/"):
            asset_rel = parsed.path.removeprefix("/preview_asset/").replace("\\", "/").lstrip("/")
            asset_path = (ROOT / asset_rel).resolve()
            try:
                asset_path.relative_to(ROOT.resolve())
            except ValueError:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if not asset_path.is_file() or asset_path.suffix.lower() not in IMAGE_EXTENSIONS:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_file(asset_path)
            return
        else:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        content_type = self.headers.get("Content-Type", "")
        raw_body = self.rfile.read(length)
        files: dict[str, UploadedFile] = {}
        multi_files: dict[str, list[UploadedFile]] = {}
        if content_type.startswith("multipart/form-data"):
            form, multi_files = parse_multipart_multi(raw_body, content_type)
            files = {key: values[-1] for key, values in multi_files.items() if values}
        else:
            body = raw_body.decode("utf-8", errors="replace")
            form = {key: values[-1] for key, values in parse_qs(body, keep_blank_values=True).items()}

        if parsed.path == "/action/save_source":
            result = save_source_file(form)
            self.send_text(result.output, status=HTTPStatus.OK if result.code == 0 else HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/action/upload_editor_images":
            result = upload_editor_images(multi_files)
            self.send_text(result.output, status=HTTPStatus.OK if result.code == 0 else HTTPStatus.BAD_REQUEST)
            return

        actions = {
            "/action/check_requirements": lambda _: check_requirements(),
            "/action/install_dependencies": lambda _: install_dependencies(),
            "/action/create_post": create_post,
            "/action/publish_post": publish_post,
            "/action/set_post_visibility": set_post_visibility,
            "/action/save_post_template": save_post_as_template,
            "/action/save_post": lambda data: save_post(data, files),
            "/action/insert_post_image": lambda data: insert_post_image(data, files),
            "/action/update_home": lambda data: update_home_settings(data, files),
            "/action/update_navigation": update_navigation,
            "/action/update_footer": update_footer,
            "/action/update_theme": lambda data: update_theme(data, files),
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

    def send_text(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_file(self, path: Path) -> None:
        payload = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local blog control panel.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    parser.add_argument("--port", type=int, default=PANEL_PORT, help="Panel port, default: 8765.")
    args = parser.parse_args()

    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    POST_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    FRIENDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PUBLIC_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    HOME_FILE.parent.mkdir(parents=True, exist_ok=True)
    NAVIGATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOOTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    THEME_FILE.parent.mkdir(parents=True, exist_ok=True)
    (PUBLIC_FONTS_DIR / "custom").mkdir(parents=True, exist_ok=True)
    if not FRIENDS_FILE.exists():
        write_friends([])
    if not HOME_FILE.exists():
        write_home(DEFAULT_HOME)
    if not NAVIGATION_FILE.exists():
        write_navigation(DEFAULT_NAVIGATION)
    if not FOOTER_FILE.exists():
        write_footer(DEFAULT_FOOTER)
    if not THEME_FILE.exists():
        write_theme(DEFAULT_THEME)
    initialize_post_templates()

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
