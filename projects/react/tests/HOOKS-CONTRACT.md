# Part 3 / Phase 2 — Component와 Hooks

## 근거와 범위

사용자 확정 설계(인스턴스의 `this.hooks`, 순서 기반 커서, 실행 문맥 정리)와 README의 공통 함수명·VNode 형식 유지 규칙을 적용했다. 공식 LMS 원문은 접근 경로가 없어 미확인이다. 기존 함수 시그니처와 VDOM/Diff/Patch/History 계약은 바꾸지 않았다. `renderWithHooks`와 `flushEffects`는 Component와 Hooks 모듈 사이의 내부 연결 함수이며 앱용 Hook이 아니다.

## 저장 구조와 실행 순서

- `FunctionComponent(component, container)`는 독립 `hooks` 배열, 이전 `vdom`, 렌더 중 여부와 추가 갱신 요청을 소유한다.
- 각 슬롯은 `kind`로 state/effect/memo를 구분한다. State는 value/setter, Effect는 deps/cleanup, Memo는 deps/value를 저장한다. initialized로 undefined 값과 미초기화를 구분한다.
- `mount()`는 빈 전용 컨테이너에 한 번만 호출한다. `mount()`/`update()`는 undefined를 반환한다. 공개 사용 순서는 생성 → mount → setter/update다.
- `setter(next)` → 함수형 값 계산 → Object.is 비교 → 해당 슬롯 갱신 → 인스턴스 update → 활성 인스턴스 지정·커서 0 → 컴포넌트 실행 → finally로 이전 실행 문맥 복구 → diff(previous,next) → patch → 이전 VDOM 교체 → Effect 처리.
- 첫 렌더는 `diff(null,next)`의 insert와 기존 patch/createElement를 사용한다. 다음 렌더는 기존 DOM을 필요한 부분만 변경한다.
- Effect에서 State를 변경하면 현재 Effect 목록 처리를 마친 뒤 같은 인스턴스를 다시 렌더한다. 이는 동기 처리이며 범용 Scheduler나 비동기 batching이 아니다. 연쇄 갱신 25회를 넘으면 오류로 중단한다.
- 최상위의 같은 순서로 Hook을 호출해야 한다. 종류/개수 변경, 컴포넌트 밖 Hook 호출, 렌더 중 setter 호출은 오류다. 중첩 실행 후 이전 활성 인스턴스를 복구한다. 중첩 컴포넌트 트리의 생명주기를 관리하는 기능은 별개이며 미지원이다.

## Hook 반환값과 의존성

| Hook | 반환값 | 계약 |
|---|---|---|
| useState(initial) | `[value, setter]` | 초기값은 최초만 저장. 함수 초기값은 지연 초기화로 실행. setter는 안정된 참조이며 `next` 또는 `prev => next` 지원. setter 반환은 undefined. Object.is로 같은 값이면 렌더하지 않음. |
| useEffect(callback, deps) | undefined | 최초 DOM 반영 후 실행. 변경 시 해당 Effect의 이전 cleanup → 새 callback. callback 반환은 cleanup 함수 또는 undefined. |
| useMemo(factory, deps) | 계산한 값 | 최초 계산. 의존성이 같으면 동일 결과 참조 유지, 달라지면 재계산. undefined 결과도 캐시 가능. |

Effect/Memo 의존성은 배열 또는 생략(undefined)만 허용한다. 배열 길이와 각 값을 Object.is로 비교한다. `[]`는 최초만, 생략은 매 렌더다. 배열 자체는 복사하지만 그 안의 객체는 깊게 복사하지 않는다. State 값도 깊게 복사하지 않으므로 객체를 직접 수정하지 말고 새 객체로 setter에 전달해야 한다.

## App 화면

`app/main.js`가 `App` 인스턴스를 `#root`에 마운트한다. App은 count와 label State, count의 두 배 Memo, 버튼 연결 Effect(`[]`), count 표시 Effect(`[count]`)를 사용한다.

VDOM props는 기존 HTML 속성만 지원한다. onClick 함수 props를 추가하지 않고 Effect에서 안정된 #root에 이벤트를 위임한다. Effect 실행 기록은 VDOM이 관리하는 #root 밖에 두어 DOM 소유권 충돌을 피했다. App 데모는 단일 #root 화면용이며 인스턴스 격리는 별도의 Component 테스트로 검증했다.

