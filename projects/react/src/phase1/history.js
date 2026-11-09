// [history.js] Patch된 Virtual DOM 기록 관리 (뒤로가기 / 앞으로가기)

/**
 * 기록은 "배열 + 현재 위치(index)" 하나로 관리한다.
 *
 *   stack: [기록0, 기록1, 기록2]      index: 2 (지금 화면 = 기록2)
 *   undo() → index 1, 기록1 반환       redo() → index 2, 기록2 반환
 *
 * 브라우저 뒤로/앞으로 가기와 같은 규칙:
 *   뒤로 간 상태에서 새로 push하면 "앞으로 갈 수 있던 기록"은 버린다. (갈라진 미래는 더 이상 이어지지 않으므로)
 *
 * Phase 1에서는 Patch된 Virtual DOM을 저장한다. (값의 모양은 따지지 않아서 무엇이든 저장할 수 있다)
 */
const stack = [];
let index = -1; // 지금 화면에 해당하는 기록의 위치. -1 = 아직 기록 없음

// 새 기록 추가. 현재 위치 뒤의 기록(앞으로가기 대상)은 잘라 낸다
export function push(vdom) {
  stack.length = index + 1; // 배열 길이를 줄이면 그 뒤 항목이 지워진다
  stack.push(vdom);
  index = stack.length - 1;
}

// 한 칸 뒤로. 더 갈 곳이 없으면 null (호출한 쪽은 아무것도 안 하면 된다)
export function undo() {
  if (index <= 0) return null;
  index -= 1;
  return stack[index];
}

// 한 칸 앞으로. 더 갈 곳이 없으면 null
export function redo() {
  if (index >= stack.length - 1) return null;
  index += 1;
  return stack[index];
}
