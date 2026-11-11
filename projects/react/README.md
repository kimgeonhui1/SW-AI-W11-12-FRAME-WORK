# WEEK11–12 Mini React

2026-11-11 20:00(KST) 팀 선정 회의용 구현·검증 안내. 실제 로컬 작업 트리를 기준으로 작성했다.

- 확인 경로: `C:\Users\Jh_KIM\Desktop\JUNGLE\WEEK11-12\SW-AI-W11-12-FRAME-WORK`
- 확인 브랜치: `feat/Kimjeonghee-React`
- 구현 시작 기준 커밋: `9d605bce042c2440366b3339e81081bc5b13993f`. 현재 커밋은 `git rev-parse HEAD`로 확인한다.
- 이 README와 함께 Part 1–3 구현·테스트·계약 문서를 기능 브랜치에 포함한다. Part 1은 VDOM/Diff/Patch, Part 2는 History, Part 3은 Component/Hooks/App이며 화면 파일의 Phase 1/2 구분과는 다르다.
- 저장소 및 상위 `크래프톤` 작업 폴더에서 공식 과제 명세 원문을 찾지 못했다. 공식 요구 충족 여부는 **확인 불가**이며, 자체 계약과 테스트 통과를 공식 채점 통과로 간주하지 않는다.

## 1. 핵심 기능 요약

별도 React 패키지 없이 브라우저 ES Module과 DOM API로 구현한 학습용 렌더러다.

| 영역 | 현재 구현 | 코드 근거 |
|---|---|---|
| VDOM | HTML 요소·문자열 텍스트 생성, DOM ↔ VDOM 변환, 주석 제외 | [vdom.js](src/core/vdom.js): `h`, `domToVdom`, `createElement` |
| Diff/Patch | 텍스트·속성 수정, 삽입·삭제·교체, 중첩 변경, 대응된 DOM 객체 보존 | [diff.js](src/core/diff.js): `diff`, `matchChildren`; [patch.js](src/core/patch.js): `patch` |
| History | 깊은 복사 스냅샷, Undo/Redo, Undo 후 새 기록에서 미래 분기 폐기 | [history.js](src/phase1/history.js): `push`, `undo`, `redo` |
| FunctionComponent | 인스턴스별 Hook 저장, 최초 mount, 동기 update, DOM 반영 후 Effect 실행 | [component.js](src/core/component.js): `FunctionComponent` |
| State / useState | 초기값 보존, 지연 초기화, 함수형 갱신, 동일 값 갱신 생략 | [hooks.js](src/core/hooks.js): `useState` |
| useEffect | 의존성 비교, 이전 cleanup 후 callback, DOM 반영 직후 동기 실행 | [hooks.js](src/core/hooks.js): `useEffect`, `flushEffects` |
| useMemo | 의존성이 같으면 계산 결과 참조 재사용 | [hooks.js](src/core/hooks.js): `useMemo` |
| Phase 1 화면 | 편집 초안 Patch, 두 영역 동기화, 기록 이동 및 버튼 상태 | [phase1/main.js](src/phase1/main.js) |
| App 화면 | count·label 상태, 두 배 Memo, 이벤트 위임, Effect 기록 | [App.js](src/app/App.js), [app/main.js](src/app/main.js) |

State는 별도 클래스/파일이 아니라 `useState`의 Hook 슬롯에 저장된다. App은 단일 함수형 루트 데모이며 자식 함수 컴포넌트 트리나 props 전달 API는 구현하지 않았다. keyed 재정렬, unmount, 비동기 스케줄링 등 미지원 범위는 마지막 절에 정리했다.

## 2. 구조와 실행 방법

