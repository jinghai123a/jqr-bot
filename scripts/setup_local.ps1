# Local Windows dev setup: venv + pip + config templates
# Usage: powershell -ExecutionPolicy Bypass -File scripts\setup_local.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Write-Step "Check Python and system tools"
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { throw "python not found" }
python --version
foreach ($tool in @("git", "adb", "ssh")) {
    $cmd = Get-Command $tool -ErrorAction SilentlyContinue
    if ($cmd) { Write-Host "OK $tool -> $($cmd.Source)" } else { Write-Warning "missing $tool" }
}

Write-Step "Create virtualenv .venv"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip wheel setuptools

Write-Step "Install requirements-lab.txt"
& $venvPy -m pip install -r requirements-lab.txt

Write-Step "Install optional vendor packages"
if (Test-Path "vendor\airtest\setup.py") {
    & $venvPy -m pip install -e vendor\airtest
}
if (Test-Path "vendor\adbutils\pyproject.toml") {
    & $venvPy -m pip install -e vendor\adbutils
}
if (Test-Path "requirements-vendor.txt") {
    & $venvPy -m pip install -r requirements-vendor.txt
}

Write-Step "Ensure local config files"
$cfgPairs = @(
    @("config\bot-start.env.example", "config\bot-start.env"),
    @("config\local-vm.env.example", "config\local-vm.env"),
    @("config\tunnel-creds.local.env.example", "config\tunnel-creds.local.env")
)
foreach ($pair in $cfgPairs) {
    $src, $dst = $pair
    if ((Test-Path $src) -and -not (Test-Path $dst)) {
        Copy-Item $src $dst
        Write-Host "created $dst"
    } elseif (Test-Path $dst) {
        Write-Host "keep existing $dst"
    }
}

Write-Step "Verify imports"
& $venvPy (Join-Path $Root "scripts\verify_local_env.py")
if ($LASTEXITCODE -ne 0) { throw "import verify failed" }

Write-Step "Done"
Write-Host "Activate: .\.venv\Scripts\Activate.ps1" -ForegroundColor Green
Write-Host "Edge brain: python -m edge_brain" -ForegroundColor Green
Write-Host "Tests: .\.venv\Scripts\python.exe -m pytest tests\ -q" -ForegroundColor Green
Write-Host "SETUP_LOCAL_OK"
