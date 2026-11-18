# 포커 UI 3D 전환 플랜

작성 2026-11-16 · 수정 2026-11-16(결정 사항·위험 대응 반영) · 브랜치 `feat/poker-ui`
관련 분석: [POKER_DEMO_REPORT.md](./POKER_DEMO_REPORT.md) · 상태: **구현 완료 (2026-11-16), 커밋 전**

> **최종 구현은 three.js가 아니라 CSS 3D(B안)입니다.** 1~14절은 처음 세운 three.js(A안) 계획이고, 실제로 three.js 버전을 만들어 확인까지 했지만 되돌렸습니다. 이유는 두 가지입니다.
> - Mini React README의 "외부 라이브러리 0개"와 맞지 않습니다.
> - README의 UI 담당 범위 밖인 연습 모드 파일까지 고쳐야 했습니다.
>
> 결정 사항(2절)과 위험 목록(11절)은 B안에도 그대로 적용했습니다. 최종 구현과 검증은 **15절**을 보세요.

## 1. 목표와 범위

- 테이블·배경·카드·칩·딜러 버튼을 **three.js 실시간 3D 장면**으로 바꾼다. 지금은 CSS로 평면을 기울인 시각효과다.
- 같은 장면에서 **3D(원근) ↔ 2D(위에서 내려다보기)** 를 카메라 전환으로 오간다.
- **바꾸지 않는 것:** 서버·엔진·DBMS·Redis, Mini React 코어(`src/core/`), 화면 로직(`roomLogic.js`), 시작점(`room-main.js`, `main.js`), API 계약(`UI_HANDOFF.md`).
- 원칙 유지: 화면은 결과를 정하지 않는다. 3D 장면은 `display`/`state`를 **그리기만** 한다. 상대 홀카드는 쇼다운 전에는 값이 없으므로 뒷면만 그린다.

## 2. 확정된 결정

| 항목 | 결정 | 반영 위치 |
|---|---|---|
| 화면 비율 | **지금 그대로 유지** | 5절 |
| 빛 번짐(bloom) | **가짜 빛 번짐을 텍스처로 구워서 항상 켬** + 진짜 bloom은 **토글 옵션(기본 꺼짐)** | 6절 |
| 카드 디자인 | **현재 디자인을 그대로 따라감** (방 대전·연습 모드 각자의 현재 카드) | 7절 |
| 의자·아바타·소품 | **넣지 않음** | 3절 |
| 3D 모델 파일 | **쓰지 않음** — 모두 기본 도형 + 코드로 그린 텍스처 | 3절 |

## 3. 3D 모델 없이 만드는 방법

모델 파일(.glb)·이미지 에셋 없이 three.js 기본 도형과 `CanvasTexture`(캔버스에 그린 그림을 텍스처로 씀)만 쓴다. 의자·아바타·장식 소품은 만들지 않는다.

| 물체 | 만드는 방법 |
|---|---|
| 테이블 상판 | 타원 `Shape` → `ExtrudeGeometry`(두께, 모서리 둥글게). 펠트는 지금 색의 방사형 그라데이션 텍스처 |
| 테이블 레일(네온 테두리) | 타원 곡선 → `TubeGeometry` + 발광 재질(`emissive`) |
| 펠트 안쪽 선·로고 | 펠트 텍스처에 같이 그림 (방 대전 "JUNGLE POKER LAB", 연습 모드 "PL" 마크) |
| 카드 | 얇은 `BoxGeometry`. 앞·뒷면은 7절의 `CanvasTexture` |
| 칩 | `CylinderGeometry` + 금색 줄무늬 옆면 텍스처(지금 `.gold-chip`/`.chip` 색) |
| 딜러 버튼 | 작은 `CylinderGeometry` + "D" 텍스처 |
| 방 배경 | 바닥 격자 `PlaneGeometry`, 벽 패널·기둥·위쪽 문은 `BoxGeometry` + 네온 선(`LineSegments`). 지금 CSS 배경의 배치·색을 3D 공간에 옮김 |

