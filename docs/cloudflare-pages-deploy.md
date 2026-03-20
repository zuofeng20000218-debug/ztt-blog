# Cloudflare Pages deployment checklist

This checklist assumes:

- repo root: `D:\Blog`
- site directory: `site`
- production domain: `https://www.200302.xyz`
- temporary Pages URL: `https://personal-blog.pages.dev`

## 1. Local setup

If Node.js is not installed, install the current LTS release first:

- [Node.js](https://nodejs.org/)

If the site has not been created yet, run:

```powershell
Set-Location "D:\Blog"
.\scripts\bootstrap-blog.ps1
```

## 2. Verify the site locally

```powershell
Set-Location "D:\Blog\site"
npm install
npm run dev
```

When ready to test production output:

```powershell
Set-Location "D:\Blog\site"
npm run build
```

Cloudflare Pages' Astro guide currently lists:

- Production branch: `main`
- Build command: `npm run build`
- Build directory: `dist`

## 3. Push to GitHub

Create an empty GitHub repository first, then run:

```powershell
Set-Location "D:\Blog"
git init
git checkout -b main
git add .
git commit -m "Initial blog scaffold"
git remote add origin <your-github-repo-url>
git push -u origin main
```

## 4. Create the Pages project

In Cloudflare Pages:

1. Create a new Pages project and connect your GitHub repository.
2. Set the root directory to `site` if the repo contains more than the site.
3. Use build command `npm run build`.
4. Use build output directory `dist`.
5. Deploy and confirm the site works on `https://personal-blog.pages.dev`.

## 5. Add your custom domain

In the Pages project's **Custom domains** section:

1. Add `www.200302.xyz`.
2. Wait for Cloudflare to show the required target.
3. In your domain registrar's DNS panel, create:

```text
Type:   CNAME
Name:   www
Target: <your-pages-project>.pages.dev
```

Important:

- Add the custom domain inside Cloudflare Pages before creating the DNS record manually.
- For an externally managed domain, Cloudflare documents the subdomain setup as a CNAME pointing to `<YOUR_SITE>.pages.dev`.
- Do not change the apex (`200302.xyz`) unless you intentionally want the root domain to serve the blog too.

## 6. Optional root-domain redirect

Once `www.200302.xyz` is stable, decide whether `200302.xyz` should:

- stay unused for now, or
- redirect to `https://www.200302.xyz`

Keep this as a second step. Do not change existing root records until you confirm they are safe to replace.