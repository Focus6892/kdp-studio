# Build kdp-studio.exe (one folder, no Python needed on the target PC) with PyInstaller.
#   .\build_exe.ps1            -> dist\kdp-studio\kdp-studio.exe  and  dist\kdp-studio-<version>-win64.zip
# Included: web interface, cover/interior pipeline, preflight, KDP publish driver (uses the Edge/Chrome already
# installed), license module, Cloudflare/OpenAI/Google/Stability/pollinations providers, Claude suggestions.
# Not included (too large for a trial build): the local GPU model stack (torch/diffusers) and the OWLv2 content
# filter (transformers); the exe says so in `doctor` and the pipeline skips the filter with a warning.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
& python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) { & python -m pip install --user pyinstaller | Select-Object -Last 1 }
$version = (Select-String -Path "pyproject.toml" -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (Test-Path "dist\kdp-studio") { Remove-Item "dist\kdp-studio" -Recurse -Force }
$args = @(
  "--noconfirm", "--clean", "--name", "kdp-studio", "--onedir", "--console",
  "--specpath", "build", "--workpath", "build\pyinstaller", "--distpath", "dist",
  "--add-data", "$root\kdp_studio\ui\templates;kdp_studio\ui\templates",
  "--add-data", "$root\kdp_studio\assets\fonts;kdp_studio\assets\fonts",
  "--add-data", "$root\examples;examples",
  "--add-data", "$root\.env.example;.",
  "--add-data", "$root\QUICKSTART.md;.",
  "--collect-submodules", "kdp_studio",
  "--collect-all", "playwright",
  "--collect-data", "reportlab",
  "--hidden-import", "tkinter", "--hidden-import", "tkinter.filedialog",
  "--exclude-module", "torch", "--exclude-module", "torchvision", "--exclude-module", "transformers", "--exclude-module", "diffusers",
  "--exclude-module", "accelerate", "--exclude-module", "peft", "--exclude-module", "matplotlib", "--exclude-module", "IPython",
  "--exclude-module", "pytest", "--exclude-module", "notebook",
  "$root\launcher.py"
)
# PyInstaller logs to stderr; Windows PowerShell 5.1 would turn those lines into errors under "Stop", so relax it here
$ErrorActionPreference = "Continue"
& python -m PyInstaller @args
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($code -ne 0) { throw "PyInstaller failed with exit code $code" }
Copy-Item "QUICKSTART.md" "dist\kdp-studio\" -Force
if (Test-Path "dist\README-DUNG-THU.md") { Copy-Item "dist\README-DUNG-THU.md" "dist\kdp-studio\" -Force }
if (Test-Path "dist\TRIAL-KEY.txt") { Copy-Item "dist\TRIAL-KEY.txt" "dist\kdp-studio\" -Force }
$zip = "dist\kdp-studio-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "dist\kdp-studio" -DestinationPath $zip
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Built dist\kdp-studio\kdp-studio.exe and $zip ($size MB)"
