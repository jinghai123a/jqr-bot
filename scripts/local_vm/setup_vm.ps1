#Requires -Version 5.1
<#
.SYNOPSIS
  按 Desktop\123.txt 创建 w49-edge-lab VMware 虚拟机目录与 .vmx
#>
# ISO：优先 D 盘（已探测 D:\ISO\ubuntu-24.04.4-desktop-amd64.iso）
param(
    [string]$VmDir = "$env:PUBLIC\虚拟机\w49-edge-lab",
    [string]$IsoPath = "",
    [int]$Cores = 4,
    [int]$MemoryMB = 4096,
    [int]$DiskGB = 40
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$VmxSrc = Join-Path $RepoRoot "local_vm\w49-edge-lab.vmx"
$VmDir = [System.IO.Path]::GetFullPath($VmDir)

Write-Host "=== W49 Edge Lab VM ===" -ForegroundColor Cyan
Write-Host "VM dir: $VmDir"
Write-Host "Host: 6C/16G -> VM ${Cores}C/${MemoryMB}MB (123.txt)"

New-Item -ItemType Directory -Force -Path $VmDir | Out-Null

# ISO：D 盘优先
if (-not $IsoPath) {
    $dCandidates = @(
        "D:\ISO\ubuntu-24.04.4-desktop-amd64.iso",
        "D:\iso\ubuntu-24.04.4-desktop-amd64.iso"
    )
    foreach ($c in $dCandidates) {
        if (Test-Path $c) { $IsoPath = $c; break }
    }
    if (-not $IsoPath) {
        foreach ($dir in @("D:\ISO", "D:\iso", "$env:USERPROFILE\Downloads")) {
            if (Test-Path $dir) {
                $found = Get-ChildItem $dir -Filter "*.iso" -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($found) { $IsoPath = $found.FullName; break }
            }
        }
    }
}
$IsoHints = @("$env:PUBLIC\虚拟机\镜像源.txt")

$VmxDst = Join-Path $VmDir "w49-edge-lab.vmx"
$vmx = Get-Content $VmxSrc -Raw -Encoding UTF8
$vmx = $vmx -replace 'HOST_PROJECT_PLACEHOLDER', ($RepoRoot -replace '\\', '/')
$vmx = $vmx -replace 'numvcpus = "4"', "numvcpus = `"$Cores`""
$vmx = $vmx -replace 'cpuid.coresPerSocket = "4"', "cpuid.coresPerSocket = `"$Cores`""
$vmx = $vmx -replace 'memsize = "4096"', "memsize = `"$MemoryMB`""
[System.IO.File]::WriteAllText($VmxDst, $vmx, [System.Text.UTF8Encoding]::new($false))

# 虚拟磁盘（拆分、动态）
$Vmdk = Join-Path $VmDir "w49-edge-lab.vmdk"
$VdiskMgr = @(
    "${env:ProgramFiles(x86)}\VMware\VMware Workstation\vmware-vdiskmanager.exe",
    "${env:ProgramFiles}\VMware\VMware Workstation\vmware-vdiskmanager.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $Vmdk) -and $VdiskMgr) {
    Write-Host "Creating split disk ${DiskGB}GB ..."
    & $VdiskMgr -c -s "${DiskGB}GB" -a lsilogic -t 0 "$Vmdk" -d split
} elseif (-not (Test-Path $Vmdk)) {
    Write-Host "WARN: vmware-vdiskmanager not found — first boot VMware will prompt to create disk" -ForegroundColor Yellow
}

if ($IsoPath -and (Test-Path $IsoPath)) {
    $vmx2 = Get-Content $VmxDst -Raw
    $vmx2 = $vmx2 -replace 'ide1:0.fileName = "auto"', "ide1:0.fileName = `"$($IsoPath -replace '\\','\\')`""
    [System.IO.File]::WriteAllText($VmxDst, $vmx2, [System.Text.UTF8Encoding]::new($false))
    Write-Host "ISO: $IsoPath"
} else {
    Write-Host "WARN: 未找到 Ubuntu ISO — 请手动挂载后安装 Server 22.04" -ForegroundColor Yellow
}

# 快捷方式旁记录
$Readme = Join-Path $VmDir "安装说明.txt"
@"
w49-edge-lab 本地 APS 实验机
========================
1. VMware 打开: $VmxDst
2. 安装 Ubuntu 24.04（D:\ISO\ubuntu-24.04.4-desktop-amd64.iso 已挂载）
   用户 bot，安装 OpenSSH，勾选开发工具
3. 复制 config\local-vm.env.example -> config\local-vm.env，填 VM_HOST
4. python scripts\local_vm\host_deploy.py --all
   → 全量代码进 /opt/55m-lab/app
5. 调试通过后: python scripts\local_vm\host_pack_deploy.py --pack
6. 上 APS: python scripts\local_vm\host_pack_deploy.py --deploy-aps

硬件(123.txt): ${Cores}核 ${MemoryMB}MB NAT ${DiskGB}GB split
"@ | Set-Content $Readme -Encoding UTF8

Write-Host ""
Write-Host "DONE: $VmxDst" -ForegroundColor Green
Write-Host "Next: VMware -> 打开虚拟机 -> 装 Ubuntu -> host_deploy.py"
