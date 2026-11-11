# 미니 React

> 브랜치 `feat/Kimjunwoo-React` · 정리한 날 2026-11-10 · 순수 HTML · CSS · JavaScript(ES 모듈)만 사용

이 문서 하나로 미니 React가 **무엇이고, 왜 이렇게 만들었고, 어떻게 돌아가는지** 알 수 있게 썼습니다.
그림으로 보려면 **[설계도 (architecture.html)](./architecture.html)** 를 Live Server로 여세요.
예시의 입력 · 출력은 모두 실제 코드를 실행해서 얻은 값입니다.

---

## 3분 요약

1. **화면을 객체로 옮긴다.** 실제 DOM 대신 `{ type, props, children }` 객체(VDOM)로 화면을 표현합니다.
2. **비교해서 바뀐 곳만 고친다.** 이전 VDOM과 새 VDOM을 비교(`diff`)해 패치 목록을 만들고, 그 부분만 실제 DOM에 반영(`patch`)합니다.
3. **Phase 1**은 이 엔진을 눈으로 보는 실험실입니다. 테스트 영역을 고치고 Patch를 누르면 실제 영역의 바뀐 노드만 바뀌고, 뒤로/앞으로도 됩니다.
4. **Phase 2**는 같은 엔진 위에 `useState` · `useEffect` · `useMemo`를 얹었습니다. `setState` → 다시 렌더 → `diff` → `patch`가 자동으로 일어납니다.
5. **상태는 `hooks` 배열에 남습니다.** Hook은 "몇 번째로 불렸는지"로 자기 칸을 찾습니다. 그래서 Hook은 항상 같은 순서로 불러야 합니다.

| | Phase 1 | Phase 2 |
|---|---|---|
| 페이지 | `index.html` | `app.html` |
| 무엇을 | VDOM · Diff · Patch · History | Component · State · Hooks |
| 화면이 바뀌는 계기 | Patch 버튼, 뒤로/앞으로 | 클릭 · 입력 → `setState` |
| 테스트 | 477개 | 245개 (합계 **722개 모두 통과**) |

---

## 목차

**처음이면 1 → 5장을 순서대로**, 그 뒤는 필요할 때 찾아보세요.

