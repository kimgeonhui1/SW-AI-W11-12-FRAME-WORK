# 방 대전 3D 화면 변경 리포트

작성 2026-11-16 · 브랜치 `feat/poker-ui` · 비교 기준: 원본 커밋(`HEAD`) · 상태: **커밋 전**

## 1. 한눈에 보기

방 대전 화면(`room.html`)의 테이블을 **외부 라이브러리 없이 CSS 3D**로 바꿨습니다.

| 원본 | 지금 |
|---|---|
| 테이블 바닥만 `rotateX(24deg)`로 기울인 그림. 좌석·카드·칩은 평면 HTML을 그 위에 겹쳐 놓음 | 하나의 3D 공간 안에 테이블 평면이 있고, 좌석·카드·칩·팟이 모두 그 평면 위에 놓임 |
| 배경: 기울인 사각형 벽 3개 | 연습 모드와 같은 배경(네온 기둥 2개, 육각 간판, ◇·♠ 벽 패널, 격자 바닥, 보라 빛)을 3D 공간에 세움 |
| 카드: 한 장짜리 `div`, 앞면이 바뀌면 새 요소 | 앞면·뒷면 두 장을 겹친 3D 카드, 공개될 때 실제로 뒤집힘 |
| 칩: 타원을 `bottom`으로 쌓은 그림 | 원판을 테이블 위로(`translateZ`) 쌓아 실제 높이가 생김 |
| 2D/3D 전환 없음 | 버튼 하나로 3D(52°) ↔ 2D(위에서 내려다봄), 선택은 브라우저에 기억 |
| 빛 번짐 조절 없음 | 네온 빛은 항상 켬 + "빛 번짐" 버튼으로 더 강하게 |
| 딜러 버튼 표시: HUD 글자("D · SB")만 | HUD 글자 + 테이블 위 "D" 버튼 |

**바꾸지 않은 것:**
- 서버, 엔진, DBMS, Redis
- Mini React 코어(`src/core/`)
- API 계약(`UI_HANDOFF.md`)
- 게임 진행·동기화 코드(`accept`, `pump`, `send`, 롱폴링)
- 연습 모드(`poker.html`, `PokerApp.js`)

화면은 여전히 서버가 준 값만 그립니다.

## 2. 바뀐 파일

모두 README의 UI 담당 파일 범위 안입니다. 아래는 `git diff --stat` 결과입니다.

| 파일 | 변경량 | 무엇을 |
|---|---|---|
| `projects/react/src/poker/RoomApp.js` | +58 / −19 | 3D 구조의 DOM, 3D 카드, 칩 높이 변수, 딜러 버튼, 토글 |
| `projects/react/src/poker/roomLogic.js` | +20 | 보기 설정 저장·읽기 함수 |
| `projects/react/src/styles/room.css` | +236 / −147 (테이블·배경 부분 다시 작성) | 3D 공간, 카메라, 배치, 애니메이션 |
| `projects/react/room.html` | 1줄 | CSS·JS 캐시 버전(`?v=room-css3d-2`) |
| `projects/react/tests/room-logic.test.js` | +12 | 보기 설정 테스트 1개 |
| `SOURCE_PROVENANCE.md` | +14 | 변경 기록 |

새 파일은 문서뿐입니다: 이 리포트, `docs/3D/3D_UI_PLAN.md`, `docs/3D/POKER_DEMO_REPORT.md`.

## 3. 동작 원리

### 3.1 3D 공간과 카메라

```
.arena  (perspective: 1300px)          ← 카메라 렌즈. 원근을 정한다
 ├ .hand-label, .view-toggles           ← 3D 밖. 화면에 고정된 글자·버튼
 └ .scene  (preserve-3d, rotateX(--tilt))  ← 3D 공간 전체를 카메라 각도만큼 눕힌다
     ├ .backdrop  ← 바닥·기둥·간판·패널
     └ .table     ← 테이블 평면. 좌석·카드·칩·팟이 모두 이 안에
```

- **`perspective`**([room.css:50](../../projects/react/src/styles/room.css:50)): `.arena`에 주면, 안쪽 3D 요소가 멀수록 작게 보입니다.
- **`transform-style: preserve-3d`**: `.scene`, `.table`, `.seat` 등에 줍니다. 자식이 납작해지지 않고 같은 3D 공간에 남습니다.
- **카메라 각도 `--tilt`**: `.scene`을 `rotateX(var(--tilt))`로 눕힙니다([room.css:63](../../projects/react/src/styles/room.css:63)).
  - 3D는 52°, 2D는 0°입니다.
  - 2D가 되면 테이블이 화면과 나란해져 위에서 내려다본 모습이 됩니다.
