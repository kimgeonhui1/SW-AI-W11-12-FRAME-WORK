// [phase1/main.js] Phase 1 페이지 시작점 — 실제/테스트 영역 렌더링, Patch·뒤로가기·앞으로가기 버튼 동작

/**
 * ── 전체 흐름 ─────────────────────────────────────────────────────────
 *
 * [페이지 로드]
 *   실제 영역 DOM ──containerToVdom──▶ VDOM₀ ──createElement──▶ 테스트 영역 렌더링
 *                                        └──▶ history.push(VDOM₀)
 *
 * [Patch 클릭]
 *   테스트 영역 DOM ──containerToVdom──▶ VDOMₙ
 *   diff(history.peek(), VDOMₙ) ──▶ patches   (비어 있으면 "변경 없음")
 *   patch(실제 영역, patches)  ← 바뀐 노드만 수정
 *   history.push(VDOMₙ)
 *
 * [뒤로가기 / 앞으로가기 / History 목록 클릭]
 *   이전 = history.peek(),  대상 = undo() / redo() / go(i)
 *   patch(실제 영역, diff(이전, 대상))  ← 실제 영역도 Diff/Patch 로 이동 (바뀐 부분만)
 *   테스트 영역 = createElement(대상)    ← 편집 영역은 통째로 다시 그림
 *
 * 규칙
 *   - 실제 영역(#real-area)에는 클래스 · 속성을 절대 추가하지 않는다.
 *     (추가하면 실제 DOM 이 VDOM 과 달라져서 다음 diff 결과가 틀어진다)
 *     강조 효과는 속성을 남기지 않는 Element.animate() 로만 한다.
 *   - 사용자에게 보여 주는 문자열(로그 등)은 모두 textContent 로 넣는다 (HTML 주입 방지).
 *
 * 파일 구성
 *   1. VDOM → HTML 문자열 변환 (소스 편집기용. toHtml 은 테스트에서도 쓰도록 export)
 *   2. 화면: 필수 요소 검사 · 렌더링 · 강조 · 로그
 *   3. 버튼 동작
 *   4. 시작 — 필수 요소가 모두 있는 페이지(index.html)에서만 실행
 * ─────────────────────────────────────────────────────────────────────
 */

import { containerToVdom, createElement } from "../core/vdom.js";
import { diff, PATCH } from "../core/diff.js";
import { patch } from "../core/patch.js";
import * as history from "./history.js";

// ── 1. VDOM → HTML 문자열 (테스트 영역의 HTML 소스 편집기용) ─────────
//
// 왜 필요한가?
//   테스트 영역의 innerHTML 을 그대로 보여 주면 한 줄로 붙어 있어서 읽기 어렵다.
//   그렇다고 아무 데나 줄바꿈 · 들여쓰기를 넣으면, 다시 파싱했을 때 텍스트 노드가 생기거나
//   텍스트 내용이 바뀌어서 "편집하지 않았는데도 Diff 가 생기는" 문제가 생긴다.
//
// 들여쓰기 규칙 (vdom.js 의 공백 처리 규칙과 짝을 이룸)
//   - 형제가 모두 요소일 때만 줄바꿈 + 들여쓰기를 넣는다.
//     → 이때 생기는 공백은 "줄바꿈이 들어 있는 공백만으로 된 텍스트" 이므로 domToVdom 이 무시한다.
//   - 형제 중 텍스트가 하나라도 있으면 (예: <p>안녕 <b>세상</b></p>) 한 줄로 붙여 쓴다.
//     → 텍스트 앞뒤에 공백을 넣으면 텍스트 내용이 바뀌기 때문
//   결과: toHtml(vdom) 을 다시 파싱한 VNode 가 원래 vdom 과 같다 (왕복 보장).

/** 닫는 태그가 없는 태그 (void element). 자식을 가질 수 없다 */
export const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);

// 여는 태그 바로 뒤의 줄바꿈 하나를 HTML 파서가 지워 버리는 태그.
// 여기에 들여쓰기를 넣으면 "\n" 은 사라지고 "  " 만 남아 공백 텍스트 노드가 생기므로 항상 한 줄로 쓴다.
const KEEP_INLINE_TAGS = new Set(["pre", "textarea", "listing"]);

const INDENT = "  "; // 들여쓰기 한 단계 = 공백 2칸

/** 텍스트 이스케이프: & < > 와 줄바꿈 없는 공백(nbsp — 눈에 안 보이므로 소스에서 알아볼 수 있게 &nbsp; 로) */
export const escapeText = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/ /g, "&nbsp;");