## 검증 기록

작업 브랜치 `feat/Kimjeonghee-React`, 기준/종료 SHA `9d605bce042c2440366b3339e81081bc5b13993f`. commit/push/merge 없음. 이전 작업의 미커밋 변경을 그대로 유지했다.

워크스페이스 루트에서 실행:

```powershell
node tasks/week11-12-mini-react-phase1/run-browser-tests.mjs
```

실제 Edge headless 결과:

| 검사 | 최초 core 구현 | App 연결 | 최종 |
|---|---:|---:|---:|
| VDOM | 7/7 | 7/7 | 7/7 |
| Diff/Patch | 22/22 | 22/22 | 22/22 |
| History | 6/6 | 6/6 | 6/6 |
| Phase 1 화면 | 6/6 | 6/6 | 6/6 |
| Component/Hooks | 10/10 | 10/10 | 12/12 |
| App 화면 | 미실행 | 4/4 | 4/4 |

최종 **57/57 PASS**, 종료 코드 0. diff/patch 테스트의 고정 시드 200회 내부 회귀도 포함한다. 실패 기대값을 완화하거나 테스트를 삭제하지 않았다. git diff --check 통과. 기존 package.json/빌드 스크립트가 없어 별도 build 명령은 없다.

App 테스트는 실제 app.html을 iframe에 로드하고 실제 버튼의 click 이벤트를 실행했다. DOM 텍스트·객체 참조·Effect 순서·이벤트 중복·동일 값의 mutation 0을 검증했다. 실제 화면의 Memo 계산 횟수를 계측하지는 않았으며 캐시 참조와 계산 횟수는 Hook 단위 테스트로 검증했다. GUI 수동 클릭, 키보드, 화면 레이아웃/모바일 시각 검증은 하지 않았다.

기존 소스/테스트의 SHA-256 비교용 기록은 저장소 밖 tasks/week11-12-mini-react-phase1/part3-preservation.json에 있다. 러너 결과는 같은 경로의 browser-results에 저장된다.

## 미지원·남은 위험 및 리뷰할 판단

- 기존 Component에는 unmount 계약이 없어서 unmount API를 추가하지 않았다. cleanup은 의존성 변경 시 실행한다. DOM에서 수동 제거해도 cleanup이 자동 호출되지 않는다. App 이벤트 구독은 페이지 수명 동안 유지된다.
- Effect는 DOM commit 직후 동기로 실행하며 브라우저 paint 이후 실행까지 보장하지 않는다. async Effect, Promise 반환은 지원하지 않는다.
- 렌더/Effect 오류가 나면 활성 문맥과 busy 상태는 정리하지만 Hook State·이미 반영한 DOM·앞서 실행한 Effect를 롤백하지 않는다. 오류 후 안전한 자동 복구는 보장하지 않는다.
- Fiber, Concurrent Rendering, 일반 Scheduler, props 전달/변경 API, keyed 컴포넌트 트리, SSR, 함수형 이벤트 props는 구현하지 않았다.
- 큰 트리/장시간 메모리 성능은 미검증이다. App의 Effect 로그는 제한 없이 늘어난다. Part 1의 unkeyed 대응·LCS 비용 제약도 그대로 적용된다.
- 코드 리뷰에서 확인할 결정: 동기 Effect 시점, unmount 미지원 범위, Object.is 비교와 객체 불변성, 이벤트 위임, 25회 연쇄 갱신 상한. 공식 LMS가 다른 계약을 요구하면 원문 대조 후 조정해야 한다.

## 사용자 확인 / 자크 이해도 점검

Live Server로 app.html을 열고 +1 두 번 → count 2 / 두 배 4, 로그가 Effect 0 → Cleanup 0 → Effect 1 → Cleanup 1 → Effect 2인지 확인한다. 표시 A/B 전환은 count와 Effect 로그를 유지해야 한다. 같은 값 설정은 화면·로그를 바꾸지 않아야 한다.

설명할 질문: setter는 어떻게 원래 인스턴스를 찾는가? 커서 초기화와 State 초기화는 왜 다른가? Hook 종류가 달라도 인덱스가 충돌하지 않는 이유는? cleanup은 왜 다음 Effect 전에 실행되는가? deps 생략과 []는 어떻게 다른가? Memo의 의존성 객체를 직접 변경하면 왜 재계산을 보장할 수 없는가?
