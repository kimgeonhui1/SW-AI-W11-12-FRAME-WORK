# Phase 2 보고서 — Component / State / Hooks

> 작성일: 2026-11-06 · 범위: `projects/react` Phase 2 (`app.html`) · 기획서: `docs/phase2-plan.md`
> 외부 라이브러리 · 프레임워크 없이 HTML · CSS · JavaScript(ES 모듈)만 사용

---

## 1. 요약

- 함수형 컴포넌트를 감싸는 **`FunctionComponent`**(`hooks` 배열, `mount()`, `update()`)와 **`useState` · `useEffect` · `useMemo`** 를 직접 구현했다.
- 상태가 바뀌면 **새 VDOM → Phase 1의 `diff` → Phase 1의 `patch`** 로 바뀐 노드만 실제 DOM에 반영한다. Phase 1 코드는 이름 · 형식을 바꾸지 않고 그대로 재사용했다.
- 규칙을 코드로 강제한다: **Hook은 루트 컴포넌트에서만**(자식 안에서 부르면 오류), Hook 순서 · 개수가 바뀌면 오류, 렌더 중 `setState` 오류, effect 무한 반복은 50번에서 멈춤.
- **Batching**(선택 과제): `setState`를 여러 번 불러도 마이크로태스크로 모아 **렌더 1번**.
- 데모: **할 일 보드**(추가 · 체크 · 삭제 · 필터 · 검색 · 완료 지우기 · 저장). 다시 렌더될 때 바뀐 노드를 잠깐 강조한다. (한때 렌더 횟수 · 패치 목록 · hooks 배열을 보여 주는 "렌더 관찰 패널"을 두었지만, 과제 요구사항이 아니어서 코드 정리 때 뺐다)
- 테스트 **422개 전부 통과** — Phase 1의 320개 + Phase 2 테스트 102개(컴포넌트 46 · Hook 36 · 페이지 20). 코드 정리 전에는 601개(Phase 1 498 + Phase 2 103)였다.
  - **2026-11-09 기준: 722개 전부 통과** — Phase 1 477개 + Phase 2 245개(컴포넌트 46 · Hook 36 · 페이지 · 테스트 패널 51 · 모든 HTML 태그 112). 자세한 목록은 [test-list.md](./test-list.md).

## 2. 요구사항별 구현 결과

| # | 요구사항 | 구현 | 결과 |
|---|---|---|---|
| P1 | 함수형 컴포넌트를 감싸는 `FunctionComponent` 클래스 | `core/component.js` | ✅ |
| P2 | `hooks` 배열 · `mount()` · `update()` | 같은 파일. `unmount()` · `onCommit()` 추가 | ✅ |
| P3 | Hook은 최상위 컴포넌트에서만 | `stateless()`가 자식 실행 중 표시 → Hook이 오류 | ✅ 강제 |
| P4 | State는 루트에서만, 자식은 props만 받는 순수 함수 | `App`에 상태 10개(처음엔 5개), 자식 6개(`TestPanel` 포함)는 모두 `stateless` | ✅ |
| P5 | State가 바뀌면 자동으로 다시 그림 | `setState` → `scheduleUpdate` → `update` | ✅ |
| P6 | `useState` / `useEffect` / `useMemo` | `core/hooks.js` | ✅ |
| P7 | Phase 1의 VDOM · Diff · Patch로 바뀐 부분만 반영 | `update()` = `diff(this.vdom, 새 VDOM)` → `patch(container)` | ✅ 노드 재사용을 테스트로 확인 |
| P8 | 입력 · 클릭에 따라 바뀌는 페이지 | `app.html` 할 일 보드 | ✅ |
| 선택 | Batching | 마이크로태스크 1회 예약 | ✅ |
| 품질 | 모듈별 단위 테스트 · 기능 테스트 · 엣지 케이스 | `component` · `hooks` · `app` 테스트 102개 (지금은 모든 HTML 태그까지 245개) | ✅ |

## 3. 구조