## 4. 구조

```
projects/react/
  room.html, poker.html    import map 추가 (9절)
  src/vendor/three/        three.js 복사본 (9절, CDN 대신 기본으로 사용)
  src/poker3d/             ← 새로 만듦 (방 대전·연습 모드 공용)
    TableScene.js          장면·렌더러·조명·카메라·크기 대응·필요할 때만 렌더·WebGL 오류 처리
    objects.js             테이블, 카드, 칩, 딜러 버튼, 배경 만들기
    textures.js            CanvasTexture: 카드(두 가지 디자인), 칩, 펠트, 구운 빛 번짐
    layout.js              좌석·보드·팟·칩 3D 좌표, 카메라 맞춤 계산 (순수 함수)
    animate.js             트윈 대기열 (라이브러리 없이 requestAnimationFrame)
    labels.js              3D 좌표 → 화면 좌표 (순수 함수)
    Table3D.js             Mini React 컴포넌트: ref로 div를 잡고 TableScene 연결
  src/poker/
    RoomApp.js             테이블 그리기 부분만 <Table3D>로 교체
    PokerApp.js            테이블 부분(236~302줄)만 <Table3D>로 교체
  tests/
    poker3d-layout.test.js, poker3d-labels.test.js, poker3d-animate.test.js   새로 추가
```

### 연결 방식 (Mini React ↔ three.js)

```js
function Table3D({ display, state, you, view, bloom, theme }) {
  const host = useRef(null);
  const scene = useRef(null);
  useEffect(() => {                                   // 한 번만 생성, 화면에서 내려가면 정리
    scene.current = TableScene.create(host.current, { theme });   // WebGL 실패 시 null
    return () => scene.current?.dispose();
  }, []);
  useEffect(() => { scene.current?.sync(display, state, you); }, [display, state]);
  useEffect(() => { scene.current?.setView(view); }, [view]);    // "3d" | "2d"
  useEffect(() => { scene.current?.setBloom(bloom); }, [bloom]); // true | false
  return h("div", { key: "table3d", className: "table3d", ref: host });
}
```

- `TableScene.sync()`는 **현재 값에 맞춰 물체를 배치**한다. 같은 값이 다시 와도 결과가 같다.
- 애니메이션 신호는 지금 그대로 쓴다: `display.flight`(칩 이동), `display.last`(마지막 행동), 보드 카드 수 변화(딜링), `state.result`(쇼다운 공개).
- `TableScene.create()`가 `null`이면(WebGL 불가) `RoomApp`/`PokerApp`은 기존 CSS 테이블을 그린다(10절).

### HTML로 남기는 것

이름·칩 숫자·남은 시간 HUD, 베팅 버튼·입력, 로비·방 코드, 알림, Inspector 패널, 2D/3D·빛 번짐 토글 버튼.
- 이름표는 3D 좌석 위치를 따라 HTML로 띄운다(11절 위험 1).
- 접근성(`aria-label`, 스크린리더)은 HTML 쪽에 둔다. 캔버스는 `aria-hidden`.

## 5. 화면 비율 (지금 그대로)

- 3D 캔버스는 **지금 테이블이 있는 상자를 그대로** 채운다. 상자 크기는 기존 CSS를 바꾸지 않는다.
  - 방 대전: `.arena` — `height: clamp(520px, 62vw, 680px)`, 720px 이하 화면 규칙 포함
  - 연습 모드: `.table-wrap` — `height: clamp(490px, 59vh, 670px)`, 1700/1100/850/560px 화면 규칙 포함
- 카메라 화면비 = 상자의 가로/세로. 창 크기가 바뀌면 `ResizeObserver`로 렌더러 크기와 카메라를 다시 맞춘다.
- 테이블이 잘리지 않도록 `layout.js`의 `fitCamera(aspect, fov)`가 **테이블 전체 폭이 들어오는 카메라 거리**를 계산한다(좁은 화면일수록 카메라가 뒤로 감). 2D 직교 카메라도 같은 방식으로 시야 크기를 정한다.
- 기본 3D 각도는 지금 화면과 비슷하게 맞춘다(테이블을 약 24° 기울인 모습, 아래 = 나, 위 = 상대).

