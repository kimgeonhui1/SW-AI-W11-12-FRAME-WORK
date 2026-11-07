// [vdom.js] Virtual DOM 생성 및 변환 (실제 DOM ↔ Virtual DOM)
//
// [팀 공통] VNode 형식 — 요소: { type: "div"(소문자), props: { id: "box" }, children: [VNode, ...] }, 텍스트: "문자열"

const ELEMENT_NODE = 1;
const TEXT_NODE = 3;

/**
 * VNode 생성 헬퍼. 예) h("ul", null, items.map((t) => h("li", null, t)))
 * - props 가 null · undefined 면 {} (원본은 얕은 복사)
 * - children 의 배열은 평탄화, null · undefined · 불리언은 제거(조건부 렌더링), 숫자는 문자열로
 */
export function h(type, props = {}, ...children) {
  return { type: String(type).toLowerCase(), props: props == null ? {} : { ...props }, children: normalizeChildren(children) };
}

function normalizeChildren(children, result = []) {
  for (const child of children) {
    if (Array.isArray(child)) normalizeChildren(child, result);
    else if (child == null || typeof child === "boolean") continue;
    else result.push(typeof child === "number" ? String(child) : child);
  }
  return result;
}

/**
 * VDOM 에서 무시할 DOM 노드인가: 주석 등 요소 · 텍스트가 아닌 노드, 그리고 "줄바꿈이 든 공백만으로 된" 텍스트
 * (HTML 들여쓰기 공백이라 화면에 의미가 없다. 단 <pre> · <textarea> 안에서는 보이므로 남긴다)
 * ※ domToVdom 과 patch 가 이 함수 하나를 같이 써야 "n번째 자식" 이 서로 같은 노드를 가리킨다.
 */
export function isIgnorableNode(node) {
  if (node.nodeType === ELEMENT_NODE) return false;
  if (node.nodeType !== TEXT_NODE) return true;
  const text = node.nodeValue;
  if (!/^[ \t\r\n]*$/.test(text) || !/[\r\n]/.test(text)) return false;
  return !node.parentElement?.closest("pre, textarea, listing");
}

/** VNode 로 바뀔 자식 DOM 노드만 (isIgnorableNode 제외) */
export function vdomChildNodes(el) {
  return Array.from(el.childNodes).filter((child) => !isIgnorableNode(child));
}

/**
 * 실제 DOM → VNode. 텍스트는 문자열, 요소는 { type, props: 모든 속성, children }.
 * input 의 value 프로퍼티처럼 속성이 아닌 상태는 옮기지 않는다 (Phase 1 은 HTML 구조 비교).
 */
export function domToVdom(node) {
  if (node.nodeType === TEXT_NODE) return node.nodeValue;
  if (node.nodeType !== ELEMENT_NODE) return null;
  // Object.fromEntries 는 "__proto__" 같은 이름도 평범한 속성으로 만든다 (props[name] = 값 은 프로토타입 설정이 됨)
  const props = Object.fromEntries(Array.from(node.attributes, (attr) => [attr.name, attr.value]));
  const childSource = node.tagName === "TEMPLATE" ? node.content : node; // <template> 내용은 content 에 있다
  return { type: node.tagName.toLowerCase(), props, children: vdomChildNodes(childSource).map(domToVdom) };
}

/**
 * 영역(컨테이너) → 루트 VNode. 실제 영역과 테스트 영역은 id · class 가 달라서,
 * 컨테이너는 속성 없는 가상 div 로 두고 내용(자식)만 비교한다.
 */
export function containerToVdom(container) {
  return { type: "div", props: {}, children: vdomChildNodes(container).map(domToVdom) };
}

/** VNode → 실제 DOM. 잘못된 VNode(true, {} 등)는 엉뚱한 요소를 만들지 않도록 TypeError */
export function createElement(vnode) {
  if (typeof vnode === "string" || typeof vnode === "number") return document.createTextNode(String(vnode));
  if (!isElementVNode(vnode)) throw new TypeError(`[createElement] 올바른 VNode 가 아닙니다: ${describeValue(vnode)}`);
  const el = document.createElement(vnode.type);
  for (const [name, value] of Object.entries(vnode.props || {})) setProp(el, name, value);
  for (const child of vnode.children || []) el.appendChild(createElement(child));
  return el;
}