```
projects/react/
├── app.html                       Phase 2 페이지 (#root)
├── src/core/
│   ├── component.js               FunctionComponent, stateless, 이벤트 위임, 배칭
│   ├── hooks.js                   useState / useEffect / useMemo, 렌더 중 컴포넌트 · Hook 인덱스 관리
│   ├── vdom.js                    (Phase 1) + setProp 의 value · checked · selected 프로퍼티 동기화
│   ├── diff.js                    (Phase 1 그대로)
│   └── patch.js                   (Phase 1) + 속성 삭제도 setProp 경유
├── src/app/
│   ├── main.js                    App 마운트, 바뀐 노드 강조
│   ├── App.js                     루트 컴포넌트 — 모든 상태
│   └── components/
│       └── Header.js  TodoForm.js  Toolbar.js  TodoList.js  TodoItem.js   (stateless 자식만)
└── tests/  component.test.js  hooks.test.js  app.test.js
```

### 3.1 공개 함수

| 파일 | 이름 | 설명 |
|---|---|---|
| `core/component.js` | `FunctionComponent(component, container, props?)` | 함수형 컴포넌트 인스턴스 |
| | `.hooks` | Hook 상태 배열 |
| | `.mount()` | 처음 렌더링 — 컴포넌트 실행 → VDOM → `createElement`로 컨테이너 채움 → effect |
| | `.update()` | 다시 렌더링 — 새 VDOM → `diff` → `patch` → effect. 패치 목록 반환 |
| | (추가) `.unmount()` | effect 정리, 이벤트 리스너 제거, 컨테이너 비움. 이후 `setState` 무시 |
| | (추가) `.scheduleUpdate()` / `.flush()` | 렌더 예약(배칭) / 예약된 렌더 즉시 실행 |
| | (추가) `.onCommit(fn)` | 화면 반영마다 `{renderCount, reason, patches, touched, ms}` 알림, 해제 함수 반환 |
| | (추가) `stateless(fn)` | 상태 없는 자식 컴포넌트 정의 (안에서 Hook 금지) |
| | (추가) `extractHandlers(tree)` · `eventNameOf(name)` · `MAX_NESTED_UPDATES` | 이벤트 함수 분리, 이벤트 이름 변환, 무한 렌더 한도(50) |
| `core/hooks.js` | `useState(initial)` | `[값, setState]` |
| | `useEffect(fn, deps?)` | 화면 반영 뒤 실행, cleanup 지원 |
| | `useMemo(factory, deps?)` | 계산 결과 재사용 |
| | (추가, 내부용) `prepareHooks` · `finishHooks` · `enterChild` · `exitChild` · `isRendering` · `runEffects` · `runAllCleanups` | `component.js`가 렌더 앞뒤에 부름 |

## 4. 핵심 원리 — "함수는 매번 새로 실행되는데, 상태는 어떻게 유지할까?"

```
FunctionComponent 인스턴스 (계속 살아 있음)
  hooks = [ {kind:"state", value:[…todos]}, {kind:"state", value:""}, … , {kind:"memo", …}, {kind:"effect", …} ]
                ▲ 0번                         ▲ 1번
App() 실행 (렌더마다 새로 실행)
  useState(loadTodos)  → hooks[0]      ← "몇 번째 Hook인가" 로 칸을 찾는다
  useState("")         → hooks[1]
  …
```

1. 렌더 직전 `prepareHooks(인스턴스)`가 "지금 렌더 중인 컴포넌트"를 모듈 변수에 두고 Hook 인덱스를 0으로 만든다.
2. 컴포넌트 함수 안의 `useState`는 그 인스턴스의 `hooks[인덱스]`를 읽고 인덱스를 1 올린다. 첫 렌더면 칸을 새로 만든다.
3. 함수가 끝나 지역 변수가 사라져도 값은 인스턴스의 `hooks` 배열에 남아 있다. 다음 렌더에서 **같은 순서로** 부르면 같은 칸을 다시 읽는다.
4. 그래서 Hook을 조건문 · 반복문 안에서 부르면 칸이 어긋난다. 이 구현은 칸마다 종류(`state`/`memo`/`effect`)를 기록해 두고, 종류나 개수가 달라지면 이유를 적은 오류를 낸다.

`setState`는 첫 렌더에서 한 번만 만든 함수라 렌더가 바뀌어도 같은 함수다(테스트로 확인). 자기 인스턴스와 칸을 클로저로 기억하므로 이벤트 · 타이머 · effect 어디서 불러도 된다.

## 5. 설계 결정

### 5.1 렌더 한 번의 흐름

