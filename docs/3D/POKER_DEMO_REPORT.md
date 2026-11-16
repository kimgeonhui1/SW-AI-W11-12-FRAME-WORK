# poker_demo 분석 리포트

작성 2026-11-16 · 수정 2026-11-16(3장: 3D 전환 방향 반영) · 브랜치 `feat/poker-ui`
이 리포트의 분석은 코드 변경 전 기준이다. 이후 방 대전 테이블을 CSS 3D로 구현했다(three.js는 시도 후 되돌림). 구현 내용과 검증 결과는 [3D_UI_PLAN.md](./3D_UI_PLAN.md) 15절. 3장의 three.js 방향 설명은 그 전 판단이다.

## 1. 한 줄 요약

브라우저 화면에서 하는 2인 텍사스 홀덤. 모든 판정은 서버(`projects/poker_demo`)가 하고, 화면(`projects/react`)은 요청을 보내고 서버가 준 값을 그리기만 한다. 가상 칩만 쓴다.

- 연습 모드: `poker.html` — 사람 대 봇
- 방 대전: `room.html` — 사람 둘이 방 코드로 만남
- 저장: Mini DBMS(직접 만든 DB, 결과를 한 번만 기록) / 캐시: Mini Redis(공개 정보만, 꺼져도 게임은 진행)

## 2. 서버 구성 (`projects/poker_demo`)

| 파일 | 줄 수 | 역할 |
|---|---|---|
| `engine.py` | 479 | 규칙 엔진: 덱, 블라인드, 턴, 베팅(레이즈 재오픈·짧은 올인), 족보 판정, 정산, 칩 총량 검사 |
| `server.py` | 739 | HTTP API: 게스트 인증(토큰 해시), 연습 모드, 결과 저장, 전적 조회 |
| `rooms.py` | 695 | 방 대전: 생성·참가·준비, 30초 턴 제한, 끊김 표시, 롱폴링, 재시작 뒤 방 복구 |
| `tests/` | 1617 | 실제 HTTP 서버 + 임시 DB로 도는 테스트 71개 |

### 잘 된 점
- 카드·턴·칩·승패를 서버가 정한다. 상대 홀카드는 쇼다운 전에는 응답에 아예 없다.
- 같은 `action_id` 재전송은 한 번만 적용. 핸드 결과는 고유 키로 한 번만 저장되고, 저장이 확인될 때까지 다음 핸드를 막는다.
- 저장된 결과마다 해시·이전 결과 ID 연결이 있고, 다시 읽을 때 칩 총량까지 검증한다.
- 한계(진행 중 핸드는 재시작 시 사라짐, 서로 다른 두 PC 접속 미검증)가 `DESIGN_NOTES.md`, `MULTIPLAYER.md`에 솔직하게 적혀 있다.

### 문제점 (중요한 순)
1. **방 500개 이후 방 생성 불가.** 메모리에서 방이 지워지는 곳은 로비에서 둘 다 나갔을 때뿐(`rooms.py:236`). 끝난 매치·버려진 로비 방이 쌓여 `MAX_ROOMS = 500`(`rooms.py:154`)에 걸리면 서버 재시작 전까지 `too_many_rooms`. 수정 방향: 끝난/오래된 방을 메모리에서 정리. 기록은 DBMS에 있으므로 다시 들어오면 `_recover`가 복구한다.
2. **DB가 느리면 전체가 멈출 수 있음.** 방 생성(`_new_code`)과 복구(`_recover`)가 전역 잠금을 쥔 채 DBMS를 호출(호출당 최대 2초). 결과 저장·Redis 쓰기도 방 잠금 안에서 해서 그 방의 롱폴링이 같이 멈춘다.
3. **메모리 누적.** `Demo.sessions`, `traces_by_user`(방마다 `room:코드` 항목), `create_replays`가 지워지지 않는다. 로컬 과제 규모에서는 문제없다.
4. **턴 시간 제한은 요청이 있을 때만 적용.** 둘 다 떠나 있으면 진행되지 않는다(문서화된 의도).
5. **쓰지 않는 코드.** `engine.py`의 `target > max_to` 검사는 앞의 `pay > stacks` 검사 때문에 실행되지 않는다. 동작 영향 없음.

### 테스트 결과 (macOS, Python 3.14.7)
- 1차: 71개 중 1개 `ConnectionResetError`(로컬 소켓 리셋)
- 2차: 71개 모두 통과
- 간헐 실패로 보이나 어느 테스트인지는 특정하지 않았다.
- 실행: `cd projects/poker_demo && python3 -B -m unittest discover -s tests`

## 3. 내 작업: UI 전체 3D 전환 (+ 3D ↔ 2D 전환)

