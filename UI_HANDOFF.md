# JUNGLE POKER LAB — UI 인계 문서

작성 2026-11-16, 2~4인 확장 반영 2026-11-17. 대상: 온라인 대전 화면을 새로 만들거나 고치는 UI 담당자.
서버·엔진·DBMS·Redis와 화면의 현재 계약을 아래에 기록합니다. 검증 범위는 README 및 VALIDATION.md를 확인하세요.
가상 칩만 사용합니다.

## 1. 먼저 알아둘 원칙 다섯 가지

1. **화면은 결과를 정하지 않습니다.** 버튼은 요청만 보내고, 칩·팟·보드·차례·승패는 서버가 준 값만 그립니다.
2. **다른 사람 홀카드는 쇼다운 전에는 브라우저에 오지 않습니다(폴드한 카드는 끝까지 안 옴).** 숨기는 게 아니라 값 자체가 없습니다. 뒷면 카드는 `cardCount`만 보고 그립니다.
3. **애니메이션은 판정과 무관합니다.** 이벤트를 순서대로 재생한 뒤에는 반드시 `state` 값으로 화면을 맞춥니다.
4. **같은 요청 재전송은 안전합니다.** 서버에 닿지 못했을 때(네트워크 오류)만 같은 본문·같은 ID로 다시 보냅니다. 서버가 오류로 답했으면 다시 보내지 않습니다.
5. **방 코드는 권한이 아닙니다.** 좌석 권한은 브라우저의 게스트 토큰에만 있습니다.

## 2. 지금 있는 파일

| 파일 | 역할 | UI 담당자가 할 일 |
|---|---|---|
| `projects/react/room.html` | 대전 화면 진입 페이지 | 자유롭게 교체 |
| `projects/react/src/poker/RoomApp.js` | 동작하는 참고 구현(로그인→방→대전) | 참고하거나 교체 |
| `projects/react/src/poker/roomLogic.js` | 화면 순수 로직: 이벤트 재생, 좌석 배치, API 주소 결정 | **재사용 권장** (테스트 있음) |
| `projects/react/src/poker/room-main.js` | 게스트 토큰, 요청 도우미, mount | 재사용 권장 |
| `projects/react/src/styles/room.css` | 참고 스타일 | 자유롭게 교체 |
| `projects/react/tests/room-logic.test.js` | `roomLogic.js` 테스트 | 로직을 바꾸면 함께 갱신 |
| `projects/poker_demo/rooms.py` | 방·좌석·동기화 서버 | 수정 불필요 |
| `projects/poker_demo/table.py` | 2~4인 한 핸드(순서·사이드 팟·정산) | 수정 불필요 |
| `projects/poker_demo/MULTIPLAYER.md` | 서버 규칙·저장 설계 | 참고 |

기존 연습 모드(`poker.html`, 사람 대 봇)와 Mini React 과제 페이지(`index.html`, `app.html`)는 그대로입니다.

## 3. 실행

### 3.1 혼자 개발할 때 (한 PC)

저장소 루트(`jungle-poker-lab`)에서 PowerShell 창 4개를 엽니다.

```powershell
# 창 1 — Mini DBMS (기록이 남는 폴더. 저장소 밖을 권장)
cd projects\dbms
python -m mini_dbms.server --data-dir "$env:USERPROFILE\poker-lab-data" --host 127.0.0.1 --port 18783

# 창 2 — Mini Redis
cd projects\redis
python -m mini_redis.server --host 127.0.0.1 --port 6382

# 창 3 — Poker API
cd projects\poker_demo
python server.py --host 127.0.0.1 --port 18784 --dbms http://127.0.0.1:18783 --redis http://127.0.0.1:6382

# 창 4 — 화면 파일
cd projects\react
python -m http.server 5500 --bind 127.0.0.1
```

브라우저에서 `http://127.0.0.1:5500/room.html`을 엽니다.

- 같은 브라우저의 두 탭은 **같은 게스트**입니다. 두 번째 사람은 시크릿 창이나 다른 브라우저로 열거나, 주소에 `?guest=2`를 붙입니다(`room.html?guest=2`).
- 게스트 토큰은 주소의 출처(호스트·포트)마다 따로 저장됩니다. `127.0.0.1`과 `localhost`, IP 주소로 열면 각각 다른 게스트가 됩니다.
- `python`이 Microsoft Store를 열거나 실행되지 않으면 `py -3`으로 바꿔 실행하세요. 실제 Python 설치가 필요합니다. 이번 공유본은 Windows Python 3.13.7로 검증하며 상세 결과는 VALIDATION.md에 기록합니다.

