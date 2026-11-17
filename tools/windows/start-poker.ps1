# [start-poker.ps1] JUNGLE POKER LAB 서버 4개를 순서대로 켠다 (start-poker.bat 에서 실행)
#
#   DBMS → Redis → Poker API → 화면 서버. 하나씩 켜고, 정상 응답을 확인한 뒤 다음으로 넘어간다.
#   - 이미 정상 실행 중인 서버는 다시 켜지 않고 그대로 쓴다
#   - 포트를 다른 프로그램이 쓰고 있으면 무엇인지 알려 주고 멈춘다 (아무것도 종료하지 않는다)
#   - 서버마다 제목이 붙은 창이 하나씩 뜨고, 그 창에 서버 로그가 보인다
#   - 준비가 끝나면 브라우저를 열고, 다른 PC가 접속할 Wi-Fi IPv4 주소를 보여 준다
#   - 테스트 봇은 넣지 않는다 (start-test-bots.bat 은 따로)
# 매개변수는 시험용이다. 평소에는 더블클릭(start-poker.bat)만 하면 된다.
param(
    [string]$DataDir = (Join-Path $env:USERPROFILE 'poker-lab-lan-test'),
    [int]$DbmsPort = 18783, [int]$RedisPort = 6382, [int]$ApiPort = 18784, [int]$WebPort = 5500,
    [switch]$NoBrowser
)
. (Join-Path $PSScriptRoot 'PokerLab.Common.ps1')

try {
    $config = New-PokerConfig -DataDir $DataDir -DbmsPort $DbmsPort -RedisPort $RedisPort -ApiPort $ApiPort -WebPort $WebPort
    Write-Host 'JUNGLE POKER LAB 서버 시작' -ForegroundColor Cyan
    Write-Info "저장소: $script:RepoRoot"
    Write-Info "DBMS 데이터: $($config.DataDir)"
    if (-not (Test-Path -LiteralPath (Join-Path $script:Projects 'poker_demo\server.py'))) {
        throw "저장소 구조가 예상과 다릅니다 (projects\poker_demo\server.py 없음): $script:RepoRoot"
    }
    if (-not (Test-Path -LiteralPath $config.DataDir)) {
        New-Item -ItemType Directory -Force -Path $config.DataDir | Out-Null
        Write-Info 'DBMS 데이터 폴더가 없어 새로 만들었습니다.'
    }
    $python = $null

    foreach ($service in $config.Services) {
        Write-Step "$($service.Title)"
        $state = Get-ServiceState $service
        if ($state -eq 'ours') {
            Write-Ok '이미 실행 중입니다. 다시 켜지 않고 그대로 씁니다.'
            continue
        }
        if ($state -eq 'foreign') {
            $owner = Get-PortOwner $service.Port
            Write-Fail "포트 $($service.Port)를 다른 프로그램이 쓰고 있습니다: $owner"
            Write-Info '그 프로그램을 직접 끄거나 포트를 비운 뒤 다시 실행하세요. 이 도구는 아무것도 종료하지 않습니다.'
            Write-Info "확인: Get-NetTCPConnection -LocalPort $($service.Port) -State Listen"
            exit 2
        }
        if (-not $python) {
            $python = Resolve-Python
            Write-Info "Python: $python"
        }
        $window = Start-ServiceWindow -Service $service -Python $python
        Write-Info "창을 열었습니다: '$($service.Title)' — 준비를 기다리는 중..."
        if (-not (Wait-ServiceReady -Service $service -HostProcess $window -TimeoutSeconds 30)) {
            Write-Fail "$($service.Name)가 30초 안에 준비되지 않았습니다. '$($service.Title)' 창의 오류를 확인하세요."
            exit 3
        }
        Write-Ok '준비 완료'
    }

    $local = "http://127.0.0.1:$($config.WebPort)/room.html"
    Write-Step '모두 준비됐습니다'
    Write-Info "이 PC에서:  $local"
    $addresses = Get-LanAddresses
    $wifi = @($addresses | Where-Object { $_.WiFi })
    if ($wifi.Count -gt 0) {
        foreach ($a in $wifi) {
            Write-Host ("  팀원 접속 주소 (Wi-Fi, {0}):  http://{1}:{2}/room.html" -f $a.Interface, $a.Address, $config.WebPort) -ForegroundColor Green
        }
    } else {
        Write-Warn 'Wi-Fi IPv4 주소를 찾지 못했습니다. 아래 다른 연결의 주소를 쓰거나 Wi-Fi 연결을 확인하세요.'
    }
    foreach ($a in @($addresses | Where-Object { -not $_.WiFi })) {
        Write-Info ("다른 연결 ({0}):  http://{1}:{2}/room.html" -f $a.Interface, $a.Address, $config.WebPort)
    }
    Write-Info "다른 PC에서 안 열리면: 같은 Wi-Fi인지, Windows 방화벽에서 Python의 개인 네트워크 허용 또는 TCP $($config.WebPort)·$($config.ApiPort) 인바운드 허용을 확인하세요."
    Write-Info 'API만 다시 켜기: restart-poker-api.bat  ·  혼자 시험용 봇: start-test-bots.bat'
    if (-not $NoBrowser) { Start-Process $local }
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}
