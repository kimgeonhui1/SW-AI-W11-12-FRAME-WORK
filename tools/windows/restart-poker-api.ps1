# [restart-poker-api.ps1] Poker API만 다시 켠다 (restart-poker-api.bat 에서 실행)
#
#   코드를 고친 뒤 DBMS·Redis·화면 서버는 그대로 두고 API만 다시 켤 때 쓴다.
#   - start-poker.bat 이 시작한 API 프로세스만 종료한다: 기록된 PID·시작 시각·명령줄(server.py)이 모두 맞아야 한다
#   - 다른 방법(직접 명령)으로 켠 API나 다른 프로그램은 종료하지 않고 안내만 한다
#   - 진행 중이던 핸드는 서버 규칙대로 무효가 되고, 마지막으로 저장된 칩에서 이어진다
param(
    [string]$DataDir = (Join-Path $env:USERPROFILE 'poker-lab-lan-test'),
    [int]$DbmsPort = 18783, [int]$RedisPort = 6382, [int]$ApiPort = 18784, [int]$WebPort = 5500
)
. (Join-Path $PSScriptRoot 'PokerLab.Common.ps1')

try {
    $config = New-PokerConfig -DataDir $DataDir -DbmsPort $DbmsPort -RedisPort $RedisPort -ApiPort $ApiPort -WebPort $WebPort
    $api = Get-PokerService $config 'api'
    Write-Host 'Poker API 다시 시작' -ForegroundColor Cyan

    Write-Step 'DBMS·Redis 확인'
    foreach ($key in @('dbms', 'redis')) {
        $service = Get-PokerService $config $key
        if ((Get-ServiceState $service) -ne 'ours') {
            Write-Fail "$($service.Name)(포트 $($service.Port))가 실행 중이 아닙니다. start-poker.bat 으로 전체를 먼저 켜세요."
            exit 2
        }
    }
    Write-Ok 'DBMS·Redis 정상'

    Write-Step "$($api.Title) 종료"
    $launch = Read-LaunchState $api
    $current = Get-ServiceState $api
    if ($launch -and (Test-OwnProcess $launch.pid $launch.start 'server.py')) {
        Write-Info "이 도구가 시작한 API를 종료합니다 (PID $($launch.pid))."
        Stop-Process -Id $launch.pid -Force
        $deadline = (Get-Date).AddSeconds(10)
        while ((Get-Date) -lt $deadline -and (Get-PortOwner $api.Port)) { Start-Sleep -Milliseconds 300 }
        if (Get-PortOwner $api.Port) {
            Write-Fail "API를 종료했지만 포트 $($api.Port)가 아직 쓰이고 있습니다: $(Get-PortOwner $api.Port)"
            exit 3
        }
        # 이전 로그 창도 이 도구가 연 창일 때만 닫는다
        if ($launch.hostPid -and (Test-OwnProcess $launch.hostPid $launch.hostStart $null)) {
            Stop-Process -Id $launch.hostPid -Force -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $api.StateFile -Force -ErrorAction SilentlyContinue
        Write-Ok '종료했습니다.'
    } elseif ($current -eq 'ours') {
        Write-Fail '실행 중인 API는 이 도구가 시작한 것이 아니어서 종료하지 않습니다.'
        Write-Info 'API를 켠 창에서 Ctrl+C로 직접 끈 뒤 이 파일을 다시 실행하세요. (다음부터는 start-poker.bat 으로 켜면 여기서 다시 켤 수 있습니다)'
        exit 4
    } elseif ($current -eq 'foreign') {
        Write-Fail "포트 $($api.Port)를 다른 프로그램이 쓰고 있습니다: $(Get-PortOwner $api.Port). 종료하지 않습니다."
        exit 4
    } else {
        Write-Info '실행 중인 API가 없습니다. 새로 켭니다.'
    }

    Write-Step "$($api.Title) 시작"
    $python = Resolve-Python
    $window = Start-ServiceWindow -Service $api -Python $python
    if (-not (Wait-ServiceReady -Service $api -HostProcess $window -TimeoutSeconds 30)) {
        Write-Fail "API가 30초 안에 준비되지 않았습니다. '$($api.Title)' 창의 오류를 확인하세요."
        exit 3
    }
    Write-Ok '준비 완료. 브라우저는 그대로 두면 자동으로 다시 연결됩니다(진행 중이던 핸드는 무효, 마지막 저장 칩에서 이어짐).'
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}
