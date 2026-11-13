# Phase 1 기획서 — Virtual DOM / Diff / Patch / State History

> 작성일: 2026-11-06 · 범위: `projects/react` Phase 1 (`index.html`)
> 제약: HTML · CSS · JavaScript만 사용 (외부 라이브러리, 번들러, npm 패키지 없음)

---

## 1. 목표

브라우저의 실제 DOM을 직접 다시 그리지 않고, **Virtual DOM(자바스크립트 객체 트리)** 두 개를 비교해서
**바뀐 부분만** 실제 DOM에 반영하는 React의 핵심 원리를 직접 구현하고 눈으로 확인한다.

## 2. 요구사항

| # | 요구사항 | 구현 위치 |
|---|---|---|
| R1 | 페이지 로드 시 **실제 영역**의 샘플 HTML을 Virtual DOM 트리로 변환 | `vdom.js` `containerToVdom`(내부에서 `domToVdom`), `phase1/main.js` |
| R2 | 만든 Virtual DOM으로 **테스트 영역**을 렌더링 | `vdom.js` `createElement` |
| R3 | 사용자가 테스트 영역의 HTML을 자유롭게 수정 | `index.html` (contenteditable + HTML 소스 편집기) |
| R4 | **Patch** 버튼 → 테스트 영역을 다시 Virtual DOM으로 변환 | `containerToVdom`(내부에서 `domToVdom`) |
| R5 | Diff 알고리즘으로 이전 Virtual DOM과 비교해 변경점 계산 | `diff.js` `diff` |
| R6 | 변경된 부분만 실제 영역에 반영 | `patch.js` `patch` |
| R7 | 새 Virtual DOM을 **State History**에 저장 | `phase1/history.js` `push` |
| R8 | **뒤로가기 / 앞으로가기**로 History의 특정 시점으로 이동, 실제·테스트 영역 동시 변경 | `history.js` `undo`/`redo`, `main.js` |

## 3. 팀 공통 규칙 (변경 금지)

- `src/core/`의 파일 이름, 함수 이름은 그대로 둔다: `h`, `domToVdom`, `createElement`, `diff`, `patch`.
- Virtual DOM 노드 형식
  - 요소: `{ type: "div", props: { id: "box" }, children: [VNode, ...] }`
  - 텍스트: `"문자열"`
- 함수를 **추가로 export** 하는 것은 허용 (기존 이름·형식은 유지).

## 4. 화면 구성

```
┌──────────────────────────────────────────────────────────────┐
│ 헤더: 제목 + 단계 설명                                         │
├──────────────────────────────┬───────────────────────────────┤
│ 실제 영역 (#real-area)        │ 테스트 영역 (#test-area)        │
│ - 읽기 전용                   │ - contenteditable 미리보기      │
│ - Patch된 노드는 잠깐 강조     │ - HTML 소스 편집기 (#test-source)│
├──────────────────────────────┴───────────────────────────────┤
│ [Patch] [뒤로가기] [앞으로가기]   현재 위치: 3 / 5             │
├──────────────────────────────┬───────────────────────────────┤
│ State History 목록 (클릭 이동) │ 마지막 Diff 결과 (패치 목록)     │
├──────────────────────────────┴───────────────────────────────┤
│ 현재 Virtual DOM (JSON, 접기/펼치기)                           │
└──────────────────────────────────────────────────────────────┘
```

- 테스트 영역은 두 가지 방법으로 편집할 수 있다.
  1. 미리보기를 직접 클릭해 글자 수정 (`contenteditable`)
  2. HTML 소스 편집기에서 태그 · 속성 · 구조 수정 (입력 즉시 미리보기에 반영)
- 두 편집 방식은 서로 동기화된다.

## 5. 동작 흐름

```
[페이지 로드]
  실제 영역 DOM ──containerToVdom──▶ VDOM₀ ──createElement──▶ 테스트 영역 렌더링
                                     └──▶ history.push(VDOM₀, { label: "초기 상태" })

[Patch 클릭]
  테스트 영역 DOM ──containerToVdom──▶ VDOMₙ
  diff(history.current(), VDOMₙ) ──▶ patches
  patches가 비어 있으면 "변경 없음" 안내 후 종료
  patch(실제 영역, patches)        ← 바뀐 노드만 수정
  history.push(VDOMₙ, { patchCount, label })

[뒤로가기 / 앞으로가기 / 목록 클릭]
  이전 = history.current()
  대상 = history.undo() / redo() / go(i)
  patch(실제 영역, diff(이전, 대상))   ← 실제 영역도 Diff/Patch로 이동
  테스트 영역 = createElement(대상)    ← 편집 영역은 통째로 다시 그림
```

## 6. 모듈 설계

### 6.1 `core/vdom.js`

