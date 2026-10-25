# kdp-studio installer for a Windows PC (run in PowerShell from the unpacked folder):
#   Set-ExecutionPolicy -Scope Process Bypass; .\install.ps1 [-Local] [-Cuda cu126]
# Installs the toolkit for the current user with Python 3.11+ (3.14 tested): web interface, browser automation
# (uses the Edge/Chrome already on the machine), license module, and optionally the free local image model stack.
param(
  [switch]$Local,   # also install CUDA PyTorch + diffusers for the free local image provider (large download, NVIDIA GPU)
  [string]$Cuda = "cu126"
)
$ErrorActionPreference = "Stop"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "Python 3.11+ is required: https://www.python.org/downloads/ (tick 'Add to PATH')"; exit 1 }
$ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
Write-Host "Python $ver found"
& python -m pip install --user --upgrade pip | Out-Null
Write-Host "Installing kdp-studio with the web interface, publishing driver and license module..."
& python -m pip install --user -e ".[ui,publish,license]" 2>&1 | Select-Object -Last 1
if ($Local) {
  Write-Host "Installing the local image model stack (PyTorch $Cuda, diffusers)..."
  & python -m pip install --user --index-url "https://download.pytorch.org/whl/$Cuda" torch | Select-Object -Last 1
  & python -m pip install --user diffusers transformers accelerate safetensors peft scipy | Select-Object -Last 1
}
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env - add API keys later in the web interface (Cai dat)" }
Write-Host ""
& python -X utf8 -m kdp_studio doctor
Write-Host ""
Write-Host "Installed. Next steps:"
Write-Host "  start.bat                                    # or: python -m kdp_studio ui   (web interface at http://127.0.0.1:8765)"
Write-Host "  python -m kdp_studio license machine-id      # send this id to the owner, then: python -m kdp_studio license activate <key>"
Write-Host "  python -m kdp_studio local-setup             # only if you use the local GPU image model (needs -Local)"