- **부드러운 전환**: `@property --tilt`([room.css:48](../../projects/react/src/styles/room.css:48))로 변수를 각도 타입으로 등록했습니다.
  - 그래서 `.arena`의 `transition: --tilt .45s`가 동작합니다.
  - 등록하지 않으면 CSS 변수는 애니메이션 없이 바로 바뀝니다.

### 3.2 세운 글자 (billboard)

이름표(HUD), 팟 글자, 베팅 금액, 로비 방 코드, 칩 이동 글자는 평면에 눕히면 읽기 어렵습니다. 그래서 세웁니다([room.css:139](../../projects/react/src/styles/room.css:139)).

```css
.hud, .bet-chip { transform-origin: 50% 100%; transform: translate(-50%, -100%) translateZ(2px) var(--stand); }
/* --stand = rotateX(calc(-1 * var(--tilt))) */
```

- **세우는 방법:** 장면이 `+tilt`만큼 누웠으니 글자는 `-tilt`만큼 되돌립니다. 그러면 결과적으로 늘 화면을 정면으로 봅니다.
- **기준점:** 아래 가운데(`transform-origin: 50% 100%`)를 기준으로 세웁니다. 그래서 글자가 테이블 평면에 묻히지 않고 그 위에 섭니다.
- **좌석을 따라감:** 글자가 좌석 안에 있어서, 각도가 바뀌어도 좌석과 함께 움직입니다. 따로 위치를 계산하는 코드가 없습니다.

### 3.3 좌석 배치

`Seat` 컴포넌트의 구조는 원본 그대로입니다(카드·HUD·칩·베팅 금액). 원본은 이 조각들을 가로 한 줄로 늘어놓는 grid였는데, 지금은 `.seat`가 테이블 평면 전체를 덮고 조각마다 평면 좌표(%)를 줍니다([room.css:129-138](../../projects/react/src/styles/room.css:129)).

| 조각 | 내 좌석(아래) | 상대 좌석(위) |
|---|---|---|
| 카드 `.seat-cards` | 가로 58%, 세로 70% | 58%, 22% |
| 이름표 `.hud` (세움) | 26%, 100% | 26%, 6% |
| 칩 `.seat-chips` | 77%, 72% | 77%, 20% |
| 베팅 금액 `.bet-chip` (세움) | 30%, 67% | 30%, 34% |
| 딜러 버튼 `.dealer-btn` | 46%, 72% | 46%, 22% |

세로 값은 `.seat`의 CSS 변수(`--cards-y` 등)로 두었습니다. 베팅 금액은 가로도 변수(`--bet-x`)이며, 보드(가로 33~67%, 세로 43~57%) 밖 왼쪽에 둡니다. `.seat-top`은 이 변수만 다시 정합니다([room.css:131](../../projects/react/src/styles/room.css:131)).

### 3.4 3D 카드와 뒤집기

**[RoomApp.js:37](../../projects/react/src/poker/RoomApp.js:37) `Card`:**
- 카드 값이 있으면 `.card3d.is-up`, 비공개(값 없음)면 `.card3d.is-down`입니다.
- 안에는 뒷면(`.side-back`, "JP")과 앞면(`.side-front`)을 겹쳐 둡니다.
- 비공개 카드의 앞면 자리는 빈 카드(`.card-blank`)입니다. 상대 카드 값은 쇼다운 전에는 브라우저에 아예 없습니다(서버 규칙 그대로).

**CSS([room.css:180-183](../../projects/react/src/styles/room.css:180)):**
```css
.card3d.is-down { rotate: y 180deg; }                 /* 뒷면이 위 */
.card3d .card { backface-visibility: hidden; }        /* 뒤를 보는 면은 안 보임 */
.card3d .side-back { transform: rotateY(180deg); }    /* 뒷면은 미리 뒤집어 둠 */
.card3d { transition: rotate .45s ease; }             /* is-down → is-up 이 되면 뒤집힘 */
```

**key 변경([RoomApp.js:53-54](../../projects/react/src/poker/RoomApp.js:53)):**
- 원본은 좌석 카드 key에 카드 값을 넣었습니다(`…-index-value`). 그러면 값이 오는 순간 다른 요소로 바뀌어 뒤집기가 보이지 않습니다.
- 지금은 key를 `handKey-좌석-번호`로 고정했습니다. 같은 요소가 `is-down` → `is-up`으로 바뀌면서 뒤집힙니다.
- 새 핸드면 `handKey`가 바뀌어 새로 나눠 줍니다.

