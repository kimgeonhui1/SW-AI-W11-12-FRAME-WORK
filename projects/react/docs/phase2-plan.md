# Phase 2 기획서 — Component / State / Hooks

> 작성일: 2026-11-06 · 범위: `projects/react` Phase 2 (`app.html`)
> 제약: HTML · CSS · JavaScript만 사용 (React · Vue 등 외부 프레임워크, 라이브러리, 번들러 없음)
> 전제: Phase 1의 `h` · `createElement` · `diff` · `patch`를 그대로 재사용한다.

---

## 1. 목표

함수형 컴포넌트가 **상태(State)** 를 가지고, 상태가 바뀌면 **새 Virtual DOM → Diff → Patch** 로
**바뀐 부분만** 실제 DOM에 반영되는 "동작하는 미니 React"를 만든다.
그리고 이것으로 사용자의 입력 · 클릭에 따라 부분 업데이트되는 웹 페이지(할 일 보드)를 만든다.

핵심 질문: **"함수는 매번 새로 실행되는데, 상태는 어떻게 유지할까?"**
→ 상태를 함수 안이 아니라 함수 **바깥의 컴포넌트 인스턴스(`FunctionComponent.hooks` 배열)** 에 두고,
Hook을 **호출 순서(인덱스)** 로 찾아온다.

## 2. 요구사항

| # | 요구사항 | 구현 위치 |
|---|---|---|
| P1 | 함수형 컴포넌트를 감싸는 `FunctionComponent` 클래스 | `core/component.js` |
| P2 | 그 클래스에 `hooks` 배열(상태 저장), `mount()`(처음 렌더링), `update()`(상태 변경 후 다시 렌더링) | `core/component.js` |
| P3 | Hook은 최상위(루트) 컴포넌트에서만 사용 | `core/hooks.js` — 자식 안에서 부르면 오류 |
| P4 | State는 루트 컴포넌트에서만 관리, 자식은 props만 받는 순수 함수 (Lifting State Up) | `core/component.js` `stateless()`, `app/components/*` |
| P5 | State가 바뀌면 화면이 자동으로 다시 그려짐 | `useState`의 setter → `scheduleUpdate()` |
| P6 | `useState` / `useEffect` / `useMemo` | `core/hooks.js` |
| P7 | 다시 렌더링할 때 Phase 1의 VDOM → Diff → Patch를 그대로 사용 | `FunctionComponent.update()` |
| P8 | 사용자 입력 · 클릭에 따라 화면이 바뀌는 테스트 페이지 | `app.html`, `app/*` |
| 선택 | 여러 상태 변경을 한 번에 처리 (Batching) | `scheduleUpdate()` — 마이크로태스크로 모아서 한 번 렌더 |
| 품질 | 단위 테스트(컴포넌트 · Hook 각각), 기능 테스트(페이지), 엣지 케이스 | `tests/component.test.js`, `tests/hooks.test.js`, `tests/app.test.js` |

## 3. 팀 공통 규칙 (변경 금지)

- `src/core/`의 파일 이름, 함수 이름은 그대로 둔다. Phase 2 뼈대에 있던 이름도 그대로 쓴다:
  `FunctionComponent(component, container)`, `hooks`, `mount()`, `update()`, `useState`, `useEffect`, `useMemo`.
- Virtual DOM 형식(`{type, props, children}` / 문자열)은 바꾸지 않는다.
  → `diff` · `patch`로 넘어가는 VDOM은 Phase 1과 **완전히 같은 형식**이다. 이벤트 함수도 VDOM에 넣지 않는다(5.4절).
- 함수를 **추가로 export** 하는 것은 허용.

## 4. 화면 구성 (`app.html`)

```
┌─────────────────────────────────────────────┐
│ #root  — App (루트 컴포넌트, 모든 상태)        │
│  Header      진행률 · 전체/남음/완료           │
│  TodoForm    입력창 · 중요도 · 추가 버튼        │
│  Toolbar     필터 · 검색 · 완료 지우기 ·        │
│              "setState 3번" 배칭 버튼           │
│  TodoList    TodoItem × n (체크 · 삭제)         │
└─────────────────────────────────────────────┘
```

- 주제: **할 일 보드**. 추가 · 완료 체크 · 삭제 · 필터 · 검색 · 완료 항목 지우기.
- 다시 렌더될 때 바뀐 노드를 잠깐 강조한다(`onCommit` 구독). (처음 계획의 "렌더 관찰 패널"은 만들었다가 코드 정리 때 뺐다)

## 5. 설계

### 5.1 `FunctionComponent` (core/component.js)