## 6. 빛 번짐 (bloom)

진짜 bloom은 매 프레임 화면 전체를 흐리게 다시 그리는 후처리라서 **그대로 구울 수는 없다.** 대신 네온 빛은 구분해서 처리한다.

| 방식 | 내용 | 기본값 |
|---|---|---|
| **구운 빛 번짐** | 네온 테두리·벽 선·문 테두리 뒤에, 미리 흐리게 그린 빛 텍스처(`textures.js`의 `glowTexture`)를 붙인 판을 더하기 혼합(`AdditiveBlending`)으로 겹친다. 계산은 텍스처 한 번 만들 때뿐 | **항상 켬** |
| **진짜 bloom** | `EffectComposer` + `UnrealBloomPass`(three.js 기본 애드온). 카드에 비친 빛까지 자연스럽지만 GPU 부담이 큼 | **토글, 기본 꺼짐** |

- 토글 버튼 "빛 번짐"은 HUD 영역에 둔다. 선택은 `localStorage`(`jungle-poker-lab.bloom`)에 저장하고, 읽기·쓰기는 try/catch로 감싸 실패하면 꺼짐으로 동작.
- 진짜 bloom을 켤 때만 애드온 모듈을 불러온다(`import()`). 꺼 두면 불러오지도 않는다.
- 진짜 bloom이 켜지면 구운 빛 번짐은 약하게 줄여 두 번 번지지 않게 한다.

## 7. 카드 디자인 (현재 것 따라가기)

두 화면의 카드가 지금 서로 다르므로 **각 화면이 자기 현재 디자인을 그대로** 쓴다. `textures.js`에 테마 두 개를 둔다.

| 테마 | 출처 | 앞면 | 뒷면 |
|---|---|---|---|
| `room` | `room.css` `.card-face` / `.card-back` (50×70) | 흰색→`#e8edf7` 세로 그라데이션, 가운데 숫자(굵게) 위 무늬 아래, 빨강 `#d0153a`, 검정 `#10131f` | `#2a1150`/`#3c1a70` 45° 줄무늬, 시안 테두리, 가운데 "JP" |
| `practice` | `poker.css` `.playing-card` (57×79) | 흰색→`#e3e6f2` 그라데이션, 왼쪽 위·오른쪽 아래(180° 회전) 모서리 숫자+무늬(Georgia 굵게), 가운데 큰 무늬, 빨강 `#bd2855` | `#3a2252`/`#231a3d` 45° 줄무늬, 안쪽 `#9779c5` 테두리, 가운데 문양 |

- 카드 비율도 각 디자인 그대로(50:70, 57:79). 텍스처는 2배 해상도 캔버스에 그려 글자가 흐리지 않게 한다.
- 52장 + 뒷면을 테마마다 한 번만 만들어 재사용한다.
- 빈 보드 자리(`.card-empty`, `.card-slot`)는 점선 테두리 판으로 그린다.
- 카드 뒤집기는 지금 CSS 애니메이션(`card-flip`: Y축 회전)과 같은 움직임을 3D로 한다.

## 8. 2D/3D 전환

- 3D: `PerspectiveCamera`, 5절의 기본 각도.
- 2D: `OrthographicCamera`, 바로 위에서. 카드·칩은 테이블에 눕혀 두므로 위에서 정면으로 보인다.
- 전환은 0.4초 카메라 이동 트윈. 게임 상태·입력에는 영향 없음.
- 선택은 `localStorage`(`jungle-poker-lab.view`)에 저장, try/catch, 실패하면 3D 기본.
- `prefers-reduced-motion`이면 전환·카드·칩 애니메이션을 즉시 끝 위치로 보낸다(지금 CSS 규칙과 같은 동작).

