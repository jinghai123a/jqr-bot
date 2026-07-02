# 双网合并提速：管理员配置主备路由 + 可选安装 Speedify 真叠加
# 用法：右键「以管理员身份运行」或在提升后的 PowerShell 中执行
$ErrorActionPreference = 'Continue'
$WifiProfile = '1211'
$WifiIface = 'WLAN'
$VpsHosts = @('46.183.27.174')
$SpeedifyInstaller = Join-Path $env:TEMP 'SpeedifyInstaller.exe'
$SpeedifyUrl = 'https://download.speedify.com/SpeedifyInstaller.exe'

function Write-Status($msg) {
    $line = "[$(Get-Date -Format HH:mm:ss)] $msg"
    Write-Host $line
    try {
        $logDir = Join-Path $env:ProgramData 'W49-DualWAN'
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        $line | Out-File -FilePath (Join-Path $logDir 'merge-last.log') -Append -Encoding utf8
    } catch {}
}

# --- 0) 确保 WiFi 在线 ---
netsh wlan connect name="$WifiProfile" interface="$WifiIface" 2>$null | Out-Null
Start-Sleep -Seconds 3

# --- 1) 虚拟网卡降权，避免与真网卡抢默认路由 ---
foreach ($vm in @('VMware Network Adapter VMnet1', 'VMware Network Adapter VMnet8')) {
    Set-NetIPInterface -InterfaceAlias $vm -InterfaceMetric 200 -ErrorAction SilentlyContinue
}

# --- 2) 主备跃点数：有线主(10)、WiFi备(25) ---
$eth = Get-NetAdapter | Where-Object {
    $_.Status -eq 'Up' -and $_.InterfaceDescription -like '*NDIS*'
} | Select-Object -First 1
if (-not $eth) {
    $eth = Get-NetAdapter | Where-Object {
        $_.Status -eq 'Up' -and $_.Name -like '以太网*' -and $_.InterfaceDescription -notlike '*VMware*'
    } | Select-Object -First 1
}
if ($eth) {
    Set-NetIPInterface -InterfaceAlias $eth.Name -InterfaceMetric 10 -ErrorAction Stop
    Write-Status "主链路 $($eth.Name) metric=10 ($($eth.LinkSpeed))"
}
Set-NetIPInterface -InterfaceAlias $WifiIface -InterfaceMetric 25 -ErrorAction SilentlyContinue
Write-Status "备链路 $WifiIface metric=25"

# --- 3) VPS 持久静态路由（走低延迟有线）---
if ($eth) {
    $ethIdx = (Get-NetIPAddress -InterfaceAlias $eth.Name -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '169.254*' } | Select-Object -First 1).InterfaceIndex
    $gw = (Get-NetRoute -InterfaceAlias $eth.Name -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Select-Object -First 1).NextHop
    if ($ethIdx -and $gw) {
        foreach ($h in $VpsHosts) {
            route delete $h 2>$null | Out-Null
            route -p add $h mask 255.255.255.255 $gw metric 1 if $ethIdx 2>$null | Out-Null
            Write-Status "VPS $h -> $gw (if $ethIdx) [persistent]"
        }
    }
}

# --- 4) 双链路连通性 ---
Write-Status '=== 连通性 ==='
foreach ($alias in @($eth.Name, $WifiIface)) {
    if (-not $alias) { continue }
    $ip = (Get-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254*' }).IPAddress
    if ($ip) {
        $r = Test-Connection 8.8.8.8 -Count 2 -Source $ip -ErrorAction SilentlyContinue |
            Measure-Object -Property ResponseTime -Average
        if ($r) { Write-Status "$alias $ip -> 8.8.8.8 avg=$([int]$r.Average)ms" }
        else { Write-Status "$alias $ip -> FAIL" }
    }
}

Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 |
    Sort-Object InterfaceMetric |
    Format-Table InterfaceAlias, NextHop, InterfaceMetric -AutoSize

# --- 5) Speedify 真带宽叠加（需免费账号首次登录）---
$scli = @(
    "${env:ProgramFiles(x86)}\Speedify\speedify_cli.exe",
    "$env:ProgramFiles\Speedify\speedify_cli.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $scli) {
    Write-Status '下载 Speedify...'
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $SpeedifyUrl -OutFile $SpeedifyInstaller -UseBasicParsing
        Write-Status '安装 Speedify (/NONINTERACTIVE /NOUI)...'
        Start-Process -FilePath $SpeedifyInstaller -ArgumentList '/NONINTERACTIVE', '/NOUI' -Wait
        $scli = @(
            "${env:ProgramFiles(x86)}\Speedify\speedify_cli.exe",
            "$env:ProgramFiles\Speedify\speedify_cli.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    } catch {
        Write-Status "Speedify 安装失败: $_"
    }
}

if ($scli) {
    Write-Status "Speedify CLI: $scli"
    Start-Sleep -Seconds 5
    & $scli state 2>&1
    & $scli mode speed 2>&1
    & $scli connect 2>&1
    Write-Status 'Speedify 已切 speed 模式并 connect（未登录则需 Speedify 客户端登录一次）'
} else {
    Write-Status '未安装 Speedify：当前为 Windows 主备双网（有线优先+WiFi备份），非单连接带宽叠加'
}

Write-Status '=== 完成 ==='