### 3.2 각자 컴퓨터에서 같이 접속할 때 (같은 공유기·LAN)

한 대를 **서버 컴퓨터**로 정하고 네 프로세스를 모두 그 컴퓨터에서 띄웁니다. 다른 컴퓨터는 브라우저만 엽니다.

**① 서버 컴퓨터의 IP 확인**

```powershell
ipconfig
```

Wi-Fi(또는 이더넷) 항목의 `IPv4 주소`를 씁니다. 아래 예시는 `192.168.0.7`입니다.

**② 방화벽 열기** (서버 컴퓨터, 관리자 PowerShell, 한 번만)

```powershell
Get-NetConnectionProfile          # NetworkCategory가 Private인지 확인
New-NetFirewallRule -DisplayName "JUNGLE POKER LAB" -Direction Inbound -Protocol TCP -LocalPort 5500,18784 -Action Allow -Profile Private
```

`NetworkCategory`가 `Public`이면 집·팀 공유기일 때만 `Set-NetConnectionProfile -InterfaceAlias "Wi-Fi" -NetworkCategory Private`로 바꿉니다(별칭은 `Get-NetConnectionProfile`에 나온 이름). 다 쓴 뒤에는 `Remove-NetFirewallRule -DisplayName "JUNGLE POKER LAB"`로 지웁니다.

**③ 서버 컴퓨터에서 네 프로세스 실행** — 3.1과 같고, **창 3과 창 4만 `0.0.0.0`** 으로 바꿉니다.

```powershell
# 창 3
cd projects\poker_demo
python server.py --host 0.0.0.0 --port 18784 --dbms http://127.0.0.1:18783 --redis http://127.0.0.1:6382

# 창 4
cd projects\react
python -m http.server 5500 --bind 0.0.0.0
```

DBMS와 Redis는 서버 컴퓨터 안에서만 쓰므로 `127.0.0.1` 그대로 둡니다. 처음 실행할 때 Windows 방화벽 창이 뜨면 "개인 네트워크"를 허용합니다.

**④ 다른 컴퓨터에서 연결 확인**

```powershell
Test-NetConnection 192.168.0.7 -Port 18784      # TcpTestSucceeded : True 여야 함
Test-NetConnection 192.168.0.7 -Port 5500
```

브라우저로 `http://192.168.0.7:18784/api/rooms/AAAAAA/public`을 열어 `{"error": "room_not_found", ...}`가 보이면 API까지 닿은 것입니다.

**⑤ 두 컴퓨터 모두 같은 주소로 접속**

```
http://192.168.0.7:5500/room.html
```

서버 컴퓨터도 `localhost` 대신 이 주소를 씁니다. 화면은 페이지를 연 주소의 호스트에서 API(18784)를 찾기 때문에 따로 설정할 것이 없습니다.

**UI를 자기 컴퓨터에서 고치면서 공유 서버에 붙을 때**: 자기 PC에서 창 4만 띄우고 `http://127.0.0.1:5500/room.html?api=http://192.168.0.7:18784`로 엽니다. API는 다른 출처의 요청을 허용합니다(CORS `*`).

**안 될 때 확인할 것**

- `127.0.0.1`로 띄운 서버에는 다른 컴퓨터가 접속할 수 없습니다(③에서 `0.0.0.0`인지 확인).
- 학교·카페 Wi-Fi는 같은 네트워크의 기기끼리 통신을 막는 경우가 많습니다. 휴대폰 핫스팟 같은 개인 공유기로 바꿔 보세요.
- 두 컴퓨터가 서로 다른 공유기에 있으면 LAN 방식으로는 접속할 수 없습니다.

### 3.3 인터넷(서로 다른 네트워크)

배포하지 않았으므로 지금은 인터넷 플레이가 되지 않습니다. 하려면 공인 주소가 있는 서버에 네 프로세스를 올리고 HTTPS를 붙여야 합니다(토큰이 평문으로 지나가지 않게). 요청 수 제한 같은 공개 서비스용 보호도 없습니다.

## 4. 화면 흐름과 호출 순서