## 9. three.js 불러오기

빌드 도구가 없으므로 HTML에 import map을 두고, **저장소 안의 복사본을 기본으로** 쓴다(11절 위험 3).

```html
<script type="importmap">
{ "imports": {
  "three": "./src/vendor/three/build/three.module.js",
  "three/addons/": "./src/vendor/three/examples/jsm/"
} }
</script>
```

- 버전은 하나로 고정(예: `three@0.170.0`). 받는 곳은 npm 공식 패키지, 라이선스 MIT. `src/vendor/three/VERSION`에 버전과 받은 날짜를 적는다.
- 복사본에는 쓰는 파일만 넣는다: 코어 빌드와 bloom에 필요한 애드온(`postprocessing/`, `shaders/`의 해당 파일).
- 새 의존성은 three.js 하나뿐. 트윈·UI 라이브러리는 추가하지 않는다.

## 10. 단계별 진행

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| 0. 준비 | vendor 복사, import map, `poker3d/` 뼈대, `Table3D` 연결, WebGL 불가 시 CSS 화면 | room.html에서 빈 3D 상자가 보이고 기존 버튼이 동작. WebGL을 꺼도 기존 화면이 나옴 |
| 1. 정적 장면 | 테이블·배경·카드(room 테마)·칩·딜러 버튼을 `display` 값대로 배치, 구운 빛 번짐 | 새로고침 직후(snap) 화면이 서버 상태와 일치. 화면 비율이 지금과 같음 |
| 2. 애니메이션 | 딜링, 보드 공개, 칩→팟, 팟→승자, 쇼다운 카드 뒤집기 | 이벤트 재생 순서대로 움직이고 재생 끝에 서버 상태와 같음 |
| 3. HUD 연결 | 이름·칩·시간 HTML을 좌석 위치에 띄움, 차례·승자 강조 | 창 크기를 바꿔도 이름표가 좌석을 따라감 |
| 4. 토글 | 2D/3D 전환, 빛 번짐(진짜 bloom) 토글, 선택 기억 | 게임 중 전환해도 상태·입력 영향 없음 |
| 5. 연습 모드 | `PokerApp.js`에 같은 `Table3D`(practice 테마) 연결 | poker.html도 3D, Inspector 유지 |
| 6. 마무리 | 성능 점검, 접근성·reduced-motion 확인, 남은 CSS 정리 | 12·13절 확인 |

방 대전을 먼저 한다. `roomLogic.js`에 테스트가 있고 이벤트 재생 구조가 명확해서 3D 연결 검증이 쉽다.

### 기존 코드에서 지울 것

- `RoomApp.js`: `Card`, `Seat`, `ChipStack`와 `.arena` 안의 backdrop/table/seat/center/flight 노드(약 200줄). 상태·동기화(`accept`, `pump`, `send`, 롱폴링)는 유지.
- `PokerApp.js`: 테이블 섹션과 같은 이름의 컴포넌트. `Trace`·Inspector 유지.
- `room.css`, `poker.css`: 3D로 옮긴 테이블·배경 규칙. **단 WebGL 불가 대체 화면에 필요한 규칙은 남긴다.** 버튼·로비·알림·Inspector 규칙 유지.

## 11. 위험과 해결 방법

설계 단계에서 각 위험을 아래처럼 막는다. 각 해결에는 확인 방법을 붙였다.

### 위험 1. HTML 이름표와 3D 좌석 위치가 어긋남
- **원인:** 창 크기 변경, 2D/3D 전환 중 카메라 이동, 화면 비율 규칙(@media) 변경.
- **해결:**
  - 좌석의 3D 기준점을 `layout.js`의 `seatAnchor(seat)` 하나에서만 정한다.
  - `labels.js`의 `project(point, camera, width, height)`는 DOM 없는 순수 함수로, 3D 점을 화면 픽셀로 바꾼다.
  - `TableScene`이 **렌더할 때마다** 같은 카메라로 이름표 위치를 다시 계산하고, 이름표 HTML에는 `transform: translate(x, y)`만 바꾼다(레이아웃 재계산 없음).
  - 상자 크기 변화는 `ResizeObserver`로 감지해 렌더러·카메라·이름표를 한 번에 갱신한다.
  - 점이 카메라 뒤로 가면(`z > 1`) 이름표를 숨긴다.