**딜링 애니메이션([room.css:192-194](../../projects/react/src/styles/room.css:192)):**
- `card-deal`: 위(`translateZ(90px)`)에서 떨어져 놓입니다.
- 보드 카드는 `card-deal-flip`: 떨어지면서 뒷면에서 앞면으로 뒤집힙니다.
- 보드 카드 key에는 원본처럼 값이 들어 있어서, 새 카드가 나올 때마다 새 요소가 생기고 애니메이션이 한 번 돕니다.
- 뒤집기는 개별 `rotate` 속성으로, 딜링은 `transform`으로 해서 둘이 서로 덮어쓰지 않습니다.

### 3.5 칩 높이

**[RoomApp.js:28](../../projects/react/src/poker/RoomApp.js:28) `ChipStack`:**
- 원본: 각 칩에 `style: { bottom: i * 5px }`를 줘서 화면상 위로 쌓은 그림이었습니다.
- 지금: `style: { "--i": i }`만 넘깁니다.
- 칩 탑 개수 규칙(금액의 log2)은 그대로입니다.

**[room.css:161](../../projects/react/src/styles/room.css:161):**
```css
.chip { border-radius: 50%; transform: translateZ(calc(var(--i, 0) * 4px + 1px)); }
```
- 칩은 테이블에 눕힌 원판입니다. i번째 칩은 4px씩 위로 올라가서 실제 높이가 생깁니다.
- 3D에서는 기둥처럼 보이고, 2D에서는 위에서 본 원판으로 보입니다.
- **화면 폭 720px 이하에서는 칩 탑을 그리지 않습니다.** 좌석 칩(`.seat-chips`)은 원본 `room.css`부터 숨기던 규칙이고, 팟 칩(`.center > .chips`)은 CSS 3D로 바꾸면서 같은 이유로 숨겼습니다. 좁은 화면에서는 칩 자리가 내 카드·보드와 겹치기 때문입니다. 금액은 이름표(CHIPS)·팟 글자·베팅 배지 숫자로 그대로 보입니다. 데스크톱 창을 720px보다 좁히면(예: 브라우저 창을 반으로 나눈 경우) 칩이 사라져 보이는 이유도 이것입니다.

### 3.6 가운데(팟·보드)와 칩 이동

**가운데([room.css:167-176](../../projects/react/src/styles/room.css:167)):**
- 보드 카드는 평면 가운데에 눕혀 놓습니다.
- 팟 글자(`.pot`)는 보드 위쪽에 세웁니다.
- 팟 칩은 보드 오른쪽에 놓습니다.
- 로비의 방 코드(`.center-lobby`)는 아래 가장자리를 기준으로 세웁니다.

**칩 이동(`.fly`, [room.css:197-205](../../projects/react/src/styles/room.css:197)):**
- 원본은 화면 위아래(`top`)로만 움직였습니다.
- 지금은 테이블 평면 좌표(`left`/`top` %)를 따라 좌석 베팅 자리와 팟 사이를 오갑니다.
- 중간에 위로 60px 떴다가(`translate: 0 0 60px`) 내려와서 포물선을 그립니다.
- 어떤 이동을 보여 줄지는 원본처럼 `display.flight`가 정합니다. 클래스 이름(`fly-bottom-to-pot` 등)도 그대로입니다.

### 3.7 배경 (연습 모드와 같은 구성)

[RoomApp.js:448](../../projects/react/src/poker/RoomApp.js:448)의 `.backdrop` 안에 넣었고, 색과 간격은 연습 모드 `poker.css` 값을 그대로 썼습니다([room.css:64-104](../../projects/react/src/styles/room.css:64)).