```text
projects/react/
├── README.md
├── index.html                 # Phase 1: 편집 / Patch / History
├── app.html                   # Phase 2: Component / Hooks 데모
├── src/
│   ├── core/
│   │   ├── vdom.js
│   │   ├── diff.js
│   │   ├── patch.js
│   │   ├── component.js
│   │   └── hooks.js
│   ├── phase1/
│   │   ├── history.js
│   │   └── main.js
│   ├── app/
│   │   ├── App.js
│   │   ├── main.js
│   │   └── components/        # .gitkeep만 존재
│   └── styles/style.css
└── tests/
    ├── vdom.test.html
    ├── diff-patch.test.html / diff-patch.test.js
    ├── history.test.html
    ├── phase1.test.html
    ├── hooks.test.html / hooks.test.js
    ├── app.test.html
    ├── DIFF-PATCH-CONTRACT.md
    ├── HISTORY-CONTRACT.md
    └── HOOKS-CONTRACT.md
```

저장소의 [공용 README](../../README.md)는 Live Server 실행 및 공통 파일명·함수명·VNode 형식 보존을 규정한다. 저장소 내부 AGENTS.md와 package.json, 별도 빌드·패키지 설치 스크립트는 발견되지 않았다.

1. VS Code에서 저장소 폴더를 연다.
2. Live Server 확장이 설치된 환경에서 `projects/react/index.html`을 **Open with Live Server**로 연다.
3. Phase 2는 `projects/react/app.html`을 같은 방식으로 연다.
4. 테스트는 `projects/react/tests/*.test.html`의 여섯 페이지를 각각 연다. 각 페이지가 실행을 마치면 `N/N PASS`와 개별 결과를 표시한다.

ES Module을 사용하는 페이지이므로 HTTP 서버로 제공한다. 별도 `npm install`, `npm run dev`, `npm run build` 명령은 이 저장소에 정의되어 있지 않다. 이번 자동 검증은 아래 Node 러너의 HTTP 서버를 사용했으며 Live Server 자체 실행은 별도로 검증하지 않았다.

## 3. 실행 흐름과 데이터 계약

### VDOM → Diff → Patch

```js
h("p", { id: "message" }, "A")
// { type: "p", props: { id: "message" }, children: ["A"] }
```

`h`는 props를 얕게 복사하고 전달된 자식을 순서대로 담는다. `domToVdom`은 요소의 HTML 속성과 텍스트를 읽고, 공백·빈 텍스트도 보존한다. 주석 등 미지원 DOM 노드는 `null`로 반환하고 자식 목록에서 제외한다. `createElement`는 문자열을 Text로 만들며 문자열 안의 마크업을 HTML로 해석하지 않는다.

`diff(oldVNode, newVNode)`는 입력과 DOM을 변경하지 않고 `insert`, `remove`, `replace`, `text`, `props` 연산 배열을 만든다. `null`은 루트의 부재를 나타낸다. 경로 `[]`는 루트, `[1, 0]`은 **이전 트리** 루트의 두 번째 자식의 첫 번째 자식이다. 같은 입력은 빈 배열이며 문자열 변화는 `text`, 타입 변화는 `replace`가 된다.

`patch(container, patches)`는 지원 대상 루트가 0~1개인 전용 컨테이너를 전제로 한다. 모든 이전 DOM 참조를 먼저 확보한 다음 연산을 적용하고 갱신된 루트 또는 `null`을 반환한다. 인덱스 계산은 요소·Text만 포함해 `domToVdom`의 주석 제외 규칙과 맞춘다. 이전 VDOM과 실제 DOM은 일치해야 한다.

### Phase 1과 History

```text
초기 section > p("A") → push → 실제/테스트 영역 표시
테스트 영역 편집 → domToVdom → 현재 기록과 diff
  → 변경 있음: push → 두 영역 patch → Undo/Redo 버튼 갱신
  → 변경 없음: 기록·미래 분기 유지
Undo/Redo → 기록 위치 이동 → 선택 스냅샷으로 두 영역 patch
```