- **확인:** `poker3d-labels.test.js`에서 알려진 카메라·점에 대한 화면 좌표, 화면 비율별 결과를 검사. 브라우저에서 창 크기 바꾸기·전환 중 확인.

### 위험 2. 이벤트가 몰려올 때 애니메이션이 밀림
- **원인:** 롱폴링으로 여러 이벤트가 한꺼번에 오거나, 재연결 뒤 바로 맞추기(snap)가 오는 경우.
- **해결:**
  - `animate.js`에 트윈 대기열을 둔다. 새 트윈이 시작되기 전에 **진행 중인 트윈을 즉시 끝 위치로 보낸다**(`finishAll()`). 화면은 항상 최신 이벤트를 따라잡는다.
  - 트윈 시간은 `roomLogic.eventDelay(event)`보다 짧게(최대 80%) 잡아, 다음 이벤트 전에 끝난다.
  - `sync()`가 받은 `display.synced === true`(재생 끝 또는 snap)이면 모든 트윈을 취소하고 **서버 상태 위치로 바로 놓는다.**
  - 탭이 숨겨졌다 돌아오면(`visibilitychange`) 밀린 트윈을 모두 끝 위치로 보낸다.
- **확인:** `poker3d-animate.test.js`에서 가짜 시계로 연속 트윈·`finishAll`·snap을 검사(DOM·WebGL 없이). 브라우저에서 한쪽 네트워크를 끊었다 복구.

### 위험 3. CDN이 막힌 환경
- **해결:** CDN을 쓰지 않는다. three.js를 `src/vendor/three/`에 넣고 import map이 상대 경로를 가리킨다(9절). 오프라인·학교망에서도 동작하고, 지금 실행 방법(`python -m http.server`) 그대로 된다.
- **확인:** 네트워크 없이 room.html이 3D로 뜨는지 확인.

### 위험 4. Mini React가 캔버스 div를 다시 만들어 장면이 사라짐
- **원인:** 다시 그릴 때 부모 구조나 형제 순서가 바뀌면 Mini React가 div를 새로 만들 수 있다. 그러면 three.js가 붙인 캔버스가 사라진다.
- **해결:**
  - `Table3D`의 div에 고정 `key`를 주고, **가상 DOM 자식을 하나도 두지 않는다.** 캔버스는 three.js만 붙이고 Mini React는 그 안을 비교하지 않는다.
  - `RoomApp`에서 `Table3D`를 항상 같은 위치(`.arena`의 첫 자식)에 두고, 로비·게임·핸드 종료 상태에서 조건부로 빼지 않는다.
  - 안전장치: `sync()` 때마다 캔버스가 host 안에 있는지 확인하고, 없으면 다시 붙인다.
  - div가 실제로 화면에서 내려가면(로그인·방 선택 화면으로 이동) `dispose()`가 정리하고, 다시 들어오면 새로 만든다.
- **확인:** Mini React 테스트 방식(`tests/*.test.js`)으로 RoomApp을 여러 상태로 다시 그려도 host div와 캔버스가 같은 객체인지 검사.

### 위험 5. WebGL을 쓸 수 없거나 도중에 끊김 (추가)
- **해결:** `TableScene.create()`가 WebGL 생성에 실패하면 `null`을 돌려주고, 화면은 기존 CSS 테이블을 그린다. 실행 중 `webglcontextlost`가 오면 렌더를 멈추고, `webglcontextrestored`에서 텍스처·재질을 다시 만든다. 복구가 안 되면 CSS 화면으로 바꾼다.
- **확인:** 브라우저에서 `WEBGL_lose_context` 확장으로 강제로 끊어 보기.

