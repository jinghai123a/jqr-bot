#Requires -Version 5.1
# 一键：D盘 ISO + VM 配置 +（Ubuntu 装好后）全量部署
param([switch]$DeployOnly)
$Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Repo

if (-not $DeployOnly) {
    & "$PSScriptRoot\setup_vm.ps1" -IsoPath "D:\ISO\ubuntu-24.04.4-desktop-amd64.iso"
    Write-Host "`n[1/2] VMware 打开 w49-edge-lab.vmx，装 Ubuntu，填 config\local-vm.env`n" -ForegroundColor Yellow
}

if (Test-Path "$Repo\config\local-vm.env") {
    python "$PSScriptRoot\host_deploy.py" --all
} else {
    Write-Host "[2/2] 装完系统后执行: python scripts\local_vm\host_one_click.ps1 -DeployOnly" -ForegroundColor Cyan
}