/**
 * 속성 하나 설정 (createElement · patch 공용). null · undefined · false → 제거, true → 값 없는 속성, 그 밖 → 문자열.
 * setAttribute 가 거부하는 이름(예: 공백이 든 "a b")은 patch 가 중간에 멈추지 않도록 경고 후 건너뛰고 false.
 */
export function setProp(el, name, value) {
  try {
    if (value == null || value === false) el.removeAttribute(name);
    else el.setAttribute(name, value === true ? "" : String(value));
    syncFormProperty(el, name, value);
    return true;
  } catch (err) {
    if (err?.name !== "InvalidCharacterError") throw err;
    console.warn(`[setProp] 쓸 수 없는 속성 이름이라 건너뜁니다: "${name}"`);
    return false;
  }
}

/**
 * 폼 요소의 프로퍼티(지금 상태)도 속성에 맞춘다 (Phase 2 의 제어 컴포넌트용).
 * value · checked · selected 속성은 "처음 값" 일 뿐이라, 사용자가 입력한 뒤에는 속성만 바꿔서는 화면이 안 바뀐다.
 * value 는 이미 같으면 건드리지 않는다 (입력 중인 커서 위치 유지).
 */
function syncFormProperty(el, name, value) {
  const off = value == null || value === false;
  if (name === "value" && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) {
    const next = off || value === true ? "" : String(value);
    if (el.value !== next) el.value = next;
  } else if (name === "checked" && el.tagName === "INPUT") el.checked = !off;
  else if (name === "selected" && el.tagName === "OPTION") el.selected = !off;
}

/** 요소 VNode 모양인가: 배열이 아닌 객체이고 type 이 비어 있지 않은 문자열 */
export function isElementVNode(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) && typeof value.type === "string" && value.type !== "";
}

/**
 * VNode 트리 전체 검사 (diff · mount 의 입력 검사). 잘못되면 위치를 담은 TypeError.
 * 올바른 VNode = 문자열, 또는 isElementVNode 이고 props 는 없거나 평범한 객체(값은 문자열 · 숫자 · 불리언 · null),
 * children 은 없거나 배열. (숫자 · null 자식은 h() 가 정리해 주지만, VNode 안에 그대로 있으면 잘못된 것)
 */
export function validateVNode(vnode, where = "VNode", at = "루트") {
  if (typeof vnode === "string") return;
  if (!isElementVNode(vnode)) throw new TypeError(`[${where}] ${at}: 올바른 VNode 가 아닙니다: ${describeValue(vnode)}`);
  checkProps(vnode.props, `[${where}] ${at} <${vnode.type}>`);
  const { children } = vnode;
  if (children == null) return;
  if (!Array.isArray(children)) {
    throw new TypeError(`[${where}] ${at} <${vnode.type}>: children 은 배열이어야 합니다: ${describeValue(children)}`);
  }
  // forEach 는 배열의 빈 칸(hole)을 건너뛰므로 인덱스로 돈다
  for (let i = 0; i < children.length; i++) validateVNode(children[i], where, `${at}.children[${i}]`);
}

/** props 검사: 없거나 평범한 객체, 값은 문자열 · 숫자 · 불리언 · null · undefined (객체면 "[object Object]" 가 되어 버림) */
export function checkProps(props, where) {
  if (props == null) return;
  const proto = typeof props === "object" ? Object.getPrototypeOf(props) : undefined;
  if (Array.isArray(props) || (proto !== Object.prototype && proto !== null)) {
    throw new TypeError(`${where}: props 는 평범한 객체여야 합니다: ${describeValue(props)}`);
  }
  for (const [name, value] of Object.entries(props)) {
    if (value != null && !["string", "number", "boolean"].includes(typeof value)) {
      throw new TypeError(`${where}: 속성 "${name}" 의 값으로 쓸 수 없습니다 (${typeof value})`);
    }
  }
}

/** 오류 메시지용으로 값을 짧게 */
function describeValue(value) {
  if (typeof value === "function") return "함수";
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}
