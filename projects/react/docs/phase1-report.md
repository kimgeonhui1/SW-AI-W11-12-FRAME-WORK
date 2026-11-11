# Phase 1 보고서 — Virtual DOM / Diff / Patch / State History

> 작성일: 2026-11-06 · 범위: `projects/react` Phase 1 (`index.html`)
> 기획서: [`phase1-plan.md`](./phase1-plan.md)
> 제약 준수: HTML · CSS · JavaScript만 사용. 외부 라이브러리 · CDN · npm · 번들러 없음.

---

## 1. 요약

- 실제 영역의 HTML을 Virtual DOM으로 바꾸고, 테스트 영역에서 고친 내용을 **Diff → Patch**로 **바뀐 노드만** 실제 영역에 반영하는 페이지를 완성했다.
- 모든 상태는 **State History**에 저장되며 뒤로가기 · 앞으로가기 · 목록 클릭으로 이동할 수 있다. 이동할 때도 실제 영역은 Diff/Patch로만 바뀐다.
- (2026-11-09 기준 Phase 1 테스트는 477개, Phase 2 포함 전체 722개 전부 통과 — [test-list.md](./test-list.md))
- 브라우저 테스트 **320개 전부 통과** — 테스트 항목 #001~#315 중 279개 + 잘못된 입력 테스트 36개 + 최적화 테스트 5개 (무작위 왕복 검증, 1,000단계 중첩, 보안 문자열, `index.html` iframe 통합 테스트 포함). 코드 정리 때 겹치던 기본 테스트 58개, 깊은 트리 테스트, 대량 · 무작위 변형 · 유니코드 항목 36개를 뺐다 (6.1 · 6.2 · 6.4절).
- 트리를 따라 내려가는 함수는 **평범한 재귀**로 짰다. 깊이 약 5,000단계가 넘는 트리는 브라우저 호출 스택 한도에 걸리지만, 화면에서 다루는 트리보다 훨씬 깊어서 코드를 짧게 두는 쪽을 택했다 (6.4절).
- `diff`는 잘못된 VNode를 `TypeError`로 거부하고, `patch`는 대상을 못 찾거나 새 노드를 만들 수 없으면 **실제 DOM을 전혀 바꾸지 않는다** (6.5절).
- 315개 항목을 추가하면서 **버그 7가지를 찾아 고쳤다** (6.2절).
- 매 동작마다 "실제 영역을 다시 VDOM으로 바꾼 결과 = History의 현재 VDOM"인지 스스로 점검하고 상태 줄에 표시한다.

## 2. 요구사항별 구현 결과

| # | 요구사항 | 구현 | 결과 |
|---|---|---|---|
| R1 | 로드 시 실제 영역 HTML → VDOM | `main.js` `init()` → `containerToVdom(#real-area)` | ✅ 들여쓴 샘플 HTML이 공백 노드 없이 변환됨 |
| R2 | VDOM으로 테스트 영역 렌더링 | `renderTestArea()` → `createElement` | ✅ 두 영역의 VDOM이 같음을 확인 |
| R3 | 테스트 영역 자유 편집 | `#test-area` `contenteditable` + `#test-source` 소스 편집기 (양방향 동기화) | ✅ 글자 수정은 미리보기, 태그 · 속성 · 구조 수정은 소스 편집기 |
| R4 | Patch → 테스트 영역 다시 VDOM으로 | `onPatch()` → `containerToVdom(#test-area)` | ✅ |
| R5 | 이전 VDOM과 Diff | `diff(history.current(), 새 VDOM)` | ✅ 패치 종류 5가지 (CREATE / REMOVE / REPLACE / TEXT / PROPS) |
| R6 | 바뀐 부분만 실제 영역에 반영 | `patch(#real-area, patches)` | ✅ 텍스트 · 같은 태그 요소는 재사용, 바뀐 노드는 `Element.animate()`로 강조 |
| R7 | 새 VDOM을 History에 저장 | `history.push(vdom, { patchCount, label })` | ✅ 패치가 0개면 "변경 없음" 안내 후 저장하지 않음 |
| R8 | 뒤로가기 / 앞으로가기 / 특정 시점 이동 | `moveTo()` → `undo` / `redo` / `go(i)` | ✅ 실제 영역은 Diff/Patch, 테스트 영역은 통째로 다시 그림. 버튼은 `canUndo` / `canRedo`에 따라 켜고 끔 |

부가 화면: 현재 위치(`현재 위치: 3 / 5`), State History 목록(클릭 이동, 패치 수 · 시각 표시), 마지막 Diff 결과(패치 종류별 색 배지), 현재 VDOM JSON(`<details>`로 접기/펼치기), 라이트/다크 모드, 좁은 화면에서 한 칸 배치.

## 3. 구조

```
projects/react/
├── index.html                 Phase 1 페이지 (실제 영역 샘플 HTML 포함)
├── src/
│   ├── core/                  ← 팀 공통 (파일 · 함수 이름 유지)
│   │   ├── vdom.js            h, domToVdom, createElement
│   │   │                      + isIgnorableNode, vdomChildNodes, containerToVdom, setProp, isElementVNode
│   │   ├── diff.js            diff + PATCH
│   │   └── patch.js           patch
│   ├── phase1/
│   │   ├── history.js         push, undo, redo + go, current, peek, canUndo, canRedo, position, entries, reset
│   │   └── main.js            화면 조립 · 이벤트 연결 + toHtml, escapeText, escapeAttr, VOID_TAGS (소스 편집기용)
│   └── styles/style.css       레이아웃 · 라이트/다크 테마
├── tests/
│   ├── index.html             브라우저 테스트 페이지 (아래 테스트 파일을 모두 불러와 실행)
│   ├── runner.js              직접 만든 테스트 러너 (describe / test / assert / assertEqual / run)
│   ├── helpers.js             테스트 공용 도우미 (render, roundTrip, 무작위 생성기, iframe 열기 …)
│   ├── cases-vdom.test.js         #001~#080  h · DOM→VDOM · VDOM→DOM
│   ├── cases-diff-patch.test.js   #081~#170  Diff · Patch · Props
│   ├── cases-history-html.test.js #171~#230  History · Serialize(toHtml)
│   ├── cases-page.test.js         #231~#255  페이지 초기화 · 이벤트 (iframe)
│   ├── cases-random.test.js       #256~#290  랜덤 · 통합 · 대량
│   ├── cases-security.test.js     #291~#315  안정성 · 보안
│   └── cases-invalid.test.js      잘못된 VNode · Patch 입력 (6.5절)
└── docs/
    ├── phase1-plan.md         기획서
    └── phase1-report.md       이 문서
```

