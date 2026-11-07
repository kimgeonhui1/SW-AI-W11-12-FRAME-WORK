// [phase1/main.js] Phase 1 페이지 시작점 — 실제/테스트 영역 렌더링, Patch·뒤로가기·앞으로가기 버튼 동작

/**
 * 흐름
 *   [로드]  실제 영역 → containerToVdom → VDOM₀ → createElement 로 테스트 영역 렌더링, history.push(VDOM₀)
 *   [Patch] 테스트 영역 → VDOMₙ, diff(history.peek(), VDOMₙ) → patch(실제 영역) → history.push(VDOMₙ)
 *   [뒤로 · 앞으로 · 목록 클릭] patch(실제 영역, diff(이전, 대상)) — 실제 영역도 Diff/Patch 로 이동,
 *                              테스트 영역은 대상 VDOM 으로 통째로 다시 그림
 * 규칙
 *   - 실제 영역에는 클래스 · 속성을 절대 추가하지 않는다 (VDOM 과 달라져 다음 diff 가 틀어짐) → 강조는 Element.animate() 로만.
 *   - 화면에 보여 주는 문자열은 모두 textContent 로 넣는다 (HTML 주입 방지).
 */

import { containerToVdom, createElement } from "../core/vdom.js";
import { diff, PATCH } from "../core/diff.js";
import { patch } from "../core/patch.js";
import * as history from "./history.js";

// ── 1. VDOM → HTML 문자열 (테스트 영역의 소스 편집기용) ──────────────
//
// innerHTML 을 그대로 보여 주면 한 줄로 붙어 읽기 어렵고, 아무 데나 줄바꿈을 넣으면 다시 파싱했을 때
// 텍스트가 바뀌어 "편집하지 않았는데도 Diff 가 생긴다". 그래서 vdom.js 공백 규칙과 짝을 맞춘다:
//   - 형제가 모두 요소일 때만 줄바꿈 + 들여쓰기 (이 공백은 "줄바꿈이 든 공백" 이라 domToVdom 이 무시)
//   - 텍스트가 섞이면 한 줄로 (텍스트 앞뒤 공백이 내용을 바꾸므로)
// 결과: toHtml(vdom) 을 다시 파싱하면 원래 vdom 과 같다 (왕복 보장).

/** 닫는 태그가 없는 태그 (void element) */
export const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
// 여는 태그 바로 뒤 줄바꿈을 파서가 지우는 태그 → 들여쓰면 공백 텍스트가 생기므로 항상 한 줄로
const KEEP_INLINE_TAGS = new Set(["pre", "textarea", "listing"]);
const INDENT = "  ";

/** 텍스트 이스케이프: & < > 와 눈에 안 보이는 nbsp */
export const escapeText = (text) =>
  text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/ /g, "&nbsp;");

/** 속성값 이스케이프: 큰따옴표로 감싸므로 & 와 " (+ nbsp) */
export const escapeAttr = (value) => String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/ /g, "&nbsp;");

/** 속성 → ` name="value"` (setProp 과 같은 규칙: null · false → 없음, true · "" → 이름만) */
const propsToString = (props) =>
  Object.entries(props ?? {})
    .filter(([, value]) => value != null && value !== false)
    .map(([name, value]) => (value === "" || value === true ? ` ${name}` : ` ${name}="${escapeAttr(value)}"`))
    .join("");

const allElements = (nodes) => nodes.every((node) => typeof node !== "string");

/** 형제 VNode 목록 → HTML. 모두 요소면 한 줄에 하나씩 depth 만큼 들여쓰고, 텍스트가 섞이면 이어 붙인다 */
export function toHtml(nodes, depth = 0) {
  const list = Array.isArray(nodes) ? nodes : [nodes];
  if (!allElements(list)) return list.map((node) => nodeToHtml(node, 0, false)).join("");
  const pad = INDENT.repeat(depth);
  return list.map((node) => pad + nodeToHtml(node, depth, false)).join("\n");
}