### 위험 6. 메모리 누수·발열 (추가)
- **해결:**
  - 가만히 있을 때는 그리지 않는다. 애니메이션·`sync`·카메라 변경·크기 변경이 있을 때만 `requestAnimationFrame`을 돈다.
  - `devicePixelRatio`는 최대 2.
  - 텍스처는 테마마다 한 번 만들어 재사용, `dispose()`에서 지오메트리·재질·텍스처·렌더러를 모두 해제.
  - 진짜 bloom은 기본 꺼짐(6절).
- **확인:** 방 화면을 여러 번 들어갔다 나온 뒤 `renderer.info.memory`의 지오메트리·텍스처 수가 늘지 않는지 확인.

### 위험 7. 상대 카드 노출 (추가)
- **해결:** 3D 쪽은 서버가 보낸 값만 쓰며, `cards`가 없으면 뒷면 텍스처만 쓴다. 상대 카드 앞면 텍스처는 값이 올 때(쇼다운)에만 고른다. 52장 텍스처를 미리 만들어 두는 것은 카드 값과 무관해서 정보가 새지 않는다.
- **확인:** 쇼다운 전 장면의 상대 카드 메시가 뒷면 재질만 쓰는지 검사.

## 12. 성능 기준

- 가만히 있을 때 GPU 사용 0(렌더 안 함).
- 애니메이션 중 일반 노트북 내장 그래픽에서 60fps 목표(구운 빛 번짐만 켠 상태).
- 진짜 bloom을 켜면 느려질 수 있으며, 그 차이를 토글로 사용자가 고른다.

## 13. 테스트

- 기존: `node tests/room-logic.test.js`, `tests/poker-ui.test.js`는 계속 통과해야 한다.
- 새로: `poker3d-layout.test.js`(좌석·보드 좌표, 카메라 맞춤), `poker3d-labels.test.js`(좌표 변환), `poker3d-animate.test.js`(트윈 대기열·finishAll·snap). 모두 DOM·WebGL 없이 node로 실행.
- 브라우저 확인: 두 브라우저로 방 대전 한 판 → 딜링·베팅·쇼다운·폴드·새로고침·2D/3D 전환·빛 번짐 토글·창 크기 변경·네트워크 끊김.
- 서버 테스트(`projects/poker_demo`)는 화면만 바꾸므로 영향 없음.

## 14. 범위 밖

의자·아바타·장식 소품·3D 모델 파일, 마우스로 카메라 돌리기, 3인 이상 테이블, 사운드.

## 15. 최종 구현: CSS 3D (B안, 2026-11-16)

### 방식

외부 라이브러리 없이 브라우저의 CSS 3D 변환만 씁니다. 범위는 방 대전 화면(`room.html`)뿐입니다.

- `.scene`이 하나의 3D 공간(`transform-style: preserve-3d`)이고, `.table`이 그 안의 테이블 평면입니다.
- 좌석·카드·칩·팟·칩 이동 연출은 모두 `.table` 안에 있습니다. 평면 위 위치는 퍼센트 좌표로 줍니다.
- 카메라 각도는 CSS 변수 `--tilt` 하나로 정합니다.
  - 3D는 52°, 2D는 0°입니다.
  - `@property`로 등록해 두어서 각도가 0.45초 동안 부드럽게 바뀝니다.
- 이름표(HUD)·팟 글자·베팅 금액·칩 이동 글자는 평면 위에 세웁니다.
  - `-tilt`만큼 되돌려 세우므로 항상 화면을 정면으로 봅니다.
  - 좌석 안에 있어서 각도가 바뀌어도 좌석을 따라갑니다.