| 요소 | 연습 모드 원본 | 3D에서 |
|---|---|---|
| `.floor` 격자 | 바닥 그림을 `rotateX(58deg)` | 실제 바닥 평면(`translateZ(-120px)`), 먼 쪽은 흐리게 |
| `.floor-glow` 보라 빛 | `.table-glow` | 테이블 아래 바닥에 흐린 보라 원 |
| `.pillar` 네온 기둥 2개 | 19° 기운 막대 | 바닥에서 세우되 수직이 아니라 64°로 뒤로 젖힘(위는 멀리, 아래는 가까이). 키를 화면 위로 넘치게 키워서 위·아래 끝 모두 안 보이게(아래 끝은 테이블 뒤에 가려짐) |
| `.portal` 육각 간판 | "POKER LAB / NEON DISTRICT / 01" | 바닥에서 세운 간판. 아래쪽이 테이블에 가리므로 키를 키우고 글자를 위쪽에 둠 |
| `.wall-panel` 벽 패널 2개 | ◇ 청록 / ♠ 분홍, 가로줄 3개 | 공중에 세워 안쪽으로 30° 돌림. 기둥과 3D로 교차하지 않게 바깥쪽(-10%)에 둠 |
| 화면 상자 배경·테두리 | `.table-wrap` | 같은 그라데이션·테두리·둥근 모서리 |

- **`.stand`:** 세운 요소의 공통 클래스입니다. 아래 가장자리를 축으로 `rotateX(-90deg)`(기둥은 -64°) 돌려 바닥에서 일으킵니다.
- **2D에서는 숨김:** 2D(위에서 내려다봄)에서는 세운 것이 옆면만 보이므로 `.arena.view-2d .stand { opacity: 0 }`으로 숨깁니다.

### 3.8 2D/3D·빛 번짐 토글과 설정 기억

**[roomLogic.js:126-145](../../projects/react/src/poker/roomLogic.js:126):**
```js
VIEW_PREF  = { key: "jungle-poker-lab.view",  allowed: ["3d", "2d"],  fallback: "3d" }
BLOOM_PREF = { key: "jungle-poker-lab.bloom", allowed: ["off", "on"], fallback: "off" }
readPref(storage, pref)         // 저장소가 막혔거나 이상한 값이면 기본값
writePref(storage, pref, value) // 허용된 값만 저장, 실패해도 조용히 넘어감
```
DOM 없이 저장소 객체를 인자로 받아서 node에서도 테스트할 수 있습니다.

**RoomApp:**
- [96-97줄](../../projects/react/src/poker/RoomApp.js:96): 처음 그릴 때 저장된 값을 읽어 `view`, `bloom` 상태를 만듭니다.
- [229-238줄](../../projects/react/src/poker/RoomApp.js:229): 버튼을 누르면 상태를 바꾸고 저장합니다.
- [442줄](../../projects/react/src/poker/RoomApp.js:442): `.arena`에 `view-3d`/`view-2d`, `bloom-on` 클래스를 붙입니다. 화면 변화는 전부 CSS가 합니다.
- [74줄](../../projects/react/src/poker/RoomApp.js:74) `ViewToggles`: props만 받는 버튼 두 개입니다. Mini React 규칙상 Hook은 루트에서만 씁니다. `aria-pressed`로 켜짐 상태를 알립니다.

**빛 번짐([room.css:57-61](../../projects/react/src/styles/room.css:57)):**
- 네온 그림자 크기에 `--glow`(기본 1, 켜면 2.2)를 곱합니다(레일, 펠트 선, 간판, 기둥, 패널).
- 켜면 화면 위에 빛 막(`.arena::after`, `mix-blend-mode: screen`)이 한 장 더 겹칩니다.
- 3D 장면에 `filter`를 걸면 3D가 납작해지므로 쓰지 않았습니다.

### 3.9 딜러 버튼

[RoomApp.js:69](../../projects/react/src/poker/RoomApp.js:69): 서버가 준 `seat.isButton`이 참이고 로비가 아니면, 그 좌석에 "D" 원판을 그립니다. 핸드가 바뀌면 서버 값에 따라 상대 쪽으로 옮겨집니다.

## 4. 원본에서 지운 것

| 지운 것 | 대신 |
|---|---|
| 기울인 벽 3개(`.wall-left/right/top`의 `skewY`) | 3.7의 3D 배경 |
| `.table`의 `rotateX(24deg)`와 `aria-hidden` | `.scene`의 `--tilt`. `.table` 안에 HUD가 들어가므로 `aria-hidden`은 펠트(`.felt`)로 옮김 |
| 좌석 grid 배치, `.seat-top{top:3%}` 등 | 3.3의 평면 좌표 |
| 칩의 `bottom` 쌓기, `card-in` 애니메이션 | 3.5, 3.4 |
| `.fly`의 화면 세로(`top`) 애니메이션 | 3.6의 평면 포물선 |

## 5. 개발 중 발견하고 고친 문제

