# Build a distributable zip of kdp-studio for another PC: source + examples + docs + installer, without build
# outputs, keys, state or your own books.   Usage:  .\package.ps1   -> dist\kdp-studio-<version>-<date>.zip
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$version = (Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$stamp = Get-Date -Format "yyyyMMdd"
$name = "kdp-studio-$version-$stamp"
$stage = Join-Path $env:TEMP $name
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage | Out-Null
$include = @("kdp_studio", "examples", "docs", "tests", "README.md", "QUICKSTART.md", "pyproject.toml", "install.ps1", "start.bat", ".env.example", ".gitignore")
foreach ($item in $include) {
  if (Test-Path $item) { Copy-Item $item -Destination (Join-Path $stage $item) -Recurse -Force }
}
# strip caches, build outputs and anything private
Get-ChildItem $stage -Recurse -Directory | Where-Object { $_.Name -in @("__pycache__", "build", ".pytest_cache") } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $stage -Recurse -File | Where-Object { $_.Name -in @(".env", "license_private.pem", "license_owner_machine.txt") } | Remove-Item -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path "dist" -Force | Out-Null
$zip = Join-Path $root "dist\$name.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
Remove-Item $stage -Recurse -Force
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Packaged $zip ($size MB). On the other PC: unzip, then  Set-ExecutionPolicy -Scope Process Bypass; .\install.ps1  and start.bat"
