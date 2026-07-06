# Local desktop bot single-instance launcher
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { throw "missing venv python: $Py" }

Write-Host "[1/3] stop old stack"
Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'desktop_local_announce|edge_mock_panel|-m edge_brain' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Remove-Item (Join-Path $Root "data\.desktop_announce.lock") -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$env:EDGE_BRAIN_JWT_SECRET = "w49-local-desktop-test"
$env:BOT_55WS_URL = "ws://127.0.0.1:5600"
$env:DESKTOP_GROUP_ID = "492316"

Write-Host "[2/3] start panel + brain"
Start-Process -FilePath $Py -ArgumentList @("$Root\scripts\edge_mock_panel.py") -WorkingDirectory $Root -WindowStyle Hidden
Start-Process -FilePath $Py -ArgumentList @("-m", "edge_brain") -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 4

Write-Host "[3/3] start announce"
$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logOut = Join-Path $logDir "desktop_announce.log"
$env:EDGE_BRAIN_JWT_SECRET = "w49-local-desktop-test"
$env:BOT_55WS_URL = "ws://127.0.0.1:5600"
$env:DESKTOP_GROUP_ID = "492316"
Start-Process -FilePath $Py -ArgumentList @("$Root\scripts\desktop_local_announce.py") -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $logOut -RedirectStandardError $logOut
Start-Sleep -Seconds 6

Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'desktop_local_announce' -and $_.CommandLine -notlike '*\.venv\Scripts\python*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

$venvAnn = @(Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'desktop_local_announce' -and $_.CommandLine -like '*\.venv\Scripts\python*' } |
  Sort-Object ProcessId)
if ($venvAnn.Count -gt 1) {
  $venvAnn | Select-Object -SkipLast 1 | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

$ann = @(Get-CimInstance Win32_Process -Filter "name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'desktop_local_announce' }).Count
Write-Host "announce_count=$ann (expect 1)"
Write-Host "OK group_id=492316 ws=5600 log=$logOut"