| 함수 | 설명 |
|---|---|
| `h(type, props, ...children)` | VNode 생성 헬퍼. `props`가 `null`이어도 `{}`로 처리, 중첩 배열 평탄화, `null/false/true` 제거, 숫자는 문자열로 변환 |
| `domToVdom(node)` | 실제 DOM 노드 → VNode. 텍스트 노드는 문자열, 요소는 `{type, props, children}` |
| `createElement(vnode)` | VNode → 실제 DOM 노드 |
| (추가) `isIgnorableNode(node)` | VDOM에서 무시할 DOM 노드인지 판단 (주석, 줄바꿈이 들어 있는 공백만으로 된 텍스트) |
| (추가) `vdomChildNodes(el)` | VNode로 변환될 자식 DOM 노드만 골라서 반환 (`isIgnorableNode`인 것 제외) |
| (추가) `containerToVdom(el)` | 영역(컨테이너) 자체는 비교 대상이 아니므로 `{type:"div", props:{}, children}` 형태의 루트로 감싸서 반환 |
| (추가) `setProp(el, name, value)` | 속성 하나를 실제 DOM에 설정 (`createElement` · `patch` 공용). `null/false`는 제거, `true`는 값 없는 속성. `setAttribute`가 거부하는 이름(예: 공백 포함)은 경고 후 건너뛰고 `false` 반환 |
| (추가) `isElementVNode(value)` | 요소 VNode 모양인지 검사 (`type`이 비어 있지 않은 문자열인 객체). `createElement`와 `patch` 입력 검사에서 사용 |
| (추가) `validateVNode(vnode, where?)` | VNode 트리 전체 검사 (props · children 모양, 속성값 종류). 잘못되면 `TypeError`. `diff`와 `patch` 입력 검사에서 사용 |
| (추가) `checkProps(props, where)` | props 객체 검사 (`validateVNode` · `patch`의 `PROPS.set` 공용) |

**공백 처리 규칙**: 줄바꿈이 포함된 공백만 있는 텍스트 노드(= HTML 들여쓰기)는 무시한다.
`<b>a</b> <i>b</i>` 사이의 공백 한 칸처럼 줄바꿈 없는 공백은 화면에 보이므로 유지한다.
이 규칙을 `domToVdom`과 `patch`가 **똑같이** 사용해야 DOM 자식 위치와 VNode 자식 위치가 일치한다.

### 6.2 `core/diff.js`

- 두 트리를 동시에 깊이 우선으로 내려가며 비교한다.
- 노드 위치는 **경로(path)** = 루트부터의 자식 인덱스 배열로 표현한다. 예: `[1, 0]` = 루트의 2번째 자식의 1번째 자식.
- 공개 이름: `diff(oldVNode, newVNode)`, (추가) `PATCH` — 아래 패치 종류 이름을 담은 상수 객체
- 패치 종류

| type | 언제 | 내용 |
|---|---|---|
| `CREATE` | 새 트리에만 자식이 있음 | `path`(부모), `index`, `node` |
| `REMOVE` | 옛 트리에만 자식이 있음 | `path` |
| `REPLACE` | 태그가 다르거나, 텍스트 ↔ 요소로 바뀜 | `path`, `node` |
| `TEXT` | 텍스트 내용만 바뀜 | `path`, `value` |
| `PROPS` | 같은 태그인데 속성이 바뀜 | `path`, `set`(추가·변경), `remove`(삭제할 이름 목록) |

- 같은 위치의 같은 태그는 재사용하고 자식으로 내려간다. 태그가 다르면 하위 트리 전체를 교체하고 내려가지 않는다 (React와 같은 휴리스틱).
- 자식 비교는 **인덱스 기준**으로 한다 (key 기반 비교는 Phase 1 범위 밖, 보고서에 한계로 기록).

### 6.3 `core/patch.js`

- `patch(container, patches)`
  0. 모든 패치의 모양을 검사한다. 종류 · `path` · 종류별 필수 필드 · `node` 트리 전체가 하나라도 잘못되면 `TypeError`. `REMOVE` · `REPLACE`의 경로 `[]`(컨테이너 자신)도 거부한다.
  1. 모든 패치의 대상 DOM 노드를 경로로 찾아 둔다 (변경 전 트리 기준). 경로에 노드가 없거나, 대상 종류가 패치와 맞지 않거나(`TEXT` → 텍스트 노드, `PROPS` · `CREATE` → 요소), `CREATE`의 index가 맞지 않으면 `TypeError`.
  2. `CREATE` · `REPLACE`로 넣을 DOM을 미리 만든다.
  3. 그다음 순서대로 적용한다.
  - 0~2단계에서 실패하면 **DOM을 전혀 건드리지 않는다**. 중간에 멈춰 실제 영역이 반쯤만 바뀌는 일을 막는다.
  - 대상을 미리 찾아 두므로 앞의 `REMOVE`가 형제 인덱스를 밀어도 뒤 패치가 엉뚱한 노드를 건드리지 않는다.
