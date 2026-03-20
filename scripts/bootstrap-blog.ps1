[CmdletBinding()]
param(
    [string]$ProjectName = "personal-blog",
    [string]$Domain = "200302.xyz",
    [string]$Subdomain = "www",
    [string]$ProjectDir = "site",
    [string]$GitBranch = "main",
    [switch]$SkipScaffold,
    [switch]$SkipGit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Write-Utf8File {
    param(
        [string]$Path,
        [string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

$root = (Get-Location).Path
$siteDir = Join-Path $root $ProjectDir
$docsDir = Join-Path $root "docs"
$fqdn = "$Subdomain.$Domain"
$pagesProjectName = $ProjectName.ToLowerInvariant().Replace(" ", "-")
$pagesPreviewUrl = "https://$pagesProjectName.pages.dev"

Write-Step "Checking local prerequisites"
$hasNode = Test-CommandExists "node"
$hasNpm = Test-CommandExists "npm"
$hasGit = Test-CommandExists "git"

if (-not $hasGit) {
    throw "Git is required but was not found in PATH."
}

if (-not $SkipScaffold) {
    if (-not $hasNode -or -not $hasNpm) {
        Write-Warning "Node.js and npm were not found. The Astro scaffold step will be skipped."
        $SkipScaffold = $true
    }
}

Ensure-Directory -Path $docsDir

if (-not $SkipScaffold) {
    if (Test-Path -LiteralPath $siteDir) {
        $hasPackageJson = Test-Path -LiteralPath (Join-Path $siteDir "package.json")
        if ($hasPackageJson) {
            Write-Step "Existing project detected in $ProjectDir, skipping Astro scaffold"
        }
        else {
            throw "Directory '$ProjectDir' already exists but does not look like a Node project. Use -SkipScaffold or choose a different -ProjectDir."
        }
    }
    else {
        Write-Step "Scaffolding an Astro blog starter into $ProjectDir"
        $template = "blog"
        $command = "create astro@latest $ProjectDir -- --template $template --install --git false --yes"
        Write-Host "Running: npm $command"
        & npm $command.Split(" ")
    }
}
else {
    Write-Step "Skipping Astro scaffold"
}

$checklistPath = Join-Path $docsDir "cloudflare-pages-deploy.md"
$checklist = @'
# Cloudflare Pages deployment checklist

This checklist assumes:

- repo root: `{0}`
- site directory: `{1}`
- production domain: `https://{2}`
- temporary Pages URL: `{3}`

## 1. Local setup

If Node.js is not installed, install the current LTS release first:

- [Node.js](https://nodejs.org/)

If the site has not been created yet, run:

```powershell
Set-Location "{0}"
.\scripts\bootstrap-blog.ps1
```

## 2. Verify the site locally

```powershell
Set-Location "{4}"
npm install
npm run dev
```

When ready to test production output:

```powershell
Set-Location "{4}"
npm run build
```

Cloudflare Pages' Astro guide currently lists:

- Production branch: `{5}`
- Build command: `npm run build`
- Build directory: `dist`

## 3. Push to GitHub

Create an empty GitHub repository first, then run:

```powershell
Set-Location "{0}"
git init
git checkout -b {5}
git add .
git commit -m "Initial blog scaffold"
git remote add origin <your-github-repo-url>
git push -u origin {5}
```

## 4. Create the Pages project

In Cloudflare Pages:

1. Create a new Pages project and connect your GitHub repository.
2. Set the root directory to `{1}` if the repo contains more than the site.
3. Use build command `npm run build`.
4. Use build output directory `dist`.
5. Deploy and confirm the site works on `{3}`.

## 5. Add your custom domain

In the Pages project's **Custom domains** section:

1. Add `{2}`.
2. Wait for Cloudflare to show the required target.
3. In your domain registrar's DNS panel, create:

```text
Type:   CNAME
Name:   {7}
Target: <your-pages-project>.pages.dev
```

Important:

- Add the custom domain inside Cloudflare Pages before creating the DNS record manually.
- For an externally managed domain, Cloudflare documents the subdomain setup as a CNAME pointing to `<YOUR_SITE>.pages.dev`.
- Do not change the apex (`{6}`) unless you intentionally want the root domain to serve the blog too.

## 6. Optional root-domain redirect

Once `{2}` is stable, decide whether `{6}` should:

- stay unused for now, or
- redirect to `https://{2}`

Keep this as a second step. Do not change existing root records until you confirm they are safe to replace.
'@ -f $root, $ProjectDir, $fqdn, $pagesPreviewUrl, $siteDir, $GitBranch, $Domain, $Subdomain

Write-Utf8File -Path $checklistPath -Content $checklist

if (-not $SkipGit) {
    $gitignorePath = Join-Path $root ".gitignore"
    $desiredEntries = @(
        "node_modules/",
        ".DS_Store",
        "dist/",
        ".astro/",
        ".wrangler/"
    )

    if (-not (Test-Path -LiteralPath $gitignorePath)) {
        Write-Step "Creating .gitignore"
        Write-Utf8File -Path $gitignorePath -Content (($desiredEntries -join [Environment]::NewLine) + [Environment]::NewLine)
    }
    else {
        $existing = Get-Content -LiteralPath $gitignorePath
        $missing = @($desiredEntries | Where-Object { $_ -notin $existing })
        if ($missing.Count -gt 0) {
            Write-Step "Updating .gitignore"
            Add-Content -LiteralPath $gitignorePath -Value ($missing -join [Environment]::NewLine)
        }
    }
}

Write-Step "Finished"
Write-Host "Generated deployment checklist: $checklistPath" -ForegroundColor Green

if ($SkipScaffold) {
    Write-Host "Astro scaffold was skipped. Install Node.js, then rerun this script without -SkipScaffold to generate the starter site." -ForegroundColor Yellow
}
else {
    Write-Host "Site directory: $siteDir" -ForegroundColor Green
    Write-Host "Next: review the generated site, then push the repo to GitHub and follow docs/cloudflare-pages-deploy.md." -ForegroundColor Green
}