```
닉네임 입력 ─ POST /api/guest
   └ 방 만들기 ─ POST /api/rooms              ┐
   └ 코드로 참가 ─ GET .../public(미리보기) → POST .../join ┘
        └ 동기화 루프 시작 ─ GET .../state (계속 반복)
             로비: POST .../ready {ready:true, hand_no:0}  → 앉은 사람 모두 준비하면 시작
                   방장: POST .../start {hand_no:0}        → 준비 2명 이상이면 그 사람들로 시작 (state.canStart)
             대전: 내 차례면 POST .../action
             핸드 끝: POST .../ready {ready:true, hand_no:<지금 handNo>} 또는 12초 뒤 준비한 사람끼리 자동 시작
             진행 중에 앉은 사람·쉬는 사람: POST .../ready {ready:true, hand_no:<지금 handNo>} → 다음 핸드 참가
             칩 정산 퇴장(핸드 사이): POST .../leave → {left, cashOut}. 같은 매치 재착석 불가
             매치 끝(칩 가진 사람 1명 이하): 새 방을 만든다
```

새로고침했을 때는 저장된 토큰으로 `POST /api/guest`(같은 이름)를 다시 보내고, 주소의 방 코드로 `POST .../join`을 부르면 본인 좌석으로 복귀합니다. 참고 구현은 방 코드를 주소 끝 `#room=ABC234`에 둡니다.

## 5. API

공통: 모든 요청·응답은 JSON입니다. `GET .../public`과 `POST /api/guest`를 뺀 모든 요청에 `Authorization: Bearer <게스트 토큰>`이 필요합니다. 방 코드는 영문 대문자·숫자 6자이고 대소문자를 가리지 않습니다(`0 O 1 I L`은 쓰지 않음).

### 5.1 게스트

`POST /api/guest` `{"guest_token": "<base64url 43~128자>", "display_name": "<1~24자>"}`

- 토큰은 브라우저가 32바이트 난수로 만들어 저장합니다(`room-main.js`의 `createGuestToken`). 서버에는 해시만 저장됩니다.
- 같은 토큰·같은 이름이면 몇 번 보내도 같은 계정입니다. **이름은 바꿀 수 없습니다**(다른 이름이면 `409 guest_name_immutable`).

### 5.2 방

| 요청 | 본문 | 성공 응답 |
|---|---|---|
| `POST /api/rooms` | `{"request_id": "<8~128자 고유값>", "max_seats": 2~4(생략 시 4)}` | `{"state": …}` (만든 사람은 0번 좌석·방장) |
| `POST /api/rooms/{code}/join` | `{}` | `{"state": …}` (빈 좌석 중 앞 번호. 이미 앉아 있으면 본인 좌석 그대로. 진행 중이면 다음 핸드부터) |
| `POST /api/rooms/{code}/ready` | `{"ready": true/false, "hand_no": <state.handNo>}` | `{"state": …}` |
| `POST /api/rooms/{code}/start` | `{"hand_no": 0}` | `{"state": …}` (방장만, 로비에서 준비 2명 이상) |
| `POST /api/rooms/{code}/action` | `{"action_id": "<8~128자 고유값>", "expected_version": <state.gameVersion>, "action": "…", "to": <정수, bet/raise만>}` | `{"state": …}` 또는 `{"state": …, "replayed": true}` |
| `GET /api/rooms/{code}/state?since=&after=&wait=` | — | `{"state": …}` |
| `GET /api/rooms/{code}/public` | — (토큰 불필요) | `{"room": …, "cache": "HIT"|"MISS"|"BYPASS"}` |
| `POST /api/rooms/{code}/leave` | `{}` | 로비 `{"left": true}` / 매치 중 `{"left": true, "cashOut": <칩>}` (내가 든 핸드 도중엔 409) |

- `action`: `fold` `check` `call` `bet` `raise` `all_in` 중 `state.legalActions`에 있는 것만 보냅니다.
- `to`: 이번 스트리트에서 **내가 낸 총액을 얼마로 만들지**입니다(“얼마 더”가 아님). `minRaiseTo` 이상 `maxRaiseTo` 이하 정수.
- 같은 `action_id`를 다시 보내면 한 번만 적용되고 `replayed: true`가 옵니다. 버튼을 누를 때마다 새 ID를 만들고, 네트워크 오류 재시도에만 같은 ID를 씁니다.
- `create`도 같은 `request_id`면 같은 방을 돌려줍니다.