> **Patch 테스트 위치**: `patch()`는 `diff()` 결과와 짝으로 검사하는 경우가 많아 별도 `patch.test.js` 없이 아래에 있다.
> - `cases-diff-patch.test.js`의 `Patch` 묶음(#116~#145) — Patch만 따로 보는 항목
> - `cases-random.test.js`(#256~#290) — `patch(box, diff(a, b))` 결과를 다시 VDOM으로 바꿔 B와 비교하는 무작위 검증
> - `cases-invalid.test.js` — 잘못된 패치가 들어오면 DOM을 전혀 바꾸지 않는지

### 3.1 공개 함수 목록 (기획서 6장과 같음)

`(추가)` = 팀 공통 이름 외에 이번 구현에서 더 export 한 것.

| 파일 | 함수 · 상수 | 설명 |
|---|---|---|
| `core/vdom.js` | `h(type, props, ...children)` | VNode 생성 헬퍼. `props`가 `null`이어도 `{}`, 중첩 배열 평탄화, `null/false/true` 제거, 숫자 → 문자열 |
| | `domToVdom(node)` | 실제 DOM 노드 → VNode |
| | `createElement(vnode)` | VNode → 실제 DOM 노드 |
| | (추가) `isIgnorableNode(node)` | VDOM에서 무시할 DOM 노드인지 판단 (주석, 줄바꿈이 들어 있는 공백만으로 된 텍스트) |
| | (추가) `vdomChildNodes(el)` | VNode로 변환될 자식 DOM 노드만 반환 |
| | (추가) `containerToVdom(el)` | 영역 내용을 `{type:"div", props:{}, children}` 루트로 감싸 반환 |
| | (추가) `setProp(el, name, value)` | 속성 하나 설정 (`createElement` · `patch` 공용). 쓸 수 없는 이름은 경고 후 건너뛰고 `false` |
| | (추가) `isElementVNode(value)` | 요소 VNode 모양인지 검사 (노드 하나만) |
| | (추가) `validateVNode(vnode, where?)` | VNode 트리 전체 검사 (props · children 모양, 속성값 종류). 잘못되면 `TypeError` |
| | (추가) `checkProps(props, where)` | props 객체 검사 (`validateVNode` · `patch` 공용) |
| `core/diff.js` | `diff(oldVNode, newVNode)` | 패치 목록 반환. 두 트리 중 하나라도 잘못된 VNode면 `TypeError` |
| | (추가) `PATCH` | 패치 종류 이름 상수 (`CREATE` / `REMOVE` / `REPLACE` / `TEXT` / `PROPS`) |
| `core/patch.js` | `patch(container, patches)` | 패치 적용, 바뀐 DOM 노드 목록 반환. 잘못된 패치 · 없는 경로 · 대상 종류 불일치가 하나라도 있으면 DOM을 건드리지 않고 `TypeError` |
| `phase1/history.js` | `push(vdom, meta?)` | 새 기록 추가 (앞쪽 기록 삭제, 깊은 복사). `meta = { patchCount, label }` |
| | `undo()` / `redo()` | 한 칸 이동 후 VNode 복사본 반환, 못 가면 `null` |
| | (추가) `go(i)` | `i`번 기록으로 이동, 범위 밖이면 `null` |
| | (추가) `current()` | 현재 VNode 복사본 |
| | (추가) `canUndo()` / `canRedo()` | 이동 가능 여부 |
| | (추가) `position()` | `{ index, length }` |
| | (추가) `entries()` | VDOM을 뺀 기록 목록 `{ time, patchCount, label }[]` |
| | (추가) `reset()` | 모든 기록 삭제 (테스트용) |
| `phase1/main.js` | `toHtml(nodes, depth?)` | VNode 배열 → 들여쓴 HTML |
| | `REQUIRED_IDS` | 화면 동작에 꼭 필요한 요소 id 12개 |
| | `checkRequiredElements(root?)` | 필수 요소 검사 → `ready` / `partial` / `none` |
| | `escapeText(text)` | 텍스트의 `& < >` 를 엔티티로, ` ` 를 `&nbsp;` 로 |
| | `escapeAttr(value)` | 속성값의 `& "` 를 엔티티로, ` ` 를 `&nbsp;` 로 |
| | `VOID_TAGS` | 닫는 태그가 없는 요소 이름 집합 |

## 4. 데이터 흐름

```
[로드]    #real-area ──containerToVdom──▶ V0 ──createElement──▶ #test-area
                                            └─▶ history.push(V0, "초기 상태")

[편집]    #test-area (contenteditable) ──input──▶ toHtml(containerToVdom) ──▶ #test-source
          #test-source (textarea)      ──input──▶ innerHTML               ──▶ #test-area

[Patch]   Vn = containerToVdom(#test-area)
          patches = diff(history.current(), Vn)
          patches 없음 → "변경 없음"
          patches 있음 → patch(#real-area, patches) → 강조 → history.push(Vn)

[이동]    prev = history.current();  target = undo() | redo() | go(i)
          patch(#real-area, diff(prev, target))   ← 실제 영역: 바뀐 부분만
          #test-area = createElement(target)       ← 편집 영역: 통째로
```

## 5. 핵심 설계 결정

### 5.1 경로 기반 패치 + "대상 먼저 찾고 나중에 적용"

- 패치는 노드 위치를 **경로(path)** = 루트부터의 자식 인덱스 배열로 가진다. 경로는 항상 **변경 전 트리** 기준이다.
- `patch()`는 DOM을 건드리기 전에 모든 패치를 검사하고, 대상 노드를 모두 찾아 두고, 새로 넣을 DOM도 미리 만든 다음에 적용한다. 그래서 입력 오류가 있으면 실제 DOM은 그대로다(6.5절).
  예를 들어 자식 4개 중 뒤의 3개를 지울 때, 하나씩 지우면서 인덱스로 찾으면 두 번째부터 엉뚱한 노드를 찾는다. 노드 참조를 미리 잡아 두면 인덱스가 밀려도 문제가 없다.
- `CREATE`는 부모 경로와 넣을 위치(index)를 가진다. 인덱스 기준 비교에서는 한 부모에 CREATE와 REMOVE가 같이 생기지 않고, CREATE는 인덱스 오름차순으로 나오므로 부모 끝에 차례로 붙이면 된다.

### 5.2 공백 규칙

- **줄바꿈이 들어 있는 공백만으로 된 텍스트 노드**(= HTML 들여쓰기)는 VDOM에서 뺀다. `<b>a</b> <i>b</i>` 사이 공백처럼 줄바꿈이 없는 공백은 화면에 보이므로 남긴다.
- 이 판단은 `isIgnorableNode` 하나로만 하고, `domToVdom`(VDOM 만들 때)과 `patch`의 경로 찾기(`vdomChildNodes`)가 **같은 함수**를 쓴다. 그래서 들여쓰기가 남아 있는 실제 영역에서도 "DOM의 n번째 자식"과 "VNode의 n번째 자식"이 항상 같은 노드다.
- `main.js`의 `toHtml`은 이 규칙에 맞춰 **형제가 모두 요소일 때만** 줄을 바꾸고 들여쓴다. 텍스트가 섞여 있으면 한 줄로 쓴다. 그래서 소스 편집기 내용을 다시 파싱해도 VDOM이 그대로다(편집하지 않았는데 Diff가 생기는 일이 없다). `<pre>` · `<textarea>`는 파서가 여는 태그 뒤 첫 줄바꿈을 지우므로 **안쪽 전체를** 항상 한 줄로 쓴다.
- 예외: `<pre>` · `<textarea>` · `<listing>` **안의** 공백은 줄바꿈이 있어도 빼지 않는다. 그 안에서는 빈 줄도 화면에 보이는 내용이기 때문이다(테스트 #048 · #049에서 발견해 수정).

### 5.3 컨테이너는 가상 루트

- `#real-area`와 `#test-area`는 id · class · contenteditable 속성이 서로 다르다. 컨테이너 자체를 비교하면 의미 없는 PROPS 패치가 생긴다.
- `containerToVdom`은 컨테이너를 속성 없는 `{ type: "div", props: {}, children }`으로 감싸고, **내용만** 비교 대상으로 삼는다. `patch(container, ...)`도 이 루트를 컨테이너 요소에 대응시킨다.

### 5.4 실제 영역에는 흔적을 남기지 않는다

- 강조 효과를 클래스로 붙였다 떼면, 그 사이에 Patch하거나 실제 영역을 다시 VDOM으로 바꿀 때 클래스가 섞여 들어간다.
- 그래서 `Element.animate()`만 쓴다. 애니메이션은 속성을 남기지 않는다. 텍스트 노드는 스타일을 줄 수 없으므로 부모 요소를 강조한다.
- 로그 · History 목록 등 사용자 입력이 들어가는 화면 문자열은 모두 `textContent`로 넣는다.

### 5.5 History는 깊은 복사

- `push`할 때와 `current/undo/redo/go`로 꺼낼 때 모두 깊은 복사를 한다. 바깥에서 VNode를 고쳐도 과거 기록이 바뀌지 않는다.
- 복사는 `structuredClone`으로 한다. 함수 · Symbol이 든 VDOM은 `DataCloneError`로 저장을 거부하고, History는 그대로 남는다(#308). 한때 깊은 트리를 버티려고 복사 함수를 직접 만들었지만, 코드 정리 때 재귀 방식으로 돌아가면서(6.4절) 다시 `structuredClone` 한 줄로 바꿨다.
- 뒤로 간 상태에서 `push`하면 앞쪽 기록을 버린다(브라우저 히스토리와 같은 분기 방식).
- `peek()`은 복사하지 않고 현재 기록을 그대로 돌려주는 **읽기 전용** 함수다. `main.js`는 diff 비교 · JSON 보기 · 자가 점검처럼 읽기만 하는 곳에서 `peek()`을 쓴다(5.6절).

### 5.6 최적화 (코드 정리 뒤 추가)

| 무엇이 느렸나 | 고친 방법 | 효과 |
|---|---|---|
| `patch`가 패치마다 루트부터 내려가며 형제 목록(`vdomChildNodes`)을 새로 만들었다 → 패치 수 × 깊이 × 형제 수 | 한 번의 `patch` 동안 "노드 → 자식 목록"을 `Map`에 기억해 재사용 (1단계는 DOM을 바꾸지 않으므로 목록이 계속 맞다) | li 3,000개 목록에 패치 1,500개: 경로 찾기 **약 1,170ms → 약 6ms** (Chrome에서 측정) |
| 버튼 한 번에 `history.current()`가 VDOM 전체를 3~4번 깊은 복사했다 (li 3,000개 트리 한 번 복사에 약 5ms) | 읽기만 하는 곳은 `peek()` 사용. 복사는 `push`할 때와 이동 대상(`undo` · `redo` · `go`)을 꺼낼 때만 | 버튼 한 번당 복사 3~4번 → 0~1번 |
| `diff`가 매번 이전 VDOM까지 트리 전체를 검사했다 | `diff(old, new, { trustOld: true })` — 이미 검사를 통과한 이전 VDOM이면 검사를 건너뛴다. History의 VDOM은 저장될 때 검사를 통과했으므로 `main.js`가 이 옵션을 쓴다 | diff 한 번당 트리 순회 1번 감소 |

## 6. 테스트 결과

`python3 -m http.server`로 `projects/react`를 띄우고 `tests/index.html`을 브라우저(데스크톱 앱 내장 브라우저, Chromium 계열)에서 실행했다.

**결과: 전체 320개 · 통과 320개 · 실패 0개** (6.5절 잘못된 입력 테스트, 5.6절 최적화 테스트 포함)

| 브라우저 | 결과 | 비고 |
|---|---|---|
| Chrome (데스크톱 앱 내장 브라우저, Chromium 계열) | 320 / 320 | 최적화 뒤 다시 실행 (Phase 2 포함 전체 422개 약 9초) |
| Firefox 159 (headless) · Safari 27 | 498 / 498 | 코드 정리 **전** 기준. 정리 뒤에는 다시 돌리지 않았다 |

시간은 대부분 iframe으로 페이지를 여는 #231~#255와 대량 입력 테스트가 차지한다.

### 6.1 기본 테스트 (코드 정리 때 삭제)

처음에는 기본 테스트 58개를 6개 파일(`vdom` · `diff` · `history` · `main` · `random` · `page`.test.js)에 따로 두었다. 이후 같은 내용을 #001~#315 항목이 더 자세히 다시 검사하게 되어, 코드 정리 때 지웠다.

| 예전 파일 | 지금 맡는 항목 |
|---|---|
| `vdom.test.js` (h · domToVdom · createElement) | #001~#080 (`cases-vdom.test.js`) |
| `diff.test.js` (패치 종류 · patch 적용) | #081~#170 (`cases-diff-patch.test.js`) |
| `history.test.js` · `main.test.js` (History · toHtml) | #171~#230 (`cases-history-html.test.js`) |
| `page.test.js` (시작 조건 · iframe 통합) | #231~#255 (`cases-page.test.js`) |
| `random.test.js` (무작위 왕복) | #256~#290 (`cases-random.test.js`) |

**자동 테스트가 확인하지 못하는 것** — 사람이 키보드로 미리보기(contenteditable)에 직접 입력하는 동작(브라우저마다 생기는 `<div>`/`<br>`가 다름), 강조 애니메이션이 실제로 보이는지, 레이아웃 · 다크 모드 · 좁은 화면. 그래서 아래 수동 확인을 함께 했다. 또 `tests/index.html`은 테스트 파일을 `import` 목록으로 직접 불러오므로, 새 `*.test.js`를 만들면 이 목록에 추가해야 실행된다(당시 10개, 2026-11-10 기준 Phase 1 · 2 합쳐 12개 파일 모두 등록 확인).

통합 테스트를 처음 돌렸을 때 1건이 실패했는데, 테스트가 두 영역을 `textContent`로 비교해서였다. 실제 영역에는 HTML 들여쓰기 공백이 남아 있지만 VDOM은 이를 무시하므로(5.2 공백 규칙) 비교 기준이 잘못된 것이다. → `containerToVdom` 결과끼리 비교하도록 테스트를 고쳤다.

처음 실행 때 무작위 검증 3건이 실패했는데, 모두 **테스트 생성기 쪽 문제**였다(핵심 코드는 수정하지 않음).
1. 변형기가 루트 VNode의 props를 바꿨다. 루트는 컨테이너라서 `containerToVdom`이 일부러 속성을 무시하므로 생길 수 없는 입력이다. → 루트는 props를 바꾸지 않게 수정.
2. HTML 렌더링 모드에서 최상위에 텍스트가 섞여 있는데도 앞뒤에 줄바꿈을 붙여 텍스트 내용이 바뀌었다. → 최상위가 모두 요소일 때만 줄바꿈을 붙이게 수정.
3. 또 HTML 파서는 `<p>` 안의 블록 요소, `<li>` 안의 `<li>`를 만나면 태그를 자동으로 닫아 트리 모양을 바꾼다. HTML 문법상 불가능한 트리이므로 `innerHTML` 모드에서는 `p` · `li`를 생성 태그에서 뺐다(`createElement` 모드에서는 그대로 사용).

### 6.2 테스트 항목 #001~#315 (315개)

요청받은 315개 항목을 **번호 그대로** 테스트 이름에 붙였다(예: `#137 잘못된 패치 종류 → TypeError …`). 테스트 페이지에서 번호로 찾을 수 있다.

| 범위 | 파일 | 개수 | 주요 확인 내용 |
|---|---|---|---|
| #001~#030 VDOM 생성 · 정규화 | `cases-vdom.test.js` | 30 | `null`/`undefined`/불리언 제거, `0` · 음수 · 소수 · `NaN` · `Infinity` → 문자열, 다단계 중첩 배열 평탄화, `props` `null`/`undefined` → `{}`, 1,000단계 중첩, 같은 객체 재사용 |
| #031~#060 DOM → VDOM | `cases-vdom.test.js` | 30 | 빈 요소 · 빈/연속 텍스트, 주석 무시, 공백 규칙(줄바꿈 · 탭 · 공백 · NBSP 조합), `<pre>`/`<textarea>`, 대문자 태그, `data-*`/`aria-*`/불리언 속성, Entity, SVG, 잘못된 HTML |
| #061~#080 VDOM → DOM | `cases-vdom.test.js` | 20 | 텍스트 · 숫자, 깊은 중첩, `className`/`style`/불리언/`null` 속성, 쓸 수 없는 속성명, void element, 잘못된 VNode |
| #081~#115 Diff | `cases-diff-patch.test.js` | 35 | 루트 교체, 텍스트 ↔ 요소, 빈 트리, 추가 · 삭제(처음 · 중간 · 끝 · 연속 · 교차), 삽입, 순서 변경, 속성 추가 · 삭제 · 변경, 1,000단계 깊이, 형제 5,000개 |
| #116~#145 Patch | `cases-diff-patch.test.js` | 30 | 5종 패치 적용, 빈 배열, 같은 패치 반복, 연속 CREATE/REMOVE/REPLACE, 없는 경로 · 범위 밖 · 빈 경로, 잘못된 종류 · 대상 없는 패치 · 잘못된 노드, 노드 재사용 · 삭제 확인, 2,000개 패치 |
| #146~#170 Props | `cases-diff-patch.test.js` | 25 | `id`/`class`/`title`/`style`/`data-*`/`aria-*`, 불리언 · 빈 속성, 특수문자 · 따옴표 · 역슬래시, 대소문자만 다른 이름, `value`/`checked`/`selected`/`disabled`, 이벤트 핸들러 문자열 |
| #171~#200 History | `cases-history-html.test.js` | 30 | 빈 History, 경계에서 Undo/Redo, 분기, 중복 저장, 깊은 복사, 잘못된 `go()` 인자(음수 · 소수 · 문자열), `reset()`, 잘못된 메타데이터, 10,000 · 20,000개 저장 |
| #201~#230 Serialize | `cases-history-html.test.js` | 30 | 특수문자 이스케이프(`& < > " '`), 빈/불리언 속성, void element, 들여쓰기 규칙, 줄바꿈 · 탭 · NBSP, `<pre>`/`<textarea>`, `null` props, 200,000자 |
| #231~#255 페이지 · 이벤트 | `cases-page.test.js` | 25 | 필수 요소 하나씩 빠진 페이지 6종, 빠른 연속 클릭, Patch 직후 Undo, 빈/잘못된 소스, 저장 안 한 편집 후 이동, 양방향 동기화 반복, 요소 교체 · 제거, 새로고침, `window.history` 미사용, 콘솔 오류 없음 |
| #256~#290 랜덤 · 대량 | `cases-random.test.js` | 13 | 시드 고정 무작위 트리로 빈 트리 · 속성 · 텍스트 · 추가 · 삭제 · 교체 · 순서 변경 왕복, 연속 Patch 50번, 무작위 Undo/Redo, 직렬화 · Diff/Patch · History 왕복, 1,000단계 중첩. (정리 때 22개 삭제: #257~#259 · #266~#271 · #274 · #275 · #277 · #278 · #281~#286 · #288~#290 — 같은 왕복을 다른 모양으로 반복하거나 대량 · 성능만 보던 항목) |
| #291~#315 안정성 · 보안 | `cases-security.test.js` | 11 | `<script>`/`onerror`/`onclick`/`javascript:` 문자열 이스케이프, 이중 이스케이프, 직렬화 안정성, 순환 참조, 복사 불가 값, `toString` · `__proto__` 이름, 예외 뒤 History 일관성. (정리 때 14개 삭제: #295 · #296 · #299~#306 · #309 · #312~#314 — `<iframe>`/`<img>` 이스케이프는 #291과 같고, 유니코드 문자열은 그대로 통과만 하며, `constructor`/`prototype`은 #310과 같은 검사) |

#### 315개 항목으로 찾아서 고친 버그

처음 실행에서 373개 중 23개가 실패했다. 6개는 테스트 생성기가 루트(컨테이너) 속성까지 바꾼 **테스트 쪽 실수**였고(생성기 수정), 나머지 17개는 아래 **코드 버그 7가지**였다. 고친 뒤 373개 모두 통과.

| # | 버그 | 드러난 항목 | 고친 곳 |
|---|---|---|---|
| 1 | `<pre>` · `<textarea>` 안의 "줄바꿈만 있는 텍스트"(빈 줄)를 들여쓰기로 보고 지움 | #048 · #049 · #224 | `vdom.js` `isIgnorableNode`가 `pre/textarea/listing` 안이면 유지. `main.js` `toHtml`은 `<pre>` 안쪽 전체를 한 줄로 |
| 2 | `setAttribute`가 거부하는 속성명(예: 공백 포함)이 있으면 예외 → Patch가 중간에 멈춰 실제 영역이 반쯤만 바뀜 | #074 | `setProp`이 그 속성만 경고 후 건너뜀 |
| 3 | 잘못된 VNode(`true`, `{}` 등)를 넣으면 `<undefined>` 같은 엉뚱한 요소가 조용히 생김 | #080 | `createElement`가 `TypeError` |
| 4 | 잘못된 패치(모르는 종류, 대상 없는 경로, VNode가 아닌 node)를 앞의 패치를 적용한 뒤에야 발견 → 반쯤 적용 | #137 · #138 · #139 | `patch`가 대상 찾기 · 새 노드 만들기를 먼저 끝내고, 하나라도 실패하면 DOM을 건드리지 않고 `TypeError` |
| 5 | 대소문자만 다른 속성(`title` → `Title`)을 바꾸면 속성이 사라짐 (설정 후 삭제 순서) | #159 | `PROPS`를 삭제 → 설정 순서로 |
| 6 | `toString` · `constructor`처럼 `Object.prototype`에 있는 이름의 속성을 지우지 못하고, `__proto__` 속성은 읽거나 설정할 때 사라짐 | #310 · #311 | `diff`는 `Object.hasOwn` · `defineProperty`, `domToVdom`은 `Object.fromEntries` |
| 7 | `history.push`가 앞으로가기 기록을 먼저 버린 뒤 복사 → 복사 실패(함수 · Symbol이 든 VDOM)나 `meta = null`이면 예외가 나면서 Redo 기록까지 잃음 | #196 · #315 | 새 기록을 먼저 만들고 성공했을 때만 기록을 자름. 잘못된 `meta`는 기본값으로 |
| + | `toHtml`이 불리언 · `null` 속성을 `disabled="true"`, `hidden="null"`로 출력하고, `props: null`이면 예외 | #213 · #227 | `setProp`과 같은 규칙으로 출력 (`true` → 이름만, `null`/`false` → 생략) |

#### 검사는 했지만 "현재 동작"으로 정한 것 (고치지 않음)

- **#069** `className`은 `class`가 되지 않는다 — HTML 속성 이름을 그대로 쓰는 것이 팀 공통 VNode 형식이다.
- **#079 · #215** void element(`br` 등)에 자식을 주면 DOM에는 붙지만 HTML로는 표현되지 않는다.
- **#122** 같은 패치 목록을 두 번 적용하면 `REMOVE`가 다른 노드를 지운다 — 패치는 "변경 전 트리" 기준이라 한 번만 적용해야 한다.
- **#136** 빈 경로 `[]`는 컨테이너 자신이다. `PROPS`는 허용하지만 `REMOVE` · `REPLACE`는 거부한다(6.5절).
- 처음에 "현재 동작"으로 정했던 **#082**(경로 `[]`의 `REPLACE`가 컨테이너를 통째로 바꿈), **#133** · **#135**(없는 경로는 경고 후 건너뜀)는 6.5절 작업에서 `TypeError`로 바꿨다.
- **#134** 범위를 넘는 `CREATE` index는 검사하지 않고 끝에 붙인다. 한때 `TypeError`로 막았지만, `diff`는 항상 차례대로 된 index를 내보내므로 코드 정리 때 그 검사를 뺐다.
- **#168 · #169 · #294** `onerror` · `onclick` 속성 문자열과 `javascript:` URL은 막지 않고 그대로 설정된다(7장 한계 4번).
- **#198** History 크기 제한이 없다(20,000개까지 확인).
- **#229** `toHtml`은 태그 이름을 검사하지 않는다(`createElement`는 DOMException).
- **#251** 초기화 뒤 테스트 영역 요소를 통째로 바꾸면 `main.js`는 예전 요소를 계속 본다(오류는 없음).
- **#307** 순환 참조 VDOM은 재귀가 호출 스택 한도에 걸려 오류로 끝난다(무한 루프는 없음). 오류 종류는 브라우저마다 다르다(Chrome `RangeError`, Firefox `InternalError`). 한때 조상 목록으로 직접 찾아 `TypeError`로 통일했지만 코드 정리 때 그 검사를 뺐다. 같은 객체를 형제 자리에 두 번 쓰는 공유는 허용한다.

### 6.3 수동 확인 (`index.html`)

| 동작 | 확인 내용 |
|---|---|
| 미리보기에서 제목 끝에 " v2" 입력 → Patch | 소스 편집기 즉시 갱신. 패치 1개 `TEXT [0,0,0]`. 실제 영역 제목만 바뀌고 강조됨 |
| 소스 편집기에서 `data-count`, `data-done` 변경 → Patch | `PROPS` 2개. 기존 `<li>` 요소가 그대로 재사용됨(같은 노드 참조) |
| `<li>` 하나 추가 → Patch | `CREATE` 1개 |
| `p.note` 삭제 → Patch | `REMOVE` 1개 |
| `<h2>` → `<h3>` → Patch | `REPLACE` 1개 |
| 아무것도 안 바꾸고 Patch | "변경 없음", History 개수 그대로(6) |
| 뒤로가기 ×2, 앞으로가기 | 각각 패치 1개로 이동, 위치 표시 · 버튼 활성 상태 정상 |
| History 1번 클릭 / 6번 클릭 | 패치 5개 / 6개로 한 번에 이동, 뒤로가기 버튼 꺼짐(1번) |
| 2번으로 간 뒤 새 Patch | 앞쪽 기록 삭제, 목록 3개로 줄어듦(분기) |
| 모든 동작 후 | 상태 줄 "실제 영역이 VDOM과 일치합니다", 테스트 영역 VDOM = 실제 영역 VDOM, JSON 보기 일치 |
| 375px 폭 | 한 칸으로 쌓이고 가로 스크롤 없음 |
| 콘솔 | `index.html`에서 오류 · 경고 없음 |

### 6.4 깊은 트리 — 명시적 스택을 썼다가 재귀로 되돌림

**처음 문제**: 정상 트리도 깊이 약 5,000단계부터 호출 스택이 넘쳐 멈췄다 (Chrome `RangeError: Maximum call stack size exceeded`, Firefox `InternalError: too much recursion`). 트리 깊이만큼 함수 호출이 쌓이는 재귀 함수가 원인이었다.

**한때 고친 방법**: `createElement` · `domToVdom` · `diff` · `validateVNode` · `toHtml` · History 깊은 복사를 모두 명시적 스택으로 바꾸고, 순환 참조도 조상 목록으로 직접 찾았다. 깊이 10,000 트리를 검사하는 `cases-deep.test.js`(30개)도 두었다.

**코드 정리 때 되돌린 이유**: 스택 버전은 재귀 버전보다 길고 읽기 어려웠다. 화면의 HTML 파서도 일정 깊이(Chrome 512단계)보다 깊은 태그는 형제로 바꿔 버리므로, 페이지에서 그렇게 깊은 트리가 생길 일이 없다. 그래서 다시 평범한 재귀로 짜고 `cases-deep.test.js`를 지웠다. 1,000단계 중첩은 #029 · #114 · #287이 여전히 검사한다.

### 6.5 잘못된 입력 검사 (`cases-invalid.test.js`, 36개)

**고치기 전에 확인한 문제** — 정상 `TEXT` 패치 하나 뒤에 잘못된 패치를 붙여 실제로 돌려 봤다.

| 입력 | 고치기 전 | 지금 |
|---|---|---|
| 없는 경로가 섞인 패치 목록 | 경고 후 그 패치만 건너뜀 → **앞의 TEXT는 적용됨** | `TypeError`, DOM 그대로 |
| 모르는 패치 종류 | 적용 중간에 오류 → **반쯤 적용** | `TypeError`, DOM 그대로 |
| `REPLACE` · `CREATE`의 node가 잘못됨 · 태그 이름에 공백 | 적용 중간에 오류 → **반쯤 적용** | `TypeError`, DOM 그대로 |
| `REMOVE` · `REPLACE`의 경로 `[]` | **컨테이너(실제 영역) 자체가 사라지거나 바뀜** | `TypeError`, DOM 그대로 |
| `diff`에 `null` · `undefined` | 브라우저 기본 오류 문구 (`Cannot read properties of null`) | `[diff …]`로 시작하는 `TypeError`, 위치 표시 |
| `diff`에 `{}` · 숫자 · `props: "x"` · `children: "abc"` 등 | 조용히 `REPLACE`의 node로 실리거나, 글자마다 속성 · 자식으로 비교됨 | `TypeError` |

**고친 방법**

- `vdom.js`에 `validateVNode`(트리 전체를 재귀로 검사, 공유 객체 허용)와 `checkProps`를 추가했다. 올바른 VNode는 문자열이거나, `type`이 비어 있지 않은 문자열이고 `props`가 없거나 평범한 객체(값은 문자열 · 숫자 · 불리언 · `null`), `children`이 없거나 배열인 요소다.
- `diff`는 시작할 때 두 트리를 `validateVNode`로 검사한다. `REPLACE` · `CREATE`로 통째로 넘어가는 하위 트리도 검사되므로, `diff`가 내놓는 패치의 node는 항상 올바르다.
- `patch`는 세 단계로 나눴다. **① 대상 찾기**(패치 종류가 맞는지, 경로가 있는지, `REMOVE` · `REPLACE`가 컨테이너 자신이 아닌지) → **② 새 DOM 미리 만들기** → **③ 적용**. ①~②에서 실패하면 `TypeError`이고, ③은 DOM을 바꾸는 일만 한다.
- 코드 정리 때 뺀 것: 한때 `patch` 앞에 "패치 모양 검사" 단계(필드 · 타입 · `CREATE` index · 대상 노드 종류 · 배열 빈 칸 등)를 두었지만, `diff`가 만든 패치는 항상 올바르므로 뺐다. 그래서 손으로 만든 이상한 패치(예: `value`가 없는 `TEXT`)는 그대로 적용될 수 있다.
- `main.js`는 `patch`가 실패하면 상태 줄에 "Patch 실패 — 실제 영역은 바뀌지 않았습니다"를 보여 주고 History에 저장하지 않는다. 뒤로가기 · 앞으로가기 중에 실패하면 History 위치도 원래대로 되돌린다.
- 그대로 둔 것: 쓸 수 없는 속성 이름(공백 포함 등)은 그 속성만 경고 후 건너뛴다(#074). 컨테이너(경로 `[]`)의 `PROPS`는 허용한다(#136).

**테스트** — 잘못된 패치는 정상 패치 다섯 종류(`TEXT` · `PROPS` · `CREATE` · `REMOVE` · `REPLACE`) **앞과 뒤**에 각각 붙여서 돌리고, HTML 문자열뿐 아니라 **모든 노드 객체가 같은 참조인지**, 컨테이너가 부모에서 떨어져 나가지 않았는지까지 확인한다.

- `diff`: 잘못된 값 17종 × (이전 · 새 · 자식 자리), 자식 배열 안의 잘못된 값과 위치 메시지, `REPLACE` · `CREATE`로 넘어갈 하위 트리 안쪽, 올바른 느슨한 입력과 공유 객체는 통과
- `patch`: 없는 경로 3종 × 다섯 종류, 모르는 종류, 잘못된 새 노드 3종 × (`CREATE` · `REPLACE`), 바깥에서 DOM이 바뀌어 경로가 어긋난 경우, 경고가 아닌 예외로 알리는지, 그대로 둔 동작 2개
- 정상 패치가 여전히 적용되는지
- 페이지(iframe): 실제 영역을 바깥에서 고친 뒤 Patch → 실패 안내, 실제 영역 · History 그대로 / 뒤로가기 실패 → History 위치 원래대로

## 7. 한계

1. **key 없는 인덱스 비교** — 자식을 앞쪽에 하나 끼워 넣으면 그 뒤의 형제가 모두 한 칸씩 밀려 "TEXT/PROPS/REPLACE 여러 개 + 맨 끝 CREATE"로 나온다. 결과 DOM은 정확하지만 최소 변경은 아니다. 이동 · 재정렬도 같은 문제가 있다.
2. **폼 상태는 VDOM에 없음** — `input`에 입력한 `value`, `checked` 같은 **프로퍼티** 상태는 HTML 속성이 아니라서 `domToVdom`이 읽지 않는다. Phase 1은 HTML 구조 비교만 다룬다.
3. **이벤트 props · SVG 미지원** — `onClick` 같은 함수 props, SVG 네임스페이스(`createElementNS`)는 처리하지 않는다.
4. **소스 편집기는 `innerHTML`로 반영** — 사용자가 입력한 HTML을 그대로 파싱하므로, 직접 `<img onerror=...>` 같은 것을 넣으면 실행될 수 있다(본인 화면에서만). 또 파서가 잘못된 중첩(`<p><div>` 등)을 자동 보정하므로 입력한 모양과 트리가 다를 수 있다.
5. **contenteditable의 브라우저별 차이** — Enter를 누를 때 `<div>`/`<br>` 중 무엇이 생기는지는 브라우저마다 다르다. Diff/Patch 자체에는 영향이 없다.
6. **Patch 전 편집 내용은 이동 시 버려짐** — 뒤로가기 등을 누르면 테스트 영역을 대상 상태로 다시 그리므로, Patch하지 않은 편집은 사라진다(의도된 동작).
7. **보안 검사는 텍스트까지만** — 텍스트로 들어온 `<script>` 등은 항상 이스케이프되지만(#291~#294), 속성으로 들어온 `onclick` · `onerror` 문자열과 `javascript:` URL은 그대로 설정된다(#168 · #169 · #294). 본인 화면에서 쓰는 학습용 도구라 막지 않았지만, 남이 쓴 HTML을 넣는 용도라면 `on*` 속성과 위험한 URL을 거르는 단계가 필요하다.
8. **History 크기 제한 없음** — 기록이 끝없이 쌓인다(#197 · #198에서 20,000개까지 확인). 오래 쓰면 메모리가 늘어나므로 최대 개수를 두는 것이 좋다.
9. **`main.js`의 책임이 큼** — `serialize.js`를 합치면서 `main.js` 한 파일이 ① VDOM → HTML 직렬화 ② 필수 요소 검사 · 초기화 ③ 이벤트 연결 ④ Patch · History 제어 ⑤ 화면 정보 갱신을 모두 맡는다(당시 약 270줄, 예시 버튼을 더한 지금은 약 580줄). 지금은 파일 안을 번호 붙은 구역으로 나눠 두었지만, Phase 2에서 기능이 늘면 직렬화(①)부터 별도 파일로 다시 나누는 것이 유지보수에 낫다.
10. **아주 깊은 트리** — 트리를 재귀로 내려가므로 깊이 약 5,000단계가 넘으면 호출 스택 한도에 걸려 오류가 난다(6.4절). 순환 참조 VDOM도 같은 오류로 끝난다(#307). 브라우저 HTML 파서는 일정 깊이(Chrome 512단계)보다 깊은 태그를 형제로 바꿔 버려서, 화면의 소스 편집기로는 그렇게 깊은 트리를 만들 수 없다. 또 요소만 이어진 사슬을 `toHtml`로 쓰면 줄마다 깊이만큼 들여쓰기가 붙어 크기가 깊이의 제곱에 비례한다.

## 8. 브라우저 배경 지식과 이 구현의 관계

### 8.1 Window와 Document

| | `window` | `document` |
|---|---|---|
| 무엇인가 | 브라우저 탭(창) 하나를 나타내는 **전역 객체**. 스크립트의 전역 범위 그 자체 | 그 창에 로드된 **HTML 문서의 DOM 트리** 진입점. `window.document`로 접근 |
| 주요 기능 | `setTimeout`, `requestAnimationFrame`, `location`, `history`(브라우저 방문 기록), `innerWidth`, `resize` · `load` 이벤트, `structuredClone` 같은 전역 함수 | `getElementById`, `createElement`, `createTextNode`, `querySelector`, `body` |
| 이 구현에서 | `history.js`의 `structuredClone`(깊은 복사)이 `window`의 전역 함수 | `vdom.js`의 `document.createElement` / `createTextNode`, `main.js`의 `document.getElementById` |

- **주의 — 이름이 같은 `history`**: `window.history`는 브라우저의 방문 기록(History API, `pushState` · `back`)이다. 이 프로젝트의 **State History**(`phase1/history.js`)는 그것과 관계없는, VDOM 스냅샷을 담는 자체 배열이다. `main.js`는 `import * as history from "./history.js"`로 불러오므로, 모듈 안에서 `history`는 우리 모듈을 가리키고 `window.history`를 가린다. URL이나 브라우저 뒤로가기 버튼과는 연동하지 않는다.
- `vdom.js`, `patch.js`는 `document`가 있어야 동작한다. 그래서 테스트도 Node.js가 아니라 브라우저(`tests/index.html`)에서 실행한다.

### 8.2 Reflow와 Repaint

브라우저는 DOM이 바뀌면 대략 다음 순서로 화면을 다시 만든다.

```
DOM/CSS 변경 → Style(스타일 계산) → Layout(=Reflow) → Paint(=Repaint) → Composite(합성)
```

| 단계 | 언제 일어나나 | 비용 |
|---|---|---|
| **Reflow (Layout)** | 노드 추가 · 삭제, 텍스트 변경, 크기 · 위치에 영향을 주는 속성(`width`, `font-size`, `class` 변경으로 인한 박스 크기 변화 등) | 가장 비쌈. 바뀐 요소뿐 아니라 부모 · 형제의 위치도 다시 계산할 수 있음 |
| **Repaint (Paint)** | 위치 · 크기는 그대로이고 색 · 배경 · 그림자만 바뀜 | 중간. 픽셀만 다시 그림 |
| **Composite** | `transform`, `opacity`만 바뀜 | 가장 쌈. GPU 레이어만 다시 합성 |

이 구현과의 관계:

- **바뀐 노드만 고친다** — `innerHTML`로 실제 영역 전체를 갈아 끼우면 모든 노드가 새로 생겨 영역 전체를 다시 Layout · Paint 한다. `patch()`는 바뀐 노드만 고치므로 다시 계산할 범위가 작고, 바뀌지 않은 노드(텍스트 선택, 포커스, 스크롤 위치 등)는 그대로 남는다.
- **쓰기를 한꺼번에 한다** — `patch()`는 모든 DOM 변경을 하나의 동기 루프에서 끝내고, 중간에 `offsetHeight` · `getBoundingClientRect()` 같은 **레이아웃 값을 읽지 않는다**. 브라우저는 변경을 모아 두었다가 다음 프레임에서 Layout · Paint를 **한 번만** 한다. 쓰기와 읽기를 번갈아 하면 읽을 때마다 강제로 Reflow가 일어난다(layout thrashing).
- `resolvePath`가 `childNodes`를 읽고, 자가 점검(`reportResult`)이 DOM 구조를 읽지만, 이는 트리 구조 읽기라 Layout을 일으키지 않는다.
- **강조 효과** — `Element.animate()`로 `backgroundColor` · `boxShadow`를 바꾸므로 애니메이션 동안 매 프레임 **Repaint**가 일어난다(Reflow는 없음). 더 가볍게 하려면 `opacity`나 `transform`만 쓰는 효과로 바꿀 수 있다.
- 참고: DOM 조작 자체가 느린 것이 아니라, **얼마나 많은 노드를 바꾸고 Reflow를 몇 번 일으키느냐**가 비용을 결정한다. Virtual DOM은 "최소한으로 바꾸기"를 자동으로 해 주는 도구이지, 손으로 최적화한 DOM 조작보다 항상 빠른 것은 아니다.

### 8.3 MutationObserver

- **무엇인가** — DOM이 바뀌는 것을 지켜보다가 알려 주는 브라우저 API. 감시 대상과 종류(`childList` 자식 추가 · 삭제, `attributes` 속성 변경, `characterData` 텍스트 변경, `subtree` 하위 전체)를 지정하면, 변경이 모인 뒤 **마이크로태스크**로 `MutationRecord` 목록을 콜백에 한꺼번에 넘긴다.

  ```js
  const observer = new MutationObserver((records) => console.log(records));
  observer.observe(realArea, { childList: true, attributes: true, characterData: true, subtree: true });
  ```

- **이 구현에서는 쓰지 않았다.** 이유:
  1. 요구사항이 "**Patch 버튼을 누르면** 테스트 영역을 다시 VDOM으로 만든다"이므로, 변경을 실시간으로 감지할 필요가 없다. 버튼을 누를 때 `containerToVdom(#test-area)`로 한 번 읽으면 된다.
  2. 미리보기 ↔ 소스 편집기 동기화에는 `input` 이벤트를 썼다. `input`은 **사용자가 편집했을 때만** 발생한다. MutationObserver는 프로그램이 바꾼 것(`renderTestArea`, `innerHTML` 대입)에도 반응하므로, 서로가 서로를 갱신하는 무한 루프를 막는 별도 플래그가 필요해진다.
- **쓸 수 있는 곳(확장 아이디어)** — `patch()` 중에 실제 영역을 관찰하면 "정말 바뀐 노드만 건드렸는지"를 기록으로 검증할 수 있다. 예를 들어 TEXT 패치 1개라면 `characterData` 레코드 1개만 나와야 한다.
- 실제 React도 MutationObserver로 변경을 감지하지 않는다. 상태 변경이 항상 `setState`를 거치므로 무엇이 바뀌었는지 이미 알고 있다.

### 8.4 Virtual DOM — 구조와 필요한 이유

**구조** — 실제 DOM 노드를 흉내 낸 평범한 자바스크립트 객체 트리다. 이 프로젝트의 형식(팀 공통):

```js
// <ul class="list"><li>우유</li></ul>
{ type: "ul", props: { class: "list" }, children: [
  { type: "li", props: {}, children: ["우유"] }   // 텍스트 노드는 그냥 문자열
] }
```

- 실제 DOM 노드는 속성 · 메서드 · 스타일 · 이벤트 등 수백 개의 프로퍼티를 가진 무거운 객체이고, 만들거나 읽기만 해도 브라우저 내부를 거친다. VNode는 `type` · `props` · `children` 세 칸뿐이라 만들고 버리고 비교하는 비용이 거의 없다.
- 이 구현에서 VDOM이 하는 일: 실제 DOM → VDOM(`domToVdom`), VDOM → 실제 DOM(`createElement`), VDOM 두 개 비교(`diff`), 차이를 실제 DOM에 반영(`patch`), 과거 화면 저장(`history` — VDOM 스냅샷).

**필요한 이유**

1. **바뀐 곳만 고치기 위해** — 상태가 바뀔 때마다 화면 전체를 `innerHTML`로 다시 만들면 모든 노드가 새로 생겨 Reflow · Repaint 범위가 커지고(8.2절), 입력 중인 글자 · 포커스 · 스크롤 위치도 사라진다. 가벼운 VDOM끼리 먼저 비교해서 실제 DOM에는 최소한의 변경만 보낸다.
2. **"화면 = 상태의 함수" 로 코드를 쓰기 위해** — 개발자는 "지금 상태라면 화면이 이래야 한다"만 선언하고(Phase 2의 컴포넌트), 무엇을 어떻게 바꿀지는 Diff가 계산한다. 직접 DOM을 하나하나 고치는 명령형 코드보다 실수가 적다.
3. **화면을 값으로 다루기 위해** — VDOM은 그냥 데이터라서 저장(State History), 비교, 복사, 테스트가 쉽다. 이 프로젝트의 Undo/Redo가 VDOM 스냅샷만으로 동작하는 이유다.
4. 주의: Virtual DOM이 "직접 DOM 조작보다 항상 빠르다"는 뜻은 아니다. 비교하는 비용이 추가로 들고, 손으로 딱 필요한 노드만 고치는 코드가 더 빠를 수 있다. 장점은 **선언형으로 쓰면서도 충분히 적은 변경**을 자동으로 얻는다는 것이다.

### 8.5 Diff — 최소 변경을 찾는 5가지 핵심 케이스와 실제 DOM 반영

두 트리를 같은 위치끼리 깊이 우선으로 비교하면서, 노드 쌍마다 아래 다섯 경우 중 하나로 판정한다 (`diff.js` `walk`).

| # | 케이스 | 판정 조건 | 패치 | 실제 DOM 반영 (`patch.js`) |
|---|---|---|---|---|
| 1 | **노드 추가** | 새 트리에만 그 자리의 자식이 있음 | `CREATE` (부모 경로 + index + 새 VNode) | `createElement(node)` → 부모에 `appendChild` |
| 2 | **노드 삭제** | 이전 트리에만 자식이 있음 (새 쪽이 `undefined`) | `REMOVE` (경로) | 대상 노드 `remove()` |
| 3 | **노드 교체** | 태그(`type`)가 다르거나 텍스트 ↔ 요소 | `REPLACE` (경로 + 새 VNode) — 하위 트리는 더 비교하지 않음 | `createElement(node)` → `replaceWith` |
| 4 | **텍스트 변경** | 둘 다 문자열인데 내용이 다름 | `TEXT` (경로 + 새 문자열) | 같은 Text 노드의 `nodeValue`만 바꿈 (노드 재사용) |
| 5 | **속성 변경** | 같은 태그인데 props가 다름 | `PROPS` (경로 + `set` · `remove`) | `setProp` / 속성 삭제 — 요소는 재사용 |

- 같은 태그이고 속성도 같으면 패치 없이 자식으로 내려간다. 바뀐 게 없으면 패치 0개.
- 왜 "같은 위치끼리만" 비교하나: 두 트리의 최소 편집 거리를 정확히 구하는 알고리즘은 O(n³)이라 쓸 수 없다. React와 같은 두 가지 가정 — ① 태그가 다르면 하위 트리도 다르다고 보고 통째로 교체 ② 같은 자리의 노드끼리 비교 — 으로 O(n)에 끝낸다. 대신 목록 맨 앞에 끼워 넣으면 뒤가 모두 밀려 바뀐 것으로 나온다(7장 1번, React는 `key`로 해결).
- 반영 순서: `patch`는 ① 모든 패치 검사 → ② 경로로 대상 노드를 **모두 먼저 찾고** → ③ 새 노드를 미리 만든 뒤 → ④ 한 번에 적용한다. 경로가 변경 전 트리 기준이라 앞의 삭제가 뒤의 인덱스를 밀어도 문제가 없고, 입력이 잘못되면 DOM은 그대로다(5.1절, 6.5절).

## 9. 실제 React와 비교

### 9.1 Diff 방식

| 항목 | 이 구현 | 실제 React (React 16 이후, Fiber) |
|---|---|---|
| 기본 휴리스틱 | 같은 위치끼리만 비교 O(n). 태그가 다르면 하위 트리 통째로 교체, 같으면 속성만 갱신 후 자식으로 | **같음.** React 문서의 재조정(reconciliation) 규칙도 "type이 다르면 버리고 새로 만든다, 같은 DOM type이면 바뀐 속성만 갱신"이다 |
| 자식 짝짓기 | 인덱스 기준만 | `key`가 있으면 key로 짝을 짓고 이동(move)을 처리. key가 없으면 인덱스 기준(개발 모드에서 경고) |
| 비교 대상 | **VDOM 스냅샷 두 개** (`diff(old, new)`) | 새로 렌더링한 **React 요소**를 현재 **Fiber 트리**(이전 렌더링 결과 + 상태 + DOM 참조를 가진 노드 트리)와 비교 |
| 노드 종류 | HTML 태그와 텍스트만 | 함수/클래스 **컴포넌트**, Fragment, Portal, Suspense 등. 컴포넌트는 type이 같으면 상태를 유지한 채 다시 렌더링 |
| 결과 형태 | 패치 목록(배열) | Fiber마다 붙는 effect 플래그(Placement, Update, Deletion 등) |
| 입력 출처 | 실제 DOM을 다시 읽어서 VDOM을 만든다 (`containerToVdom`) | **DOM을 읽지 않는다.** 상태(state)와 props가 유일한 원본이고, DOM은 출력일 뿐이다 (예외: 서버 렌더링 HTML에 붙는 hydration) |

### 9.2 DOM 업데이트 방식

| 항목 | 이 구현 | 실제 React |
|---|---|---|
| 단계 | `diff`(계산) → `patch`(적용) 두 단계 | **Render 단계**(계산, 중단 가능) → **Commit 단계**(DOM 반영, 한 번에 동기 실행) 두 단계 — 구조는 비슷 |
| 대상 노드 찾기 | 매번 컨테이너에서 경로(`[1, 0, 2]`)를 따라 내려가 찾음 | 각 Fiber가 자기 DOM 노드(`stateNode`)를 직접 들고 있어서 찾을 필요가 없음 |
| 중단 · 우선순위 | 없음. 한 번 시작하면 끝까지 | Render 단계를 쪼개서 브라우저에 양보하고, 입력 같은 급한 업데이트를 먼저 처리 (Concurrent 렌더링, 우선순위 lane) |
| 업데이트 묶기 | 버튼 한 번 = Patch 한 번 | 여러 `setState`를 모아 한 번만 렌더링 (React 18 자동 배칭) |
| 속성 설정 | 모두 `setAttribute` (HTML 속성) | `className`, `value`, `checked`, `style` 객체 등 **DOM 프로퍼티**로 설정. 제어 컴포넌트(controlled input) 지원 |
| 이벤트 | 지원 안 함 | 루트 한 곳에 이벤트를 위임하는 합성 이벤트(SyntheticEvent) 시스템 |
| 과거 상태 이동 | State History에 VDOM 스냅샷을 저장하고 Diff/Patch로 이동 | React 자체에는 Undo/Redo가 없다. 상태 관리 쪽(예: 상태 스냅샷 저장)에서 구현하고, 상태가 바뀌면 React가 다시 렌더링 |

### 9.3 미니 React의 한계와 실제 React와의 차이 정리

| 한계 | 이 구현에서 생기는 일 | 실제 React는 |
|---|---|---|
| key 없음 | 맨 앞에 항목을 넣으면 뒤 형제가 모두 TEXT/PROPS/REPLACE로 바뀌고 끝에 CREATE. 결과는 맞지만 최소 변경이 아님 | key로 짝을 지어 기존 노드를 **이동**만 함 |
| 컴포넌트 · 상태 없음 | HTML 구조만 비교. 상태가 바뀌어 다시 그리는 개념이 없음 (Phase 2에서 구현 예정) | 컴포넌트 단위로 다시 렌더링하고 `memo` 등으로 건너뛸 수 있음 |
| DOM을 다시 읽어 비교 | 사용자가 DOM을 직접 고치는 과제 특성상 필요. 대신 읽을 때 공백 규칙 등 정규화가 필요함 | DOM을 읽지 않음. 바깥에서 DOM을 직접 고치면 React가 모르는 상태가 됨 |
| 경로로 노드 찾기 | 깊은 트리 · 많은 패치에서 매번 루트부터 탐색 | Fiber가 DOM 참조를 들고 있음 |
| 프로퍼티 상태 미반영 | `input`에 입력한 `value`, `checked`는 VDOM에 안 들어감 | 프로퍼티로 다루고 제어 컴포넌트로 동기화 |
| 이벤트 · ref · SVG 없음 | `onClick` 같은 함수 props, `ref`, SVG 네임스페이스 미지원 | 모두 지원 |
| 중단 불가 · 배칭 없음 | 큰 트리를 비교하는 동안 화면이 멈출 수 있음 | 작업을 쪼개고 우선순위를 둠, 업데이트를 묶음 |
| 오류 처리 단순 | DOM과 VDOM이 어긋나면 `patch`가 `TypeError`로 거부하고(DOM 그대로) 화면 상태 줄에 "Patch 실패"를 보여 줌. 스스로 복구하지는 않음 | Error Boundary, 개발 모드 경고, hydration 불일치 경고 |

## 10. Phase 2를 위한 다음 단계

> Phase 2에서 실제로 한 일은 `docs/phase2-report.md`에 있다. 아래 목록 중 **컴포넌트 렌더 루프 · Hooks · 프로퍼티 상태 · 이벤트**는 구현했고(이벤트는 `setProp` 대신 루트 위임 방식으로), **key 기반 비교는 하지 않았다**(Phase 2 보고서 한계).

- **key 기반 자식 비교**: `props.key`가 있으면 key로 짝을 짓고 `MOVE` 패치를 추가해 재정렬을 최소화한다.
- **이벤트 props**: `on*` 이름은 `setAttribute` 대신 `addEventListener`로 연결하고, 이전 핸들러를 기억해 교체한다(`setProp` 확장).
- **컴포넌트 렌더 루프**: `component.js`에서 `render() → h(...) 트리 → diff(이전, 새) → patch(container)`를 상태가 바뀔 때마다 돌린다. Phase 1의 `diff`/`patch`/`containerToVdom` 규칙을 그대로 재사용할 수 있다.
- **Hooks**: `hooks.js`의 `useState`가 값을 바꾸면 위 렌더 루프를 예약(배치)한다.
- **프로퍼티 상태**: `value` · `checked`는 속성이 아니라 프로퍼티로 설정하도록 `setProp`에 분기를 추가한다.
