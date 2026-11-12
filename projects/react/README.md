<div align="center">

# Mini React

**Virtual DOM부터 Hooks까지, React의 핵심을 직접 만들어 본 프로젝트**

Phase 1 · Virtual DOM / Diff / Patch &nbsp;|&nbsp; Phase 2 · Component / State / Hooks

![JavaScript](https://img.shields.io/badge/JavaScript-ES%20Modules-f7df1e?logo=javascript&logoColor=black)
![dependencies](https://img.shields.io/badge/dependencies-0-2ea44f)
![tests](https://img.shields.io/badge/unit%20tests-276%20passed-2ea44f)
![fuzz](https://img.shields.io/badge/fuzz-7%2C000%20cases-3b6fe0)
![browsers](https://img.shields.io/badge/tested-Chrome%20%C2%B7%20Edge-555)

| 🧩 외부 라이브러리 | ✅ 단위 테스트 | 🎲 무작위(퍼즈) 테스트 | ⚡ 1,000줄 중 1줄 바꾸기 |
|:---:|:---:|:---:|:---:|
| **0개** | **276개** 통과 | 실행마다 **7,000건** 통과 | 통째로 다시 그리기보다 **약 10배 빠름** |

</div>

**실행**: `projects/react` 폴더를 VS Code **Live Server**로 열기 → `index.html` (Phase 1) · `app.html` (Phase 2 초능력 윷놀이) · `tests/*.test.html` (테스트) · `tests/bench.html` (성능 측정)

**발표 순서**: [1. 협업 방식](#1-협업-방식) → [2. 구현](#2-구현) → [3. 회고](#3-회고)

---

안녕하세요. Vanilla 자바스크립트로 미니 리액트를 만든 과정을 협업 방식, 구현, 회고 순서로 말씀드리겠습니다.

## 1. 협업 방식

<p align="center"><img src="docs/images/collaboration.svg" alt="협업 흐름: 인터페이스 합의 → dev 뼈대 → 각자 브랜치 → 서로 비교 → dev" width="100%"></p>

협업은 먼저 **인터페이스를 맞추는 것**부터 시작했습니다.
VDOM 형식과 core의 파일 이름, 함수 이름은 고정하고, 내부 구현은 각자 자유롭게 하기로 했습니다.

이 뼈대를 dev 브랜치에 올린 뒤, 세 명이 **각자 브랜치에서 같은 과제를 처음부터** 구현했고, 진행 상황은 GitHub Project 이슈로 공유했습니다.

인터페이스가 같아서 **서로의 코드를 바꿔 끼워 비교**할 수 있었습니다.
실제로 팀원 코드와 비교하면서 제 코드에 입력 검사, 무한 렌더링 감지 같은 안전장치가 부족하다는 걸 발견하고 보완했습니다.

AI는 구현에 활용하고 다른 AI로 교차 검증했는데, 지적을 그대로 받지 않고 **테스트로 재현되는 것만** 고쳤습니다.

| 고정한 것 (팀 공통) | 자유롭게 한 것 (각자) |
|---|---|
| VDOM 모양 `{ type, props, children }`, 텍스트는 문자열 | diff 결과의 형식, patch 방식 |
| `src/core/` 파일 이름과 함수 이름 (`h`, `diff`, `patch`, `useState` …) | 내부 알고리즘, 테스트 방식 |

---

## 2. 구현

<table>
  <tr>
    <td width="50%"><img src="docs/images/phase1.png" alt="Phase 1 화면: 테스트 영역에서 li 추가 · 글자색 변경 후 Patch → 실제 영역에 반영, 아래에 diff 결과(패치 트리)"></td>
    <td width="50%"><img src="docs/images/yut.png" alt="Phase 2 화면: 초능력 윷놀이 — 청팀 · 윷판 · 홍팀, 고른 말이 갈 수 있는 칸에 '도 ▼' 표시"></td>
  </tr>
  <tr>
    <td align="center"><b>Phase 1</b> · 테스트 영역의 HTML을 고치고 Patch<br>→ 실제 영역에는 <b>바뀐 곳만</b> 반영, 아래에 diff 결과</td>
    <td align="center"><b>Phase 2</b> · Hooks로 만든 초능력 윷놀이<br>말을 고르면 갈 수 있는 칸과 결과(도 · 개 …)를 표시</td>
  </tr>
</table>

### 기술 선택

| | 선택 | 이유 |
|---|---|---|
| 언어 | **JavaScript (ES Modules)** | 외부 프레임워크 금지. `import` / `export`로 파일을 나눔 |
| 실행 | **Live Server** (빌드 도구 없음) | 브라우저가 모듈을 직접 읽음 |
| 테스트 | **브라우저용 테스트 도구를 직접 만듦** | DOM이 필요해서 `*.test.html`을 열면 바로 결과가 나오게 함 |

외부 라이브러리 없이 ES 모듈로 파일을 나누고, Live Server로 실행했습니다.
테스트는 DOM이 필요해서 **브라우저에서 돌아가는 테스트 도구를 직접** 만들었습니다.

<details>
<summary>용어 설명 (ES 모듈 · Live Server · Jest)</summary>

- **ES 모듈**: `export`로 함수를 내보내고 `import`로 가져다 쓰는 자바스크립트 표준 파일 나누기 문법. 브라우저가 `<script type="module">`로 직접 지원
- **Live Server**: 폴더를 로컬 웹 서버로 열어 주는 VS Code 확장. ES 모듈은 파일을 직접 열면(`file://`) 동작하지 않아서 필요
- **Jest**: 가장 많이 쓰는 자바스크립트 테스트 라이브러리. Node.js에서 돌아가서 DOM을 쓰려면 가짜 DOM 설정이 따로 필요

</details>

### 구성도: 화면이 그려지는 과정

<p align="center"><img src="docs/images/architecture.svg" alt="A. 처음: App() 호출 → VDOM → createElement → 화면. B. 클릭할 때마다: setState → 다시 그리기 예약(Batching) → App() 다시 호출 → diff(이전 VDOM, 새 VDOM) → patch(실제 DOM, 패치 트리) → useEffect. 그리고 파일 구성" width="100%"></p>

동작은 이 그림 한 장으로 설명할 수 있습니다.
처음에는 App 함수가 돌려준 VDOM을 그대로 실제 DOM으로 만듭니다.
클릭으로 setState가 불리면 바로 그리지 않고, 여러 번 불려도 **한 번만 그리도록 예약**하는데, 이것이 Batching입니다.
그다음 App을 **한 번 더 호출**해 새 VDOM을 만들고, 이전 VDOM과 diff해서 **바뀐 곳만** patch로 고칩니다. 마지막으로 useEffect가 실행됩니다.

<details>
<summary>용어 정리 (VDOM · 렌더링 · Batching · diff · patch · useEffect)</summary>

| 용어 | 뜻 |
|---|---|
| **VDOM** (Virtual DOM) | 화면을 자바스크립트 객체로 적은 것. `{ type: "li", props: {}, children: ["할 일"] }` |
| **렌더링** | 컴포넌트 함수(`App`)를 호출해서 VDOM을 얻는 것. 상태가 바뀌면 **같은 함수를 다시 호출**해 새 화면을 계산한다 |
| **Batching** | `setState`를 연달아 여러 번 불러도 바로 그리지 않고 모아 두었다가 **한 번만** 다시 그리는 것 (`queueMicrotask`로 "지금 하던 일이 끝난 직후"에 실행) |
| **diff** | 이전 VDOM과 새 VDOM(둘 다 객체)을 비교해 바뀐 곳만 담은 **패치 트리**를 만드는 함수 |
| **patch** | 패치 트리를 보고 **실제 DOM**에서 바뀐 곳만 고치는 함수 |
| **useEffect** | 화면이 바뀐 **뒤**에 할 일을 등록하는 Hook (탭 제목 바꾸기, 스크롤 등) |

</details>

### 핵심 설계 ① diff 결과 = 패치 트리, key는 꼭 필요한 것만 이동

<p align="center"><img src="docs/images/patch-tree.svg" alt="이전 VDOM과 새 VDOM을 비교한 패치 트리, key 리스트에서 A만 이동" width="100%"></p>

diff 결과는 VDOM과 같은 모양의 **패치 트리**로 만들었습니다. 바뀐 곳만 표시하고 나머지는 null이라서, patch는 트리를 따라 내려가기만 하면 됩니다.
리스트는 **key로 같은 항목을 짝지어 노드를 재사용**하고, React와 같은 규칙으로 순서가 어긋난 노드만 옮겨서 입력 중인 포커스도 유지됩니다.

### 핵심 설계 ② Hook = "배열 + 호출 순서"

```js
// App.js — 컴포넌트 객체가 hooks 배열을 들고 있고, Hook은 "몇 번째로 불렸는지"로 자기 칸을 찾는다
const [actions, setActions] = useState(() => [시작]);           // hooks[0]  일어난 일의 목록 (던지기 · 옮기기 · 초능력)
const [pickSel, setPickSel] = useState({ yut: null, mal: null }); // hooks[1]  초능력 고르기 화면에서 고른 것
const [chosen, setChosen] = useState(null);                      // hooks[2]  옮기려고 고른 말 → 판에 갈 수 있는 칸 표시
// … hooks[3~6] targeting · notice · confirming · victoryClosed (useState), hooks[7~8] logRef · dialogFocusRef (useRef)
const state = useMemo(() => replay(actions), [actions]);         // hooks[9]  판 · 차례 · 승자는 목록을 처음부터 적용해 계산
```

Hook은 컴포넌트의 hooks 배열에 값을 저장하고, **호출 순서로 자기 칸**을 찾습니다.
그래서 조건문 안에서 Hook을 부르면 순서가 바뀌는데, 이런 실수는 **바로 에러가 나도록** 막았습니다.

| 과제 규칙 | 코드로 강제한 방법 |
|---|---|
| Hook은 루트 컴포넌트에서만 | 자식 컴포넌트(TeamPanel 등)를 실행하는 중에 Hook을 부르면 에러 |
| Hook은 항상 같은 순서로 | 렌더링마다 Hook의 **개수와 종류**를 이전과 비교해서 다르면 에러 |
| 무한 렌더링 방지 | 사용자 입력 없이 렌더링이 **50번 연속** 일어나면 멈추고 에러 (effect 안의 setState 실수 등) |

### 핵심 설계 ③ 성능: 바뀐 곳만 고치면 얼마나 빠른가

1,000줄 목록을 바꾸는 같은 작업을 세 방법으로 반영하고, **걸린 시간**과 **실제 DOM 작업량**을 쟀습니다.

| 1,000줄 목록에서 | **바뀐 곳만 고치기**<br>`diff` + `patch` (이 프로젝트) | 통째로 다시 만들기<br>`createElement` | 통째로 다시 만들기<br>`innerHTML` |
|---|---|---|---|
| 1줄 글자 바꾸기 | **4.4 ms** · 글자 1개 수정 | 43.4 ms · 노드 7,001개 생성 | 40.8 ms · 노드 7,001개 생성 |
| 끝에 1줄 추가 | **4.3 ms** · 노드 7개 생성 | 45.3 ms · 7,008개 생성 | 42.0 ms · 7,008개 생성 |
| 맨 앞에 1줄 추가 (key 있음) | **4.1 ms** · 노드 7개 생성 | 44.4 ms · 7,008개 생성 | 42.5 ms · 7,008개 생성 |
| 맨 앞에 1줄 추가 (key 없음) | 21.1 ms · 7개 생성 + 글자 1,999개 수정 | 44.5 ms · 7,008개 생성 | 40.9 ms · 7,008개 생성 |
| 멀리 떨어진 2줄 자리 바꾸기 | ⚠️ 47.0 ms · 997줄 이동 | 47.3 ms · 7,001개 생성 | 42.1 ms · 7,001개 생성 |
| 입력 중인 값 · 포커스 | **그대로 남음** | 사라짐 | 사라짐 |

| 그 밖에 잰 것 | 결과 |
|---|---|
| Batching | 클릭 한 번에 `setState` 100번 → **렌더링 1번** (값은 정확히 +100) |
| 실제 앱 (윷놀이 말 1개 옮기기) | 화면 요소 112개 중 **노드 7개 생성 + 값 19개 수정**만 일어남. 한 번 그리는 데(App 호출 + diff + patch) **약 2~3 ms** |

1줄만 바꿀 때는 통째로 다시 만드는 것보다 **약 10배 빠르고**, 입력 중인 값도 그대로 남습니다.
key가 없으면 5배 느려져 **key가 왜 필요한지** 확인했고, 멀리 떨어진 두 줄을 바꿀 때는 React와 같은 **약점**도 찾았습니다.

<details>
<summary>측정 방법</summary>

- `tests/bench.html`을 열면 직접 잴 수 있습니다. 위 숫자는 Edge 157 (Windows 11), 방법마다 25번 반복한 중앙값을 3번 측정해 다시 중앙값을 낸 값입니다.
- 같은 PC에서도 측정 때마다 시간은 최대 2배까지 달라졌지만, **방법 사이의 비율(약 10배)은 늘 같았습니다**.
- 시간은 DOM을 고친 뒤 **레이아웃 계산까지** 끝난 시점까지입니다 (`offsetHeight`로 강제). 새 화면의 VDOM · HTML 문자열은 세 방법 모두 미리 만들어 두고 시작합니다 (diff 시간은 포함).
- 시간은 기기마다 다르지만, DOM 작업량(`MutationObserver`로 센 노드 생성 · 이동 · 값 수정 수)은 어디서 재도 같습니다.
- 한 줄 = `<li><span>이름</span><b>점수</b><button>삭제</button></li>` (텍스트 포함 노드 7개).
- 두 줄 바꾸기의 약점: React의 key 정렬은 "앞에서부터 보며, 이전 위치보다 뒤로 간 것만 옮기는" 방식이라 뒤쪽 항목이 맨 앞으로 오면 사이 항목이 전부 옮겨집니다. Vue는 최장 증가 부분 수열(LIS)로 이 경우를 줄입니다.

</details>

---

## 3. 회고

| | |
|---|---|
| 👍 **잘한 점** | 결과가 맞는지 **자동으로 확인하는 장치를 먼저** 만든 것 |
| 😵 **어려웠던 점** | **폼 요소**. 같은 값이라도 넣는 순서나 사용자가 건드렸는지에 따라 화면이 달라짐 |
| 💡 **배운 점** | key와 Hook 규칙이 **왜 필요한지** 직접 만들면서 이해함 |
| ➡️ **다음에는** | 처음부터 팀원과 코드를 **더 자주 비교**하기 |

잘한 점은 결과가 맞는지 자동으로 확인하는 장치를 먼저 만든 것입니다. 덕분에 리뷰 지적이 진짜 버그인지 바로 판단할 수 있었습니다.

어려웠던 점은 폼 요소였습니다. input의 값은 attribute와 property가 따로 있어서, 같은 값이라도 넣는 순서나 사용자가 건드렸는지에 따라 화면이 달라졌습니다.
예를 들어 range 입력은 value가 max보다 먼저 들어가면 100으로 잘려서, value를 항상 마지막에 넣도록 고쳤습니다.

배운 점은 리액트가 왜 key를 요구하는지, 왜 Hook을 조건문 안에서 쓰면 안 되는지 직접 만들어 보면서 이해했다는 것입니다.
다음에는 처음부터 팀원과 코드를 더 자주 비교해서, 서로의 좋은 점을 더 빨리 가져오고 싶습니다.

이상으로 발표를 마치겠습니다. 감사합니다.