```
new FunctionComponent(component, container, props?)
  hooks      : Hook 상태 배열. hooks[i] = 이번 렌더에서 i번째로 호출된 Hook의 상태
  vdom       : 마지막으로 화면에 반영한 루트 VDOM ({type:"div", props:{}, children})
  mount()    : 처음 렌더링 — 함수 실행 → VDOM → createElement 로 컨테이너를 채움 → effect 실행
  update()   : 다시 렌더링 — 함수 실행 → 새 VDOM → diff(이전, 새) → patch(container) → effect 실행
  unmount()  : effect 정리(cleanup), 이벤트 리스너 제거, 컨테이너 비움
  scheduleUpdate() : setState가 부름. 이미 예약돼 있으면 아무것도 안 함 (배칭)
  flush()    : 예약된 update를 지금 바로 실행 (테스트용)
  onCommit(fn) : 화면에 반영할 때마다 fn({ renderCount, reason, patches, touched, ms }) — 구독 해제 함수 반환
```

렌더 한 번의 순서

1. `prepareHooks(this)` — "지금 렌더 중인 컴포넌트"를 이 인스턴스로, Hook 인덱스를 0으로
2. `component(props)` 실행 → Hook들이 `hooks[0]`, `hooks[1]` … 을 순서대로 읽고 씀
3. `finishHooks()` — Hook 개수 · 종류가 이전 렌더와 같은지 확인
4. 결과를 루트 VDOM으로 정리 + 이벤트 함수를 떼어 내기(5.4절)
5. `diff` → `patch` (여기까지 오류가 나면 실제 DOM은 그대로 — Phase 1의 원자적 patch)
6. `onCommit` 알림 → `useEffect` 실행

### 5.2 Hooks (core/hooks.js)

| Hook | hooks[i]에 저장하는 것 | 동작 |
|---|---|---|
| `useState(initial)` | `{ kind:"state", value, setState }` | 처음에만 `initial`(함수면 실행 결과)로 시작. `setState(값 또는 이전값=>새값)` — `Object.is`로 같으면 아무것도 안 함, 다르면 값을 바꾸고 `scheduleUpdate()`. setter는 렌더가 바뀌어도 같은 함수 |
| `useEffect(fn, deps)` | `{ kind:"effect", deps, cleanup, pending }` | 렌더 중에는 "실행 예정" 표시만. 화면 반영(commit) 뒤에 이전 cleanup → fn 실행. deps 없음: 매번 / `[]`: 처음 한 번 / `[a,b]`: 하나라도 `Object.is`로 다를 때 |
| `useMemo(factory, deps)` | `{ kind:"memo", deps, value }` | deps가 같으면 저장한 값 재사용, 다르면 factory 다시 실행 |

규칙 검사 (어기면 이유를 적은 오류)

- 렌더 중이 아닐 때 Hook 호출 → 오류
- **자식 컴포넌트(`stateless`) 안에서 Hook 호출 → 오류** (P3)
- 렌더할 때마다 Hook 순서 · 종류 · 개수가 같아야 함 (조건문 안에서 Hook을 부르면 오류)
- 렌더 도중 `setState` → 오류 (무한 렌더 방지)
- `useEffect` 안의 `setState`가 끝없이 렌더를 부르면 50번째에서 멈추고 오류
- 언마운트 뒤의 `setState`는 무시

### 5.3 State 위치와 자식 컴포넌트 (Lifting State Up)

- 모든 상태는 `App`(루트)에만 있다: `todos`, `draft`, `priority`, `filter`, `query`.
- 자식은 `stateless(props => VNode)`로 정의한 **순수 함수**다. 상태 대신 props(값과 콜백)를 받는다.
  자식에서 상태를 바꾸고 싶으면 부모가 내려 준 콜백(`onToggle(id)` 등)을 부른다 → 부모의 `setState` → 루트 다시 렌더.
- `stateless`는 함수를 실행하는 동안 "자식 렌더 중" 표시를 켜서, 그 안에서 Hook을 부르면 오류가 나게 한다.

### 5.4 이벤트 — VDOM 형식을 지키면서 함수 연결하기

- 컴포넌트는 React처럼 `h("button", { onClick: () => … })`로 함수를 넘긴다.
- 렌더 결과를 `diff`에 넘기기 **전에** `on대문자…` 함수 props를 떼어 내고, 그 자리에
  `data-on-click="3"` 같은 **문자열 속성**을 넣는다. 함수는 이번 렌더의 핸들러 표(`Map`)에 `3 → 함수`로 보관한다.
  → `diff` · `patch`가 보는 VDOM은 Phase 1과 같은 문자열 속성뿐이다.
- 컨테이너에 이벤트 종류별로 리스너를 **하나만** 단다(이벤트 위임, React도 루트에서 위임).
  이벤트가 오면 `event.target`부터 위로 올라가며 `data-on-<종류>`가 있는 요소의 핸들러를 **최신 표**에서 찾아 부른다.
