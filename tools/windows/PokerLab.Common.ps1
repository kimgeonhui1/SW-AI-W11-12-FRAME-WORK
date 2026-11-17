# [PokerLab.Common.ps1] JUNGLE POKER LAB 실행 도구 공용 함수 (Windows PowerShell 5.1)
#
# start-poker.ps1 / restart-poker-api.ps1 / start-test-bots.ps1 가 함께 쓴다.
#   - 서버 4개: DBMS(18783) → Redis(6382) → Poker API(18784) → 화면(5500)
#   - "우리 서버인지"는 포트가 열려 있는지가 아니라 응답 내용으로 확인한다(다른 프로그램을 잘못 재사용하지 않게)
#   - 이 도구가 시작한 프로세스는 %LOCALAPPDATA%\jungle-poker-lab\run 에 PID·시작 시각을 남긴다.
#     API 재시작은 여기 기록된 프로세스(PID와 시작 시각, 명령줄이 모두 맞을 때)만 종료한다.
#   - 경로에 한글·공백이 있어도 되도록 새 창 명령은 -EncodedCommand(UTF-16)로 넘기고, 인수는 모두 따옴표 처리한다.
# 이 파일은 UTF-8(BOM) 이다. BOM이 없으면 PowerShell 5.1이 한글을 CP949로 잘못 읽는다.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:RepoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$script:Projects = Join-Path $script:RepoRoot 'projects'
$script:StateDir = Join-Path $env:LOCALAPPDATA 'jungle-poker-lab'
$script:RunDir = Join-Path $script:StateDir 'run'
$script:LogDir = Join-Path $script:StateDir 'logs'

function Write-Step([string]$Text) { Write-Host ''; Write-Host "== $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  [OK] $Text" -ForegroundColor Green }
function Write-Info([string]$Text) { Write-Host "  $Text" }
function Write-Warn([string]$Text) { Write-Host "  [주의] $Text" -ForegroundColor Yellow }
function Write-Fail([string]$Text) { Write-Host "  [중단] $Text" -ForegroundColor Red }

# ── 설정 ────────────────────────────────────────────────────────────────

function New-PokerConfig {
    param(
        [string]$DataDir = (Join-Path $env:USERPROFILE 'poker-lab-lan-test'),
        [int]$DbmsPort = 18783, [int]$RedisPort = 6382, [int]$ApiPort = 18784, [int]$WebPort = 5500
    )
    $dbmsUrl = "http://127.0.0.1:$DbmsPort"
    $redisUrl = "http://127.0.0.1:$RedisPort"
    # 순서가 곧 실행 순서다. DBMS·Redis는 이 컴퓨터 안에서만(127.0.0.1), API·화면은 LAN에서 접속하므로 0.0.0.0
    $services = @(
        @{ Key = 'dbms'; Name = 'Mini DBMS'; Port = $DbmsPort; Dir = (Join-Path $script:Projects 'dbms')
           Args = @('-u', '-m', 'mini_dbms.server', '--data-dir', $DataDir, '--host', '127.0.0.1', '--port', "$DbmsPort")
           ProbeUrl = "$dbmsUrl/"; Expect = { param($r) $r.Status -eq 405 -and $r.Body -match 'POST /sql' } },
        @{ Key = 'redis'; Name = 'Mini Redis'; Port = $RedisPort; Dir = (Join-Path $script:Projects 'redis')
           Args = @('-u', '-m', 'mini_redis.server', '--host', '127.0.0.1', '--port', "$RedisPort")
           ProbeUrl = "$redisUrl/health"; Expect = { param($r) $r.Status -eq 200 -and $r.Body -match '"keys"' } },
        @{ Key = 'api'; Name = 'Poker API'; Port = $ApiPort; Dir = (Join-Path $script:Projects 'poker_demo')
           Args = @('-u', 'server.py', '--host', '0.0.0.0', '--port', "$ApiPort", '--dbms', $dbmsUrl, '--redis', $redisUrl)
           ProbeUrl = "http://127.0.0.1:$ApiPort/api/game"; Expect = { param($r) $r.Status -eq 401 -and $r.Body -match 'guest_auth_required' } },
        @{ Key = 'web'; Name = '화면 서버'; Port = $WebPort; Dir = (Join-Path $script:Projects 'react')
           Args = @('-u', '-m', 'http.server', "$WebPort", '--bind', '0.0.0.0')
           ProbeUrl = "http://127.0.0.1:$WebPort/room.html"; Expect = { param($r) $r.Status -eq 200 -and $r.Body -match 'JUNGLE POKER LAB' } }
    )
    $index = 0
    foreach ($s in $services) {
        $index += 1
        $s.Title = "POKER LAB $index/4 · $($s.Name) :$($s.Port)"
        $s.StateFile = Join-Path $script:RunDir ("{0}-{1}.json" -f $s.Key, $s.Port)
    }
    return @{ DataDir = $DataDir; Services = $services; ApiPort = $ApiPort; WebPort = $WebPort }
}

