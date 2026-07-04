#Requires -Version 5.1
param([switch]$SkipVmCreate)
$Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Repo

if (-not $SkipVmCreate) {
    & "$PSScriptRoot\setup_vm.ps1"
}

Write-Host "`n=== 若 Ubuntu 已装好并配置 local-vm.env ===" -ForegroundColor Cyan
python "$PSScriptRoot\host_deploy.py" --all
