# Local desktop bot single-instance launcher
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "missing venv python: $Py" }

Write-Host "[1/2] stop old stack"
Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'desktop_local_announce|desktop_local_stack|edge_mock_panel|-m edge_brain' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item (Join-Path $Root "data\.desktop_announce.lock") -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$env:EDGE_BRAIN_JWT_SECRET = "w49-local-desktop-test"
$env:BOT_55WS_URL = "ws://127.0.0.1:5600"
$env:DESKTOP_GROUP_ID = "492316"
$env:PYTHONUNBUFFERED = "1"
$env:DESKTOP_PYTHON = $Py

Write-Host "[2/2] start stack (panel+brain+announce)"
Start-Process -FilePath $Py -ArgumentList @("$Root\scripts\desktop_local_stack.py") -WorkingDirectory $Root -WindowStyle Minimized

Start-Sleep -Seconds 15

Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -match 'desktop_local_announce|desktop_local_stack|edge_mock_panel|-m edge_brain' -and
    $_.CommandLine -notlike '*\.venv\Scripts\python*'
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$lock = Join-Path $Root "data\.desktop_announce.lock"
$annPid = 0
if (Test-Path $lock) {
  try { $annPid = [int](Get-Content $lock -Raw).Trim() } catch {}
}
$ann = @(Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'desktop_local_announce' -and $_.CommandLine -like '*\.venv\Scripts\python*' }).Count
try { $brain = (Invoke-WebRequest -Uri http://127.0.0.1:8790/health -UseBasicParsing -TimeoutSec 3).StatusCode } catch { $brain = "down" }
try { $panel = (Invoke-WebRequest -Uri http://127.0.0.1:3000/api/bots -UseBasicParsing -TimeoutSec 3).StatusCode } catch { $panel = "down" }
Write-Host "panel=$panel brain=$brain announce_count=$ann announce_pid=$annPid (expect 1)"
Write-Host "OK group_id=492316 ws=5600 (minimized python window)"