/** 속성 값 이스케이프: 큰따옴표로 감싸므로 & 와 " 만 바꾸면 충분 (+ nbsp 표시) */
export const escapeAttr = (value) => String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/ /g, "&nbsp;");

/**
 * 속성 객체 → ` name="value"` 문자열
 * setProp 과 같은 규칙: null · undefined · false → 속성 없음, true · "" → 이름만 (예: ` disabled`)
 */
const propsToString = (props) =>
  Object.entries(props ?? {})
    .filter(([, value]) => value != null && value !== false)
    .map(([name, value]) => (value === "" || value === true ? ` ${name}` : ` ${name}="${escapeAttr(value)}"`))
    .join("");

/** 형제가 모두 요소인가? (줄바꿈 · 들여쓰기를 넣어도 되는지 판단) */
const allElements = (nodes) => nodes.every((node) => typeof node !== "string");

/**
 * VNode 배열(형제들) → HTML 문자열
 *
 * @param {Array<object|string>|object|string} nodes 형제 VNode 목록 (보통 루트 VNode 의 children)
 * @param {number} [depth] 들여쓰기 깊이
 * @returns {string}
 */
export function toHtml(nodes, depth = 0) {
  const list = Array.isArray(nodes) ? nodes : [nodes];
  // 텍스트가 섞인 형제 → 줄바꿈 없이 이어 붙임
  // (앞에 들여쓰기를 붙이지 않는다: 줄바꿈 다음이 아니므로 "줄바꿈 + 공백" 텍스트가 되지 않게)
  if (!allElements(list)) return list.map((node) => nodeToHtml(node, 0, false)).join("");
  // 모두 요소 → 한 줄에 하나씩, depth 만큼 들여쓰고 줄바꿈("\n")으로 구분
  const pad = INDENT.repeat(depth);
  return list.map((node) => pad + nodeToHtml(node, depth, false)).join("\n");
}

/**
 * 노드 하나 → HTML 문자열
 * @param {object|string} node VNode
 * @param {number} depth 이 노드의 들여쓰기 깊이 (닫는 태그 위치 계산용)
 * @param {boolean} inline <pre> 안쪽처럼 끝까지 한 줄로 써야 하는가
 */
function nodeToHtml(node, depth, inline) {
  if (typeof node === "string") return escapeText(node);
  const open = `<${node.type}${propsToString(node.props)}>`;
  if (VOID_TAGS.has(node.type)) return open; // <br>, <img …> 는 닫는 태그 없음
  const close = `</${node.type}>`;
  const children = node.children || [];
  if (children.length === 0) return open + close;
  // <pre> 안쪽은 끝까지 한 줄로 쓴다 (그 안에서는 줄바꿈 공백도 내용이므로 들여쓰기를 넣으면 VDOM 이 바뀐다).
  // 텍스트가 섞여 있어도 한 줄로 이어 붙인다 (자식 요소 안쪽도 들여쓰기 없이).
  const keepInline = inline || KEEP_INLINE_TAGS.has(node.type);
  if (keepInline || !allElements(children)) {
    return open + children.map((child) => nodeToHtml(child, 0, keepInline)).join("") + close;
  }
  // 자식이 모두 요소 → 한 단계 들여쓴 여러 줄
  return `${open}\n${toHtml(children, depth + 1)}\n${INDENT.repeat(depth)}${close}`;
}

// ── 2. 화면 ─────────────────────────────────────────────────────────

/**
 * Phase 1 화면이 동작하는 데 꼭 필요한 요소 id 목록.
 * index.html 의 id 와 반드시 같아야 한다. 하나라도 없으면 init() 안에서 null 오류가 난다.
 */
export const REQUIRED_IDS = Object.freeze([
  "real-area", "test-area", "test-source", "patch-btn", "undo-btn", "redo-btn",
  "position-label", "status", "history-list", "patch-log", "log-summary", "vdom-json",
]);

/**
 * 필수 요소가 모두 있는지 검사한다.
 *
 * @param {Document|Element} [root] 검사할 범위 (테스트에서는 임시 div 를 넘긴다)
 * @returns {{state: "none"|"partial"|"ready", missing: string[]}}
 *   none    : 하나도 없음 → Phase 1 페이지가 아니다 (예: tests/index.html 에서 toHtml 만 import). 조용히 아무것도 안 한다
 *   partial : 일부만 있음 → index.html 이 잘못 수정된 것. 시작하지 않고 빠진 id 를 알린다
 *   ready   : 모두 있음   → 시작한다
 */
