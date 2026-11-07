// [history.js] Patch된 Virtual DOM 기록 관리 (뒤로가기 / 앞으로가기)

/**
 * 브라우저 뒤로가기 · 앞으로가기와 같은 방식의 기록 저장소.
 *   stack = [A, B, C], index = 2 (현재 C) → undo() 하면 index 1 · B
 *   그 상태에서 push(D) → C 를 버리고 [A, B, D] (뒤로 간 뒤 새 기록을 만들면 앞쪽 기록이 사라짐 = 분기)
 * VNode 는 평범한 객체라, 바깥에서 고쳐도 과거 기록이 바뀌지 않도록 넣을 때 · 꺼낼 때 깊은 복사를 한다.
 * 함수 · Symbol 이 든 VDOM 은 structuredClone 이 DataCloneError 를 던진다.
 */

let stack = []; // 기록: { vdom, patchCount, label, time }
let index = -1; // 현재 위치 (-1 = 기록 없음)

/**
 * 새 기록 추가. meta = { patchCount, label } (화면 목록용, 잘못된 값은 기본값). @returns 새 위치
 * 새 기록을 먼저 완성(복사)한 뒤 앞쪽 기록을 버린다 → 복사가 실패해도 History 가 그대로 남는다.
 */
export function push(vdom, meta) {
  const info = meta !== null && typeof meta === "object" ? meta : {};
  const entry = {
    vdom: structuredClone(vdom),
    patchCount: Number.isFinite(info.patchCount) ? info.patchCount : 0,
    label: typeof info.label === "string" && info.label !== "" ? info.label : `기록 ${index + 2}`,
    time: Date.now(),
  };
  stack = [...stack.slice(0, index + 1), entry];
  return (index = stack.length - 1);
}

/** 한 칸 뒤로 / 앞으로 / i 번째로 이동 → 그 위치의 VNode 복사본 (갈 수 없으면 null, 위치 그대로) */
export const undo = () => (canUndo() ? go(index - 1) : null);
export const redo = () => (canRedo() ? go(index + 1) : null);
export function go(i) {
  if (!Number.isInteger(i) || i < 0 || i >= stack.length) return null;
  index = i;
  return current();
}

/** 현재 VNode 복사본 (기록이 없으면 null) */
export const current = () => (index < 0 ? null : structuredClone(stack[index].vdom));

/**
 * 현재 VNode 를 복사 없이 그대로 (읽기 전용). diff 비교 · JSON 표시 · 자가 점검처럼 읽기만 할 때 쓴다.
 * current() 는 부를 때마다 트리 전체를 복사한다. ※ 돌려받은 객체를 고치면 기록이 바뀐다.
 */
export const peek = () => (index < 0 ? null : stack[index].vdom);

export const canUndo = () => index > 0;
export const canRedo = () => index >= 0 && index < stack.length - 1;
/** { index(0부터, 기록 없으면 -1), length } */
export const position = () => ({ index, length: stack.length });

/** 화면 목록용 요약 (VNode 는 빼고 메타 정보만) */
export const entries = () =>
  stack.map(({ label, patchCount, time }, i) => ({ index: i, label, patchCount, time, active: i === index }));

/** 기록 전체 삭제 (테스트 · 초기화용) */
export function reset() {
  stack = [];
  index = -1;
}