- `PROPS`는 **삭제 → 설정** 순서로 적용한다. HTML 속성 이름은 대소문자를 구분하지 않아서 `Title` 설정 후 `title` 삭제를 하면 방금 설정한 속성이 지워지기 때문이다.
- 반환값: 변경된 DOM 노드 목록 (화면 강조 효과에 사용).

### 6.4 `phase1/history.js`

- 내부 상태: `stack`(기록 배열 — 각 기록은 `{ vdom, time, patchCount, label }`), `index`(현재 위치, 기록이 없으면 `-1`).

| 함수 | 설명 |
|---|---|
| `push(vdom, meta?)` | 현재 위치 뒤의 "앞으로가기" 기록을 버리고 새 기록 추가 (브라우저 히스토리와 같은 방식). 저장할 때 깊은 복사. `meta = { patchCount, label }`은 목록 표시용 |
| `undo()` / `redo()` | 한 칸 이동 후 해당 VNode 복사본 반환, 이동할 수 없으면 `null` |
| (추가) `go(i)` | `i`번 기록으로 바로 이동 (목록 클릭용). 범위 밖이면 `null` |
| (추가) `current()` | 현재 위치의 VNode 복사본 (기록이 없으면 `null`) |
| (추가) `canUndo()` / `canRedo()` | 이동 가능 여부 (버튼 켜고 끄기용) |
| (추가) `position()` | `{ index, length }` — "현재 위치: 3 / 5" 표시용 |
| (추가) `entries()` | VDOM을 뺀 기록 목록 `{ time, patchCount, label }[]` — History 목록 표시용 |
| (추가) `reset()` | 모든 기록 삭제 (테스트용) |

### 6.5 `phase1/main.js`

- `main.js`: 위 모듈을 조립하고 버튼 · 편집기 이벤트를 연결한다.
- VNode → 보기 좋은 HTML 문자열 변환(소스 편집기용)도 `main.js` 안에 둔다. 테스트에서 쓰도록 아래 함수를 export 하고, 화면 시작(`init`)은 `#real-area`가 있는 페이지(`index.html`)에서만 실행한다.

| 함수 · 상수 | 설명 |
|---|---|
| `toHtml(nodes, depth?)` | VNode 배열 → 들여쓴 HTML 문자열. 형제가 모두 요소일 때만 줄을 바꿔, 다시 파싱해도 같은 VDOM이 나오게 함 |
| `escapeText(text)` | 텍스트의 `& < >` 를 엔티티로, ` ` 를 `&nbsp;` 로 |
| `escapeAttr(value)` | 속성값의 `& "` 를 엔티티로, ` ` 를 `&nbsp;` 로 |
| `VOID_TAGS` | 닫는 태그가 없는 요소 이름 집합 (`br`, `img`, `input` …) |
| `REQUIRED_IDS` | 화면 동작에 꼭 필요한 요소 id 12개 (`index.html`의 id와 같아야 함) |
| `checkRequiredElements(root?)` | 필수 요소 검사. 모두 있으면 `ready` → `init()`, 일부만 있으면 `partial` → 시작하지 않고 빠진 id를 콘솔 · 화면에 알림, 하나도 없으면 `none` → 아무것도 안 함(테스트 페이지에서 import 한 경우) |

## 7. 검증 계획

- `tests/index.html` — 외부 라이브러리 없는 간단한 테스트 러너를 브라우저에서 실행.
  - `h` 정규화, `domToVdom` 공백 규칙, `createElement` 왕복 변환 (#001~#080)
  - `diff` 패치 종류별 결과와 `patch` 적용 결과 — 연속 REMOVE, 들여쓴 컨테이너, 노드 재사용 (#081~#170. diff와 짝으로 검사하므로 같은 파일에 둔다)
  - `history` push / undo / redo / 분기, `toHtml` 들여쓰기 · 이스케이프 · 왕복 (#171~#230)
  - `main.js` 시작 조건과 `index.html`을 iframe으로 열어 버튼을 눌러 보는 통합 테스트 (#231~#255)
  - **왕복 검증**: 무작위 트리 A, B를 만들고 A를 렌더링 → `patch(diff(A, B))` → 결과 DOM을 다시 VNode로 바꿔 B와 같은지 확인 (#256~#290)
  - 잘못된 VNode는 `TypeError`, 대상을 못 찾는 Patch는 `TypeError` + DOM 그대로 (`tests/cases-invalid.test.js`)
  - **테스트 항목 #001~#315** — 경계값 · 잘못된 입력 · 대량 · 보안 · 페이지 이벤트까지 315개 항목을 번호대로 하나씩 검사 (`tests/cases-*.test.js`, 공용 도우미 `tests/helpers.js`)
- 실제 페이지에서 텍스트 수정, 속성 수정, 노드 추가 · 삭제, 태그 교체, 뒤로가기 · 앞으로가기를 직접 확인.

## 8. 범위 밖

- Phase 2 (`component.js`, `hooks.js`, `app.html`) — 이번 작업에서는 손대지 않는다.
- key 기반 자식 재배치, 이벤트 핸들러 props, SVG 네임스페이스.