- 번호는 렌더할 때마다 트리 순서대로 다시 매기므로 구조가 같으면 번호도 같다 → 핸들러 함수가 매번 새로 만들어져도 패치가 생기지 않는다.
- 이름 규칙: `onClick` → `click`, `onInput` → `input`, `onChange` → `change`, `onSubmit` → `submit`, `onKeyDown` → `keydown`, `onFocus` → `focusin`, `onBlur` → `focusout` (위임하려면 버블링되는 이벤트가 필요).

### 5.5 폼 요소의 현재 값 (Phase 1 보고서 10장의 숙제)

- `setAttribute("value")`는 사용자가 이미 입력한 `<input>`의 화면 값을 바꾸지 못한다(속성 ≠ 프로퍼티).
- `setProp`에서 `value` · `checked` · `selected`는 속성과 함께 **프로퍼티도** 맞춘다(값이 같으면 건드리지 않아 커서 위치 유지).
- `patch`의 속성 삭제도 `setProp(…, null)`을 거치게 해서 프로퍼티를 같이 끈다.
  → "추가 후 입력창 비우기", "체크 상태 되돌리기" 같은 제어 컴포넌트(controlled input)가 동작한다.

### 5.6 Batching (선택 과제)

- `setState`는 바로 렌더하지 않고 `queueMicrotask`로 **한 번만** 예약한다.
- 같은 이벤트 처리 안에서 `setState`를 여러 번 불러도, 이벤트 처리가 끝난 직후 **렌더 1번**으로 모두 반영된다.
- 함수형 업데이트(`setX(x => x + 1)`)는 차례로 적용되므로 3번 부르면 +3, 값 업데이트(`setX(x + 1)`)는 같은 x를 보므로 +1 (React와 같음).
- 데모: "예시 3개 추가" 버튼이 `setTodos`를 3번 부르고, 렌더 횟수가 1만 늘어나는 것을 테스트로 확인한다.

## 6. 파일 구성

| 파일 | 내용 |
|---|---|
| `src/core/hooks.js` | `useState` · `useEffect` · `useMemo`, 렌더 중인 컴포넌트 · Hook 인덱스 관리(`prepareHooks` · `finishHooks` 등 내부용 export) |
| `src/core/component.js` | `FunctionComponent`, `stateless`, 이벤트 위임, effect 실행, 배칭 |
| `src/core/vdom.js` | `setProp`에 `value` · `checked` · `selected` 프로퍼티 동기화 추가 |
| `src/core/patch.js` | `PROPS`의 속성 삭제도 `setProp`을 거치게 |
| `src/app/App.js` | 루트 컴포넌트 — 모든 상태, `useMemo`(보이는 목록 · 통계), `useEffect`(저장 · 제목 · 단축키) |
| `src/app/components/*.js` | `Header` · `TodoForm` · `Toolbar` · `TodoList` · `TodoItem` (stateless 자식만) |
| `src/app/main.js` | `#root`에 App을 마운트, 바뀐 노드 강조 |
| `app.html` | `#root` + Phase 1 페이지 링크 |
| `src/styles/style.css` | Phase 2 스타일 구역 추가 |
| `tests/component.test.js` · `tests/hooks.test.js` · `tests/app.test.js` | 단위 · 기능 테스트 |
| `docs/phase2-report.md` | 만든 뒤 보고서 |

## 7. 테스트 계획

- **component**: mount 결과 DOM, update가 바뀐 노드만 고치는지(노드 객체가 그대로인지), 이벤트 위임 · 버블링 · `stopPropagation`, 핸들러가 최신 함수인지, 핸들러가 매번 새 함수여도 패치가 없는지, `stateless` 안의 Hook 오류, Hook 순서 · 개수 오류, 렌더 오류 시 DOM 그대로, unmount, onCommit, 여러 루트 독립.
- **hooks**: `useState`(초깃값 · 지연 초기화 · 함수형 업데이트 · `Object.is` 같으면 렌더 안 함 · setter 고정 · 배칭 · 렌더 중 호출 오류 · 언마운트 뒤 무시), `useEffect`(commit 뒤 실행 · deps 없음/`[]`/변화 · cleanup 순서 · 언마운트 cleanup · effect 안 setState · 무한 반복 멈춤 · 잘못된 deps), `useMemo`(재사용 · 재계산 · deps 없음).
- **app (iframe으로 `app.html`)**: 추가 · 빈 입력 무시 · 입력창 비워짐 · 체크 · 삭제 · 필터 · 검색 · 완료 지우기 · 배칭 버튼(렌더 1번) · 새로고침 뒤 유지(localStorage) · 콘솔 오류 없음.
- Chrome · Firefox · Safari에서 전체 테스트(Phase 1 포함) 실행.

## 8. 범위 밖 (보고서에 한계로 기록)

- key 기반 자식 비교(목록 앞에서 지우면 뒤 항목이 모두 바뀐 것으로 나옴)
- 자식 컴포넌트의 상태 · Hook(과제 제약상 의도적으로 막음), Context, Ref, 에러 경계
- 렌더 중단 · 우선순위(React Fiber의 concurrent rendering)
