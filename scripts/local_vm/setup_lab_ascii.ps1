#Requires -Version 5.1
# 无中文路径：C:\w49-edge-lab
$ErrorActionPreference = "Stop"
$Lab = "C:\w49-edge-lab"
$Iso = "D:\ISO\ubuntu-24.04.4-desktop-amd64.iso"
$Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
New-Item -ItemType Directory -Force -Path $Lab | Out-Null
Copy-Item "$Repo\local_vm\w49-edge-lab.vmx" "$Lab\w49-edge-lab.vmx" -Force
$vmx = Get-Content "$Lab\w49-edge-lab.vmx" -Raw
$vmx = $vmx -replace 'HOST_PROJECT_PLACEHOLDER', ($Repo -replace '\\','/')
$vmx = $vmx -replace 'ide1:0.fileName = "auto"', "ide1:0.fileName = `"$($Iso -replace '\\','\\')`""
$extra = @"

guestinfo.cis.domain = "local"
guestinfo.cis.username = "bot"
guestinfo.cis.password = "w49-edge-lab"
guestinfo.cis.password.confirm = "w49-edge-lab"
guestinfo.cis.fullname = "W49 Edge Lab"
guestinfo.cis.autoinstall = "TRUE"
"@
if ($vmx -notmatch 'guestinfo.cis.username') { $vmx += $extra }
[System.IO.File]::WriteAllText("$Lab\w49-edge-lab.vmx", $vmx)
Write-Host "LAB_PATH=$Lab"
Write-Host "VMX=$Lab\w49-edge-lab.vmx"
$vmware = "C:\Users\haijin\VMware\Installation\vmware.exe"
if (Test-Path $vmware) {
    Start-Process $vmware -ArgumentList "`"$Lab\w49-edge-lab.vmx`""
    Write-Host "VMware started"
}
