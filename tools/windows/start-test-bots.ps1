# [start-test-bots.ps1] 테스트용 봇 1~3명을 지정한 방에 넣는다 (start-test-bots.bat 에서 실행)
#
#   혼자서 멀티플레이를 시험할 때만 쓴다. 일반 서버 시작(start-poker.bat)은 봇을 넣지 않는다.
#   봇은 일반 사용자와 같은 API로 참가·준비·행동한다 (tools\test-bots\poker_test_bots.py).
#   - 방 코드·봇 수·모드·시드를 물어본 뒤, 제목이 붙은 새 창에서 봇을 실행한다. 그 창이 봇 로그다
#   - 봇을 멈추려면 그 창에서 Ctrl+C: 진행 중인 핸드는 마치고 정상 퇴장(칩 정산)한다
param(
    [string]$Room, [int]$Bots = 0, [string]$Mode, [string]$Seed,
    [int]$ApiPort = 18784, [int]$Hands = 0, [switch]$NoWindow
)
. (Join-Path $PSScriptRoot 'PokerLab.Common.ps1')

try {
    Write-Host 'JUNGLE POKER LAB 테스트 봇 (테스트 전용)' -ForegroundColor Cyan
    $config = New-PokerConfig -ApiPort $ApiPort
    $api = Get-PokerService $config 'api'
    if ((Get-ServiceState $api) -ne 'ours') {
        Write-Fail "Poker API(포트 $ApiPort)가 실행 중이 아닙니다. start-poker.bat 으로 서버를 먼저 켜고, 화면에서 방을 만든 뒤 실행하세요."
        exit 2
    }
    while (-not $Room -or $Room.Trim().ToUpper() -notmatch '^[A-HJKMNP-Z2-9]{6}$') {
        if ($Room) { Write-Warn '방 코드는 화면에 보이는 영문·숫자 6자입니다.' }
        $Room = Read-Host '방 코드 (6자)'
    }
    $Room = $Room.Trim().ToUpper()
    while ($Bots -lt 1 -or $Bots -gt 3) {
        $answer = Read-Host '봇 수 1~3 [Enter = 3]'
        if (-not $answer) { $Bots = 3 } else { [int]::TryParse($answer, [ref]$Bots) | Out-Null }
    }
    while ($Mode -notin @('basic', 'allin')) {
        $answer = Read-Host '모드 1 = 기본(체크·콜 위주), 2 = 올인 테스트(파산·리바이 확인) [Enter = 1]'
        $Mode = switch ($answer) { '' { 'basic' } '1' { 'basic' } '2' { 'allin' } 'basic' { 'basic' } 'allin' { 'allin' } default { $null } }
    }
    if (-not $Seed) {
        $answer = Read-Host '난수 시드 [Enter = 자동]'
        $Seed = if ($answer) { $answer.Trim() } else { [string](Get-Random -Minimum 1 -Maximum 1000000) }
    }
    New-Item -ItemType Directory -Force -Path $script:LogDir | Out-Null
    $log = Join-Path $script:LogDir ("bots-{0}-{1}.log" -f $Room, (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $python = Resolve-Python
    $script = Join-Path $script:RepoRoot 'tools\test-bots\poker_test_bots.py'
    $botArgs = @('-u', $script, '--room', $Room, '--bots', "$Bots", '--mode', $Mode, '--seed', $Seed,
                 '--api', "http://127.0.0.1:$ApiPort", '--log', $log)
    if ($Hands -gt 0) { $botArgs += @('--hands', "$Hands") }
    $title = "POKER LAB TEST BOTS · $Room · ${Bots}명 · $Mode · seed $Seed"
    Write-Info "방 $Room · 봇 ${Bots}명 · 모드 $Mode · 시드 $Seed"
    Write-Info "로그 파일: $log"
    if ($NoWindow) {
        & $python @botArgs
        exit $LASTEXITCODE
    }
    $inner = @"
`$Host.UI.RawUI.WindowTitle = $(ConvertTo-PsLiteral $title)
Write-Host $(ConvertTo-PsLiteral "[$title] 멈추려면 이 창에서 Ctrl+C (진행 중인 핸드를 마치고 정상 퇴장)") -ForegroundColor Cyan
`$env:PYTHONUNBUFFERED = '1'
& $(ConvertTo-PsLiteral $python) $(($botArgs | ForEach-Object { ConvertTo-PsLiteral ([string]$_) }) -join ' ')
Write-Host ''
Write-Host '봇이 끝났습니다. 이 창은 닫아도 됩니다.' -ForegroundColor Yellow
"@
    $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($inner))
    Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) | Out-Null
    Write-Ok "봇 창을 열었습니다: '$title'"
    exit 0
} catch {
    Write-Fail $_.Exception.Message
    exit 1
}