### 5.3 동기화(`GET .../state`)

서버가 바뀔 때까지 응답을 잠시 붙잡는 방식(long polling)입니다.

| 쿼리 | 뜻 |
|---|---|
| `since` | 내가 가진 `state.version`. 이보다 큰 버전이 생기면 바로 응답 |
| `after` | 내가 받은 마지막 이벤트 번호(`lastEventSeq`). 이보다 큰 이벤트만 `events`에 담김 |
| `wait` | 최대 대기 초. 서버는 5초까지만 기다림 |

권장 루프:

1. 처음(또는 새로고침): `?after=0` → 받은 `state`로 화면을 그대로 그림(재생 없음).
2. 이후 계속: `?since={version}&after={lastEventSeq}&wait=5` → 새 이벤트가 있으면 순서대로 재생, 끝나면 `state`로 맞춤.
3. 받은 `version`이 내가 가진 것보다 작으면 버림(늦게 도착한 옛 응답).
4. `instance`가 바뀌면 서버가 재시작돼 방이 복구된 것이므로, 가진 번호를 모두 버리고 1번처럼 바로 맞춤.
5. 네트워크 오류면 0.7~5초 간격으로 다시 시도. `403`·`404`면 루프를 멈추고 방 밖으로.

**요청 간격이 8초를 넘으면 다른 사람 화면에 "연결 끊김"으로 보이고, 다음 핸드에서 빠집니다.** 루프를 멈추지 마세요. `roomLogic.js`의 `planUpdate`·`applyEvent`·`displayFromState`가 1~4를 구현하고 있습니다.

### 5.4 오류 응답

모양: `{"error": "<코드>", "message": "<한국어 또는 영어 설명>", "state"?: …}`. `state`가 있으면 그 값으로 화면을 다시 맞춥니다.

| HTTP | error | 언제 / 화면 처리 |
|---|---|---|
| 400 | `invalid_*_request`, `illegal_action` | 잘못된 본문·규칙 위반. 메시지를 보여 주고 재시도하지 않음 |
| 401 | `guest_auth_required`, `guest_auth_invalid` | 토큰 없음·미등록. `/api/guest`부터 다시 |
| 403 | `not_seated` | 이 방의 좌석 주인이 아님 |
| 403 | `not_host` | 방장이 아닌데 시작 요청 |
| 404 | `room_not_found`, `not_found` | 방 없음(코드 오타, 또는 시작 전 방이 서버 재시작으로 사라짐) |
| 409 | `stale_state` | 화면이 본 상태가 이미 지남. 함께 온 `state`로 맞춤 |
| 409 | `not_your_turn`, `hand_not_active`, `hand_active` | 차례·단계가 맞지 않음. `state`로 맞춤 |
| 409 | `request_id_reused` | 같은 ID에 다른 본문. 새 ID로 다시 |
| 409 | `room_full`, `left_match`, `match_in_progress`, `match_over`, `result_storage_pending` | 참가·이탈 불가. 메시지 표시 |
| 409 | `not_enough_ready`, `busted` | 시작 조건 부족 / 칩 0이라 참가 불가 |
| 409 | `guest_name_immutable` | 이 브라우저 게스트는 다른 이름으로 이미 등록됨 |
| 503 | `match_storage_unknown` | 매치 시작 기록을 저장하지 못함. 준비가 풀렸으니 다시 준비 |
| 503 | `seat_storage_unknown` | 매치 중 참가·퇴장 기록을 저장하지 못함. 일어나지 않은 것으로 처리. 다시 시도 |
| 503 | `room_store_unavailable`, `room_recovery_failed`, `guest_store_unavailable` | DBMS 연결 문제. 잠시 뒤 재시도 |
| 503 | `too_many_rooms`, `room_code_exhausted` | 방 생성 불가. 잠시 뒤 재시도 |

## 6. `state` 필드 (본인 시점)

