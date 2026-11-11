// [history.js] Patch된 Virtual DOM 기록 관리 (뒤로가기 / 앞으로가기)

const states = [];
let position = -1;

function current() {
  if (position < 0) return null;
  return {
    vdom: structuredClone(states[position]),
    canUndo: position > 0,
    canRedo: position < states.length - 1
  };
}

export function push(vdom) {
  // Clone before discarding the future: a failed copy must leave history intact.
  const snapshot = structuredClone(vdom);
  states.splice(position + 1);
  states.push(snapshot);
  position = states.length - 1;
  return current();
}

export function undo() {
  if (position > 0) position--;
  return current();
}

export function redo() {
  if (position < states.length - 1) position++;
  return current();
}