| 문제 | 원인 | 해결 |
|---|---|---|
| 버튼을 누르면 테이블이 옆으로 365px 밀림 | 넓은 바닥·기둥이 상자 밖으로 퍼져 있어, 포커스 때 브라우저가 `overflow: hidden` 상자를 스크롤함 | `overflow: clip`(스크롤 불가) ([room.css:52](../../projects/react/src/styles/room.css:52)) |
| 로비 방 코드가 반쯤 묻힘 | 가운데 기준으로 세워 아래 절반이 평면 아래로 들어감 | 아래 가장자리 기준으로 세움 |
| 간판 글자가 테이블에 가림 | 바닥에 세운 간판 아래쪽이 테이블 높이보다 낮음 | 키를 키우고 글자를 위쪽에 |
| 기둥 끝이 잘려 보임 | 기둥 길이가 화면보다 짧음 | 길이를 키우고 뒤로 젖혀 아래 끝을 테이블 뒤로 |
| 기둥이 패널을 뚫음 | 기울어진 기둥과 돌린 패널이 3D로 교차 | 패널을 바깥쪽으로 |
| 베팅 배지가 보드 카드 무늬를 가림 (검토 P1) | 내 쪽 배지(44%, 57%)가 보드 바로 아래에 세워져, 3D에서는 보드 아래쪽을, 2D에서는 보드 아래 끝을 덮음 | 배지를 보드 밖 왼쪽(내 쪽 30%·67%, 상대 30%·34%)으로. 칩 이동 출발점도 같이 옮김 |
| 375px 모바일 3D에서 내 이름표 왼쪽이 잘림 (검토 P2) | 내 쪽은 원근으로 커지면서 바깥으로 밀리는데, 이름표가 26%에 있어 화면 왼쪽 밖으로 나감 | 720px 이하에서 이름표를 37%, 내 카드를 74%로 |

**지켜야 할 규칙:** `preserve-3d` 요소에 `opacity`, `filter`, `overflow`를 주면 그 아래 3D가 납작해집니다. 이런 효과는 끝 요소(카드 면, 칩, HUD, 세운 배경)에만 씁니다.

## 6. 검증

| 항목 | 결과 |
|---|---|
| `node projects/react/tests/room-logic.test.js` | 8/8 통과 (보기 설정 테스트 포함) |
| `node --check src/poker/RoomApp.js` | 통과 |
| 두 게스트(`?guest=2`) 방 대전 여러 핸드 | 카드·보드·칩·딜러 버튼·승자 강조 정상 |
| 쇼다운 상대 카드 | 같은 요소가 `is-down` → `is-up`으로 뒤집힘 |
| 2D/3D·빛 번짐 | 정상, 새로고침 후 유지. 2D에서 세운 배경 5개 숨김 확인 |
| 옆으로 밀림 | 수정 후 `scrollLeft` 0 |
| 휴대폰 폭 375px | 가로 스크롤 없음, 3D·2D 모두 이름표 잘림 없음(왼쪽 여백 35px 이상) |
| 베팅 배지와 보드 카드 겹침 | 데스크톱·375px × 3D·2D 네 경우 모두 겹침 없음 (요소 위치로 검사) |

## 7. 한계와 남은 일

- **빛 번짐:** 진짜 bloom이 아니라 그림자를 키우는 근사입니다.
- **좁은 화면의 칩:** 720px 이하에서는 좌석·팟 칩 탑이 보이지 않습니다(3.5절). 보이게 하려면 칩을 줄이고 내 카드(74%)와 겹치지 않는 자리로 옮겨야 합니다. 아직 하지 않았습니다.
- **새로고침 직후:** 카드 딜링 애니메이션(0.4~0.5초) 동안에는 카드가 위에 떠 있고, 보드 카드는 뒷면으로 보입니다. 그 사이에 찍은 화면은 카드가 겹치거나 뒷면으로 보일 수 있습니다.
- **곡면:** 테이블 두께와 칩 옆면은 근사입니다(아래 판 한 장, 원판 쌓기).
- **확인하지 못한 환경:** Safari·Firefox, 실제 휴대폰, 서로 다른 두 컴퓨터. 배경 조정 뒤의 휴대폰 화면도 다시 보지 않았습니다.
- **오래된 브라우저:** `@property`, `overflow: clip`, 개별 `rotate` 속성을 지원하지 않으면 각도 전환이 애니메이션 없이 바뀌거나 카드 뒤집기가 바로 바뀔 수 있습니다.
- **연습 모드:** UI 담당 범위 밖이라 3D로 바꾸지 않았습니다.
- **기존 문서 숫자:** README와 UI_HANDOFF의 room-logic "7개"는 이전 검증 기록이라 그대로 두었습니다. 지금은 8개입니다.
- **개발 중 캐시:** `python -m http.server`는 캐시를 막지 않아서, 코드를 고친 뒤에는 강력 새로고침이 필요할 수 있습니다.

