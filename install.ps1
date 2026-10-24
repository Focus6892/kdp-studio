# kdp-studio installer for another Windows PC (run in PowerShell from the unpacked folder):
#   Set-ExecutionPolicy -Scope Process Bypass; .\install.ps1 [-Local] [-UI]
# Installs the toolkit for the current user with Python 3.11+ (3.14 tested), the browser automation
# driver (uses the Edge/Chrome already on the machine), optionally the free local image model stack.
param(
  [switch]$Local,   # also install CUDA PyTorch + diffusers for the free local image provider (large download)
  [switch]$UI,      # also install Flask for `kdp ui`
  [string]$Cuda = "cu126"
)
$ErrorActionPreference = "Stop"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "Python 3.11+ is required: https://www.python.org/downloads/ (tick 'Add to PATH')"; exit 1 }
$ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Python $ver found"
& python -m pip install --user --upgrade pip | Out-Null
& python -m pip install --user -e . 2>&1 | Select-Object -Last 1
& python -m pip install --user playwright pyyaml | Out-Null
if ($UI)    { & python -m pip install --user flask | Out-Null }
if ($Local) { & python -m pip install --user --index-url "https://download.pytorch.org/whl/$Cuda" torch | Select-Object -Last 1
              & python -m pip install --user diffusers transformers accelerate safetensors | Select-Object -Last 1 }
& python -m pip install --user cryptography | Out-Null
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env - fill in API keys if you use paid image providers" }
Write-Host ""
Write-Host "Installed. Next steps:"
Write-Host "  python -m kdp_studio license machine-id      # send this id to the owner, then: python -m kdp_studio license activate <key>"
Write-Host "  python -m kdp_studio validate examples/bold-easy-flowers/book.yaml"
Write-Host "  python -m kdp_studio ui                      # local web interface (needs -UI)"