export function checkRequiredElements(root = document) {
  const missing = REQUIRED_IDS.filter((id) => !root.querySelector(`#${id}`));
  const state = missing.length === 0 ? "ready" : missing.length === REQUIRED_IDS.length ? "none" : "partial";
  return { state, missing };
}

// DOM 참조 (tests/index.html 처럼 요소가 없는 페이지에서는 모두 null — 그래서 맨 아래에서 먼저 검사한다)
const $ = (id) => document.getElementById(id);
const realArea = $("real-area"); //     실제 영역: Patch 로만 바뀐다
const testArea = $("test-area"); //     테스트 영역: 사용자가 편집하는 미리보기 (contenteditable)
const testSource = $("test-source"); // 테스트 영역의 HTML 소스 편집기
const [patchBtn, undoBtn, redoBtn] = ["patch-btn", "undo-btn", "redo-btn"].map($);
// 위치 라벨("현재 위치: 3 / 5") · 상태 줄 · History 목록 · 마지막 Diff 결과 · 그 요약 · 현재 VDOM JSON
const [positionLabel, statusEl, historyList, patchLog, logSummary, vdomJson] =
  ["position-label", "status", "history-list", "patch-log", "log-summary", "vdom-json"].map($);

let patchCounter = 0; // "Patch #n" 라벨 번호

/**
 * 테스트 영역을 VDOM 으로 통째로 다시 그리고, 소스 편집기 내용도 맞춘다.
 * (편집 영역은 사용자가 마음대로 바꾼 상태라 diff 로 맞추기보다 새로 그리는 편이 확실하다)
 * @param {object} vdom containerToVdom 모양의 루트 VNode
 */
function renderTestArea(vdom) {
  testArea.replaceChildren(...vdom.children.map(createElement));
  testSource.value = toHtml(vdom.children);
}

/**
 * patch() 가 돌려준 "바뀐 노드" 들을 잠깐 반짝이게 한다.
 * - 텍스트 노드는 스타일을 줄 수 없으므로 부모 요소를 강조한다.
 * - 클래스를 붙였다 떼는 대신 Element.animate() 를 쓴다
 *   → 애니메이션이 끝나면 아무 흔적(속성)도 남지 않아 실제 DOM 이 VDOM 과 계속 일치한다.
 * @param {Node[]} nodes
 */
function highlight(nodes) {
  const targets = new Set(nodes.map((node) => (node.nodeType === Node.TEXT_NODE ? node.parentElement : node)));
  for (const el of targets) {
    if (!el || !realArea.contains(el)) continue;
    el.animate(
      [
        { backgroundColor: "rgba(250, 204, 21, 0.55)", boxShadow: "0 0 0 2px rgba(234, 179, 8, 0.9)" },
        { backgroundColor: "rgba(250, 204, 21, 0)", boxShadow: "0 0 0 2px rgba(234, 179, 8, 0)" },
      ],
      { duration: 1400, easing: "ease-out" },
    );
  }
}

/** 상태 메시지 한 줄 표시. kind: "info" | "ok" | "warn" (CSS 가 data-kind 로 색을 바꾼다) */
function setStatus(message, kind = "info") {
  statusEl.textContent = message;
  statusEl.dataset.kind = kind;
}

/** 패치 하나를 사람이 읽기 쉬운 한 줄로 (마지막 Diff 결과 목록용) */
function describePatch(p) {
  const path = `[${p.path.join(", ")}]`;
  const nodeName = (node) => (typeof node === "string" ? `"${node}"` : `<${node.type}>`);
  switch (p.type) {
    case PATCH.CREATE: return `부모 ${path}의 ${p.index}번 자리에 ${nodeName(p.node)} 추가`;
    case PATCH.REMOVE: return `${path} 노드 삭제`;
    case PATCH.REPLACE: return `${path} 노드를 ${nodeName(p.node)}(으)로 교체`;
    case PATCH.TEXT: return `${path} 텍스트 → "${p.value}"`;
    default: { // PATCH.PROPS — 설정한 속성과 지운 속성을 " / " 로 이어서
      const set = Object.entries(p.set).map(([k, v]) => `${k}="${v}"`);
      const parts = [set.length && `설정 ${set.join(" ")}`, p.remove.length && `삭제 ${p.remove.join(", ")}`].filter(Boolean);
      return `${path} 속성 ${parts.join(" / ")}`;
    }
  }
}