방향: **three.js로 테이블·배경·카드·칩을 실시간 3D로 새로 만들고**, 같은 장면에서 카메라로 3D/2D를 오간다. 세부 계획은 [3D_UI_PLAN.md](./3D_UI_PLAN.md).

### 지금 화면은 진짜 3D가 아니다
WebGL·canvas·three.js는 없다. **CSS로 평면 요소를 기울인 시각효과**다. 요소마다 원근값이 따로라(`perspective(400px)`, `500px`, `1100px`) 하나의 3D 공간이 아니고, 정해진 한 각도에서만 입체처럼 보인다. 그래서 카메라를 움직이는 3D로는 옮길 수 없고 **디자인(색·배치·네온 느낌)만 참고**한다.

| 화면 | 위치 | CSS 효과 |
|---|---|---|
| 방 대전 | `room.css:44` `.arena` | `perspective: 1100px` |
| 방 대전 | `room.css:51` `.table` | `rotateX(24deg)` — 실제로 기울어지는 건 테이블뿐 |
| 방 대전 | `room.css:47-48` 벽 | `skewY(±8deg)` |
| 연습 모드 | `.table-base, .poker-table` | `perspective(1100px) rotateX(24deg)` |
| 연습 모드 | `.floor-grid` | `perspective(400px) rotateX(58deg)` |
| 연습 모드 | `.wall-panel` | `perspective(500px) rotateY(±26deg)` |

좌석·카드·칩·HUD는 평면 HTML을 테이블 위에 `position: absolute`로 얹은 것이다.

### 얼마나 바뀌나
- **그대로:** 서버·엔진·DB·Redis, Mini React 코어(`src/core/`), `roomLogic.js`(+테스트), `room-main.js`/`main.js`, `RoomApp.js`의 상태·동기화(약 220줄).
- **교체:** `RoomApp.js`의 테이블 그리기(약 200줄), `PokerApp.js` 테이블 부분(236~302줄), CSS의 테이블·배경 규칙(대체 화면용은 남김).
- **새로:** `src/poker3d/` 모듈(약 500~1000줄 예상) + `src/vendor/three/`.
- Mini React의 `useRef`로 캔버스 자리를 잡고 `useEffect`로 three.js 장면에 `display`/`state`를 넘기는 방식으로 연결한다.

### 확정된 결정 (2026-11-16)
- 화면 비율: 지금 그대로 (`.arena`, `.table-wrap`의 CSS 크기 유지).
- 빛 번짐: 진짜 bloom은 구울 수 없으므로, 빛 텍스처로 **구운 가짜 번짐을 항상 켜고**, 진짜 bloom은 **토글(기본 꺼짐)**.
- 카드 디자인: 두 화면 각자의 현재 카드 디자인을 그대로 텍스처로 옮김.
- 의자·아바타·소품·3D 모델 파일: 넣지 않음. 모두 기본 도형 + 코드로 그린 텍스처.
- 위험(이름표 어긋남, 애니메이션 밀림, CDN 차단, 캔버스 재생성, WebGL 끊김, 메모리, 상대 카드 노출)과 해결 방법은 플랜 11절.

### 주의할 점
- **판정과 무관.** 화면 표시만 바뀐다. 서버·`roomLogic.js`는 건드리지 않는다.
- 상대 홀카드는 쇼다운 전에 값 자체가 없으므로 3D에서도 뒷면만 그린다.
- `poker.css`는 한 줄 압축이라 수정 시 diff가 크게 보인다.
- 테스트: `projects/react/tests/poker-ui.test.js`, `room-logic.test.js`는 계속 통과해야 한다.
- 화면 계약 전체는 저장소 루트 `UI_HANDOFF.md` 참고.

## 4. 실행 (UI 확인용, 터미널 4개)

```bash
cd projects/dbms && python3 -m mini_dbms.server --data-dir ~/poker-lab-data --host 127.0.0.1 --port 18783
cd projects/redis && python3 -m mini_redis.server --host 127.0.0.1 --port 6382
cd projects/poker_demo && python3 server.py --host 127.0.0.1 --port 18784 --dbms http://127.0.0.1:18783 --redis http://127.0.0.1:6382
cd projects/react && python3 -m http.server 5500 --bind 127.0.0.1
```

- 연습: http://127.0.0.1:5500/poker.html
- 대전: http://127.0.0.1:5500/room.html (두 번째 사람은 `room.html?guest=2`)

## 5. 확인하지 않은 것
- DBMS·Redis 내부 코드, 화면 코드 전체(3D 관련 부분만 읽음)
- 방 500개 버그는 코드 판독 결과이며 재현하지 않음
- 앱은 실행해 연습 모드 한 판 시작까지만 확인(방 대전 화면은 열지 않음)