/** 노드 하나 → HTML. inline: <pre> 안쪽처럼 끝까지 한 줄로 써야 하는가 */
function nodeToHtml(node, depth, inline) {
  if (typeof node === "string") return escapeText(node);
  const open = `<${node.type}${propsToString(node.props)}>`;
  if (VOID_TAGS.has(node.type)) return open;
  const close = `</${node.type}>`;
  const children = node.children || [];
  if (children.length === 0) return open + close;
  const keepInline = inline || KEEP_INLINE_TAGS.has(node.type);
  if (keepInline || !allElements(children)) {
    return open + children.map((child) => nodeToHtml(child, 0, keepInline)).join("") + close;
  }
  return `${open}\n${toHtml(children, depth + 1)}\n${INDENT.repeat(depth)}${close}`;
}

// ── 2. 화면 ─────────────────────────────────────────────────────────

/** 화면에 꼭 필요한 요소 id (index.html 과 같아야 함). tests/index.html 처럼 없는 페이지에서는 시작하지 않는다 */
export const REQUIRED_IDS = Object.freeze([
  "real-area", "test-area", "test-source", "patch-btn", "undo-btn", "redo-btn",
  "position-label", "status", "history-list", "patch-log", "log-summary", "vdom-json",
]);

/**
 * 필수 요소 검사 → { state, missing }
 *   none: 하나도 없음(테스트 페이지에서 import) → 조용히 아무것도 안 함
 *   partial: 일부만 있음(index.html 이 잘못 수정됨) → 시작하지 않고 빠진 id 를 알림
 *   ready: 모두 있음 → 시작
 */
export function checkRequiredElements(root = document) {
  const missing = REQUIRED_IDS.filter((id) => !root.querySelector(`#${id}`));
  const state = missing.length === 0 ? "ready" : missing.length === REQUIRED_IDS.length ? "none" : "partial";
  return { state, missing };
}

const $ = (id) => document.getElementById(id);
const realArea = $("real-area"); //     실제 영역: Patch 로만 바뀐다
const testArea = $("test-area"); //     테스트 영역: contenteditable 미리보기
const testSource = $("test-source"); // 테스트 영역의 HTML 소스 편집기
const [patchBtn, undoBtn, redoBtn] = ["patch-btn", "undo-btn", "redo-btn"].map($);
const [positionLabel, statusEl, historyList, patchLog, logSummary, vdomJson] =
  ["position-label", "status", "history-list", "patch-log", "log-summary", "vdom-json"].map($);

let patchCounter = 0; // "Patch #n" 번호

/** 테스트 영역을 VDOM 으로 통째로 다시 그리고 소스 편집기도 맞춘다 (사용자가 마음대로 바꾼 곳이라 새로 그리는 편이 확실) */
function renderTestArea(vdom) {
  testArea.replaceChildren(...vdom.children.map(createElement));
  testSource.value = toHtml(vdom.children);
}

/**
 * 바뀐 노드를 잠깐 반짝인다. 텍스트 노드는 부모를 강조.
 * 클래스 대신 Element.animate() → 끝나면 흔적이 없어 실제 DOM 이 VDOM 과 계속 일치한다.
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

/** 상태 줄 한 줄. kind: "info" | "ok" | "warn" */
function setStatus(message, kind = "info") {
  statusEl.textContent = message;
  statusEl.dataset.kind = kind;
}

/** 패치 하나를 읽기 쉬운 한 줄로 */
function describePatch(p) {
  const path = `[${p.path.join(", ")}]`;
  const nodeName = (node) => (typeof node === "string" ? `"${node}"` : `<${node.type}>`);
  switch (p.type) {
    case PATCH.CREATE: return `부모 ${path}의 ${p.index}번 자리에 ${nodeName(p.node)} 추가`;
    case PATCH.REMOVE: return `${path} 노드 삭제`;
    case PATCH.REPLACE: return `${path} 노드를 ${nodeName(p.node)}(으)로 교체`;
    case PATCH.TEXT: return `${path} 텍스트 → "${p.value}"`;
    default: {
      const set = Object.entries(p.set).map(([k, v]) => `${k}="${v}"`);
      const parts = [set.length && `설정 ${set.join(" ")}`, p.remove.length && `삭제 ${p.remove.join(", ")}`].filter(Boolean);
      return `${path} 속성 ${parts.join(" / ")}`;
    }
  }
}

/** 마지막 Diff 결과 표시. reason: 어떤 동작으로 생긴 diff 인지 */
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