```
setState(새 값)
 ├─ Object.is(새 값, 이전 값)이면 끝 (렌더 생략)
 └─ 값 저장 → scheduleUpdate()  ─ 이미 예약됐으면 끝 (배칭)
                 └─ queueMicrotask → flush() → update()
                        1. render()      prepareHooks → App(props) → finishHooks
                                         → h("div", null, 결과) 로 루트 정리 → 이벤트 함수 분리
                        2. diff(이전 VDOM, 새 VDOM, { trustOld: true })  ← Phase 1
                        3. patch(container, patches)    ← Phase 1 (입력 오류면 DOM 그대로)
                        4. commit        VDOM · 핸들러 표 교체, onCommit 알림
                        5. runEffects    deps가 바뀐 effect: cleanup → 실행
```

- 1~3에서 오류가 나면 실제 DOM은 그대로이고, 그 렌더에서 예약된 effect도 취소된다(테스트 "렌더 실패 시 그 렌더에서 예약된 effect는 실행되지 않음").
- `mount()`는 2~3 대신 `createElement`로 컨테이너를 채운다. 노드를 **모두 만든 뒤** 한 번에 `replaceChildren` 하므로 중간에 실패해도 컨테이너는 그대로다.
- **최적화**: `mount()`에서 첫 VDOM을 `validateVNode`로 한 번 검사해 두고, `update()`는 `diff(…, { trustOld: true })`로 이전 VDOM 검사를 건너뛴다. 이전 VDOM은 항상 지난 렌더에서 검사를 마친 트리이므로, 렌더마다 트리 순회가 1번 줄어든다.

### 5.2 State 위치 — Lifting State Up

- `App`(루트)에만 상태 10개: `todos`, `draft`, `priority`, `filter`, `query` (처음 5개) + `sorted`, `editingId`, `editText`, `past`, `testValues` (11-09 추가: 정렬 · 수정 · 되돌리기 · 테스트 패널).
- 자식 `Header` · `TodoForm` · `Toolbar` · `TodoList` · `TodoItem`은 `stateless(props => VNode)`로 정의한 순수 함수다. 값과 콜백만 props로 받는다.
- 예: 체크박스 클릭 → `TodoItem`의 `onChange` → 부모가 준 `onToggle(id)` → `App`의 `setTodos` → `App` 다시 렌더 → 통계(`Header`), 필터 개수(`Toolbar`), 항목(`TodoItem`)이 한 번에 맞춰진다. 상태가 한 곳에 있어서 화면끼리 어긋날 수 없다.
- `stateless`는 자식 함수를 실행하는 동안 표시를 켜서, 그 안에서 Hook을 부르면 `"…는 최상위(루트) 컴포넌트에서만 쓸 수 있습니다"` 오류를 낸다.

### 5.3 이벤트 — VDOM 형식을 바꾸지 않고 함수 연결하기

- 컴포넌트는 React처럼 `h("button", { onClick: () => … })`로 쓴다.
- 렌더 결과를 `diff`에 넘기기 전에 `extractHandlers`가 `on대문자…` 함수를 떼어 내고 `data-on-click="3"` 같은 **문자열 속성**으로 바꾼다. 함수는 이번 렌더의 핸들러 표에 둔다. → `diff` · `patch` · `validateVNode`가 보는 VDOM은 Phase 1과 같다(팀 규칙 "VDOM 형식 유지").
- 컨테이너에 이벤트 종류마다 리스너를 **하나만** 단다(이벤트 위임). 이벤트가 오면 `event.target`부터 위로 올라가며 `data-on-<종류>` 요소의 핸들러를 **최신 표**에서 찾아 부른다. `stopPropagation()`을 부르면 거기서 멈춘다.
- 번호는 트리 순서대로 매기므로 구조가 같으면 렌더마다 같다 → 핸들러가 매번 새 화살표 함수여도 **패치가 생기지 않는다**(테스트로 확인).
- `onFocus`/`onBlur`는 버블링되지 않아 위임할 수 없으므로 `focusin`/`focusout`으로 바꾼다. 문자열 핸들러(`onClick: "alert(1)"`)는 실행하지 않고 `TypeError`.

### 5.4 폼 요소 — 속성과 프로퍼티

