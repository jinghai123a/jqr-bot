# 连接 WiFi「1201」并与有线合并（主备 + VPS 走低延迟口）
# 用法（管理员 PowerShell）:
#   .\win_wifi_1201_merge.ps1 -Password '你的1201密码'
param(
    [Parameter(Mandatory = $true)]
    [string]$Password,
    [string]$WifiProfile = '1201',
    [string]$WifiIface = 'WLAN'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$xmlPath = Join-Path $env:TEMP "wlan_1201_profile.xml"

@'
<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>1201</name>
  <SSIDConfig>
    <SSID>
      <name>1201</name>
    </SSID>
  </SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>auto</connectionMode>
  <MSM>
    <security>
      <authEncryption>
        <authentication>WPA2PSK</authentication>
        <encryption>AES</encryption>
        <useOneX>false</useOneX>
      </authEncryption>
      <sharedKey>
        <keyType>passPhrase</keyType>
        <protected>false</protected>
        <keyMaterial>__PASSWORD__</keyMaterial>
      </sharedKey>
    </security>
  </MSM>
</WLANProfile>
'@.Replace('__PASSWORD__', [System.Security.SecurityElement]::Escape($Password)) | Set-Content -Path $xmlPath -Encoding UTF8

netsh wlan disconnect interface="$WifiIface" | Out-Null
Start-Sleep -Seconds 2
netsh wlan add profile filename="$xmlPath" user=all | Out-Null
netsh wlan connect name="$WifiProfile" interface="$WifiIface" | Out-Null
Start-Sleep -Seconds 5

$st = netsh wlan show interfaces
if ($st -notmatch 'SSID\s*:\s*1201') {
    Write-Error "未能连上 1201，请检查密码或信号"
}

Write-Host "[OK] 已连接 WiFi 1201"
& (Join-Path $here 'win_dual_wan_setup.ps1')