History는 모듈의 `states` 배열과 `position`으로 관리한다. `push`는 입력을 `structuredClone`한 후 현재 위치 뒤의 기록을 지우고 추가한다. 반환값도 복사한 `{ vdom, canUndo, canRedo }`이며, 빈 History는 `null`이다. 기록된 `vdom: null`과 빈 History는 구분된다. 처음/끝에서 Undo/Redo는 범위를 벗어나지 않는다.

예: `A → B → C → Undo(B) → push(D)`는 `A → B → D`가 되고 C로 Redo할 수 없다. 직접 `push`하면 같은 값도 기록하지만, 화면에서는 먼저 diff하여 동일 Patch를 생략한다. Undo/Redo 중에는 push하지 않는다. 미반영 초안은 기록 이동 시 폐기한다. 편집 권한인 `contenteditable`은 저장 VDOM에서 제거하고 화면에만 적용한다.

### FunctionComponent, State, Hooks

```text
new FunctionComponent(App, 빈 container) → mount → update
  → renderWithHooks: 활성 인스턴스 지정, hookCursor = 0
  → App 실행: 순서대로 hooks 슬롯 조회, 다음 VDOM 반환
  → 이전 활성 문맥 복구 → diff(이전 VDOM, 다음 VDOM) → patch
  → 인스턴스 vdom/mounted 갱신 → flushEffects

setter(next) → 값 계산 → Object.is 비교
  → 같음: 종료 / 다름: 슬롯 value 변경 → 소유 인스턴스 update
```

인스턴스는 `hooks`, `vdom`, `mounted`, `busy`, `pendingUpdate`를 소유한다. `mount`는 빈 컨테이너에서 한 번만 허용한다. 초기 렌더도 `diff(null, next)`와 patch를 사용한다.

Hook 슬롯은 호출 순서의 인덱스와 `kind`로 구분한다. `state`는 value/setter, `effect`는 deps/cleanup, `memo`는 deps/value를 보관한다. 매 렌더 커서만 0으로 되돌리며 기존 값은 유지한다. setter가 슬롯과 소유 인스턴스를 캡처하므로 나중에 호출해도 올바른 인스턴스가 갱신된다. Hook 종류·개수 변화, 렌더 밖 Hook 호출, 렌더 중 setter 호출은 오류다.

| Hook | 반환·동작 | 의존성/동일성 |
|---|---|---|
| `useState(initial)` | `[value, setter]`; 함수 initial은 최초 지연 초기화, setter는 값 또는 `prev => next` 수용 | `Object.is`가 같으면 update 생략; setter 참조 유지 |
| `useEffect(callback, deps)` | 반환값 없음; DOM 반영 후 해당 Effect의 이전 cleanup → 새 callback | 최초 실행; `[]`는 최초만, 생략은 매 렌더, 배열은 길이·원소별 `Object.is` 비교 |
| `useMemo(factory, deps)` | 계산 결과; 같은 deps이면 기존 결과 참조 반환 | Effect와 같은 deps 규칙; `undefined` 결과도 캐시 |

deps는 배열 또는 생략만 허용하고 배열을 얕게 복사한다. State 객체와 deps 안 객체는 깊게 복사하지 않는다. 객체를 직접 바꾸고 같은 참조를 전달하면 변경을 감지하지 못할 수 있으므로 새 객체로 갱신해야 한다.

Effect 중 setter가 호출되면 `busy`에 의해 추가 갱신을 표시하고 현재 Effect 목록을 마친 뒤 다시 렌더한다. 한 update 안에서 렌더를 최대 25회 수행하며 다음 시도에서 오류를 던진다. 이는 동기 재진입 제어이며 일반적인 batching이나 Scheduler가 아니다.

### App에서 확인할 동작

`app/main.js`가 `App`을 `#root`에 마운트한다. App은 `count = 0`, `label = "A"`, `useMemo(() => count * 2, [count])`를 사용한다.

