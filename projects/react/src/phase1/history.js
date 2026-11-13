// [history.js] Patch된 Virtual DOM 기록 관리 (뒤로가기 / 앞으로가기)

/**
 * State History — 브라우저의 뒤로가기 / 앞으로가기와 같은 방식으로 동작하는 기록 저장소
 *
 *   stack : 저장된 기록 배열. 각 기록 = { vdom, patchCount, label, time }
 *   index : 지금 화면에 보이는 기록의 위치 (-1 이면 아직 기록이 없음)
 *
 *   예) stack = [A, B, C], index = 2  → 현재 C
 *       undo()  → index = 1, B 반환
 *       push(D) → C 를 버리고 stack = [A, B, D], index = 2
 *       (뒤로 간 상태에서 새 기록을 만들면 "앞으로가기" 기록은 사라진다 = 분기)
 *
 * 깊은 복사 이유
 *   VNode 는 평범한 객체라서 참조를 그대로 저장하면, 바깥에서 객체를 수정했을 때 과거 기록까지 같이 바뀐다.
 *   그래서 넣을 때(push)도, 꺼낼 때(current · undo · redo · go)도 structuredClone 으로 복사한다.
 *   함수 · Symbol 처럼 복사할 수 없는 값이 든 VDOM 은 structuredClone 이 DataCloneError 를 던진다.
 *   읽기만 할 때는 복사 없이 peek() 을 쓴다 (최적화).
 */

// 모듈 내부 상태 (밖에서는 아래 함수로만 접근)
let stack = [];
let index = -1;

/**
 * 새 기록 추가
 *
 * 순서가 중요하다: 새 기록을 먼저 완성(복사)한 뒤에 앞쪽 기록을 버린다.
 * 복사가 실패하면(함수가 든 VDOM 등) 여기서 예외가 나고, 아래의 "앞으로가기 기록 버리기" 는 실행되지 않으므로
 * History 가 그대로 남는다.
 *
 * @param {object} vdom 저장할 Virtual DOM (복사해서 저장)
 * @param {{patchCount?: number, label?: string}} [meta] 화면 목록에 보여 줄 부가 정보
 *   patchCount : 이 기록을 만들 때 적용된 패치 개수 (숫자가 아니면 0)
 *   label      : 기록 이름. 예) "초기 상태", "Patch #1" (없으면 "기록 n")
 * @returns {number} 새 기록의 위치(index)
 */
export function push(vdom, meta) {
  const info = meta !== null && typeof meta === "object" ? meta : {}; // null · 문자열 같은 잘못된 meta 는 무시
  const entry = {
    vdom: structuredClone(vdom),
    patchCount: Number.isFinite(info.patchCount) ? info.patchCount : 0,
    label: typeof info.label === "string" && info.label !== "" ? info.label : `기록 ${index + 2}`,
    time: Date.now(),
  };
  stack = [...stack.slice(0, index + 1), entry]; // 현재 위치 뒤("앞으로가기" 기록)를 버리고 새 기록을 붙인다
  return (index = stack.length - 1);
}

/** 한 칸 뒤로 이동 → 그 위치의 VNode 복사본 (맨 앞이라 갈 수 없으면 null) */
export const undo = () => (canUndo() ? go(index - 1) : null);

/** 한 칸 앞으로 이동 → 그 위치의 VNode 복사본 (맨 뒤라 갈 수 없으면 null) */
export const redo = () => (canRedo() ? go(index + 1) : null);

/**
 * 특정 위치로 바로 이동 (History 목록 클릭)
 * @param {number} i 이동할 위치 (0부터)
 * @returns {object|null} 그 위치의 VNode 복사본. 범위 밖 · 정수가 아니면 null (위치는 그대로)
 */
export function go(i) {
  if (!Number.isInteger(i) || i < 0 || i >= stack.length) return null;
  index = i;
  return current();
}

/** 현재 위치의 VNode 복사본 (기록이 없으면 null). 돌려받은 객체를 고쳐도 기록은 바뀌지 않는다 */
export const current = () => (index < 0 ? null : structuredClone(stack[index].vdom));

/**
 * 현재 위치의 VNode 를 복사하지 않고 그대로 돌려준다 (기록이 없으면 null).
 * 읽기 전용: diff 비교 · JSON 표시 · 자가 점검처럼 바꾸지 않고 읽기만 할 때 쓴다.
 * current() 는 부를 때마다 트리 전체를 깊은 복사하므로, 버튼 한 번에 여러 번 부르면 그만큼 느려진다.
 * ※ 돌려받은 객체를 고치면 기록이 바뀐다. 고칠 일이 있으면 current() 를 쓴다.
 */
export const peek = () => (index < 0 ? null : stack[index].vdom);

/** 뒤로 갈 수 있는가 (첫 기록보다 뒤에 있는가) */
export const canUndo = () => index > 0;

/** 앞으로 갈 수 있는가 (마지막 기록보다 앞에 있는가) */
export const canRedo = () => index >= 0 && index < stack.length - 1;

/** 현재 위치 정보 { index(0부터, 기록이 없으면 -1), length } — "현재 위치: 3 / 5" 표시용 */
export const position = () => ({ index, length: stack.length });

/**
 * 화면 목록용 기록 요약 (VNode 자체는 빼고 메타 정보만 — 바깥에서 고쳐도 기록에 영향 없음)
 * @returns {Array<{index: number, label: string, patchCount: number, time: number, active: boolean}>}
 */
export const entries = () =>
  stack.map(({ label, patchCount, time }, i) => ({ index: i, label, patchCount, time, active: i === index }));

/** 기록 전체 삭제 (테스트 · 초기화용) */
export function reset() {
  stack = [];
  index = -1;
}