- 칩은 평면에 눕힌 원판입니다. `--i`번째 칩은 4px씩 위(`translateZ`)로 쌓이므로 실제 높이가 생깁니다.
- 카드는 앞면·뒷면 두 장을 겹친 3D 카드입니다.
  - 값이 없으면 `rotate: y 180deg`(뒷면이 위)입니다.
  - 값이 오면 같은 요소가 뒤집힙니다. 쇼다운 때 상대 카드가 실제로 뒤집히는 이유입니다.
  - 딜링은 위에서 떨어지는 애니메이션이고, 보드 카드는 떨어지면서 뒤집힙니다.
- 배경은 연습 모드(`poker.css`의 `.casino-room`, `.portal`, `.wall-panel`, `.floor-grid`, `.table-glow`)와 같은 구성·색을 3D 공간에 세웠습니다.
  - 바닥에 눕힌 것: 격자, 보라 빛
  - 세운 것: 네온 기둥 2개(안쪽으로 19° 기울임), 육각 간판 "POKER LAB / NEON DISTRICT / 01", 양옆 벽 패널(◇ 청록, ♠ 분홍)
  - 화면 상자의 배경색·테두리·모서리도 연습 모드 `.table-wrap`과 같습니다.
  - 간판은 바닥에 세우면 아래쪽이 테이블에 가려져서 연습 모드보다 키를 키우고 글자를 위쪽에 두었습니다.
  - 2D에서는 세운 배경이 옆면만 보이므로 숨깁니다.

### 결정 사항 반영

| 항목 | 구현 |
|---|---|
| 화면 비율 | `.arena` 크기 규칙(`clamp(520px, 62vw, 680px)`, 720px 이하 600px)을 그대로 유지 |
| 빛 번짐 | 구운 빛: 네온 `box-shadow`, 항상 켬. 강한 빛 번짐: 토글(기본 꺼짐). 켜면 `--glow` 값이 커지고 화면 위에 빛 막이 한 장 더 겹침. 3D 장면에 `filter`를 걸면 납작해지므로 쓰지 않음. three.js bloom만큼 자연스럽지는 않음 |
| 카드 디자인 | 지금 방 대전 카드 그대로 (흰 바탕·숫자 위·무늬 아래, 뒷면 보라 줄무늬 + "JP") |
| 의자·아바타·모델 | 없음 |

### 바꾼 파일 (모두 README의 UI 담당 범위 안)

| 파일 | 변경 |
|---|---|
| `src/poker/RoomApp.js` | 테이블 DOM 구조를 바꿈: `.scene` → `.table`, 그 안에 좌석·가운데·칩 이동. 그 밖의 변경: 3D 카드(`Card`), 칩 `--i`, 딜러 버튼, 2D/3D·빛 번짐 토글(`ViewToggles`), 상대 카드 key에서 값을 빼서 뒤집히게 함. 상태·동기화(`accept`, `pump`, `send`, 롱폴링)는 그대로 |
| `src/poker/roomLogic.js` | `VIEW_PREF`, `BLOOM_PREF`, `readPref`, `writePref` (저장소가 막혀도 기본값) |
| `src/styles/room.css` | 테이블 부분을 CSS 3D로 다시 작성. 버튼·로비·알림 규칙은 그대로 |
| `room.html` | CSS·JS 캐시 버전만 |
| `tests/room-logic.test.js` | 보기 설정 테스트 1개 추가 (8개) |

### 위험 목록(11절)은 어떻게 됐나