/**
 * 마지막 Diff 결과(패치 목록)를 화면에 보여 준다. 패치마다 종류 배지 + 설명 한 줄.
 * @param {object[]} patches
 * @param {string} reason 어떤 동작으로 생긴 diff 인지 (예: "Patch", "뒤로가기")
 */
function renderPatchLog(patches, reason) {
  logSummary.textContent = `(${reason} · 패치 ${patches.length}개)`;
  const items = patches.map((p) => {
    const li = document.createElement("li");
    const badge = Object.assign(document.createElement("span"), { className: `badge badge--${p.type.toLowerCase()}`, textContent: p.type });
    li.append(badge, Object.assign(document.createElement("span"), { textContent: describePatch(p) }));
    return li;
  });
  if (items.length === 0) items.push(Object.assign(document.createElement("li"), { className: "empty", textContent: "변경 없음" }));
  patchLog.replaceChildren(...items);
}

/** History 목록 · 위치 라벨 · 버튼 켜짐/꺼짐 · 현재 VDOM JSON 보기를 갱신한다 */
function renderHistoryUI() {
  const { index, length } = history.position();
  positionLabel.textContent = `현재 위치: ${index + 1} / ${length}`;
  undoBtn.disabled = !history.canUndo(); // 이동할 수 없으면 버튼을 끈다
  redoBtn.disabled = !history.canRedo();

  // State History 목록: 각 항목은 버튼 → 누르면 그 시점으로 이동
  const items = history.entries().map((entry) => {
    const btn = Object.assign(document.createElement("button"), { type: "button", className: "history-item" });
    if (entry.active) btn.setAttribute("aria-current", "step");
    const time = new Date(entry.time).toLocaleTimeString("ko-KR", { hour12: false });
    btn.append(
      Object.assign(document.createElement("span"), { className: "history-label", textContent: `${entry.index + 1}. ${entry.label}` }),
      Object.assign(document.createElement("span"), { className: "history-meta", textContent: `패치 ${entry.patchCount}개 · ${time}` }),
    );
    btn.addEventListener("click", () => moveTo(() => history.go(entry.index), `${entry.index + 1}번 기록으로 이동`));
    const li = document.createElement("li");
    li.append(btn);
    return li;
  });
  historyList.replaceChildren(...items);
  vdomJson.textContent = JSON.stringify(history.peek(), null, 2); // 읽기만 하므로 복사 없는 peek()
}

// ── 3. 버튼 동작 ────────────────────────────────────────────────────
// History 의 VDOM 은 저장될 때 diff 검사를 통과했으므로 diff 에 trustOld 를 주고,
// 읽기만 하므로 복사 없는 history.peek() 을 쓴다 (최적화).

/** [Patch] 테스트 영역의 변경 사항을 실제 영역에 반영하고 History 에 저장한다 */
function onPatch() {
  const newVdom = containerToVdom(testArea); //                    사용자가 편집한 상태
  const patches = diff(history.peek(), newVdom, { trustOld: true }); // 지금 실제 영역에 그려진 상태와 비교
  renderPatchLog(patches, "Patch");
  if (patches.length === 0) return setStatus("변경 없음 — 저장할 기록이 없습니다.", "warn"); // History 에 쌓지 않는다

  // 바뀐 노드만 실제 DOM 에 반영한다.
  // patch 가 실패하면(예: 누군가 실제 영역을 직접 고쳐 경로가 어긋남) DOM 은 전혀 바뀌지 않으므로
  // History 에도 저장하지 않고 이유를 상태 줄에 보여 준다.
  let touched;
  try {
    touched = patch(realArea, patches);
  } catch (err) {
    return reportPatchError(err);
  }
  highlight(touched);
  history.push(newVdom, { patchCount: patches.length, label: `Patch #${++patchCounter}` });
  renderHistoryUI();
  reportResult(`패치 ${patches.length}개 적용`);
}

/**
 * [뒤로가기 / 앞으로가기 / 목록 클릭] 공통 처리
 * @param {() => object|null} move history 를 움직이고 대상 VDOM 을 돌려주는 함수
 * @param {string} reason 로그에 표시할 이름
 */
