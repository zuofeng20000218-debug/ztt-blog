---
title: '第一次更新博客的工作流'
description: '把本地预览、修改内容、提交并自动部署这套流程先固定下来。'
pubDate: 'Mar 23 2026'
heroImage: '../../assets/blog-placeholder-5.jpg'
---

为了让这个博客真的长期可用，我先把日常更新流程固定成最简单的版本。

## 本地预览

启动本地预览脚本，检查页面是否正常：

```bash
python scripts/preview_blog.py
```

## 修改内容

目前最常改的几个位置：

- `src/pages/index.astro`：首页内容
- `src/pages/about.astro`：关于页
- `src/content/blog/`：文章内容
- `src/components/Header.astro` 和 `src/components/Footer.astro`：导航和页脚

## 提交和发布

改完后直接执行：

```bash
python scripts/update_blog.py -m "update blog"
```

GitHub 收到推送后，Cloudflare Pages 会自动重新部署。对个人博客来说，这种方式已经足够顺手。
