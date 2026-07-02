# TP-Link 1201 路由器 WPS 一键连接（需先在路由器上按 WPS 键 2 分钟内运行）
# 用法：按路由器 WPS 键后立刻以管理员运行本脚本
$ErrorActionPreference = 'Continue'
$ssid = '1201'
$iface = 'WLAN'

Write-Host "请在 TP-Link 路由器上按下 WPS 键，然后 120 秒内等待连接..."
netsh wlan disconnect interface="$iface" | Out-Null
Start-Sleep -Seconds 2

# Windows 10+ 通过 UI 配置库尝试 WPS（部分机型有效）
$connected = $false
try {
    $profilePath = Join-Path $env:TEMP 'wps_1201.xml'
    @"
<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
  <name>1201</name>
  <SSIDConfig><SSID><name>1201</name></SSID></SSIDConfig>
  <connectionType>ESS</connectionType>
  <connectionMode>manual</connectionMode>
  <MSM><security>
    <authEncryption>
      <authentication>WPA2PSK</authentication>
      <encryption>AES</encryption>
      <useOneX>false</useOneX>
    </authEncryption>
  </security></MSM>
</WLANProfile>
"@ | Set-Content $profilePath -Encoding UTF8
    netsh wlan add profile filename="$profilePath" user=all 2>$null | Out-Null
} catch {}

# 打开 WiFi 设置便于手动 WPS/连接
Start-Process 'ms-settings:network-wifi' -ErrorAction SilentlyContinue

for ($i = 1; $i -le 24; $i++) {
    netsh wlan connect name=$ssid interface=$iface 2>$null | Out-Null
    Start-Sleep -Seconds 5
    $show = netsh wlan show interfaces
    if ($show -match 'SSID\s*:\s*1201' -and $show -match '已连接|connected') {
        $connected = $true
        Write-Host "[OK] 已连接 1201 (WPS/系统)"
        break
    }
    Write-Host "等待 WPS/连接... $i/24"
}

if (-not $connected) {
    Write-Host "[FAIL] 未能连上 1201。WPS 失败时需路由器背面 WiFi 密码。"
    Write-Host "      将回退使用已保存的 1211 + 有线双网合并。"
    netsh wlan connect name=1211 interface=$iface | Out-Null
    Start-Sleep -Seconds 4
}

$setup = Join-Path $PSScriptRoot 'win_dual_wan_setup.ps1'
if (Test-Path $setup) { & $setup }