- **+1**: 함수형 setter → count 및 두 배 값 갱신 → count Effect의 cleanup 및 재실행.
- **표시 A/B 전환**: label만 갱신. count Memo 의존성과 count Effect 의존성은 유지.
- **같은 값 설정**: 동일 값 판정으로 렌더 및 Effect 생략.
- 이벤트 Effect(`[]`)는 `#root`에 click을 한 번 위임한다. VDOM에 함수형 `onClick` props를 넣지 않는다.
- count Effect(`[count]`)는 `#root` 밖의 상태 표시·로그를 갱신한다. +1 두 번의 기대 로그는 `Effect: 0 → Cleanup: 0 → Effect: 1 → Cleanup: 1 → Effect: 2`다.

## 4. 테스트와 재현 근거

### 2026-11-11 커밋 전 현재 코드 재실행 결과

환경: Windows / PowerShell, Node.js `v24.16.0`, Microsoft Edge `157.0.4341.42` headless. 기존 로컬 러너가 `127.0.0.1`의 임시 HTTP 포트로 파일을 제공하고 `--dump-dom --virtual-time-budget=5000 --timeout=10000`으로 각 테스트 페이지의 결과를 수집했다.

**이번에 직접 다시 실행하여 총 57/57 PASS, 러너 종료 코드 0을 확인했다.** 계약 문서의 이전 57/57 보고를 현재 결과로 인용한 것이 아니다.

| 테스트 페이지 | 현재 결과 | 주요 검증 범위 |
|---|---:|---|
| [vdom.test.html](tests/vdom.test.html) | 7/7 PASS | 생성·변환, 텍스트/공백, 주석 제외, 왕복 변환 |
| [diff-patch.test.html](tests/diff-patch.test.html) | 22/22 PASS | 변경 연산, 이전 경로, DOM/Text/listener 보존, 중복·유사 서브트리, 동일 VDOM mutation 0 |
| [history.test.html](tests/history.test.html) | 6/6 PASS | 경계, 분기 폐기, 입출력 복사, 복사 실패 시 미래 보존 |
| [phase1.test.html](tests/phase1.test.html) | 6/6 PASS | 실제 페이지 iframe·버튼 이벤트, 양쪽 화면, 초안 폐기, 동일 Patch, identity |
| [hooks.test.html](tests/hooks.test.html) | 12/12 PASS | 슬롯/인스턴스 격리, Memo 계산 횟수·참조, deps, cleanup 순서, 오류 문맥 정리, 25회 제한 |
| [app.test.html](tests/app.test.html) | 4/4 PASS | 실제 App iframe·버튼 이벤트, 값/로그, identity, 중복 이벤트 및 동일 값 mutation 검사 |

Diff/Patch의 고정 시드 `20261110`으로 200회 연속 트리를 변경하는 검사는 22개 중 **1개 테스트 내부 반복**이다. 총수에 200개를 별도로 더하지 않는다. DOM 변경 수·객체 참조 검사는 해당 사례에 대한 기능 검증이며 속도·메모리 성능 벤치마크가 아니다.

팀원 재현 방법은 위의 Live Server 실행과 여섯 테스트 페이지 확인이다. 구현·테스트·계약 문서는 저장소에 포함되며, 아래 개인 PC용 자동 러너는 포함되지 않는다.

이 PC에서 외부 러너로 재실행한 명령:

```powershell
Set-Location 'C:\Users\Jh_KIM\Desktop\JUNGLE\WEEK11-12\SW-AI-W11-12-FRAME-WORK'
$reactRepo = (Get-Location).Path
$runnerWorkspace = Join-Path $env:USERPROFILE 'Documents\ChatGPT\크래프톤'
Push-Location $runnerWorkspace
try {
  node tasks/week11-12-mini-react-phase1/run-browser-tests.mjs $reactRepo
} finally {
  Pop-Location
}
```