- `<input value="a">`의 `value` **속성**은 처음 값일 뿐이라, 사용자가 입력한 뒤에는 `setAttribute`로 화면 값을 바꿀 수 없다.
- `setProp`이 `value`(input · textarea · select), `checked`(input), `selected`(option)는 **프로퍼티도** 맞춘다. 값이 이미 같으면 쓰지 않아 입력 중 커서가 튀지 않는다.
- `patch`의 속성 삭제도 `setProp(…, null)`을 거쳐 `checked` 같은 프로퍼티를 같이 끈다.
- 덕분에 "추가하면 입력창 비우기", "체크 해제 반영", "선택 유지" 같은 **제어 컴포넌트**가 동작한다.

### 5.5 `setState`는 상태 변경 외에 무엇을 하나

1. **같은 값이면 아무것도 안 함** — `Object.is` 비교. 렌더를 아낀다(객체는 새 객체면 다른 값 → 불변 업데이트 필요).
2. **렌더 예약** — 바로 그리지 않고 컴포넌트에 "다시 그려야 함"을 표시하고 마이크로태스크를 예약한다.
3. **배칭** — 이미 예약돼 있으면 또 예약하지 않는다. 같은 이벤트 처리 안의 여러 `setState`가 렌더 1번으로 합쳐진다.
4. **함수형 업데이트** — `setX(x => x + 1)`은 직전 값에 차례로 적용(3번 → +3). `setX(x + 1)`은 렌더 당시의 x를 보므로 3번 불러도 +1. React와 같다.
5. **안전장치** — 렌더 도중 호출은 오류(무한 렌더 방지), 언마운트 뒤 호출은 무시.

### 5.6 Batching (선택 과제)

- `queueMicrotask`는 지금 실행 중인 코드(이벤트 핸들러)가 끝나자마자, 브라우저가 화면을 그리기 **전에** 실행된다. 그래서 한 번의 클릭에서 부른 `setState`들이 모두 반영된 상태로 한 번만 렌더하고, 사용자는 중간 상태를 보지 않는다.
- 데모: "3개 추가" 버튼은 `setTodos`를 3번 부른다. 렌더 횟수(`app.renderCount`)는 1만 늘어난다(페이지 테스트로 확인). 할 일 추가도 `setTodos` + `setDraft` 두 번이지만 렌더 1번.
- 무한 반복 방지: 사용자 입력 같은 새 작업 없이 렌더가 50번 넘게 이어지면(effect 안에서 deps 없이 `setState`) 멈추고 오류를 낸다.

### 5.7 useEffect · useMemo

| | 언제 실행 | deps 없음 | `[]` | `[a, b]` |
|---|---|---|---|---|
| `useEffect` | 화면 반영(commit) 뒤 | 매 렌더 | 처음 한 번 | a · b 중 하나라도 `Object.is`로 다를 때 |
| `useMemo` | 렌더 중 (값을 바로 돌려줌) | 매 렌더 다시 계산 | 처음 한 번 | 다를 때만 다시 계산 |

- effect를 다시 실행하기 전에 이전 cleanup을 먼저 부르고, 언마운트하면 모든 cleanup을 부른다. effect 하나가 오류를 내도 다음 effect는 실행한다.
- App의 사용 예: `useMemo`로 통계 · 보이는 목록 계산(입력창에 글자를 칠 때는 재계산 안 함), `useEffect`로 localStorage 저장(`[todos]`) · 문서 제목(`[stats.active]`) · `/` 단축키(`[]`, cleanup으로 리스너 제거).

## 6. 테스트 결과

브라우저에서 `tests/index.html`을 열면 Phase 1 · 2 테스트가 모두 실행된다.

| 브라우저 | 결과 | 시간 |
|---|---|---|
| Chrome (데스크톱 앱 내장 브라우저, Chromium 계열) | 422 / 422 | 약 9초 (최적화 뒤 다시 실행) |
| Firefox 159 (headless) · Safari 27 | 601 / 601 | 코드 정리 **전** 기준. 정리 뒤에는 다시 돌리지 않았다 |

### 6.1 `component.test.js` (46개)

