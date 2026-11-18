# Poker Lab

Mini React 화면에서 사람과 서버 측 봇이 가상 칩으로 Heads-up Texas Hold’em을 플레이합니다. 현재 구현 범위는 P1 엔진, P2 게스트 식별·완료 Hand 전적 저장, P3 프로필·최근 기록 API입니다. 랭크는 비활성입니다.

## 실행

기존 DBMS 데이터를 보존할 수 있는 안정적인 데이터 폴더를 지정합니다. 이 코드에는 `guest_users` 스키마와 `/sql/insert-once`가 추가됐으므로 Mini DBMS 프로세스는 변경된 코드로 다시 시작해야 합니다. 기존 `.rows` 파일은 그대로 읽고, 게스트가 처음 등록될 때 새 `guest_users.rows` 파일이 생깁니다.

저장소 루트에서 네 개의 터미널을 엽니다.

1. DBMS: `cd projects/dbms` 후 `python -m mini_dbms.server --data-dir <기존 DBMS 데이터 폴더> --host 127.0.0.1 --port 18783`
2. Mini Redis: `cd projects/redis` 후 `python -m mini_redis.server --host 127.0.0.1 --port 6382`
3. Poker API: `cd projects/poker_demo` 후 `python server.py --host 127.0.0.1 --port 18784 --dbms http://127.0.0.1:18783 --redis http://127.0.0.1:6382`
4. Mini React 정적 서버: `cd projects/react` 후 `python -m http.server 5500 --bind 127.0.0.1`

브라우저에서 [http://127.0.0.1:5500/poker.html](http://127.0.0.1:5500/poker.html)을 엽니다. 공식 Mini React 페이지 `index.html`, `app.html`, 테스트 페이지는 그대로 둡니다.

## HTTP API

브라우저가 256-bit 난수 게스트 토큰을 생성해 `localStorage`에 보관합니다. API는 토큰 해시만 DBMS에 저장하고, 이후 요청은 `Authorization: Bearer …`로 사용자를 식별합니다. 본문으로 전달한 `user_id`는 인증에 사용하지 않습니다.

- `POST /api/guest`: `{ "guest_token": "<base64url 43 chars>", "display_name": "Guest Player" }`
- `GET /api/profile`: 프로필, 완료 Hand 수, 승·패·무, 최근 10개 Hand, 비활성 랭크 필드
- `GET /api/game`: 인증 사용자의 현재 메모리 게임 상태
- `POST /api/game/start`: `{ "request_id": "<stable request id>" }`
- `POST /api/game/action`: `{ "action_id": "<stable request id>", "action": "call" }` 또는 `check`, `fold`, `all_in`, `bet`/`raise`와 정수 `to`
- `POST /api/game/next`: `{ "request_id": "<stable request id>" }`

서버가 카드, 턴, 합법 액션, 베팅, 봇 행동, 평가, 정산을 결정합니다. 같은 `action_id` 재시도는 이미 처리한 결과를 돌려주며 다시 베팅하지 않습니다. 완료 결과의 DBMS 저장이 불명확하면 같은 저장 키만 재확인하고, 확인될 때까지 다른 액션과 다음 Hand를 막습니다.

## 보장 및 범위

- 게스트 계정·매치·완료 Hand 결과는 Mini DBMS append-only 테이블에 저장합니다. 프로필 전적은 이 기록에서 계산하며 Redis 캐시에 의존하지 않습니다.
- `hand_results` 한 행에 정산 결과와 비공개 카드가 없는 액션 이력을 함께 저장합니다. 각 행은 `operation_key`, payload hash, 이전 결과 ID, 시작/종료 칩 잔액을 포함합니다.
- Redis는 TTL 300초 공개 상태 캐시입니다. 홀카드와 게스트 토큰은 캐시와 Inspector Trace에서 제외합니다. Redis 장애는 게임 정산이나 영구 전적 저장을 막지 않습니다.
- Mini DBMS의 append-once 키 탐색은 ID B+Tree가 아닌 테이블 선형 탐색입니다. 테이블 잠금 안에서 키 확인과 fsync append를 직렬화하므로 현재 과제 규모의 정확성을 얻지만, 대규모 전적용 보조 인덱스는 아닙니다.
- API 재시작 뒤 게스트·완료 전적은 복원됩니다. 미완료 Hand의 덱과 액션 상태는 메모리에만 있으므로 폐기되고, 완료 전적으로 집계되지 않습니다. 실제 금전 가치가 없는 연습 칩만 사용합니다.
- 게스트 토큰은 브라우저 로컬 저장소에만 보관합니다. 브라우저 저장소를 잃으면 계정 복구나 다른 기기 이전이 없습니다. 이 구현은 로컬 과제용 게스트 식별이고, 정식 로그인·토큰 회전·다중 기기 복구는 아닙니다.
- 봇은 서버에서 무료일 때 체크하고, 베팅을 마주하면 콜하는 연습 정책입니다. 사람 간 대전은 room.html에 별도로 구현되어 있습니다(MULTIPLAYER.md 참고). 봇 난이도 전략, 랭크전, 현금/환전 기능은 없습니다.

세부 감사와 DBMS 계약, 데이터 모델, 재시작 동작 및 랭크 활성화 기준은 [DESIGN_NOTES.md](./DESIGN_NOTES.md)에 기록했습니다.
