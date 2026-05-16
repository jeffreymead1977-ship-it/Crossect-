param(
  [string]$DigestDate = (Get-Date -Format "yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"
$env:GIT_TERMINAL_PROMPT = "0"
$env:GCM_INTERACTIVE = "Never"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$branch = (git branch --show-current).Trim()
if (-not $branch) {
  $branch = "main"
}

$origin = (git remote get-url origin).Trim()
if (-not $origin) {
  throw "No git remote named origin is configured."
}

$changedDigestFiles = git status --porcelain -- docs/data/digests
if (-not $changedDigestFiles) {
  Write-Host "No digest changes to publish."
  exit 0
}

$digestPath = Join-Path $repoRoot "docs\data\digests\$DigestDate-expanded.json"
if (Test-Path $digestPath) {
  node .\scripts\validate-digest-freshness.mjs $digestPath .\docs\data\digests
  if ($LASTEXITCODE -ne 0) {
    throw "Digest freshness validation failed. Regenerate $DigestDate with fresher current-day sources before publishing."
  }
}

git add -- docs/data/digests

git diff --cached --quiet -- docs/data/digests
if ($LASTEXITCODE -eq 0) {
  Write-Host "No staged digest changes to publish."
  exit 0
}

git commit -m "Update daily news digest $DigestDate"
git pull --rebase origin $branch
git push origin $branch

Write-Host "Published daily news digest $DigestDate to $origin on $branch."