## 8. 직접 확인하는 방법

1. README대로 서버 4개를 켭니다.
2. `http://127.0.0.1:5500/room.html`에서 방을 만듭니다.
3. 다른 창에서 `room.html?guest=2`로 같은 방에 들어갑니다.
4. 오른쪽 위 "2D로 보기"와 "빛 번짐" 버튼으로 전환을 확인합니다.

## 9. 3~4인 화면 배치 (feat/poker-multiway)

4인 방에서 화면 폭에 따라 이름표(HUD)·카드·베팅 배지·칩·행동 기록이 서로 겹치거나 화면 밖으로 잘리던 문제를 고쳤습니다. 바꾼 파일은 `RoomApp.js`(한 줄)와 `room.css`, `room.html`(캐시 번호 `room-css3d-4`)뿐입니다.

### 9.1 바꾼 것

- **`--ui-scale`:** 세운 글자(이름표·베팅 배지·팟)의 transform 끝에 `scale(var(--ui-scale, 1))`을 붙여, 아래 가운데를 기준으로 줄입니다. 위치만 옮기면 한쪽을 풀 때 다른 쪽이 겹쳐서, 좁은 폭에서는 크기를 줄이는 쪽을 택했습니다.
  - 721~1100px: 0.86, 721~900px: 0.74 (인원수와 관계없이)
  - 720px 이하 3~4인: 0.86, 430px 이하 3~4인: 0.8
- **좌석 위치:** 3~4인일 때 위·왼쪽·오른쪽·아래 좌석의 `--hud-*`, `--cards-*`, `--chips-*`, `--bet-*` 값을 다시 잡았습니다(값과 이유는 `room.css` 주석).
- **행동 기록:** 3~4인은 모든 폭에서, 721~1100px은 인원수와 관계없이 테이블 안 기록을 숨기고 테이블 아래 기록(`.action-log-below`)을 보여 줍니다. 이를 위해 `RoomApp.js`가 화면 상자(`.arena`)에도 `seats-N` 클래스를 붙입니다.
- **좌석 칩 탑:** 721~1040px의 3~4인 방에서는 좌석 칩 탑을 숨깁니다(칩 수는 이름표에 그대로 보입니다).
- **2D 위 좌석:** 2D 보기에서 위 좌석 이름표를 `--hud-y: 10%`로 내려 1280px에서 화면 위로 잘리지 않게 했습니다.

### 9.2 검증

테스트 봇(`tools/test-bots/poker_test_bots.py`)으로 방을 채우고, 핸드의 여러 단계(프리플롭~쇼다운)에서 3D·2D 둘 다 요소 위치를 재서 겹침(60px² 초과)과 화면 밖을 검사했습니다. 모두 문제 없음.

| 인원 | 확인한 폭(px) |
|---|---|
| 4인 | 360, 375, 414, 480, 540, 600, 640, 720, 721, 768, 800, 900, 950, 1001, 1041, 1060, 1100, 1101, 1150, 1280, 1440 |
| 3인 | 375~1280 |
| 2인 | 375, 768, 900, 1024, 1280 |

`node projects/react/tests/room-logic.test.js`: 16/16 통과.

### 9.3 감수한 것

- 3~4인 방과 721~1100px 폭에서는 행동 기록이 테이블 아래로 내려갑니다.
- 721~1040px의 3~4인 방에서는 좌석 칩 탑이 보이지 않습니다.
- 좁은·중간 폭에서는 이름표가 작아집니다.
- Safari·Firefox, 실제 휴대폰은 확인하지 않았습니다.

### 9.4 UI 밖 문제 (기록만, 고치지 않음)

- mac + Python 3.14에서 poker 동시 요청 테스트 2개가 실패합니다(connection reset / Errno 22). listen backlog를 늘려도 그대로라 환경 문제로 봤습니다.
- Redis를 안 켠 환경에서 관련 테스트가 실패합니다.
- 페이지 제목 "2인 대전", README "2인 포커" 문구가 여러 명 방과 맞지 않습니다.
- 로비의 CHIPS가 0으로 보입니다.
- 칩 이동 경로 `FLIGHT_POINTS`가 고정값이라 좌석 배치와 따로 움직입니다.