| 필드 | 타입 | 뜻 |
|---|---|---|
| `code` | string | 방 코드 |
| `instance` | string | 방 객체 식별자. 바뀌면 서버 재시작 후 복구된 것 |
| `version` | int | 보이는 무엇이든 바뀌면 증가(접속·준비 표시 포함). 동기화 커서 |
| `gameVersion` | int | 게임 진행(핸드 시작·행동·시간 초과)에서만 증가. `expected_version`에 그대로 보냄 |
| `phase` | string | `lobby` `playing` `hand_over` `match_over` |
| `capacity` | int | 좌석 수 2~4 (`seats` 길이) |
| `hostSeat` | int\|null | 방장 좌석 |
| `you` | `{seat, name, isHost}` | 내 좌석 번호와 이름. **내 좌석을 아래에, 나머지는 좌석 번호 순서대로 왼쪽 → 위 → 오른쪽**(`roomLogic.seatLayout`) |
| `seats` | array(capacity) | 아래 표 |
| `readyCount` / `canStart` | int / bool | 로비 준비 인원 / 내가 방장이고 지금 시작할 수 있는지 |
| `handNo` | int | 핸드 번호(로비는 0) |
| `street` | string\|null | `preflop` `flop` `turn` `river` `showdown` `complete`(폴드로 끝남). 로비는 `null` |
| `board` | string[] | 공개 카드 0·3·4·5장 |
| `pot` | int | 이번 핸드 팟 합계. 정산 뒤 0 |
| `pots` | `[{amount, eligible[]}]` | 팟 구성(메인 먼저). 올인한 사람이 있을 때만 여러 개. 진행 중이 아니면 `[]` |
| `turnSeat` | int\|null | 차례인 좌석(`playing`일 때만) |
| `turnRemainingMs` | int\|null | 차례 남은 시간(ms). 받은 시각부터 화면에서 줄여 보여 주기만 함 |
| `turnSeconds` | number | 차례 제한(30) |
| `nextHandInMs` | int\|null | `hand_over`에서 자동 시작까지 남은 시간 |
| `legalActions` | string[] | **내 차례일 때만** 비어 있지 않음 |
| `toCall` | int | 콜하려면 더 낼 금액(내 차례일 때) |
| `minRaiseTo` / `maxRaiseTo` | int\|null | `to`의 범위(내 차례일 때) |
| `result` | object\|null | 핸드 결과(아래) |
| `recordStatus` | string | 결과 저장 상태(아래) |
| `notice` | string | 서버가 정한 안내 문구 |
| `recovered` | bool | 서버 재시작으로 복구된 직후면 `true`. 다음 핸드가 시작되면 `false` |
| `lastEventSeq` | int | 가장 최근 이벤트 번호 |
| `events` | array | `after`보다 큰 번호의 이벤트(아래) |

`seats[i]`:

| 필드 | 뜻 |
|---|---|
| `seat` | 좌석 번호 0~3 |
| `occupied` | 앉은 사람이 있는지 |
| `name` | 닉네임(빈 자리는 `null`) |
| `connected` | 최근 8초 안에 요청이 있었는지 |
| `ready` | 준비 여부(`lobby`·`hand_over`에서 의미 있음) |
| `stack` | 앞에 남은 칩 |
| `committed` | **이번 핸드에** 낸 총액 |
| `streetBet` | **이번 스트리트에** 낸 금액(좌석 앞 베팅 칩 표시에 적합) |
| `isButton` / `isSmallBlind` / `isBigBlind` | 이번 핸드 포지션(2인이면 버튼이 SB) |
| `isHost` | 방장 |
| `isTurn` | 지금 차례인지 |
| `inHand` | 이번 핸드 참가자인지(진행 중 착석·쉬는 사람은 `false`) |
| `sittingIn` | 다음 핸드 참가 예약 |
| `folded` / `allIn` / `busted` | 폴드 / 올인 / 칩 0(관전) |
| `cardCount` | 홀카드 장수(이번 핸드 참가자면 2) |
| `cards` | 카드 배열 또는 `null`. 내 좌석은 항상, 다른 사람은 `street == "showdown"`이고 폴드하지 않았을 때만 |

카드 문자열: 랭크 `2…9 T J Q K A` + 무늬 `♠ ♥ ♦ ♣` (예: `"T♠"`는 스페이드 10).

`result`: `{reason: "fold"|"showdown", pot, pots: [{amount, eligible, winners, shares: [[좌석, 금액], …]}], payouts: [좌석별], winnerSeats: [], winnerSeat: 혼자 다 가져갔으면 그 좌석 아니면 null, hands: [좌석별 족보 이름|null] | null}`. `hands`는 쇼다운일 때만, 끝까지 남은 좌석만 값이 있습니다(예: `"투 페어"`). 내 승·패·무는 `roomLogic.outcomeWord`(팟별 `winners` 기준).