- **기본**: 인자 검사, mount 결과 · 반환값 · 렌더 횟수, 원래 내용 교체, 반환값 종류(문자열 · 숫자 · 배열 · 중첩 배열 · null · false), 루트 props, mount 두 번 · mount 전 update 오류, **update가 바뀐 텍스트만 고치고 나머지 노드 객체를 재사용**, 변경 없음 → 패치 0, VDOM이 Phase 1 형식(`containerToVdom`과 같음), 여러 루트 독립, 렌더 중 다른 루트 렌더 오류, 순환 VNode(오류로 끝나고 DOM 그대로), mount에서 잘못된 VDOM 거부(DOM 그대로)
- **렌더 오류 · 원자성**: 렌더 예외 · 함수 prop · 첫 렌더 실패 시 DOM 그대로, 실패한 렌더의 effect 취소
- **stateless**: props → VNode, 이름 유지, 자식 안 Hook 오류(DOM 그대로), 자식 뒤 루트 Hook 정상, 자식 예외 뒤 복구, Lifting State Up
- **이벤트 위임**: 이름 변환, VDOM에 함수 대신 `data-on-*`, 이벤트 객체 전달, 버블링 순서, `stopPropagation`, 최신 핸들러, 새 함수여도 패치 없음, 종류마다 리스너 하나, null · undefined · false 핸들러, 문자열 핸들러 거부, `online` 같은 이름은 일반 속성, 사라진 요소 이벤트, 원래 트리 보존
- **폼 요소**: 사용자 입력 뒤에도 `value` 반영, `checked` 해제(값 변경 · 속성 삭제 둘 다), `selected`, 같은 값이면 프로퍼티를 다시 쓰지 않음
- **unmount · onCommit**: 정리 · 비움 · 리스너 제거 · 이후 setState 무시, 두 번 unmount, 다시 mount 오류, 구독 · 해제, 구독자 오류 격리

### 6.2 `hooks.test.js` (36개)

- **useState**: 초깃값, 지연 초기화 1회, 렌더 사이 값 유지, setter 고정, `Object.is` 같으면 렌더 생략(NaN), 새 객체는 렌더, 3번 → 렌더 1번, 함수형 +3 · 값 +1, 여러 상태 한 번에, 렌더 중 setState 오류, 렌더 밖 Hook 오류, 비동기 setState, `flush()`
- **Hook 규칙**: 순서 바뀜 · 적게 · 많이 부르면 오류, 오류 뒤 복구
- **useEffect**: commit 뒤 실행(새 DOM을 읽음), deps 없음 · `[]` · 값 변화 · NaN · 길이 변화, cleanup → effect 순서, cleanup의 클로저, 언마운트 cleanup, 함수 아닌 반환값, effect 안 setState(deps로 멈춤), **무한 반복 50번에서 멈춤**, effect 오류 격리, 잘못된 인자
- **useMemo**: 재사용(같은 참조), deps 변화 재계산, deps 없음 · `[]`, 관련 없는 상태 변화에 재계산 안 함, `undefined` 결과 재사용, 잘못된 인자

### 6.3 `app.test.js` (20개, 실제 `app.html`을 iframe으로)

처음 화면 · hooks 10개(iframe 안의 `app` 객체로 확인), 추가(CREATE, 기존 노드 재사용, 입력창 비움), 추가 = 렌더 1번, 빈 입력 거부, 중요도, 체크 · 해제(같은 li, PROPS), 삭제, 필터, 검색(`<mark>`, 빈 결과), 검색 + 필터, 완료 지우기, **배칭 버튼 렌더 1번**, 빈 상태, 새로고침 뒤 유지, 망가진 저장 값, `/` 단축키, 타이핑 중 요소 · 값 · 포커스 유지, 강조가 DOM에 흔적을 남기지 않음, `onclick` 속성 없이 위임 · 콘솔 오류 없음, (정리) 테스트 전 저장 값 복원

### 6.4 만들면서 발견한 것

- 첫 실행에서 600개 중 1개 실패: 테스트 러너의 `deepEqual`이 `NaN`을 `NaN`과 다르다고 봐서 생긴 **테스트 쪽 문제**였다(구현은 `Object.is`로 NaN을 같게 봄). 해당 비교만 직접 하도록 고쳤다.
- 체크박스 하나를 누르면 패치가 9개 나온다. 패치 목록을 보면 항목 2개(li 클래스, checked), 진행률 2개(aria-valuenow, style), 통계 숫자 3개, 필터 개수 2개 — 모두 실제로 화면에서 바뀌어야 하는 곳이다. 나머지 노드는 손대지 않는다.

