#Requires -Version 5.1
<#
  挂载 D 盘 ISO、生成 nocloud seed、启动 VMware 安装 Ubuntu。
  密码: w49-edge-lab  用户: bot
#>
param(
    [string]$IsoPath = "D:\ISO\ubuntu-24.04.4-desktop-amd64.iso",
    [string]$VmDir = "",
    [string]$VmwareLnk = ""
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $VmDir) {
    $VmDir = Join-Path $env:PUBLIC "虚拟机\w49-edge-lab"
}
$VmDir = [System.IO.Path]::GetFullPath($VmDir)
$Vmx = Join-Path $VmDir "w49-edge-lab.vmx"
$SeedDir = Join-Path $VmDir "nocloud"
$SeedIso = Join-Path $VmDir "cidata.iso"

& "$PSScriptRoot\setup_vm.ps1" -IsoPath $IsoPath -VmDir $VmDir

# nocloud seed (autoinstall)
New-Item -ItemType Directory -Force -Path $SeedDir | Out-Null
# 明文密码 late-commands 已在 repo user-data 内
Copy-Item "$Repo\local_vm\autoinstall\user-data" $SeedDir -Force
Copy-Item "$Repo\local_vm\autoinstall\meta-data" $SeedDir -Force

# 用 PowerShell 打 ISO（若 oscdimg 不可用则复制到 floppy 目录供手动）
$oscdimg = @(
    "${env:ProgramFiles(x86)}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe",
    "${env:ProgramFiles}\Windows Kits\10\Assessment and Deployment Kit\Deployment Tools\amd64\Oscdimg\oscdimg.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($oscdimg) {
    & $oscdimg -n "$SeedIso" "$SeedDir" | Out-Null
    Write-Host "cidata.iso OK"
} else {
    Write-Host "WARN: oscdimg missing — seed at $SeedDir (VM 安装时选手动或装 ADK)"
}

# 更新 vmx：第二光驱挂 nocloud 目录（或 cidata.iso）
$vmxLines = @(Get-Content -LiteralPath $Vmx -ErrorAction Stop)
if (-not ($vmxLines -match 'ide1:1.present')) {
    $seedPath = if (Test-Path $SeedIso) { $SeedIso } else { $SeedDir }
    $escaped = $seedPath -replace '\\', '\\'
    $vmxLines += ""
    $vmxLines += 'ide1:1.present = "TRUE"'
    $vmxLines += "ide1:1.fileName = `"$escaped`""
    if (Test-Path $SeedIso) {
        $vmxLines += 'ide1:1.deviceType = "cdrom-image"'
    } else {
        $vmxLines += 'ide1:1.deviceType = "floppy"'
    }
}
[System.IO.File]::WriteAllLines($Vmx, $vmxLines)

# 找 VMware
if (-not $VmwareLnk) {
    $VmwareLnk = cmd /c "for /r `"$env:PUBLIC`" %i in (VMware*Pro*.lnk) do @echo %i" 2>$null | Select-Object -First 1
}
$vmwareExe = ""
if ($VmwareLnk -and (Test-Path $VmwareLnk.Trim())) {
    $sh = New-Object -ComObject WScript.Shell
    $vmwareExe = $sh.CreateShortcut($VmwareLnk.Trim()).TargetPath
}
if (-not $vmwareExe -or -not (Test-Path $vmwareExe)) {
    Write-Host "WARN: VMware exe not found — 请手动打开 $Vmx" -ForegroundColor Yellow
    exit 0
}

Write-Host "Starting VMware: $vmwareExe"
Start-Process -FilePath $vmwareExe -ArgumentList "`"$Vmx`"" 
Write-Host "VM_BOOT_OK — 安装完成后: copy config\local-vm.env.example config\local-vm.env ; 填 VM_HOST"
Write-Host "Then: python scripts\local_vm\host_deploy.py --all"
