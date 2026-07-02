# 一次性注册「最高权限自动双网合并」计划任务（之后登录/开机不再弹 UAC）
# 用法：双击 一键安装自动提权双网.bat（仅首次需点一次「是」）
$ErrorActionPreference = 'Stop'
$TaskName = 'W49-DualWAN-Merge'
$TaskNameBoot = 'W49-DualWAN-Merge-Boot'
$LogDir = Join-Path $env:ProgramData 'W49-DualWAN'
$MergeScript = Join-Path $PSScriptRoot 'win_dual_wan_merge_admin.ps1'

if (-not (Test-Path $MergeScript)) {
    Write-Error "找不到 $MergeScript"
}

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $admin) {
    Write-Host '需要管理员 — 正在请求提权（仅此一次）...'
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arg -Wait
    exit $LASTEXITCODE
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$log = Join-Path $LogDir 'install.log'
"$(Get-Date -Format o) register auto-elevate" | Out-File -FilePath $log -Append -Encoding utf8

$psArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$MergeScript`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $psArgs

# 当前用户登录时最高权限（WiFi 配置需交互用户上下文）
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest

$tLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$tLogon.Delay = 'PT30S'

$tBoot = New-ScheduledTaskTrigger -AtStartup
$tBoot.Delay = 'PT1M'

$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $tLogon -Principal $principal `
    -Settings $settings -Force | Out-Null

Register-ScheduledTask -TaskName $TaskNameBoot -Action $action -Trigger $tBoot -Principal $principal `
    -Settings $settings -Force | Out-Null

# schtasks 兜底（部分环境 Register-ScheduledTask 失败时）
$mergeEsc = $MergeScript -replace '\\', '\\'
schtasks /Create /TN $TaskName /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$MergeScript`"" `
    /SC ONLOGON /RU $env:USERNAME /RL HIGHEST /DELAY 0000:30 /F 2>$null | Out-Null
schtasks /Create /TN $TaskNameBoot /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$MergeScript`"" `
    /SC ONSTART /RU $env:USERNAME /RL HIGHEST /DELAY 0001:00 /F 2>$null | Out-Null

"$(Get-Date -Format o) tasks registered: $TaskName, $TaskNameBoot" | Out-File -FilePath $log -Append -Encoding utf8

Write-Host '[OK] 已注册计划任务（最高权限，登录+开机自动跑，不再弹 UAC）'
Write-Host "     - $TaskName  (登录后 30s)"
Write-Host "     - $TaskNameBoot (开机后 60s)"
Write-Host '[..] 立即执行一次合并...'

& $MergeScript *>&1 | Tee-Object -FilePath (Join-Path $LogDir 'merge-last.log') -Append

Write-Host '[OK] 完成。日志:' (Join-Path $LogDir 'merge-last.log')
