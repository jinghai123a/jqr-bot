# 双网并存：WiFi + 有线 — 建议右键「以管理员身份运行」
$ErrorActionPreference = 'Stop'
$WifiProfile = '1211'   # 1201 无密码不可用；已保存可连的是 1211
$WifiIface = 'WLAN'
# 机器人 VPS（走最快口，避免 WiFi/有线抢默认路由时抖动）
$VpsHosts = @('46.183.27.174')

function Get-ActiveIpv4Adapter {
    param([string]$AliasPattern)
    Get-NetAdapter | Where-Object {
        $_.Status -eq 'Up' -and $_.Name -like $AliasPattern
    } | Select-Object -First 1
}

# 1) 连接 WiFi
$wlan = Get-NetAdapter -Name $WifiIface -ErrorAction SilentlyContinue
if ($wlan -and $wlan.Status -ne 'Up') {
    netsh wlan connect name="$WifiProfile" interface="$WifiIface" | Out-Null
    Start-Sleep -Seconds 4
}

# 2) 接口跃点数：数字越小越优先（主出口）
$eth = Get-ActiveIpv4Adapter '以太网*'
if ($eth) {
    Set-NetIPInterface -InterfaceAlias $eth.Name -InterfaceMetric 10 -ErrorAction SilentlyContinue
    Write-Host "[OK] 主链路: $($eth.Name) metric=10"
}
if ($wlan) {
    Set-NetIPInterface -InterfaceAlias $WifiIface -InterfaceMetric 30 -ErrorAction SilentlyContinue
    Write-Host "[OK] 备链路: $WifiIface metric=30"
}

# 3) VPS 静态路由 — 绑定当前主链路网关
if ($eth) {
    $ethIp = Get-NetIPAddress -InterfaceAlias $eth.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254*' } | Select-Object -First 1
    $gw = (Get-NetRoute -InterfaceAlias $eth.Name -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
        Select-Object -First 1).NextHop
    if ($ethIp -and $gw) {
        foreach ($h in $VpsHosts) {
            route delete $h 2>$null | Out-Null
            route add $h mask 255.255.255.255 $gw metric 1 if $ethIp.InterfaceIndex | Out-Null
            Write-Host "[OK] VPS $h -> gw $gw via $($eth.Name)"
        }
    }
}

# 4) 状态
Write-Host "`n=== 当前默认路由 ==="
Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 |
    Sort-Object RouteMetric | Format-Table InterfaceAlias, NextHop, RouteMetric, InterfaceMetric -AutoSize

Write-Host "=== 连通性 ==="
foreach ($alias in @($eth.Name, $WifiIface)) {
    if (-not $alias) { continue }
    $ip = (Get-NetIPAddress -InterfaceAlias $alias -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike '169.254*' }).IPAddress
    if ($ip) {
        $r = Test-Connection 8.8.8.8 -Count 1 -Source $ip -ErrorAction SilentlyContinue
        if ($r) { Write-Host "$alias ($ip): OK latency=$($r.ResponseTime)ms" }
        else { Write-Host "$alias ($ip): FAIL" }
    }
}
