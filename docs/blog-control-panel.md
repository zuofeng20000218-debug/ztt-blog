# 博客控制面板使用说明

这个控制面板是本地工具，只在你的电脑上运行，用来管理这个 Astro 静态博客。它不会给线上网站增加后台，也不需要服务器或数据库。

## 双击启动

在仓库根目录双击：

```text
open-blog-panel.bat
```

启动后会自动打开浏览器：

```text
http://127.0.0.1:8765/
```

也可以用命令启动：

```powershell
Set-Location D:\Blog
python .\scripts\blog_panel.py
```

## 换电脑后的首次使用

1. 安装 Git、Python 3、Node.js 22.12 或更新版本。
2. 从 GitHub 下载或 clone 这个仓库。
3. 双击 `open-blog-panel.bat`。
4. 在面板里点击“检查环境”。
5. 在面板里点击“安装/更新依赖”。
6. 点击“启动预览”，确认博客能在本机打开。

`node_modules/`、`site/dist/`、`.astro/` 这类本地生成文件不会上传到 GitHub。换电脑后用“安装/更新依赖”重新生成即可。

## 面板能做什么

- 检查环境：确认 Git、Node、npm 是否可用。
- 安装/更新依赖：在 `site/` 里执行 `npm ci` 或 `npm install`。
- 新建文章：自动生成 Markdown/MDX 文件和 frontmatter。
- 发布草稿：把 `draft: true` 改成 `draft: false`。
- 添加友链：写入 `site/src/data/friends.json`。
- 删除友链：从 `friends.json` 移除对应链接。
- 启动预览：打开 Astro 本地预览服务。
- 停止预览：停止由面板启动的预览服务。
- 构建检查：运行 `npm run build`。
- 构建并推送：先构建，通过后再 `git add`、`git commit`、`git push`。

## 哪些应该上传 GitHub

这些都应该保留在仓库里，换电脑后才能继续用：

- `open-blog-panel.bat`
- `scripts/blog_panel.py`
- `scripts/update_blog.py`
- `docs/blog-control-panel.md`
- `site/src/data/friends.json`
- `site/src/content/blog/` 里的文章
- `site/src/assets/` 里的图片
- `site/package.json` 和 `site/package-lock.json`

这些不要上传：

- `node_modules/`
- `site/dist/`
- `site/.astro/`
- `.env`、`.env.*`
- `scripts/github_token.txt`
- SSH 私钥、`.pem`、`.key`、`.p12`、`.pfx`

## 文章草稿

面板新建文章时默认保存为草稿：

```yaml
draft: true
```

草稿不会出现在首页、文章列表、标签、归档、搜索和 RSS 里。写完后在面板点击“发布这篇”即可公开。

## 友链数据

友链保存在：

```text
site/src/data/friends.json
```

手工编辑时保持这种格式：

```json
[
  {
    "name": "朋友名字",
    "url": "https://example.com",
    "description": "一句话介绍",
    "avatar": "https://example.com/avatar.png"
  }
]
```

## GitHub 密钥

日常推送推荐使用 SSH key。SSH key 保存在当前电脑用户目录的 `.ssh` 里，不在仓库里。

如果你使用 GitHub token，可以把它放在：

```text
scripts/github_token.txt
```

这个文件已经被 `.gitignore` 忽略，不会上传。换电脑后需要重新配置 SSH key 或重新放 token。

## 注意

- 控制面板只建议在本机打开，不要暴露到公网。
- “构建并推送”会真正提交并推送到远程仓库。
- Cloudflare Pages 会在 GitHub 收到 push 后自动部署。