외부 러너는 `$runnerWorkspace`의 `tasks/week11-12-mini-react-phase1/run-browser-tests.mjs`에 있고, 저장소 경로를 인자로 받는다. 결과는 같은 tasks 폴더의 `browser-results/` 아래 페이지별 `.html`, `.stderr.txt`로 저장한다. 이 작업 폴더는 저장소 이동 후에도 유지되며 결과·브라우저 프로필·이동 보고서는 커밋에 포함하지 않는다. 러너는 Edge 설치 경로를 고정 사용하고 결과 파일을 재실행 시 덮어쓴다. 외부 러너가 없는 팀원은 Live Server 방식으로 검증한다.

실패·미실행을 구분하면 다음과 같다.

- 이전 검증의 첫 샌드박스 실행: `net::ERR_NETWORK_ACCESS_DENIED`로 여섯 페이지 모두 `NO RESULT`, 러너 종료 코드 1. 테스트 assertion 실패가 아니라 환경 차단으로 완료 결과를 얻지 못한 실행이다.
- 이번 커밋 전 새 저장소 경로로 기존 러너를 권한 확장 실행: 모든 페이지 브라우저 종료 코드 0, 위 57개 검사 PASS, assertion 실패 0.
- 별도 build: 빌드 설정/명령이 없어 실행 대상 없음.
- 미실행: GUI 직접 타이핑·붙여넣기·IME·선택/커서, 키보드 접근성, 모바일/시각 레이아웃, 다른 브라우저, 대규모/장시간 성능 검증. App 자체의 Memo 호출 횟수는 계측하지 않았으며 계산 횟수 검증은 Hook 테스트에 한정된다.

## 5. 핵심 설계 선택과 이유

### DOM identity: 전체 재생성 대신 대응된 노드 갱신

[diff.js](src/core/diff.js)의 `matchChildren`은 타입·속성·자식 순서·후손까지 같은 서브트리의 LCS(최장 공통 부분수열)를 앵커로 삼는다. 앵커 사이를 비교하되 길이가 다르고 타입도 다르면 길이 차이 범위에서 같은 타입 후보를 찾아 앞의 잉여 노드를 먼저 삽입/삭제한다. 이는 앞쪽 삽입 때문에 뒤의 유지 가능한 노드를 불필요하게 교체하는 사례를 줄이기 위한 규칙이다.

[patch.js](src/core/patch.js)는 Text의 `.data`, 달라진 속성만 수정하고 모든 대상 참조를 변경 전에 해석한다. 앞쪽 삽입/삭제로 인덱스가 밀려 뒤쪽 수정 대상이 달라지는 문제를 피한다. 예를 들어 `<i>A</i><b>B</b>` 앞에 `<u>X</u>`를 추가하면서 B를 B2로 바꾸는 테스트에서 기존 i·b·Text 참조를 유지한다.

이는 모든 상황의 identity 보장이나 최소 연산 알고리즘을 뜻하지 않는다. 동일 중복은 앞쪽 후보를 우선 대응하며, key가 없으므로 의미상 어느 항목이 이동·삭제되었는지 추론하지 않는다. 타입 교체·삭제 시 해당 객체는 보존되지 않는다.

### History: 복사된 스냅샷과 선형 분기

[history.js](src/phase1/history.js)는 입력과 반환값을 모두 복사해 외부 객체 수정이 기록을 오염하지 않도록 한다. 미래 기록을 버리기 전에 복사하므로 복사 실패 시 기존 분기를 보존한다. Undo 뒤 새 편집은 현재 지점에서 이어지는 새 이력으로 취급한다. [phase1/main.js](src/phase1/main.js)의 동일 diff 검사는 실질적 변경이 없는 Patch가 Redo 분기를 지우는 것을 막는다.

### Hooks: 인스턴스 저장과 순서 기반 연결

[component.js](src/core/component.js)의 인스턴스별 `hooks`와 [hooks.js](src/core/hooks.js)의 커서를 사용해 렌더 함수가 재실행되어도 값을 보존하고 서로 다른 인스턴스를 격리한다. 슬롯의 `kind`와 호출 수 검사는 순서 변경을 오류로 드러낸다. `try/finally`로 활성 컴포넌트 문맥과 busy 상태를 정리한다. Hook 값까지 롤백하는 구조는 아니다.

