// [phase1/main.js] Phase 1 페이지 시작점 — 실제/테스트 영역 렌더링, Patch·뒤로가기·앞으로가기 버튼 동작
import { h, domToVdom } from "../core/vdom.js";
import { diff } from "../core/diff.js";
import { patch } from "../core/patch.js";
import { push, undo, redo } from "./history.js";

const realArea = document.querySelector("#real-area");
const testArea = document.querySelector("#test-area");
const undoButton = document.querySelector("#undo-btn");
const redoButton = document.querySelector("#redo-btn");
const status = document.querySelector("#history-status");
let current = null;

function readDraft() {
  const root = testArea.firstChild;
  if (!root) return null;
  const vnode = domToVdom(root);
  // Editing permission belongs to the UI, not the recorded document.
  delete vnode.props.contenteditable;
  return vnode;
}

function display(state) {
  patch(realArea, diff(current?.vdom ?? null, state.vdom));
  patch(testArea, diff(readDraft(), state.vdom));
  testArea.firstChild.contentEditable = "true";
  current = state;
  undoButton.disabled = !state.canUndo;
  redoButton.disabled = !state.canRedo;
}

document.querySelector("#patch-btn").addEventListener("click", () => {
  const draft = readDraft();
  if (diff(current.vdom, draft).length === 0) {
    status.textContent = "변경된 내용이 없습니다.";
    return;
  }
  display(push(draft));
  status.textContent = "변경을 반영하고 기록했습니다.";
});

undoButton.addEventListener("click", () => {
  display(undo());
  status.textContent = "이전 기록으로 이동했습니다.";
});

redoButton.addEventListener("click", () => {
  display(redo());
  status.textContent = "다음 기록으로 이동했습니다.";
});

display(push(h("section", {}, h("p", {}, "A"))));
status.textContent = "초기 상태를 기록했습니다.";
