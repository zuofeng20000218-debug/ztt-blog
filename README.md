# Blog bootstrap

This workspace contains setup scripts for a static personal blog deployed on Cloudflare Pages with an externally managed domain.

## Available scripts

- `scripts/bootstrap-blog.ps1`
  - checks whether `git`, `node`, and `npm` are available
  - scaffolds an Astro blog starter into `site/` when Node.js is installed
  - creates `docs/cloudflare-pages-deploy.md`
  - creates or updates a root `.gitignore`
- `scripts/setup_blog.py`
  - checks local environment and project status
  - initializes git and creates the first commit
  - auto-fills local git identity as `ztt / ztt@users.noreply.github.com` when missing
  - creates a GitHub repository, defaulting to `ztt-blog`
  - sets `origin` and optionally pushes to GitHub
  - runs `npm run build`
  - prints the Cloudflare Pages settings for `www.200302.xyz`
- `scripts/create_repo_and_push.py`
  - reads the token from `scripts/github_token.txt` if present, otherwise prompts for it
  - initializes git, creates the `ztt-blog` repository, sets `origin`, and pushes `main`
- `scripts/push_to_existing_repo.py`
  - assumes `ztt-blog` already exists on GitHub
  - initializes git, points `origin` to the repo, and pushes `main`
  - reads GitHub and git identity defaults from `scripts/blog_config.json`
- `scripts/open_github_token.py`
  - opens the GitHub Fine-grained personal access token creation page in your default browser
- `scripts/open_github_new_repo.py`
  - opens the GitHub new repository page in your default browser
  - reminds you to create an empty `ztt-blog` repository
- `scripts/blog_config.json`
  - stores the GitHub owner, repo name, branch, and local git identity defaults
- `scripts/test_github_connectivity.py`
  - checks DNS, HTTPS, and Git access to GitHub from the current machine
- `scripts/setup_ssh_for_github.py`
  - generates a dedicated GitHub SSH key and prints the public key
- `scripts/open_github_ssh_keys.py`
  - opens the GitHub SSH keys settings page
- `scripts/push_via_ssh.py`
  - switches `origin` to SSH and pushes `main`
- `scripts/trust_github_host.py`
  - fetches GitHub's SSH host keys and appends them to `known_hosts`
- `scripts/configure_github_ssh.py`
  - writes an SSH config entry so `github.com` uses the dedicated blog key
- `scripts/test_github_ssh.py`
  - tests SSH authentication to GitHub
- `scripts/update_blog.py`
  - stages local blog changes, creates a commit, and pushes to GitHub
- `scripts/preview_blog.py`
  - starts the local Astro preview server with one command

## Run it

```powershell
Set-Location D:\Blog
.\scripts\bootstrap-blog.ps1
```

```powershell
Set-Location D:\Blog
python .\scripts\open_github_token.py
```

```powershell
Set-Location D:\Blog
python .\scripts\create_repo_and_push.py
```

```powershell
Set-Location D:\Blog
python .\scripts\open_github_new_repo.py
```

```powershell
Set-Location D:\Blog
python .\scripts\push_to_existing_repo.py
```

```powershell
Set-Location D:\Blog
python .\scripts\setup_blog.py check
python .\scripts\setup_blog.py git-init
python .\scripts\setup_blog.py create-repo --set-origin
python .\scripts\setup_blog.py cloudflare
```

## Useful options

```powershell
.\scripts\bootstrap-blog.ps1 -ProjectName "200302-blog"
.\scripts\bootstrap-blog.ps1 -SkipScaffold
.\scripts\bootstrap-blog.ps1 -ProjectDir "blog-site" -Subdomain "www" -Domain "200302.xyz"
```

```powershell
$env:GITHUB_TOKEN="你的 GitHub token"
python .\scripts\setup_blog.py create-repo --repo-name ztt-blog --set-origin --push
python .\scripts\setup_blog.py set-remote --repo https://github.com/<you>/<repo>.git
python .\scripts\setup_blog.py set-remote --repo https://github.com/<you>/<repo>.git --push
python .\scripts\setup_blog.py build
```

## Current environment note

This machine currently has `git`, but `node`, `npm`, and `wrangler` were not found in `PATH`. Install Node.js before expecting the scaffold step to run successfully.