function Get-PokerService([hashtable]$Config, [string]$Key) {
    foreach ($s in $Config.Services) { if ($s.Key -eq $Key) { return $s } }
    throw "unknown service $Key"
}

# ── 확인 ────────────────────────────────────────────────────────────────

# HTTP 응답 상태와 본문. 연결이 안 되면 $null. 시스템 프록시를 거치지 않는다(127.0.0.1)
function Invoke-Probe([string]$Url) {
    try {
        $request = [System.Net.HttpWebRequest]::Create($Url)
        $request.Proxy = $null
        $request.Timeout = 3000
        $request.ReadWriteTimeout = 3000
        $request.KeepAlive = $false
        try { $response = $request.GetResponse() }
        catch [System.Net.WebException] {
            $response = $_.Exception.Response
            if ($null -eq $response) { return $null }
        }
        $reader = New-Object System.IO.StreamReader($response.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $body = $reader.ReadToEnd()
        $reader.Close()
        $status = [int]$response.StatusCode
        $response.Close()
        return @{ Status = $status; Body = $body }
    } catch {
        return $null
    }
}

# 포트를 듣고 있는 프로세스 설명. 없으면 $null (Get-NetTCPConnection이 없으면 netstat으로)
function Get-PortOwner([int]$Port) {
    $owningPid = $null
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($connection) { $owningPid = [int]$connection.OwningProcess }
    } else {
        foreach ($line in (netstat -ano -p TCP)) {
            if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)") { $owningPid = [int]$Matches[1]; break }
        }
    }
    if ($null -eq $owningPid) { return $null }
    $process = Get-Process -Id $owningPid -ErrorAction SilentlyContinue
    $name = if ($process) { $process.ProcessName } else { '알 수 없음' }
    return "PID $owningPid ($name)"
}

# 'ours' = 우리 서버가 정상 응답 / 'foreign' = 다른 프로그램이 포트 점유 / 'free' = 비어 있음
function Get-ServiceState([hashtable]$Service) {
    $response = Invoke-Probe $Service.ProbeUrl
    if ($response -and (& $Service.Expect $response)) { return 'ours' }
    if ($response -or (Get-PortOwner $Service.Port)) { return 'foreign' }
    return 'free'
}

# ── 파이썬 ──────────────────────────────────────────────────────────────

# 실제 python.exe 경로(3.10 이상). py 런처를 그대로 띄우면 PID가 런처라서 재시작 때 서버를 못 끈다
function Resolve-Python {
    $candidates = @(@('py', '-3'), @('python'), @('python3'))
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate[0] -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $command) { continue }
        $extra = @()
        if ($candidate.Count -gt 1) { $extra = $candidate[1..($candidate.Count - 1)] }
        try {
            $output = & $command.Source @extra -c 'import sys; print(sys.executable); print(sys.version_info[0] * 100 + sys.version_info[1])' 2>$null
        } catch { continue }
        if ($LASTEXITCODE -ne 0 -or -not $output -or @($output).Count -lt 2) { continue }
        $exe = [string]@($output)[0]
        $version = [int]@($output)[1]
        if ($version -ge 310 -and (Test-Path -LiteralPath $exe)) { return $exe }
    }
    throw 'Python 3.10 이상을 찾지 못했습니다. python.org에서 설치하고(“Add python.exe to PATH” 체크) 다시 실행하세요.'
}

# ── 새 창으로 실행 ──────────────────────────────────────────────────────

# Windows 명령줄 인수 하나를 따옴표 처리 (공백·따옴표·끝 역슬래시)
function ConvertTo-WinArg([string]$Value) {
    if ($Value -ne '' -and $Value -notmatch '[\s"]') { return $Value }
    $escaped = $Value -replace '(\\*)"', '$1$1\"'
    $escaped = $escaped -replace '(\\+)$', '$1$1'
    return '"' + $escaped + '"'
}

function ConvertTo-PsLiteral([string]$Value) { return "'" + ($Value -replace "'", "''") + "'" }