function moveTo(move, reason) {
  const prevVdom = history.peek(); //        움직이기 전 = 지금 실제 영역 상태
  const prevIndex = history.position().index;
  const target = move();
  if (!target) return; // 이동할 수 없음 (버튼이 꺼져 있어야 정상)

  // 실제 영역: 이전 상태 → 대상 상태로 diff / patch (바뀐 부분만)
  const patches = diff(prevVdom, target, { trustOld: true });
  try {
    highlight(patch(realArea, patches));
  } catch (err) {
    history.go(prevIndex); // patch 가 실패하면 실제 영역은 그대로이므로 History 위치도 되돌려 둘을 맞춘다
    return reportPatchError(err);
  }
  renderTestArea(target); // 테스트 영역: Patch 하지 않은 편집 내용은 버리고 대상 상태로 새로 그림
  renderPatchLog(patches, reason);
  renderHistoryUI();
  reportResult(`${reason} · 패치 ${patches.length}개`);
}

/** patch 가 실패했을 때: 실제 영역은 바뀌지 않았음을 상태 줄과 콘솔에 알린다 */
function reportPatchError(err) {
  setStatus(`Patch 실패 — 실제 영역은 바뀌지 않았습니다. (${err.message})`, "warn");
  console.error("[phase1] patch 실패", err);
}

/**
 * 작업 결과 + 자가 점검을 상태 줄에 표시한다.
 * 자가 점검: 실제 영역을 다시 VDOM 으로 바꾼 결과가 History 의 현재 VDOM 과 정확히 같은가.
 * patch 가 올바르게 동작했다면 항상 같아야 한다.
 */
function reportResult(message) {
  if (JSON.stringify(containerToVdom(realArea)) === JSON.stringify(history.peek())) {
    setStatus(`${message} — 실제 영역이 VDOM과 일치합니다.`, "ok");
  } else {
    setStatus(`${message} — 경고: 실제 영역이 VDOM과 다릅니다!`, "warn");
    console.warn("[phase1] 실제 영역과 History VDOM 불일치", containerToVdom(realArea), history.peek());
  }
}

// ── 4. 시작 ────────────────────────────────────────────────────────

/**
 * 이벤트를 연결하고 첫 화면을 만든다.
 *   R1: 실제 영역의 샘플 HTML → VDOM
 *   R2: 그 VDOM 으로 테스트 영역 렌더링 + 초기 상태를 History 의 첫 기록으로 저장
 */
function init() {
  // 미리보기(contenteditable)를 고치면 → 미리보기 DOM 을 VDOM 으로 바꿔 보기 좋은 HTML 로 소스 편집기에 쓴다
  testArea.addEventListener("input", () => (testSource.value = toHtml(containerToVdom(testArea).children)));
  // 소스 편집기를 고치면 → 브라우저 파서(innerHTML)에 맡겨 미리보기에 그린다 (덜 닫힌 태그는 파서가 보정)
  // 프로그램으로 value · innerHTML 을 바꾸면 input 이벤트가 생기지 않으므로 둘이 서로를 끝없이 갱신하지 않는다.
  testSource.addEventListener("input", () => (testArea.innerHTML = testSource.value));
  patchBtn.addEventListener("click", onPatch);
  undoBtn.addEventListener("click", () => moveTo(history.undo, "뒤로가기"));
  redoBtn.addEventListener("click", () => moveTo(history.redo, "앞으로가기"));

  const initial = containerToVdom(realArea);
  renderTestArea(initial);
  history.push(initial, { patchCount: 0, label: "초기 상태" });
  renderPatchLog([], "초기 상태");
  renderHistoryUI();
  setStatus("테스트 영역을 고친 뒤 Patch를 눌러 보세요.");
}

// 필수 요소가 "모두" 있을 때만 화면을 시작한다.
//   ready   → init()
//   partial → 시작하지 않고 빠진 요소를 콘솔과 화면(body 맨 앞 안내 문단)에 알린다 (#status 도 없을 수 있으므로)
//   none    → tests/index.html 에서 toHtml 만 import 한 경우. 아무것도 하지 않는다
const startup = checkRequiredElements();
if (startup.state === "ready") {
  init();
} else if (startup.state === "partial") {
  const message = `Phase 1 화면을 시작할 수 없습니다. index.html 에 없는 요소: ${startup.missing.map((id) => `#${id}`).join(", ")}`;
  console.error(`[phase1] ${message}`);
  const notice = Object.assign(document.createElement("p"), { className: "startup-error", textContent: message }); // textContent: HTML 주입 방지
  notice.setAttribute("role", "alert");
  document.body.prepend(notice);
}