| 읽기 | 찾아보기 |
|---|---|
| 1. [실행 방법](#1-실행-방법) | 6. [전체 흐름 한 장 요약](#6-전체-흐름-한-장-요약) |
| 2. [먼저 알아 둘 개념](#2-먼저-알아-둘-개념) | 7. [함수별 구현](#7-함수별-구현) |
| 3. [전체 구조](#3-전체-구조) | 8. [화면 기능](#8-화면-기능) |
| 4. [Phase 1 원리](#4-phase-1-원리) | 9. [테스트](#9-테스트) |
| 5. [Phase 2 원리](#5-phase-2-원리) | 10. [실제 React와 비교](#10-실제-react와-비교) |
| | 11. [한계와 남은 일](#11-한계와-남은-일) |
| | 12. [용어 정리](#12-용어-정리) · 13. [커밋 기록](#13-커밋-기록) |

더 자세한 기록: [phase1-plan](./phase1-plan.md) · [phase1-report](./phase1-report.md) · [phase2-plan](./phase2-plan.md) · [phase2-report](./phase2-report.md) · [test-list](./test-list.md)
(보고서 안의 테스트 수 320 · 422개는 쓸 당시 숫자입니다.)

---

## 1. 실행 방법

> **핵심** VS Code **Live Server**로 `projects/react`를 엽니다.

| 주소 | 내용 |
|---|---|
| `index.html` | Phase 1 · Virtual DOM 실험실 |
| `app.html` | Phase 2 · 할 일 앱 |
| `tests/index.html` | 테스트 722개 전체 실행 (약 30초) |

- 파일을 더블클릭(`file://`)하면 ES 모듈(`import`)이 막혀서 동작하지 않습니다.
- 두 페이지는 머리말 디자인이 같고, 오른쪽 위 메뉴로 서로 오갑니다.

---

## 2. 먼저 알아 둘 개념

> **핵심** 실제 DOM은 고치기 비싸다 → 객체로 비교해서 → 바뀐 곳만 고친다.

### 2.1 왜 Virtual DOM인가

**문제:** 실제 DOM을 고치면 비쌉니다.
- 크기 · 위치가 바뀌면 브라우저가 레이아웃을 다시 계산(**Reflow**)하고 다시 칠합니다(**Repaint**).
- `innerHTML`로 통째로 바꾸면 안 바뀐 부분까지 새로 만들어지고, 입력 중인 글자 · 포커스 · 스크롤도 사라집니다.

**해결:**
1. 화면을 가벼운 **자바스크립트 객체(Virtual DOM)** 로 표현한다.
2. 상태가 바뀌면 새 객체를 만들어 **이전 객체와 비교(Diff)** 한다.
3. **바뀐 곳만 실제 DOM에 반영(Patch)** 한다.

### 2.2 VNode — VDOM의 노드 하나 (팀 공통 형식)

```js
{ type: "div", props: { id: "box" }, children: [ /* VNode 들 */ ] }   // 요소
"문자열"                                                               // 텍스트
```

| 필드 | 뜻 |
|---|---|
| `type` | 태그 이름 (항상 소문자) |
| `props` | HTML 속성 그대로 (`class`, `style`, `data-*` …) |
| `children` | 자식 배열 (요소 또는 문자열) |

코드로 만들 때는 `h()`를 씁니다 (JSX 대신).

```js
h("ul", { class: "list" }, [h("li", null, "하나"), h("li", null, 2)], false && h("p"), null)
```
```json
{"type":"ul","props":{"class":"list"},"children":[
  {"type":"li","props":{},"children":["하나"]},
  {"type":"li","props":{},"children":["2"]}]}
```
- 배열은 펼쳐지고, `false` · `null`은 사라지고, 숫자 `2`는 `"2"`가 됩니다.
- 그래서 `items.map(...)`, `조건 && h(...)`를 그대로 쓸 수 있습니다.

### 2.3 Diff와 Patch

| | 하는 일 | DOM을 건드리나 |
|---|---|---|
| **Diff** | 이전 · 새 VDOM을 비교해 **패치 목록**을 만든다 | 아니오 (순수 계산) |
| **Patch** | 패치 목록대로 실제 DOM을 고친다 | 예 |

패치는 5종류입니다.

| 종류 | 뜻 | 실제 DOM에서 |
|---|---|---|
| `CREATE` | 새 노드 추가 | `appendChild` |
| `REMOVE` | 노드 삭제 | `remove()` |
| `REPLACE` | 다른 노드로 교체 | `replaceWith()` |
| `TEXT` | 글자만 변경 | `nodeValue` 변경 (노드 재사용) |
| `PROPS` | 속성만 변경 | `setAttribute` / `removeAttribute` (노드 재사용) |

### 2.4 Component · State · Hooks

| 용어 | 뜻 |
|---|---|
| 컴포넌트 | props를 받아 VNode를 돌려주는 **함수** |
| State | 바뀌면 화면을 다시 그려야 하는 값 (할 일 목록, 입력 중인 글자 …) |
| Hooks | 함수 컴포넌트 안에서 상태를 쓰게 해 주는 함수 — `useState` 상태 · `useEffect` 화면 반영 뒤 할 일 · `useMemo` 계산 재사용 |

> **질문** 함수는 렌더마다 새로 실행되고 지역 변수는 사라지는데, 상태는 어디에 남을까?
> → [5.2](#52-hooks의-원리--상태는-어디에-남는가)에서 답합니다.

---

## 3. 전체 구조

> **핵심** Phase 2는 Phase 1의 `diff` · `patch`를 그대로 씁니다. Phase 1 엔진이 곧 Phase 2의 렌더링 엔진입니다.
> 그림: [설계도 ① 전체 구조](./architecture.html#arch)

### 3.1 누가 누구를 쓰나

```
[Phase 1]  index.html
            └─ phase1/main.js ─┬─ core/vdom.js      DOM ↔ VDOM
                               ├─ core/diff.js      비교
                               ├─ core/patch.js     반영
                               └─ phase1/history.js 기록

[Phase 2]  app.html
            └─ app/main.js ─┬─ core/component.js  FunctionComponent
                            │   ├─ core/vdom.js
                            │   ├─ core/diff.js    ← Phase 1 그대로
                            │   ├─ core/patch.js   ← Phase 1 그대로
                            │   └─ core/hooks.js
                            └─ app/App.js ─┬─ core/hooks.js     useState · useEffect · useMemo
                                           ├─ core/vdom.js      h()
                                           ├─ core/component.js stateless (TestPanel)
                                           └─ app/components/*  상태 없는 자식 (각각 h · stateless 사용)
```

### 3.2 폴더

```
projects/react/
├── index.html · app.html        Phase 1 · Phase 2 페이지
├── src/
│   ├── core/                    팀 공통 엔진 (파일 · 함수 이름 바꾸지 않기)
│   │   ├── vdom.js              VNode 만들기 · DOM ↔ VDOM · 속성 설정 · 검사
│   │   ├── diff.js              두 VNode 비교 → 패치 목록
│   │   ├── patch.js             패치 목록 → 실제 DOM
│   │   ├── component.js         FunctionComponent · stateless · 이벤트 위임 · 배칭
│   │   └── hooks.js             useState · useEffect · useMemo
│   ├── phase1/                  main.js(화면 · 예시 버튼 · toHtml) · history.js
│   ├── app/                     App.js(할 일 앱 + 테스트 패널) · main.js · components/
│   └── styles/style.css         두 페이지 공용 스타일
├── tests/                       index.html(실행) · runner.js · helpers.js · *.test.js
└── docs/                        이 README · architecture.html(설계도) · 계획 · 보고서 · 테스트 목록
```

---

## 4. Phase 1 원리

> **핵심** 실제 DOM → VDOM으로 읽고, `diff`로 차이를 찾고, `patch`로 그 차이만 실제 영역에 반영합니다.

화면에는 두 영역이 있습니다.

| 영역 | 역할 |
|---|---|
| **실제 영역** | 진짜 화면. **Patch로만** 바뀝니다 |
| **테스트 영역** | 마음대로 고치는 연습장 (직접 편집 + HTML 소스 편집기) |

### 4.1 실제 DOM → VDOM (`domToVdom`, `containerToVdom`)

DOM을 재귀로 내려가며 텍스트는 문자열, 요소는 `{ type, props, children }`으로 바꿉니다. 여기에 규칙이 두 개 있습니다.

**규칙 ① 들여쓰기 공백은 버린다**

```html
<ul>
  <li>사과</li>
</ul>
```
- `<ul>` 안에는 `"\n  "`라는 텍스트 노드가 있습니다.
- 남겨 두면 소스의 들여쓰기만 바꿔도 Diff가 "바뀌었다"고 판단합니다.
- 그래서 **줄바꿈이 든 공백만으로 된 텍스트**와 주석은 버립니다 (`isIgnorableNode`).
- 남기는 것: 줄바꿈 없는 공백(`<b>a</b> <i>b</i>`의 띄어쓰기), `<pre>` · `<textarea>` · `<listing>` 안의 공백.
- `domToVdom`과 `patch`가 **같은 규칙**(`vdomChildNodes`)으로 자식 번호를 세서, "n번째 자식"이 항상 같은 노드를 가리킵니다.

**규칙 ② 영역은 가상의 div로 감싼다**
- 실제 영역(`#real-area`)과 테스트 영역(`#test-area`)은 id가 다릅니다.
- 영역 자체까지 비교하면 "id가 바뀌었다"는 엉뚱한 패치가 생깁니다.
- 그래서 영역은 `{ type: "div", props: {}, children: [...] }`로 두고 **안의 내용만** 비교합니다. Phase 2의 루트도 같은 모양입니다.

### 4.2 Diff 알고리즘 (`diff`)

두 트리를 **같은 위치끼리** 동시에 깊이 우선으로 내려갑니다. O(n)입니다. (트리 전체를 최적으로 비교하면 O(n³)이라 쓰지 않습니다.)

노드 한 쌍은 반드시 다음 중 하나입니다.

| 경우 | 결과 | 더 내려가나 |
|---|---|---|
| ① 새 트리에 없음 | `REMOVE` | — |
| ② 둘 다 텍스트 | 글자가 다르면 `TEXT` | — |
| ③ 텍스트 ↔ 요소, 또는 태그가 다름 | `REPLACE` (하위 트리 통째로) | 아니오 |
| ④ 같은 태그 | 속성 차이만 `PROPS` | 예 → ⑤ |
| ⑤ 자식들 | 인덱스 순서로 짝지어 ①~⑤ 반복, 새 쪽에만 있으면 `CREATE` | 예 |

**`path`란?** 루트에서 대상까지 내려가는 자식 번호 배열입니다. **항상 이전 트리 기준**입니다.

| path | 뜻 |
|---|---|
| `[]` | 루트 |
| `[2]` | 셋째 자식 |
| `[2, 0]` | 셋째 자식의 첫째 자식 |

#### 예시 1 — 네 가지 패치가 한 번에

```
이전 A: <h1 title="a">안녕</h1>    <ul><li>사과</li><li>배</li></ul>              <p>끝</p>
새   B: <h1 class="big">반가워</h1> <ul><li>사과</li><li>배</li><li>감</li></ul>  <section>끝</section>
```
`diff(A, B)` 실제 결과:
```json
{"type":"PROPS","path":[0],"set":{"class":"big"},"remove":["title"]}
{"type":"TEXT","path":[0,0],"value":"반가워"}
{"type":"CREATE","path":[1],"index":2,"node":{"type":"li","props":{},"children":["감"]}}
{"type":"REPLACE","path":[2],"node":{"type":"section","props":{},"children":["끝"]}}
```

| 노드 | 판정 | 이유 |
|---|---|---|
| `<h1>` | `PROPS` + `TEXT` | 태그가 같아 **재사용**, 속성(④)과 글자(②)만 변경 |
| `<ul>` | `CREATE` 1개 | "사과" · "배"는 그대로, 셋째 `<li>`만 새로 생김(⑤) |
| `<p>` → `<section>` | `REPLACE` | 태그가 다름(③) |

CREATE는 아직 DOM에 없는 노드라서 "부모 경로 `[1]` + 넣을 자리 `index: 2`"로 표현합니다.

#### 예시 2 — key가 없어서 생기는 일

```
이전: <li>A</li><li>B</li><li>C</li>     새: <li>B</li><li>C</li>
```
실제 결과:
```json
{"type":"TEXT","path":[0,0,0],"value":"B"}
{"type":"TEXT","path":[0,1,0],"value":"C"}
{"type":"REMOVE","path":[0,2]}
```
- "첫째를 지운다"가 아니라 "첫째를 B로, 둘째를 C로 바꾸고, 셋째를 지운다"가 됩니다.
- 결과 화면은 맞지만 최소 변경은 아닙니다. 실제 React는 `key`로 이 문제를 풉니다.

**입력 검사:** `diff`는 먼저 `validateVNode`로 두 트리를 검사합니다. 잘못되면 위치(`루트.children[0]…`)를 담은 `TypeError`를 던집니다.

### 4.3 Patch — 3단계로 나눈 이유 (`patch`)

```
① 대상 찾기          모든 패치의 대상 노드를 경로로 "먼저" 다 찾아 둔다
② 새 DOM 미리 만들기  CREATE · REPLACE 에 넣을 노드를 만든다
③ 적용               찾아 둔 노드에 한꺼번에 적용한다
```

| 이유 | 설명 |
|---|---|
| **경로는 이전 트리 기준** | 자식 0번을 먼저 지우면 뒤 번호가 당겨져 2번을 못 찾습니다 → DOM을 건드리기 전에 노드 참조를 전부 잡아 둡니다 |
| **전부 되거나, 전혀 안 되거나** | 실패할 수 있는 일(①②)을 먼저 끝냅니다. ①②에서 오류가 나면 `TypeError`를 던지고 **실제 DOM은 그대로**입니다 |

- **최적화:** ①에서 노드마다 자식 목록을 `Map`에 기억합니다. (li 3,000개 · 패치 1,500개: 1,170ms → 6ms)
- **PROPS 순서:** 지울 속성을 먼저 지우고 설정합니다. HTML 속성 이름은 대소문자를 구분하지 않아서, 반대 순서면 방금 넣은 `Title`이 `title` 삭제에 지워질 수 있습니다.

### 4.4 State History (`history.js`)

브라우저의 뒤로/앞으로와 같습니다.
```
stack = [A, B, C], index = 2   → 지금 C
undo()   → index = 1, B
push(D)  → C 를 버리고 [A, B, D]   (뒤로 간 상태에서 새 기록 = 앞으로가기 기록 삭제)
```
- **깊은 복사:** 넣고 꺼낼 때 `structuredClone`으로 복사합니다. 참조를 그대로 두면 바깥에서 객체를 고칠 때 과거 기록까지 바뀝니다.
- **읽기 전용 `peek()`:** 읽기만 할 때는 복사하지 않습니다(최적화).
- **이동도 Diff/Patch로:** 뒤로/앞으로 갈 때도 실제 영역은 `diff(지금, 대상)` → `patch`로 바뀐 부분만 바꿉니다. 테스트 영역은 통째로 다시 그립니다.

### 4.5 자가 점검

- 동작이 끝날 때마다 "실제 영역을 다시 읽은 VDOM = History의 현재 VDOM"인지 상태 줄에 보여 줍니다 (`reportResult`).
- 그래서 **실제 영역에는 클래스 · 속성을 절대 붙이지 않습니다.** 바뀐 노드 강조도 흔적이 남지 않는 `Element.animate()`로 합니다.

---

## 5. Phase 2 원리

> **핵심** `setState` → 렌더 예약 → 컴포넌트 다시 실행 → 새 VDOM → Phase 1의 `diff` · `patch` → effect 실행.

### 5.1 FunctionComponent — 함수 바깥에서 살아 있는 상자

```js
const app = new FunctionComponent(App, document.getElementById("root"));
app.mount();   // 첫 렌더. 이후에는 setState 가 알아서 다시 렌더한다
```

함수 `App`은 렌더마다 새로 실행되어 아무것도 기억하지 못합니다. 그래서 **인스턴스가 대신 기억합니다.**

| 필드 | 내용 |
|---|---|
| `hooks` | Hook 상태 배열 — **진짜 상태 저장소** |
| `vdom` | 마지막으로 반영한 VDOM (다음 diff의 "이전") |
| `handlers` | 이벤트 핸들러 표 (`"0"` → `{ type: "click", fn }`) |
| `updateScheduled` | 렌더가 예약되어 있는가 (배칭) |

### 5.2 Hooks의 원리 — 상태는 어디에 남는가

> **답** 인스턴스의 `hooks` 배열에 남고, Hook은 **몇 번째로 불렸는지**로 자기 칸을 찾습니다.

```
FunctionComponent 인스턴스 (계속 살아 있음)
  hooks = [ {kind:"state", value:[…todos]}, {kind:"state", value:""}, … ]
              ▲ 0번 칸                      ▲ 1번 칸

App() 실행 (렌더마다 새로 실행)
  useState(loadTodos)  → hooks[0]   ← 이름이 아니라 순서로 찾는다
  useState("")         → hooks[1]
```

1. 렌더 직전 `prepareHooks`가 "지금 렌더 중인 컴포넌트"(`current`)를 기억하고 칸 번호(`hookIndex`)를 0으로 만듭니다.
2. `useState`는 `current.hooks[hookIndex]`를 읽고 번호를 1 올립니다. 첫 렌더면 칸을 새로 만듭니다.
3. 함수가 끝나도 값은 `hooks` 배열에 남습니다. 다음 렌더에서 같은 순서로 부르면 같은 칸을 읽습니다.

**그래서 Hook을 조건문 · 반복문 안에서 부르면 안 됩니다.** 순서가 바뀌면 남의 칸을 읽습니다.
이 구현은 칸마다 종류(`state`/`memo`/`effect`)를 기록해 두고, **종류가 바뀌거나 개수가 달라지면 오류**를 냅니다.

### 5.3 setState가 하는 일

```js
const [count, setCount] = useState(0);
setCount((n) => n + 1);
```

1. 인자가 함수면 `함수(이전 값)`, 아니면 그 값이 새 값입니다.
2. `Object.is`로 이전 값과 같으면 **아무것도 안 합니다** (렌더 생략).
3. 다르면 저장하고 **렌더를 예약**합니다. 바로 렌더하지 않습니다.

- `setState`는 매 렌더 **같은 함수**입니다 (`useEffect` deps에 넣어도 안전).
- 렌더 도중에 부르면 오류, 언마운트 뒤에는 무시합니다.

### 5.4 Batching — setState 여러 번, 렌더 한 번

```js
setTodos(…); setTodos(…); setTodos(…);   // "3개 추가" 버튼
```
- `scheduleUpdate`는 `queueMicrotask`로 렌더를 **한 번만** 예약합니다. 이미 예약돼 있으면 아무것도 안 합니다.
- 마이크로태스크는 지금 핸들러가 끝나자마자, 화면을 그리기 **전**에 실행됩니다 → 렌더 1번, 중간 상태는 안 보임.
- 함수형 업데이트(`list => [...list, 새것]`)를 쓰면 세 번의 변경이 차례로 쌓입니다.

### 5.5 렌더 한 번의 흐름 (`update`)

```
flush() → update()
 1. render()      prepareHooks → App() → finishHooks → 루트 div로 감싸기 → extractHandlers
 2. diff()        이전 VDOM ↔ 새 VDOM        ← Phase 1
 3. patch()       바뀐 노드만 #root 에 반영   ← Phase 1
 4. commit()      vdom · 핸들러 표 교체, 새 이벤트 종류면 리스너 추가, onCommit 알림
 5. runEffects()  deps가 바뀐 effect 실행
```
- `mount()`는 2~3 대신 노드를 **모두** 만든 뒤 `replaceChildren`으로 한 번에 넣습니다.
- 1~3에서 오류가 나면(`guard`) 실제 DOM은 그대로이고, 그 렌더의 effect도 취소됩니다.

### 5.6 이벤트 — VDOM 형식을 지키면서 함수 연결하기

**문제:** VDOM 속성은 문자열인데 `onClick`에는 함수가 들어갑니다.
**해결:** 렌더 결과에서 함수를 떼어 표에 넣고, 속성에는 **번호만** 남깁니다 (`extractHandlers`).

```js
h("div", null,
  h("button", { class: "btn", onClick: () => {…} }, "+1"),
  h("input", { onInput: () => {…}, value: "x" }))
```
```json
vdom:     {"type":"div","props":{},"children":[
            {"type":"button","props":{"class":"btn","data-on-click":"0"},"children":["+1"]},
            {"type":"input","props":{"data-on-input":"1","value":"x"},"children":[]}]}
handlers: [["0","click"],["1","input"]]
```

| 장점 | 설명 |
|---|---|
| Phase 1 엔진 그대로 | diff · patch에는 함수 없는 평범한 VDOM만 들어감 |
| 불필요한 패치 없음 | 번호는 트리 순서라, 구조가 같으면 매 렌더 같은 번호 |
| 리스너가 적음 | 이벤트 종류마다 `#root`에 **하나씩만** (이벤트 위임) |

**이벤트 위임 동작:** 클릭 → `handleEvent`가 클릭된 요소부터 위로 올라가며 `data-on-click`을 찾음 → 최신 핸들러 표에서 함수를 꺼내 실행.
버블링되지 않는 `focus` · `blur`는 `focusin` · `focusout`으로 바꿔 듣습니다.

### 5.7 State는 루트에서만 — Lifting State Up

- 상태는 **루트 `App`만** 가집니다.
- 자식(`Header` · `TodoForm` · `Toolbar` · `TodoList` · `TodoItem` · `TestPanel`)은 `stateless`로 감싼 **순수 함수**입니다. props만 받아 VNode를 돌려줍니다.
- `stateless` 안에서 Hook을 부르면 **오류** → 규칙을 코드로 강제합니다.
- 자식이 상태를 바꾸려면 부모가 준 콜백을 부릅니다.

```
체크박스 클릭 → TodoItem 의 onChange → onToggle(id) → App 의 setTodos
→ App 다시 렌더 → Header(통계) · TodoList 가 새 props 로 → diff → 바뀐 노드만 patch
```

### 5.8 useEffect · useMemo

**`useEffect(fn, deps)`** — 화면 반영 **뒤에** 할 일
- 렌더 중에는 "실행 예정" 표시만 하고, commit이 끝난 뒤 실행합니다 → effect 안에서 DOM을 읽으면 이미 새 화면.
- `fn`이 함수를 돌려주면 **cleanup**으로 기억했다가 다음 실행 직전 · 언마운트 때 부릅니다.

| deps | 실행 시점 |
|---|---|
| 없음 | 매 렌더 |
| `[]` | 처음 한 번 (예: App의 `/` 단축키 리스너) |
| `[a, b]` | a나 b가 바뀔 때 (`Object.is` 비교) |

**`useMemo(factory, deps)`** — deps가 그대로면 이전 결과 재사용
- 예) 통계 `stats`는 `todos`가 바뀔 때만 다시 셉니다. 입력창에 글자를 칠 때는 재사용합니다.

**무한 렌더 방지** — 입력 없이 **50번 넘게** 연달아 렌더되면 멈추고 오류를 냅니다 (deps 없는 effect 안에서 setState를 계속 부르는 경우).

### 5.9 폼 요소 — 속성과 프로퍼티

| | 뜻 | 예 |
|---|---|---|
| 속성 (attribute) | HTML에 쓰인 **처음 값** | `getAttribute("value")` |
| 프로퍼티 (property) | **지금 상태** | `el.value` |

- 사용자가 한 번 입력하면 `setAttribute("value", "")`로는 화면 글자가 지워지지 않습니다.
- 그래서 `setProp`은 `value` · `checked` · `selected`의 **프로퍼티도 함께** 맞춥니다 → 제어 컴포넌트가 됩니다.
- value가 이미 같으면 건드리지 않아 입력 중인 커서가 튀지 않습니다.

---

## 6. 전체 흐름 한 장 요약

> **핵심** 두 Phase 모두 **새 VDOM 만들기 → `diff` → `patch` → 마무리(기록 또는 effect)**.

### Phase 1

```
[페이지 열기]
실제 영역 ──containerToVdom──▶ VDOM₀ ──createElement──▶ 테스트 영역
                                 └──▶ history.push(VDOM₀)

[Patch 버튼]  onPatch
테스트 영역 ──containerToVdom──▶ 새 VDOM
diff(history.peek(), 새 VDOM) ──▶ 패치 목록      0개면 "변경 없음"으로 끝
patch(실제 영역, 패치 목록)                       실패하면 DOM 그대로, 기록 안 함
highlight → history.push → 자가 점검

[뒤로 · 앞으로 · 기록 목록 클릭]  moveTo
대상 = history.undo() / redo() / go(i)
patch(실제 영역, diff(이전, 대상))                실패하면 History 위치 되돌림
renderTestArea(대상)                             테스트 영역은 통째로 다시 그림
```

### Phase 2

```
[처음 실행]  mount
new FunctionComponent(App, #root).mount()
 └─ render: App() 실행 → Hook 16개가 hooks[0..15] 칸을 만듦
 └─ 노드를 모두 만든 뒤 한 번에 넣기
 └─ commit: 이벤트 리스너 달기 → effect 실행

[클릭 · 입력]
클릭 → handleEvent(위임) → 핸들러 → setState
setState: 같은 값이면 끝 / 다르면 저장 → scheduleUpdate (1번 예약)
update: render → diff → patch(#root) → commit → 바뀐 deps 의 effect 실행
```

---

## 7. 함수별 구현

> **핵심** 파일별 함수 목록입니다. 원리는 4 · 5장, 여기는 찾아보기용입니다. ★ = 팀 뼈대에 있던 함수(이름 그대로).

<details>
<summary><b>7.1 <code>core/vdom.js</code></b> — 실제 DOM ↔ VDOM</summary>

| 함수 | 하는 일 |
|---|---|
| ★ `h(type, props, ...children)` | VNode 만들기. 태그 소문자, props 얕은 복사(`null` → `{}`), 자식 정리(배열 펼치기 · `null`/불리언 버리기 · 숫자 → 문자열) |
| ★ `domToVdom(node)` | 실제 DOM → VNode(재귀). 속성을 `Object.fromEntries`로 옮김. 입력값처럼 속성이 아닌 상태는 옮기지 않음 |
| ★ `createElement(vnode)` | VNode → 실제 DOM(재귀). 잘못된 VNode면 `TypeError` |
| `containerToVdom(container)` | 영역 안 내용만 가상 div로 감쌈 ([4.1](#41-실제-dom--vdom-domtovdom-containertovdom)) |
| `isIgnorableNode` · `vdomChildNodes` | 주석 · 들여쓰기 공백 제외 규칙 (diff와 patch가 함께 씀) |
| `childHost(node)` | `<template>`이면 `content`, 아니면 그대로 (template의 자식은 `content` 안에 있음) |
| `setProp(el, name, value)` | `null`/`false` → 제거, `true` → 값 없는 속성, 나머지 → 문자열. 쓸 수 없는 이름은 경고 후 건너뜀 |
| `syncFormProperty` | `setProp` 안에서 `value` · `checked` · `selected` 프로퍼티도 맞춤 ([5.9](#59-폼-요소--속성과-프로퍼티)) |
| `isElementVNode(value)` | 요소 VNode 모양인지 (노드 하나만, 자식은 안 봄) |
| `validateVNode` · `checkProps` | 트리 전체 검사, 틀린 위치를 담은 `TypeError` |

</details>

<details>
<summary><b>7.2 <code>core/diff.js</code></b> — 두 VDOM 비교</summary>

| 함수 | 하는 일 |
|---|---|
| `PATCH` | 패치 종류 상수 (`CREATE` · `REMOVE` · `REPLACE` · `TEXT` · `PROPS`) |
| ★ `diff(old, new, { trustOld })` | 검사(`trustOld`면 이전 트리 검사 생략) 후 패치 목록 생성 |
| `walk(old, new, path, patches)` | 다섯 경우 판정 ([4.2](#42-diff-알고리즘-diff)) |
| `diffProps(old, new)` | `{ set, remove }` 또는 `null`. `Object.hasOwn`으로 `toString` 같은 이름 오판 방지 |

</details>

<details>
<summary><b>7.3 <code>core/patch.js</code></b> — 실제 DOM에 반영</summary>

| 함수 | 하는 일 |
|---|---|
| ★ `patch(container, patches)` | 3단계 적용 ([4.3](#43-patch--3단계로-나눈-이유-patch)). 바뀐 노드 목록을 돌려줌(강조용) |
| `applyOne(job)` | 패치 종류별 DOM 조작 |
| `resolvePath(container, path, cache)` | 경로로 노드 찾기, 자식 목록 캐시 |

</details>

<details>
<summary><b>7.4 <code>core/component.js</code></b> — 함수형 컴포넌트</summary>

| 함수 | 하는 일 |
|---|---|
| ★ `FunctionComponent(component, container, props)` | 상태 · VDOM · 핸들러를 들고 있는 상자 |
| ★ `mount()` · ★ `update()` | 첫 렌더 / 다시 렌더 ([5.5](#55-렌더-한-번의-흐름-update)) |
| `render()` · `commit()` · `guard()` | 컴포넌트 실행 / 결과 확정 / 실패 시 정리 |
| `scheduleUpdate()` · `flush()` | 배칭 예약 / 실행 + 무한 렌더 감지(`MAX_NESTED_UPDATES` = 50) |
| `handleEvent(event)` | 이벤트 위임 |
| `unmount()` | effect 정리 · 리스너 제거 · 컨테이너 비우기 |
| `onCommit(listener)` | 화면 반영마다 알림 (강조 · 테스트용) |
| `stateless(render)` | 자식 컴포넌트 정의, 안에서 Hook 금지 |
| `extractHandlers(root)` | 함수 → `data-on-*` 번호 ([5.6](#56-이벤트--vdom-형식을-지키면서-함수-연결하기)) |
| `eventNameOf(name)` | `onClick` → `click`. 예외: `onFocus` → `focusin`, `onBlur` → `focusout`, `onDoubleClick` → `dblclick` |

</details>

<details>
<summary><b>7.5 <code>core/hooks.js</code></b> — Hooks</summary>

| 함수 | 하는 일 |
|---|---|
| ★ `useState` · ★ `useEffect` · ★ `useMemo` | [5.2](#52-hooks의-원리--상태는-어디에-남는가) ~ [5.8](#58-useeffect--usememo) |
| `nextHook(kind, create)` | 모든 Hook의 입구. 렌더 중 아님 · 자식 안 · 종류 바뀜 · 개수 늘어남이면 오류 |
| `prepareHooks` · `finishHooks` | 렌더 앞뒤. 개수가 줄어도 오류 |
| `enterChild` · `exitChild` | `stateless` 자식 실행 구간 표시 (깊이를 셈). 이 안에서 Hook을 부르면 오류 |
| `isRendering` | 렌더 중인가 (렌더 도중 `setState` 막기) |
| `checkArgs` | `useEffect` · `useMemo` 인자 검사 (함수인지, deps가 배열인지) |
| `depsChanged` | deps 없음 → 항상 바뀜, 길이 · 값(`Object.is`) 비교 |
| `runEffects` · `runAllCleanups` | "이전 cleanup → callback" / 언마운트 때 전부 정리 |

</details>

<details>
<summary><b>7.6 <code>phase1/history.js</code></b> — State History</summary>

| 함수 | 하는 일 |
|---|---|
| ★ `push(vdom, meta)` | 복사본을 먼저 만든 뒤 앞으로가기 기록을 버리고 붙임 |
| ★ `undo()` · ★ `redo()` · `go(i)` | 이동 후 복사본, 못 가면 `null` |
| `current()` · `peek()` | 복사본 / 복사 없는 읽기 전용 |
| `canUndo` · `canRedo` · `position` · `entries` · `reset` | 버튼 상태 · 위치 표시 · 목록 · 초기화 |

</details>

<details>
<summary><b>7.7 <code>phase1/main.js</code></b> — Phase 1 화면</summary>

| 함수 | 하는 일 |
|---|---|
| `init()` | 첫 화면 + 버튼 연결, 미리보기 ↔ 소스 편집기 동기화 |
| `onPatch(source)` · `moveTo(move, reason)` | [6장](#6-전체-흐름-한-장-요약) 흐름 그대로 |
| `runExample(example)` | 예시 버튼: 테스트 영역을 고친 뒤 바로 `onPatch` |
| `toHtml(nodes)` | VDOM → 들여쓴 HTML(소스 편집기용), 이스케이프 |
| `reportResult` · `highlight` · `checkRequiredElements` | 자가 점검 · 강조 · 필수 id 12개 확인 |

</details>

<details>
<summary><b>7.8 <code>app/</code></b> — Phase 2 할 일 앱</summary>

| 함수 | 하는 일 |
|---|---|
| `app/main.js` | `FunctionComponent(App, #root).mount()`, 바뀐 노드 강조 |
| `App()` | 상태 10 · `useMemo` 2(`stats`, `visible`) · `useEffect` 4(저장 · 탭 제목 · `/` 단축키 · 수정창 포커스) |
| `changeTodos` · `remember` · `undo` | 바꾸기 전 목록을 `past`에 쌓기(최대 20), 되돌리기 |
| `addBatch` | `setTodos` 3번, 렌더 1번 |
| `move` · `startEdit` · `saveEdit` · `editKey` | 순서 옮기기, 더블클릭 수정 |
| `loadTodos` | localStorage를 읽어 모양 검사, 틀리면 예시 목록 |
| `setField(key, value)` | 테스트 패널 값 하나만 바꾼 새 객체 |
| 자식 컴포넌트 | `Header` · `TodoForm` · `Toolbar` · `TodoList` · `TodoItem` · `TestPanel` 모두 `stateless` |

</details>

---

## 8. 화면 기능

> **핵심** Phase 1은 예시 버튼 20개로 패치 종류를 눈으로 보고, Phase 2는 할 일 앱과 테스트 패널로 State → Patch를 봅니다.

### 8.1 Phase 1 (`index.html`)

**구성:** 실제 영역 · 테스트 영역(직접 편집 + 소스 편집기) · 예시 버튼 · State History · 마지막 Diff 결과 · 현재 VDOM JSON

**예시 변경 버튼 20개** — 누르면 테스트 영역을 고치고 바로 Patch 합니다.

| 나오는 패치 | 예시 |
|---|---|
| TEXT | 제목 글자 바꾸기 |
| PROPS | 부제 색 · 제목 title · 체크박스 · details · 버튼 끄기 · 입력 칸 값 · 완료 표시 뒤집기 |
| CREATE | 목록 끝에 추가 · 카드 추가 · HTML 같은 글자 넣기(보안) |
| REMOVE | 마지막 항목 삭제 · 추가한 카드 삭제 · 모두 비우기 |
| REPLACE | em ↔ i 태그 바꾸기 · 굵은 글씨 풀기 |
| 섞임 | 목록 순서 뒤집기 · 맨 앞 항목 삭제(key 없음 한계) · 여러 곳 한꺼번에 · 처음 상태로 |

**"테스트" 카드 (실제 영역 안)** — 폼(input 7종 · 체크박스 · 라디오 · select · textarea · 버튼들), details · dialog · progress · meter · output · 표 · ol · dl · blockquote · figure · pre · address

### 8.2 Phase 2 (`app.html`)

**할 일 앱** — `App.js`, Hook 16개 (state 10 · memo 2 · effect 4)

| 기본 | 추가한 기능 |
|---|---|
| 추가 · 체크 · 삭제 | 우선순위(높음 · 보통 · 낮음)와 정렬 |
| 필터 · 검색 (`/` 단축키) | 더블클릭 수정 (Enter 저장 · Esc 취소) |
| 완료 지우기 | 위 · 아래로 순서 옮기기 |
| localStorage 저장 | 전체 완료 · 되돌리기(최대 20번) · "3개 추가"(배칭 데모) · "처음 목록으로" |

**테스트 패널** — 할 일 앱 아래. HTML 입력 요소를 상태와 묶어 State → Diff → Patch를 확인합니다.

| 묶음 | 내용 |
|---|---|
| 입력 | 글자 · 이메일 · 비밀번호 · 숫자 · 범위 · 색 · 날짜 · 시각 · 여러 줄 |
| 선택 | select(optgroup) · 체크박스 · 라디오 |
| 버튼 | 클릭 +1 · input 버튼 · 대화상자 열기 · 꺼진 버튼 · 초기화 |
| 결과 | progress · meter · output |
| 기타 | details(상태 없음) · dialog(상태로 여닫기) · 입력 잠그기 |
| 지금 상태 | 모든 값을 표로 → 바뀐 칸만 TEXT 패치 |

---

## 9. 테스트

> **핵심** 722개 모두 통과 (Chrome). `tests/index.html`을 열면 직접 만든 러너(`runner.js`)로 모두 실행됩니다.

- **모든 HTML 태그(112개):** Phase 1은 만들기 → 다시 읽기 → HTML 왕복 → patch → REPLACE, Phase 2는 클릭 → setState → 같은 요소에서 속성 · 글자만 바뀌는지
- **랜덤:** 시드 고정 무작위 트리로 `patch(diff(A, B))` 결과가 B와 같은지
- **페이지:** 실제 `index.html` · `app.html`을 iframe으로 열어 클릭 · 입력

<details>
<summary><b>묶음별 개수</b></summary>

| Phase 1 (477) | 개수 | Phase 2 (245) | 개수 |
|---|---|---|---|
| VDOM 생성 · 변환 | 80 | 컴포넌트 | 46 |
| Diff · Patch · Props | 93 | Hooks | 36 |
| History · toHtml | 62 | 할 일 앱 · 테스트 패널 | 51 |
| 랜덤 · 보안 | 24 | 모든 HTML 태그 | 112 |
| 잘못된 입력 | 36 | | |
| 페이지 | 25 | | |
| 예시 버튼 · 테스트 카드 | 42 | | |
| 모든 HTML 태그 (+ template · 한꺼번에) | 115 | | |

</details>

전체 목록: [test-list.md](./test-list.md)

---

## 10. 실제 React와 비교

> **핵심** 기본 원리(위치 기준 Diff, 호출 순서로 찾는 Hook)는 같고, key · Fiber · 우선순위 스케줄러가 없습니다.

| 항목 | 이 구현 | 실제 React |
|---|---|---|
| Diff 기본 규칙 | 같은 위치끼리, 태그가 다르면 통째로 교체 | **같음** |
| 상태 저장 | `hooks` 배열, 호출 순서로 | Fiber의 Hook 목록, 호출 순서로 — **같음** |
| 자식 짝짓기 | 인덱스만 | `key`로 짝짓고 **이동** 처리 |
| 비교 대상 | VDOM 스냅샷 두 개 | 새 요소 ↔ 현재 Fiber 트리 |
| 노드 찾기 | 매번 경로(`[1, 0, 2]`)로 | Fiber가 DOM 노드를 직접 가짐 |
| 상태를 가질 수 있는 곳 | 루트만 | 모든 함수 컴포넌트 |
| 다시 그리는 범위 | 루트 전체 | 바뀐 컴포넌트만 (`memo`로 건너뛰기도) |
| 렌더 예약 | `queueMicrotask` 1회 | 우선순위 스케줄러 + 자동 배칭 |
| 렌더 중단 | 없음 | Concurrent 렌더링 |
| 이벤트 | 위임 + `data-on-*` 번호 | 위임 + 합성 이벤트 |
| effect 시점 | commit 직후 동기 | 화면을 그린 뒤 비동기 |
| Hook 규칙 위반 | 매 렌더 검사해 오류 | 개발 모드 경고 + ESLint |
| DOM 읽기 | Phase 1은 실제 DOM을 다시 읽음 | DOM을 읽지 않음 |

---

## 11. 한계와 남은 일

**한계**

| 한계 | 결과 |
|---|---|
| key 없음 | 맨 앞을 지우면 뒤 항목이 모두 TEXT · PROPS로 바뀜 ([4.2 예시 2](#예시-2--key가-없어서-생기는-일)) |
| `<svg>` · `<math>` | 다른 이름공간이라 지원 안 함 |
| Phase 1 프로퍼티 | 테스트 영역에서 직접 입력 · 클릭한 값은 VDOM · Patch에 안 잡힘 |
| 재귀 | 깊이 약 5,000단계가 넘으면 호출 스택 한도 |
| History | 크기 제한 없음 |
| 브라우저 | Firefox · Safari · 모바일은 마지막 UI 정리 뒤 확인 안 함 |

**남은 일**
- `dev`로 PR (base가 `dev`인지 확인)

---

## 12. 용어 정리

<details>
<summary><b>용어 18개 펼치기</b></summary>

| 용어 | 뜻 |
|---|---|
| VDOM / VNode | 화면을 표현한 자바스크립트 객체 / 그 노드 하나 |
| Diff | 이전 · 새 VDOM을 비교해 패치 목록을 만드는 계산 |
| Patch | 패치 목록을 실제 DOM에 적용하는 일 |
| path | 루트에서 대상까지의 자식 번호 배열. 예) `[2, 0]` |
| Reflow / Repaint | 레이아웃 다시 계산 / 다시 칠하기 |
| 컨테이너 | VDOM을 그려 넣는 실제 요소 (`#real-area`, `#root`) |
| mount / update / unmount | 첫 렌더 / 다시 렌더 / 제거 |
| commit | 렌더 결과를 확정하고 effect를 실행하는 마지막 단계 |
| Batching | setState 여러 번을 렌더 한 번으로 |
| 마이크로태스크 | 지금 코드가 끝나자마자, 화면을 그리기 전에 실행되는 작업 |
| 이벤트 위임 | 컨테이너 하나에서 이벤트를 받아 처리 |
| stateless | 상태 없는 자식 컴포넌트 |
| Lifting State Up | 상태를 공통 부모(루트)로 올리는 것 |
| deps | `useEffect` · `useMemo`의 의존성 배열 |
| cleanup | effect가 돌려준 정리 함수 |
| 제어 컴포넌트 | 입력값을 상태로 관리하는 폼 요소 |
| 속성 / 프로퍼티 | HTML에 쓰인 처음 값 / 지금 상태 |
| key | 실제 React의 자식 이름표. 이 구현에는 없음 |

</details>

---

## 13. 커밋 기록

<details>
<summary><b>커밋 8개 펼치기</b></summary>

| 커밋 | 날짜 | 내용 |
|---|---|---|
| `19b43f5` | 11-06 | 프로젝트 뼈대 및 공통 인터페이스 |
| `afbc9c9` | 11-06 | Phase 1 VDOM/Diff/Patch, Phase 2 Component/State/Hooks 구현 |
| `3378230` | 11-07 | 코드 정리와 최적화 (Inspector 제거, 재귀로 단순화) |
| `f6f3876` | 11-07 | 기능은 그대로 두고 코드 양 줄이기 |
| `a8997fe` | 11-09 | 모든 소스 파일에 자세한 한글 주석 |
| `ef8e132` | 11-09 | 예시 버튼 · 테스트 영역, 두 페이지 디자인 통일, 모든 HTML 태그 테스트 |
| `e14ea0c` | 11-09 | vdom.js에 빠진 `childHost` 다시 추가 |
| `40418db` | 11-09 | dev merge (redis 뼈대, react 폴더는 그대로) |

</details>