# 제목이 붙은 PowerShell 창에서 서버를 실행한다. 서버 출력(로그)은 그 창에 보인다.
# 창 안의 스크립트가 서버 프로세스의 PID와 시작 시각을 상태 파일에 남긴다
function Start-ServiceWindow([hashtable]$Service, [string]$Python) {
    New-Item -ItemType Directory -Force -Path $script:RunDir | Out-Null
    if (Test-Path -LiteralPath $Service.StateFile) { Remove-Item -LiteralPath $Service.StateFile -Force }
    $argumentLine = ($Service.Args | ForEach-Object { ConvertTo-WinArg ([string]$_) }) -join ' '
    $inner = @"
`$ErrorActionPreference = 'Stop'
`$Host.UI.RawUI.WindowTitle = $(ConvertTo-PsLiteral $Service.Title)
Set-Location -LiteralPath $(ConvertTo-PsLiteral $Service.Dir)
`$env:PYTHONUNBUFFERED = '1'
Write-Host $(ConvertTo-PsLiteral ("[$($Service.Title)] 실행: python $argumentLine")) -ForegroundColor Cyan
Write-Host '이 창이 서버 로그입니다. 끄려면 이 창에서 Ctrl+C (API만 다시 켜려면 restart-poker-api.bat)' -ForegroundColor DarkGray
`$p = Start-Process -FilePath $(ConvertTo-PsLiteral $Python) -ArgumentList $(ConvertTo-PsLiteral $argumentLine) -NoNewWindow -PassThru
`$null = `$p.Handle
`$me = Get-Process -Id `$PID
`$state = [ordered]@{ key = $(ConvertTo-PsLiteral $Service.Key); port = $($Service.Port); pid = `$p.Id; start = `$p.StartTime.ToUniversalTime().Ticks; hostPid = `$PID; hostStart = `$me.StartTime.ToUniversalTime().Ticks; launcher = 'jungle-poker-lab' }
`$state | ConvertTo-Json | Set-Content -LiteralPath $(ConvertTo-PsLiteral $Service.StateFile) -Encoding UTF8
`$p.WaitForExit()
Write-Host ''
Write-Host ('[' + $(ConvertTo-PsLiteral $Service.Title) + '] 서버가 끝났습니다 (종료 코드 ' + `$p.ExitCode + '). 이 창은 닫아도 됩니다.') -ForegroundColor Yellow
"@
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($inner))
    $shell = Join-Path $PSHOME 'powershell.exe'
    return Start-Process -FilePath $shell -ArgumentList @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) -PassThru
}

# 서버가 정상 응답할 때까지 기다린다
function Wait-ServiceReady([hashtable]$Service, $HostProcess, [int]$TimeoutSeconds = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Get-ServiceState $Service) -eq 'ours') { return $true }
        Start-Sleep -Milliseconds 400
        if ($HostProcess -and (Test-Path -LiteralPath $Service.StateFile)) {
            $state = Read-LaunchState $Service
            if ($state -and -not (Get-Process -Id $state.pid -ErrorAction SilentlyContinue)) { return $false }  # 서버가 바로 끝남
        }
    }
    return $false
}

# ── 이 도구가 시작한 프로세스 ────────────────────────────────────────────

function Read-LaunchState([hashtable]$Service) {
    if (-not (Test-Path -LiteralPath $Service.StateFile)) { return $null }
    try { return (Get-Content -LiteralPath $Service.StateFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

# 상태 파일의 PID가 지금도 "그때 이 도구가 띄운 그 프로세스"인지: PID·시작 시각·명령줄이 모두 맞아야 한다
function Test-OwnProcess($ProcessId, $StartTicks, [string]$CommandLineMustContain) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    try { $ticks = $process.StartTime.ToUniversalTime().Ticks } catch { return $false }
    if ([int64]$ticks -ne [int64]$StartTicks) { return $false }
    if ($CommandLineMustContain) {
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
        if (-not $info -or -not $info.CommandLine -or $info.CommandLine -notlike "*$CommandLineMustContain*") { return $false }
    }
    return $true
}

# ── 접속 주소 ────────────────────────────────────────────────────────────

# 다른 PC가 접속할 IPv4. Wi-Fi(무선)를 먼저, 그다음 나머지(이더넷 등)
function Get-LanAddresses {
    $list = @()
    if (Get-Command Get-NetIPAddress -ErrorAction SilentlyContinue) {
        $all = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -ne '127.0.0.1' -and $_.IPAddress -notlike '169.254.*' }
        foreach ($a in $all) {
            $wifi = $a.InterfaceAlias -match 'Wi-?Fi|WLAN|Wireless|무선'
            $list += [pscustomobject]@{ Address = $a.IPAddress; Interface = $a.InterfaceAlias; WiFi = [bool]$wifi }
        }
    } else {
        foreach ($ip in [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName())) {
            if ($ip.AddressFamily -eq 'InterNetwork' -and $ip.ToString() -ne '127.0.0.1' -and -not $ip.ToString().StartsWith('169.254.')) {
                $list += [pscustomobject]@{ Address = $ip.ToString(); Interface = '?'; WiFi = $false }
            }
        }
    }
    return @($list | Sort-Object @{ Expression = { -not $_.WiFi } }, Interface)
}