`recordStatus`:

| 값 | 뜻 | 화면 |
|---|---|---|
| `not_saved` | 핸드 진행 중이거나, 복구된 방에 저장된 핸드가 아직 없음 | 표시 불필요(`hand_over`면 다음 판 버튼 활성) |
| `confirmed` | 결과가 DBMS에 저장됨 | 다음 판 버튼 활성 |
| `unknown` | 결과는 정해졌지만 저장 확인 전. 서버가 2초마다 다시 시도 | "결과 저장 확인 중" 표시, 다음 판 버튼 비활성 |
| `blocked` | 저장 기록 충돌. 이 방은 더 진행 불가 | 오류 안내 |

## 7. 이벤트 (모든 화면이 같은 순서로 받음)

모든 이벤트의 공통 필드: `seq`(1씩 증가, 빈 번호 없음), `type`, `gameVersion`, `handNo`, 그리고 **그 이벤트 직후의 테이블**인 `board`, `pot`, `pots`, `stacks[capacity]`, `committed[capacity]`.

| type | 추가 필드 | 의미 |
|---|---|---|
| `hand_start` | `button`, `sb`, `bb`(좌석), `participants`(좌석 배열) | 블라인드까지 낸 직후 |
| `action` | `seat`, `action`, `paid`, `allIn`, `auto`, `to`(bet/raise) | 한 사람의 행동. `auto: true`는 시간 초과 자동 처리 |
| `returned` | `seat`, `amount` | 아무도 맞추지 못한 초과 베팅을 돌려줌 |
| `street` | `street`(`flop`/`turn`/`river`) | 보드 카드 공개 |
| `hand_end` | `reason`, `potWon`, `pots`(승자 포함), `winnerSeat`, `winnerSeats`, `payouts` | 정산. 이 이벤트에서만 칩이 승자에게 감 |
| `recovered` | — | 서버 재시작 후 방 복구 |

- 올인 콜 한 번에 `action` → `street` ×3 → `hand_end`가 한꺼번에 올 수 있습니다. 순서대로 재생하세요.
- 각 이벤트의 값으로 그 순간을 그리면 되므로 화면에서 칩을 계산할 필요가 없습니다.
- 재생이 끝나기 전에는 상대 카드 공개·결과 문구·행동 버튼을 보이지 않게 하는 것을 권장합니다(참고 구현이 그렇게 함).
- 방마다 최근 300개만 보관합니다. 많이 밀렸으면 재생하지 말고 `state`로 바로 맞추세요(`planUpdate`가 16개 초과 시 그렇게 함).
- 이벤트에는 홀카드가 없습니다.

## 8. 전적 `GET /api/profile`

```json
{"profile": {
  "userId": "...", "displayName": "...", "createdAt": "...",
  "practice": {"matches": 0, "hands": 0, "wins": 0, "losses": 0, "draws": 0},
  "online":   {"matches": 1, "hands": 5, "wins": 3, "losses": 2, "draws": 0},
  "recentGames":  [ ...연습(봇) 최근 10핸드... ],
  "recentOnline": [ ...온라인 최근 10핸드... ],
  "rank": {"enabled": false, ...}
}}
```

최근 기록 한 줄: `matchKey`, `id`, `handNo`, `mode`(`practice`/`online`), `seat`, `result`(`win`/`loss`/`draw`, **내 기준**), `reason`, `startStack`, `endStack`(내 좌석 기준), `board`, `opponent`(온라인만). 2~4인 방 기록은 `source: "room"`, `net`, `players`(참가 인원), `opponents`(이름 배열)가 더 있습니다.

- 모든 좌석이 자기 좌석 기준으로 집계됩니다. 2~4인 방은 핸드마다 내 칩 증감으로 승(+)·패(−)·무(0)를 셉니다.
- 이전 2인 방 기록(`matches`/`hand_results`)도 계속 합산됩니다.
- `winner` 필드도 남아 있지만 내부 값(`human`/`bot`/`tie`)이라 화면에는 `result`를 쓰세요.
- DBMS에 저장이 확인된 핸드만 셉니다. DBMS에 연결할 수 없으면 숫자 대신 `503 profile_store_unavailable`을 돌려줍니다.

## 9. 서버가 정한 규칙 (화면은 보여 주기만)

