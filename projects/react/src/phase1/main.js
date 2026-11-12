// [phase1/main.js] Phase 1 페이지 시작점 — 실제/테스트 영역 렌더링, Patch·뒤로가기·앞으로가기 버튼 동작

import { domToVdom, createElement, validateVNode, commitLiveState } from "../core/vdom.js";
import { diff } from "../core/diff.js";
import { patch } from "../core/patch.js";
import { push, undo, redo } from "./history.js";
import { htmlToVdom, vdomToHtml } from "./htmlText.js";

const realArea = document.getElementById("real-area");
const testInput = document.getElementById("test-input");
const patchLog = document.getElementById("patch-log");

/**
 * 실제 영역을 target VDOM 모양으로 바꾼다 (Patch / 뒤로가기 / 앞으로가기 공통)
 *
 * 이전 VDOM은 기록이 아니라 "지금 실제 영역 화면"을 domToVdom으로 읽어서 쓴다.
 * 사용자가 실제 영역의 input에 입력하거나 체크박스를 눌렀으면 그 상태가 이전 VDOM에 들어가서,
 * diff가 그 차이까지 찾아 target 상태로 되돌린다. (기록의 VDOM을 쓰면 이 차이를 못 본다)
 * Phase 1 HTML에는 onClick 같은 함수 prop이 없어서 화면에서 읽어도 빠지는 정보가 없다.
 */
function render(target) {
  // 사용자가 바꾼 option 선택을 attribute에도 적어 둔다 → 읽은 VDOM과 DOM의 기준이 같아진다 (vdom.js commitLiveState 참고)
  commitLiveState(realArea.firstChild);
  const patches = diff(domToVdom(realArea.firstChild), target);
  patch(realArea, patches);
  patchLog.textContent = patches === null ? "변경 없음 (null)" : JSON.stringify(patches, null, 2);
  return patches;
}

// ── 페이지 로드 (과제 요구사항 순서) ──
// 1) "실제 영역"에 적혀 있는 샘플 HTML(DOM)을 Virtual DOM으로 변환한다.
//    #real-area 자체(id 포함)가 아니라 그 "안쪽"만 쓰고, 루트는 htmlToVdom과 같은 모양(속성 없는 <div>)으로 맞춘다.
//    그래야 테스트 영역에서 읽은 VDOM과 같은 기준으로 diff할 수 있다.
const sample = domToVdom(realArea);
const initialVdom = { type: "div", props: {}, children: sample.children };

// 2) 실제 영역을 그 VDOM으로 만든 DOM으로 교체한다.
//    patch는 container.firstChild를 루트로 보고 "VDOM 자식 i번째 = DOM 자식 i번째"를 전제로 한다.
//    HTML에 적힌 원래 DOM에는 들여쓰기 공백 노드가 있어서 이 전제가 깨지므로, 한 번 다시 만들어 모양을 맞춘다.
realArea.replaceChildren(createElement(initialVdom));

// 3) 방금 만든 Virtual DOM으로 테스트 영역을 렌더링한다. (VDOM → HTML 코드)
testInput.value = vdomToHtml(initialVdom);

// State History에는 Virtual DOM을 저장한다.
// current = 지금 실제 영역이 보여 주기로 한 VDOM. 새 기록을 남길지 판단할 때 쓴다
let current = initialVdom;
push(current);

document.getElementById("patch-btn").addEventListener("click", () => {
  // 현재 테스트 영역 상태를 다시 Virtual DOM으로 만들고 → diff → 바뀐 부분만 실제 영역에 반영
  const vdom = htmlToVdom(testInput.value);
  // 실제 영역을 건드리기 "전에" 검사한다. 브라우저 HTML 파서는 받아 주지만 setAttribute는 거부하는 속성 이름
  // (브라우저에 따라 <p "a"="1"> 같은 이름)이 있으면 patch가 중간에 멈춰 실제 영역이 반쯤만 바뀐다 → 검사에서 막고 이유를 보여 준다
  try {
    validateVNode(vdom);
  } catch (e) {
    patchLog.textContent = `Patch 취소 (실제 영역은 그대로): ${e.message}`;
    return;
  }
  render(vdom);
  // 직전 기록과 VDOM이 같으면 기록을 남기지 않는다 (뒤로가기를 눌렀는데 화면이 그대로인 칸이 생기지 않게).
  // render의 diff 결과로 판단하지 않는 이유: 사용자가 실제 영역 input만 바꿨을 때도 diff 결과가 생기기 때문이다
  if (diff(current, vdom) !== null) {
    current = vdom;
    push(current);
  }
});

// 뒤로/앞으로: 기록의 Virtual DOM으로 실제 영역은 patch, 테스트 영역은 다시 렌더링한다
function restore(vdom) {
  if (vdom === null) return; // 더 갈 기록이 없음
  current = vdom;
  render(vdom);
  testInput.value = vdomToHtml(vdom);
}
document.getElementById("undo-btn").addEventListener("click", () => restore(undo()));
document.getElementById("redo-btn").addEventListener("click", () => restore(redo()));