| 위험 | B안에서 |
|---|---|
| 1. 이름표 어긋남 | 이름표가 3D 평면 안에 세워져 있어서 좌석과 함께 움직임. 계산 코드 자체가 없음 |
| 2. 애니메이션 밀림 | 기존 재생 순서(`pump`)를 그대로 따름. CSS 전환은 새 상태가 오면 그 자리에서 이어서 바뀜 |
| 3. CDN 차단 | 외부 파일 없음 |
| 4. 캔버스 재생성 | 캔버스 없음. 모두 Mini React가 그리는 DOM |
| 5. WebGL 끊김 | WebGL 없음 |
| 6. 메모리·발열 | GPU 자원 직접 관리 없음. 가만히 있으면 브라우저가 다시 그리지 않음 |
| 7. 상대 카드 노출 | 값이 없으면 앞면 자리는 빈 카드. 서버 규칙 그대로 |
| 8. 프레임 예약 버려짐 | `requestAnimationFrame`을 쓰지 않음 |
| **새 위험 9. 3D 상자가 옆으로 스크롤됨** | 넓은 바닥·벽이 상자 밖으로 퍼져 있어서, 버튼 포커스 때 브라우저가 `.arena`를 365px 옆으로 스크롤했음. `overflow: clip`(스크롤 불가)로 해결하고 다시 확인 |
| **새 위험 10. 3D가 납작해짐** | `preserve-3d` 요소에 `opacity`·`filter`·`overflow`를 주면 3D가 사라짐. 이런 효과는 끝 요소(카드 면, 칩, HUD)에만 쓰고, 빛 번짐은 3D 장면 밖의 빛 막으로 처리함 |

### 확인한 것

| 항목 | 방법 | 결과 |
|---|---|---|
| 화면 로직 | `node tests/room-logic.test.js` | 8/8 통과 |
| 문법 | `node --check src/poker/RoomApp.js` | 통과 |
| 방 대전 | 두 게스트(`?guest=2`)로 방 생성·참가·준비·여러 핸드·쇼다운 | 내 카드는 아래·상대 카드는 위, 보드 5장, 칩 높이, 딜러 버튼 이동, 승자 강조 정상 |
| 상대 카드 뒤집기 | 쇼다운 직후 상대 카드 요소 | `is-down` → `is-up`(7♥ Q♠). 같은 요소가 뒤집힘 |
| 2D/3D·빛 번짐 | 버튼, 새로고침 후 선택 유지 | 정상 (`--tilt` 52° ↔ 0°) |
| 옆으로 밀림(위험 9) | 버튼 클릭 뒤 `.arena.scrollLeft` | 수정 전 365, 수정 후 0 |
| 휴대폰 폭 375px | 브라우저 크기 흉내 | 가로 스크롤 없음, 카드·HUD 읽힘 |

### 남은 한계

- **강한 빛 번짐:** 진짜 bloom처럼 번지지는 않습니다. 네온 그림자를 키우고 빛 막을 겹치는 근사입니다.
- **좁은 화면(720px 이하):** 좌석·팟 칩 탑을 숨깁니다. 좌석 칩은 원본부터 숨기던 규칙입니다. 금액은 숫자로 보입니다. 자세한 내용은 `ROOM_3D_CHANGES.md` 3.5절.
- **검토 반영 (2026-11-17):**
  - P1: 베팅 배지를 보드 밖 왼쪽으로 옮겼습니다.
  - P2: 720px 이하에서 내 이름표를 안쪽으로 옮겼습니다.
  - 데스크톱·375px × 3D·2D 네 경우에서 겹침과 잘림이 없는 것을 다시 확인했습니다.
- **곡면:** 테이블 두께와 칩 옆면은 근사입니다. 테이블 두께는 아래쪽 판 한 장, 칩은 원판을 겹쳐 쌓은 것입니다.
- **연습 모드(`poker.html`):** 담당 범위 밖이라 그대로입니다. 기존 CSS로 기울인 화면 그대로입니다.
- **확인하지 못한 환경:** Safari·Firefox, 실제 휴대폰, 서로 다른 두 컴퓨터.
  - `@property`, `overflow: clip`, 개별 `rotate` 속성은 최신 브라우저에서 지원합니다.
  - 오래된 브라우저에서는 각도 전환이 애니메이션 없이 바로 바뀔 수 있습니다.
- **개발 중 캐시:** `python -m http.server`는 캐시를 막지 않습니다. 코드를 고친 뒤에는 강력 새로고침이 필요할 수 있습니다.
- **three.js 버전(A안) 백업:** 저장소 밖 임시 폴더에만 있습니다. 재부팅하면 지워질 수 있습니다.