| 항목 | 규칙 |
|---|---|
| 인원 | 방마다 2~4석, 준비 2명 이상이면 시작 가능 |
| 블라인드·시작 칩 | 10/20, 각자 1,000(매치 중 참가도 1,000) |
| 순서·팟 | 버튼 → SB → BB, 헤즈업은 버튼=SB. 사이드 팟은 팟마다 따로 정산, 홀수 칩은 버튼 왼쪽부터. 자세히는 `MULTIPLAYER.md` |
| 차례 제한 | 30초. 넘기면 체크, 베팅을 받은 상태면 폴드. 서버 시계로만 판정 |
| 다음 핸드 | 참가 예약한 사람이 모두 준비하면 즉시, 아니면 결과 저장 확인 후 12초 뒤 준비한 사람끼리 자동(칩 있고 접속 중인 사람만) |
| 연결 끊김 | 8초간 요청이 없으면 표시. 진행 중 핸드는 차례 제한대로 계속, 다음 핸드에서 빠짐 |
| 매치 종료 | 칩 가진 사람이 1명 이하. 칩 0 좌석은 관전. 같은 방에서 재대결 없음 → 새 방 |
| 서버 재시작 | 좌석과 마지막 **저장 확인된** 핸드의 칩으로 복구. 진행 중이던 핸드와 저장 확인 전 결과는 무효 |
| 시작 전 방 | 저장하지 않음. 서버 재시작 시 사라짐(`404`) |
| 중복 탭 | 같은 좌석을 봄. 먼저 도착한 행동만 반영되고 나머지는 `409 stale_state` |

## 10. 이전 보고의 검증 상태 (이번 직접 실행과 구분)

| 검사 | 결과 | 실행 위치 |
|---|---|---|
| Poker 서버 테스트 71개(연습 42 + 방 대전 26 + 장애 주입 3) | 통과 | 사용자 작업 폴더, Linux Python 3.10 |
| 장애 주입: 시드 3개 × 무작위 320단계, API 재시작 15~18회, DBMS 재시작 4~9회, 저장 실패·응답 유실·시간 초과·중복·지난 요청 | 매 단계 칩 합 2,000, 핸드당 저장 1행, 확정된 결과 불변 | 같음 |
| Mini DBMS 17개 | 8회 연속 통과 | 같음 |
| Mini Redis 87개 | 통과 | 같음 |
| `roomLogic.js` 7개 | 통과 | node |
| 한 PC의 독립 브라우저 두 세션: 방 생성~5핸드, 새로고침, 네트워크 끊김, API 프로세스 재시작, 제3자 차단, 전적 대칭 | 72항목 통과 | 작업 공간 사본(해시 일치 확인), Linux Chrome |

**2026-11-17 2~4인 확장 (기준 커밋 6e117d0, 작업 공간 사본)**: Poker 서버 133개, DBMS 17개, Redis 87개, `roomLogic.js` 10개, Mini React 브라우저 스위트 10종 통과. 독립 브라우저 세션 4개 E2E 31/31, 기존 2인 브라우저 E2E 118/121(실패 3개는 375px HUD 잘림 D1, 보류).

**확인하지 못한 것**: 서로 다른 컴퓨터(2~4대)의 LAN 접속, Windows·Python 3.14에서의 실행, 인터넷 접속.

테스트 실행:

```powershell
cd projects\poker_demo; python -B -m unittest discover -s tests -v
cd projects\dbms;       python -B -m unittest discover -s tests -v
cd projects\redis;      python -B -m unittest discover -s tests -v
cd projects\react;      node tests\room-logic.test.js     # 또는 브라우저로 tests/room-logic.test.html
```

## 11. GitHub 협업

김준우(molru-1)는 feat/poker-ui, 서버 담당은 feat/poker-server 등 별도 기능 브랜치에서 작업하고 main 대상 PR로 합칩니다. clone·브랜치 생성·실행 명령은 README.md를 따릅니다. API·이벤트·필드 변경은 서버 담당과 합의합니다. 이번 직접 실행 결과는 VALIDATION.md가 기준이며 실제 두 컴퓨터 LAN 검증은 대기 상태입니다.


이번 Chrome 직접 검사: Mini React 276/276, 방 화면 로직 7/7 통과. 연습 모드 UI는 7/9 통과, Inspector 높이 및 HUD 겹침 검사 실패. 이전 보고의 전체 통과와 구분하며 자세한 결과는 VALIDATION.md를 확인하세요.