/** History 목록 · 위치 · 버튼 상태 · JSON 보기 갱신 */
function renderHistoryUI() {
  const { index, length } = history.position();
  positionLabel.textContent = `현재 위치: ${index + 1} / ${length}`;
  undoBtn.disabled = !history.canUndo();
  redoBtn.disabled = !history.canRedo();

  // 각 항목은 버튼 → 누르면 그 시점으로 이동
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
  vdomJson.textContent = JSON.stringify(history.peek(), null, 2);
}

// ── 3. 버튼 동작 ────────────────────────────────────────────────────
// History 의 VDOM 은 저장될 때 diff 검사를 통과했으므로 diff 는 trustOld 로, 읽기만 하므로 복사 없는 peek() 로 쓴다.

/** [Patch] 테스트 영역의 변경을 실제 영역에 반영하고 History 에 저장 */
function onPatch() {
  const newVdom = containerToVdom(testArea);
  const patches = diff(history.peek(), newVdom, { trustOld: true });
  renderPatchLog(patches, "Patch");
  if (patches.length === 0) return setStatus("변경 없음 — 저장할 기록이 없습니다.", "warn");

  // patch 가 실패하면(예: 누군가 실제 영역을 직접 고쳐 경로가 어긋남) DOM 은 그대로이므로 History 에도 저장하지 않는다
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

/** [뒤로 · 앞으로 · 목록 클릭] move: history 를 움직이고 대상 VDOM 을 돌려주는 함수 */
function moveTo(move, reason) {
  const prevVdom = history.peek();
  const prevIndex = history.position().index;
  const target = move();
  if (!target) return;

  const patches = diff(prevVdom, target, { trustOld: true });
  try {
    highlight(patch(realArea, patches));
  } catch (err) {
    history.go(prevIndex); // 실제 영역이 그대로이므로 History 위치도 되돌려 둘을 맞춘다
    return reportPatchError(err);
  }
  renderTestArea(target); // Patch 하지 않은 편집 내용은 버리고 대상 상태로 다시 그림
  renderPatchLog(patches, reason);
  renderHistoryUI();
  reportResult(`${reason} · 패치 ${patches.length}개`);
}

function reportPatchError(err) {
  setStatus(`Patch 실패 — 실제 영역은 바뀌지 않았습니다. (${err.message})`, "warn");
  console.error("[phase1] patch 실패", err);
}

/** 결과 + 자가 점검: 실제 영역을 다시 VDOM 으로 바꾼 것이 History 의 현재 VDOM 과 같은가 (patch 가 맞으면 항상 같다) */
function reportResult(message) {
  if (JSON.stringify(containerToVdom(realArea)) === JSON.stringify(history.peek())) {
    setStatus(`${message} — 실제 영역이 VDOM과 일치합니다.`, "ok");
  } else {
    setStatus(`${message} — 경고: 실제 영역이 VDOM과 다릅니다!`, "warn");
    console.warn("[phase1] 실제 영역과 History VDOM 불일치", containerToVdom(realArea), history.peek());
  }
}

// ── 4. 시작 ────────────────────────────────────────────────────────

/** 실제 영역 → VDOM → 테스트 영역 렌더링, 초기 상태를 History 첫 기록으로 */
function init() {
  // 소스 편집기 ↔ 미리보기 동기화. 프로그램으로 innerHTML · value 를 바꾸면 input 이벤트가 안 생겨 무한 루프가 없다.
  testArea.addEventListener("input", () => (testSource.value = toHtml(containerToVdom(testArea).children)));
  testSource.addEventListener("input", () => (testArea.innerHTML = testSource.value)); // 덜 닫힌 태그는 파서가 보정
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

// 필수 요소가 모두 있을 때만 시작. 일부만 있으면 빠진 id 를 콘솔과 화면(body 맨 앞)에 알린다.
const startup = checkRequiredElements();
if (startup.state === "ready") {
  init();
} else if (startup.state === "partial") {
  const message = `Phase 1 화면을 시작할 수 없습니다. index.html 에 없는 요소: ${startup.missing.map((id) => `#${id}`).join(", ")}`;
  console.error(`[phase1] ${message}`);
  const notice = Object.assign(document.createElement("p"), { className: "startup-error", textContent: message });
  notice.setAttribute("role", "alert");
  document.body.prepend(notice);
}