Effect는 DOM이 반영된 뒤 실행해 새 화면을 읽을 수 있게 하며, 의존성 변경 시 이전 구독/자원을 cleanup한 후 새 callback을 실행한다. 동기 처리로 흐름을 단순하게 유지하지만 브라우저 paint 이후 실행을 보장하지 않는다. App은 기존 HTML 속성 전용 VDOM 규약을 유지하기 위해 이벤트 위임을 사용하고 Effect 로그를 관리 루트 밖에 둬 DOM 소유권 충돌을 피한다.

## 6. 한계와 다음 확인 사항

| 구분 | 현재 한계 / 확인할 내용 |
|---|---|
| 공식 요구 | 원문 미확인. 저장소 공용 README와 자체 계약만 확인했으며, 공식 기능 목록·평가 기준·필수 UI와의 일치 여부는 판정하지 못함 |
| VDOM 범위 | HTML 요소와 문자열 Text, 문자열 HTML 속성 중심. children 배열 평탄화·숫자/boolean/null 자동 정규화, 함수형 이벤트 props, live form property, SVG, Fragment 렌더링 미지원. `null` 루트는 diff/patch 계약이며 `createElement(null)` 지원을 뜻하지 않음 |
| 자식 대응 | keyed reorder/move 미지원. 동일 중복이나 모두 변경된 같은 타입 형제의 의미상 identity와 전체 최소 DOM 연산 수는 보장하지 않음 |
| 성능 | 자식 수 n,m에서 LCS 테이블 공간 O(n×m), 시간은 O(n×m×서브트리 동등성 비교 비용). 큰 트리·깊은 재귀·장시간 메모리 미측정. 타 구현 대비 우위 주장 없음 |
| History | 모듈 단위 단일 기록, 메모리 저장만 지원. 새로고침 시 초기화, 기록 수 제한·영구 저장·독립 History 인스턴스 API 없음 |
| Component | unmount/자동 cleanup, props 갱신 API, 자식 함수 컴포넌트 트리 생명주기, Fiber/Concurrent Rendering, SSR 미구현 |
| Effect | DOM 반영 직후 동기 실행. Promise/async callback 반환 미지원. cleanup은 의존성 변경 때 실행하며 DOM에서 수동 제거해도 자동 호출되지 않음 |
| 오류·외부 변경 | 잘못된 VNode, 외부 DOM 조작, patch 중복 적용은 계약 밖. 경로 검사는 있지만 전체 DOM 일치 검사나 임의 patch의 원자성은 보장하지 않음. 렌더/Effect 오류 후 State·이미 반영된 DOM·기존 Effect를 롤백하지 않음 |
| 데모 | Phase 1 편집 루트 section 유지가 전제. App은 고정 ID의 단일 화면이며 Effect 로그가 제한 없이 늘어남. 실제 입력·접근성·모바일은 미검증 |
| 공유·재현 | 기능 브랜치의 구현·테스트·계약 문서로 Live Server 재현 가능. 개인 자동 러너와 실행 결과는 저장소 밖에 있어 clone에 포함되지 않음 |

우선 공식 원문과 위 기능 표를 대조하고, 회의에서 Phase 1의 B→C→Undo→D 분기와 App의 +1 두 번·A/B 전환·동일 값 설정을 시연한다. 다음 개선 후보는 GUI 입력 검증, 저장소 내부 재현 러너, 요구에 따른 unmount·기록 제한, 큰 트리 성능 측정이다. 이들은 이번 README 작업에서 구현하지 않았다.

세부 자체 계약: [Diff/Patch](tests/DIFF-PATCH-CONTRACT.md), [History](tests/HISTORY-CONTRACT.md), [Component/Hooks](tests/HOOKS-CONTRACT.md). 계약 문서의 과거 작업 범위·과거 실행 기록과 이 README의 현재 코드/재실행 결과를 구분해서 읽는다.
