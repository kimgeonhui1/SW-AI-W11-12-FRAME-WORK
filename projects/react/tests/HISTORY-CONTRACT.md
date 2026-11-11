# History / Undo / Redo 계약과 검증

## 요구와 범위

사용자가 이번 작업을 Mini React Part 2라고 지정했다. 구현 위치는 기존 Phase 1 화면과 `src/phase1/`이다. 공식 LMS 원문은 접근 경로가 없어 미확인이다. 사용자 요구와 README의 기존 함수명·VNode 형식 유지 규칙을 기준으로 구현했다. `src/app/`, hooks, component는 이번 범위가 아니다.

## History 계약

- 모듈 내부 `states` 배열에 스냅샷을 저장하고 `position` 인덱스를 관리한다. 비어 있을 때 인덱스는 -1이다.
- `push(vdom)`: 입력을 `structuredClone`으로 복사한 후 현재 위치 다음 기록을 폐기하고 새 스냅샷을 추가한다. 같은 값도 직접 push하면 기록된다.
- `undo()` / `redo()`: 범위 내에서 인덱스만 이동한다. 처음/끝에서는 현재 위치를 유지한다.
- 세 함수 모두 `{ vdom, canUndo, canRedo }`를 반환한다. 기록이 없으면 `null`이다. 기록된 null VDOM은 `{ vdom: null, ... }`이므로 빈 History와 구분된다.
- 반환 VDOM도 매번 깊은 복사한다. 입력·반환 객체 수정은 과거 기록에 영향을 주지 않는다. 함수명과 인자는 보존하고, 기존 빈 함수에 없던 반환값 계약만 정의했다.
- 복사는 미래 기록 폐기 전에 실행하므로 복사 실패 시 위치와 미래 기록은 유지된다. 함수·실제 DOM 등을 넣지 않는 기존 VNode 계약을 전제로 하며, History는 VNode 유효성 검사기가 아니다.
- 저장은 페이지 메모리 안에서만 유지한다. 새로고침 시 초기화되며 기록 수 제한이나 영구 저장은 구현하지 않았다.

## Phase 1 화면 흐름

1. 초기 `section > p("A")`를 push하고 실제/테스트 영역에 patch한다.
2. 테스트 영역의 section 내부를 편집한다. 루트 section은 UI가 유지한다. `contenteditable`은 UI 속성으로만 사용하고 VDOM 기록에서 제외한다.
3. Patch: `domToVdom(편집 루트)` → 현재 기록과 diff → 변경이 있으면 push → 두 영역을 diff/patch로 동기화한다.
4. 같은 내용의 Patch는 기록을 추가하지 않으며 Undo 후의 미래 기록도 보존한다.
5. Undo/Redo: History 이동 → 반환 상태로 두 영역을 diff/patch → 버튼 비활성화 상태 갱신. 이동 중 push하지 않는다.
6. 미반영 초안이 있을 때 Undo/Redo를 누르면 해당 초안을 폐기하고 선택 기록을 표시한다. 화면 안내에도 명시했다.

이전 상태와 실제 DOM의 일치는 Part 1 patch의 전제다. 개발자 도구로 실제 영역이나 편집 루트 자체를 제거하는 외부 조작, 임의 수제 VNode, patch 예외 시 트랜잭션 롤백은 지원하지 않는다. 페이지는 기존 Part 1의 HTML/속성 범위를 사용하며 SVG나 live form property를 추가 지원하지 않는다.

## 실제 검증 결과

워크스페이스 루트에서:

```powershell
node tasks/week11-12-mini-react-phase1/run-browser-tests.mjs
```

- 실제 Edge headless: VDOM **7/7**, diff/patch **22/22**, History **6/6**, Phase 1 화면 **6/6** PASS, 종료 코드 0.
- History 검사는 각 테스트를 별도 모듈 인스턴스로 격리했다. 제품에 reset API를 추가하지 않았다.
- 화면 검사는 실제 `index.html`을 iframe에 로드하고 실제 버튼 `.click()`으로 이벤트 처리 및 양쪽 DOM을 확인했다. UI 전용 속성 분리, 기록 경계, 미래 기록 폐기, 초안 폐기, 동일 Patch, DOM identity, 빈 내용과 중첩 속성 복원을 검사했다.
- 초기 History 실행은 비동기 모듈이 완료되기 전 dump되어 '실행 대기 중'이었다. 테스트 기대값은 그대로 두고 러너에 virtual-time-budget을 추가한 뒤 완료 결과를 확인했다.
- GUI에서 직접 타이핑·붙여넣기·IME·선택/커서 동작은 미검증이다. headless DOM 검증을 수동 화면 조작 검증으로 간주하지 않는다.
- 기존 Part 1 소스/테스트는 작업 전후 SHA-256으로 보존 확인. 별도 빌드 스크립트나 package.json은 없다.

## 사용자 확인 순서 / 리뷰 질문

Live Server로 `index.html`을 열고 테스트 영역의 A를 B로 바꾼 뒤 Patch, C로 바꾼 뒤 Patch를 누른다. 뒤로가기에서 양쪽 B, 앞으로가기에서 양쪽 C가 되어야 한다. 다시 뒤로가기 후 D로 편집·Patch하면 앞으로가기가 비활성화되고 C로 이동할 수 없어야 한다.

코드 리뷰·자크 이해도 점검: push에서 복사를 먼저 하는 이유, Undo 중 push하지 않는 이유, 반환 객체도 복사하는 이유, 동일 Patch와 직접 push의 차이, 이전 VDOM 경로를 확보하는 patch가 필요한 이유를 설명한다. 이 점검 전 Part 3로 자동 진행하지 않는다.