## 7. 한계

1. **key 없음** — 목록 앞쪽 항목을 지우면 뒤 항목이 한 칸씩 밀려 TEXT · PROPS 패치가 여러 개 나온다(결과는 정확). React는 `key`로 노드를 이동만 한다.
2. **자식 컴포넌트는 매번 다시 실행** — 루트가 렌더되면 모든 자식 함수를 다시 부른다(`React.memo` 같은 건너뛰기 없음). 바뀐 DOM은 Diff가 걸러 주지만 계산 자체는 반복된다.
3. **자식의 상태 · Hook 금지** — 과제 제약대로 의도적으로 막았다. 그래서 Context, 컴포넌트별 상태, `useRef` 등은 없다.
4. **렌더는 동기 · 중단 불가** — React Fiber처럼 작업을 쪼개거나 우선순위를 두지 않는다.
5. **effect 타이밍** — commit 직후 같은 작업 안에서 실행한다(React의 `useLayoutEffect`에 가까움). React의 `useEffect`는 화면을 그린 뒤 실행한다.
6. **이벤트** — 버블링되는 이벤트만 위임할 수 있다(`mouseenter` 등은 지원 안 함). 핸들러에 넘기는 것은 브라우저의 원래 이벤트이고, React의 SyntheticEvent처럼 `currentTarget`을 바꿔 주지 않는다. `onChange`는 브라우저 의미 그대로(텍스트 입력은 포커스를 잃을 때) — 글자마다 반응하려면 `onInput`을 쓴다(React는 `onChange`를 글자마다 부름).
7. **에러 경계 없음** — 렌더 오류는 DOM을 그대로 두고 예외를 던질 뿐, 대체 화면을 보여 주지 않는다.
8. **data-on-\* 속성** — 이벤트 연결을 위해 실제 DOM에 `data-on-click="3"` 같은 속성이 보인다.

## 8. 실제 React와 비교

| 항목 | 이 구현 | 실제 React |
|---|---|---|
| 상태 저장 | 인스턴스의 `hooks` 배열, 호출 순서로 찾음 | Fiber 노드의 `memoizedState` 연결 리스트, 호출 순서로 찾음 — **원리는 같다** |
| 컴포넌트 단위 | 루트만 상태를 가짐, 자식은 순수 함수로 매번 실행 | 모든 함수 컴포넌트가 상태를 가질 수 있고, 각자 Fiber를 가짐. 바뀐 컴포넌트만 다시 렌더 |
| 렌더 예약 | `queueMicrotask`로 1회 예약 | 우선순위(lane)가 있는 스케줄러. React 18부터 이벤트 · 타이머 · Promise 어디서든 자동 배칭 |
| 같은 값 | `Object.is`로 같으면 렌더 생략 | 같음 (bail out) |
| Diff 대상 | 루트 전체 VDOM 스냅샷 두 개 | 다시 렌더된 컴포넌트의 요소와 현재 Fiber 트리 |
| 이벤트 | 컨테이너에 종류별 리스너 1개 + `data-on-*` 번호 | 루트에 위임 + 합성 이벤트(SyntheticEvent), Fiber의 props에서 핸들러를 찾음 |
| effect | commit 직후 동기 실행 | `useEffect`는 paint 뒤 비동기, `useLayoutEffect`는 commit 직후 동기 |
| Hook 규칙 위반 | 순서 · 종류 · 개수를 매 렌더 검사해 오류 | 개발 모드에서 경고 · 오류, ESLint 규칙(`rules-of-hooks`)으로 미리 검사 |
| 폼 | `value` · `checked` · `selected` 프로퍼티 동기화 | 제어 컴포넌트가 매 렌더 DOM 값을 상태로 되돌림 |

## 9. 실행 방법

- VS Code Live Server 등으로 `projects/react`를 열고 `app.html`(Phase 2), `index.html`(Phase 1), `tests/index.html`(테스트)을 연다.
- ES 모듈을 쓰므로 `file://`로 직접 열면 동작하지 않는다(브라우저가 모듈 로드를 막음). 아무 정적 서버면 된다.
