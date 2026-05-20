# ztt-blog

这是一个 Astro 静态博客项目。网站源码在 `site/`，本地管理工具在 `scripts/`，日常写文章、管理友链、预览、构建和推送都可以通过控制面板完成。

## 快速开始

Windows 上双击根目录的：

```text
open-blog-panel.bat
```

浏览器会打开本地控制面板：

```text
http://127.0.0.1:8765/
```

控制面板只在本机运行，不会成为线上后台，也不需要服务器。

## 换电脑使用

1. 安装 Git、Python 3、Node.js 22.12 或更新版本。
2. 从 GitHub clone 这个仓库。
3. 双击 `open-blog-panel.bat`。
4. 在面板里点击“检查环境”。
5. 在面板里点击“安装/更新依赖”。
6. 点击“启动预览”，确认本地站点正常。

密钥和本地依赖不会跟着仓库走。换电脑后需要重新配置 SSH key 或 token。

## 常用操作

控制面板可以完成这些事：

- 新建 Markdown/MDX 文章草稿
- 编辑已发布文章或草稿
- 发布草稿
- 添加或删除友链
- 启动和停止本地预览
- 运行构建检查
- 构建通过后提交并推送到 GitHub
- 检查本机环境和安装依赖

命令行方式也可用：

```powershell
Set-Location D:\Blog\site
npm run dev
npm run build
```

```powershell
Set-Location D:\Blog
python .\scripts\update_blog.py -m "update blog"
```

`update_blog.py` 默认会先运行 Astro 构建，构建通过后才提交和推送。

## 目录结构

```text
D:\Blog
├─ open-blog-panel.bat            # 双击打开本地控制面板
├─ README.md                      # 项目说明
├─ docs/
│  ├─ blog-control-panel.md       # 控制面板说明
│  └─ cloudflare-pages-deploy.md  # Cloudflare Pages 部署说明
├─ scripts/
│  ├─ blog_panel.py               # 控制面板服务
│  └─ update_blog.py              # 构建、提交、推送
└─ site/
   ├─ src/
   │  ├─ assets/                  # 图片资源
   │  ├─ components/              # 页面组件
   │  ├─ content/blog/            # 文章
   │  ├─ data/friends.json        # 友链数据
   │  ├─ layouts/                 # 页面布局
   │  ├─ pages/                   # 页面路由
   │  ├─ styles/                  # 全局样式
   │  └─ utils/                   # 文章过滤等工具
   ├─ public/                     # 静态资源
   ├─ astro.config.mjs            # Astro 配置
   ├─ package.json                # npm 命令和依赖
   └─ package-lock.json           # 依赖锁定
```

## 写文章

文章放在：

```text
site/src/content/blog/
```

推荐通过控制面板新建和编辑文章。手动创建时保持这个 frontmatter：

```md
---
title: "文章标题"
description: "文章摘要"
tags: ["建站", "记录"]
draft: true
pubDate: "2026-05-20"
heroImage: "../../assets/blog-placeholder-1.jpg"
---

正文内容。
```

`draft: true` 的文章不会出现在首页、列表、标签、归档、搜索和 RSS 中。写完后在控制面板里发布即可。已发布文章也可以在控制面板里重新打开编辑。

## 友链

友链数据在：

```text
site/src/data/friends.json
```

可以用控制面板维护，也可以手动编辑 JSON。

## 不要上传的文件

`.gitignore` 已经忽略这些本地文件：

- `node_modules/`
- `site/dist/`
- `site/.astro/`
- `.env`、`.env.*`
- `scripts/github_token.txt`
- Python 缓存
- SSH 私钥和常见证书文件

代码、文章、图片、友链、启动器和文档都应该提交到 GitHub。

## 部署

当前部署链路是：

```text
本地修改
  -> 构建检查
  -> git commit
  -> git push
  -> Cloudflare Pages 自动构建
  -> 发布 www.200302.xyz
```

Cloudflare Pages 配置参考：

- 项目目录：`site`
- 构建命令：`npm run build`
- 输出目录：`dist`
- 站点域名：`https://www.200302.xyz`

更多面板说明见 [docs/blog-control-panel.md](docs/blog-control-panel.md)。
