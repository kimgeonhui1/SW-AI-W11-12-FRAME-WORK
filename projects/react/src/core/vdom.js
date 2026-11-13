// [vdom.js] Virtual DOM 생성 및 변환 (실제 DOM ↔ Virtual DOM)

/**
 * ── 이 파일이 하는 일 ─────────────────────────────────────────────────
 * 브라우저의 실제 DOM 은 고칠 때마다 레이아웃을 다시 계산(Reflow)하고 다시 칠해서(Repaint) 비싸다.
 * 그래서 화면을 가벼운 "자바스크립트 객체(Virtual DOM)" 로 옮겨 놓고, 객체끼리 비교한 뒤
 * 정말 바뀐 곳만 실제 DOM 에 반영한다. 이 파일은 그 "객체로 옮기기 / 다시 DOM 으로 만들기" 를 맡는다.
 *
 *   실제 DOM ──domToVdom / containerToVdom──▶ VNode
 *   VNode    ──createElement──────────────────▶ 실제 DOM
 *   h()      : 코드로 VNode 를 직접 만드는 도우미 (Phase 2 컴포넌트가 사용)
 *
 * [팀 공통] VNode 형식 (팀원 모두 같은 모양을 쓴다 — 바꾸면 안 됨)
 *   요소  : { type: "div", props: { id: "box" }, children: [VNode, ...] }
 *           - type     : 태그 이름 (항상 소문자)
 *           - props    : 속성 이름 → 값. 실제 HTML 속성 이름을 그대로 쓴다 (class, style, data-* …)
 *           - children : 자식 VNode 배열 (요소 또는 문자열)
 *   텍스트: "문자열" 그대로 (객체로 감싸지 않는다)
 * ─────────────────────────────────────────────────────────────────────
 */

// DOM 노드 종류 번호 (Node.ELEMENT_NODE, Node.TEXT_NODE 와 같은 값)
const ELEMENT_NODE = 1;
const TEXT_NODE = 3;

/**
 * VNode 를 만드는 도우미 함수 (JSX 대신 쓰는 함수)
 *
 *   예) h("ul", { class: "list" }, h("li", null, "하나"), items.map((t) => h("li", null, t)))
 *       → { type: "ul", props: { class: "list" }, children: [ {type:"li",…}, … ] }
 *
 * 정리 규칙 (컴포넌트 코드를 편하게 쓰기 위한 것)
 *   1. props 가 null · undefined 면 {} 로 바꾼다.
 *      (매개변수 기본값 props = {} 는 undefined 일 때만 동작하고 null 일 때는 동작하지 않기 때문)
 *   2. props 는 얕은 복사한다 → 호출한 쪽의 객체를 나중에 고쳐도 VNode 가 같이 바뀌지 않는다.
 *   3. 자식 안의 배열은 평탄화한다 → items.map(...) 결과를 그대로 넣을 수 있다.
 *   4. null · undefined · true · false 는 버린다 → 조건부 렌더링 `cond && h(...)` 을 쓸 수 있다.
 *   5. 숫자는 문자열로 바꾼다 → 숫자도 화면에는 글자(텍스트 노드)로 보이기 때문.
 *
 * @param {string} type 태그 이름 (대문자로 줘도 소문자로 바뀜)
 * @param {object|null} [props] 속성
 * @param {...any} children 자식들 (VNode · 문자열 · 숫자 · 배열 · null · 불리언)
 * @returns {{type: string, props: object, children: Array}} 요소 VNode
 */
export function h(type, props = {}, ...children) {
  return { type: String(type).toLowerCase(), props: props == null ? {} : { ...props }, children: normalizeChildren(children) };
}

/**
 * h() 의 자식 목록을 위 규칙(3~5)대로 정리한다.
 * 배열을 만나면 재귀로 들어가 펼치고, 결과는 하나의 배열(result)에 차례로 모은다.
 *
 * @param {Array} children 정리할 자식 목록
 * @param {Array} [result] 결과를 쌓는 배열 (재귀 호출끼리 공유)
 * @returns {Array} 문자열 · 요소 VNode 만 남은 평평한 배열
 */
function normalizeChildren(children, result = []) {
  for (const child of children) {
    if (Array.isArray(child)) normalizeChildren(child, result); //              중첩 배열 → 펼친다
    else if (child == null || typeof child === "boolean") continue; //          그리지 않는 값 → 버린다
    else result.push(typeof child === "number" ? String(child) : child); //    숫자 → 문자열, 나머지는 그대로
  }
  return result;
}

/**
 * 이 DOM 노드를 Virtual DOM 에서 "없는 것" 으로 칠지 판단한다.
 *
 * 무시하는 것
 *   - 주석, 처리 명령 등 요소도 텍스트도 아닌 노드 → 화면에 보이지 않는다
 *   - "줄바꿈이 들어 있는 공백만으로 된" 텍스트 → HTML 소스를 들여쓰기하면서 생긴 공백이다.
 *     화면에는 의미가 없는데 남겨 두면, 소스의 들여쓰기만 바꿔도 Diff 가 "바뀌었다" 고 판단해 버린다.
 * 남기는 것
 *   - `<b>a</b> <i>b</i>` 사이의 " " 처럼 줄바꿈 없는 공백 → 화면에 실제로 띄어쓰기로 보인다
 *   - <pre> · <textarea> · <listing> 안의 줄바꿈 공백 → 이 태그들은 공백을 그대로 화면에 보여 준다
 *
 * ※ domToVdom 과 patch(resolvePath) 가 반드시 이 함수 하나를 같이 써야 한다.
 *   그래야 "DOM 의 n번째 자식" 과 "VNode 의 n번째 자식" 이 같은 노드를 가리킨다.
 *
 * @param {Node} node 검사할 DOM 노드
 * @returns {boolean} true 면 VDOM 에서 무시
 */
export function isIgnorableNode(node) {
  if (node.nodeType === ELEMENT_NODE) return false; //    요소는 항상 남긴다
  if (node.nodeType !== TEXT_NODE) return true; //        주석 등은 항상 버린다
  const text = node.nodeValue;
  // "공백 문자만" 이면서 "줄바꿈이 하나라도 있는" 텍스트만 들여쓰기로 본다
  if (!/^[ \t\r\n]*$/.test(text) || !/[\r\n]/.test(text)) return false;
  // 들여쓰기처럼 보여도 <pre> 같은 태그 안이면 화면에 보이는 내용이므로 남긴다
  return !node.parentElement?.closest("pre, textarea, listing");
}

/**
 * VNode 로 바뀔 자식 DOM 노드만 골라 배열로 돌려준다.
 * (el.childNodes 에서 isIgnorableNode 인 것을 뺀 목록 — "n번째 자식" 을 셀 때 항상 이 목록을 쓴다)
 *
 * @param {Node} el 부모 노드 (요소 또는 DocumentFragment)
 * @returns {Node[]}
 */
export function vdomChildNodes(el) {
  return Array.from(el.childNodes).filter((child) => !isIgnorableNode(child));
}

/**
 * 실제 DOM → VNode (자식까지 재귀로 전부)
 *
 *   텍스트 노드 → 그 글자(문자열)
 *   요소 노드   → { type: 태그 이름(소문자), props: 모든 속성, children: 자식들을 차례로 변환 }
 *
 * 주의: 사용자가 input 에 입력한 값(value 프로퍼티)처럼 "속성(attribute)이 아닌 상태" 는
 *       HTML 에 나타나지 않으므로 옮기지 않는다. Phase 1 은 HTML 구조를 비교하는 것이 목적이다.
 *
 * @param {Node} node 변환할 DOM 노드
 * @returns {object|string|null} VNode (주석 등 변환할 수 없는 노드면 null)
 */
export function domToVdom(node) {
  if (node.nodeType === TEXT_NODE) return node.nodeValue;
  if (node.nodeType !== ELEMENT_NODE) return null; // 주석 등. vdomChildNodes 를 거치면 여기까지 오지 않는다

  // 속성 목록(NamedNodeMap)을 평범한 객체로 옮긴다.
  // Object.fromEntries 를 쓰는 이유: "__proto__" 같은 이름도 평범한 자기 속성으로 만들어 준다.
  // (props[name] = value 로 넣으면 "__proto__" 는 속성이 아니라 프로토타입 설정으로 처리되어 사라진다)
  const props = Object.fromEntries(Array.from(node.attributes, (attr) => [attr.name, attr.value]));

  // <template> 은 내용이 childNodes 가 아니라 content(DocumentFragment) 안에 들어 있다 (childHost)
  return { type: node.tagName.toLowerCase(), props, children: vdomChildNodes(childHost(node)).map(domToVdom) };
}

/**
 * 자식이 실제로 들어가는 곳.
 * <template> 의 자식은 template 자신이 아니라 content(DocumentFragment) 안에 있다 (화면에 그려지지 않는 내용).
 * domToVdom(읽기) · createElement(만들기) · patch(경로 찾기 · CREATE) 가 모두 이 함수로 같은 곳을 본다.
 * 셋 중 하나라도 다른 곳을 보면 template 의 VDOM 과 실제 DOM 이 어긋난다.
 *
 * @param {Node} node
 * @returns {Node} template 이면 content, 아니면 node 그대로
 */
export const childHost = (node) => (node.tagName === "TEMPLATE" ? node.content : node);

/**
 * 영역(컨테이너) → 루트 VNode
 *
 * Phase 1 의 실제 영역(#real-area)과 테스트 영역(#test-area)은 id · class 가 서로 다르다.
 * 컨테이너 자체까지 비교하면 "id 가 바뀌었다" 는 엉뚱한 패치가 생기므로,
 * 컨테이너는 속성이 없는 가상의 div 로 두고 "안에 든 내용(자식)" 만 비교 대상으로 삼는다.
 * Phase 2 의 FunctionComponent 도 같은 모양의 루트를 만들어 쓴다.
 *
 *   반환 예) { type: "div", props: {}, children: [ ...영역 안의 노드들 ] }
 *
 * @param {Element} container 영역 요소
 * @returns {{type: "div", props: {}, children: Array}}
 */
export function containerToVdom(container) {
  return { type: "div", props: {}, children: vdomChildNodes(container).map(domToVdom) };
}

/**
 * VNode → 실제 DOM (자식까지 재귀로 전부 만든다)
 *
 *   문자열(또는 숫자) → Text 노드
 *   요소 VNode        → document.createElement + 속성 설정(setProp) + 자식 생성
 *
 * 요소 VNode 는 { type: "태그 이름" } 이 반드시 있어야 한다.
 * 검사하지 않으면 true 같은 값이 <undefined> 요소처럼 엉뚱한 노드로 조용히 만들어지므로 TypeError 로 알린다.
 *
 * @param {object|string|number} vnode
 * @returns {Node} 새로 만든 DOM 노드 (아직 문서에 붙지 않은 상태)
 * @throws {TypeError} 올바른 VNode 가 아닐 때
 */
export function createElement(vnode) {
  if (typeof vnode === "string" || typeof vnode === "number") return document.createTextNode(String(vnode));
  if (!isElementVNode(vnode)) throw new TypeError(`[createElement] 올바른 VNode 가 아닙니다: ${describeValue(vnode)}`);
  const el = document.createElement(vnode.type);
  for (const [name, value] of Object.entries(vnode.props || {})) setProp(el, name, value); // 속성
  const host = childHost(el); // <template> 이면 content 에 붙인다 (domToVdom 이 거기서 읽으므로)
  for (const child of vnode.children || []) host.appendChild(createElement(child)); //      자식 (재귀)
  return el;
}

/**
 * 속성 하나를 실제 DOM 에 설정한다. (createElement 와 patch 가 같이 쓴다)
 *
 *   null · undefined · false → 속성 제거   (예: disabled 를 끔)
 *   true                     → 값 없는 속성 (예: <input disabled>)
 *   그 밖의 값               → 문자열로 setAttribute
 * Phase 1 의 props 는 domToVdom 에서 오므로 항상 문자열이지만, Phase 2 에서 h() 로 만든 VNode 에는
 * 숫자 · 불리언이 들어올 수 있어서 위처럼 나눠 처리한다.
 *
 * HTML 파서는 받아 주지만 setAttribute 는 거부하는 이름이 있다 (예: 공백이 든 "a b").
 * 여기서 예외를 그대로 던지면 patch 가 중간에 멈춰 실제 영역이 반쯤만 바뀐 상태가 되므로,
 * 그 속성 하나만 경고 후 건너뛰고 false 를 돌려준다. (Phase 1 의 자가 점검이 불일치를 화면에 알려 준다)
 *
 * @param {Element} el 대상 요소
 * @param {string} name 속성 이름
 * @param {*} value 속성 값
 * @returns {boolean} 설정했으면 true, 쓸 수 없는 이름이라 건너뛰었으면 false
 */
export function setProp(el, name, value) {
  try {
    if (value == null || value === false) el.removeAttribute(name);
    else el.setAttribute(name, value === true ? "" : String(value));
    syncFormProperty(el, name, value); // 폼 요소의 "지금 상태" 도 함께 맞춘다
    return true;
  } catch (err) {
    if (err?.name !== "InvalidCharacterError") throw err; // 이름 문제가 아닌 오류는 그대로 알린다
    console.warn(`[setProp] 쓸 수 없는 속성 이름이라 건너뜁니다: "${name}"`);
    return false;
  }
}

/**
 * 폼 요소의 프로퍼티(지금 상태)도 속성 값에 맞춘다. (Phase 2 의 "제어 컴포넌트" 용)
 *
 * 속성(attribute)과 프로퍼티(property)는 다르다.
 *   <input value="a"> 의 value 속성은 "처음 값" 일 뿐이라, 사용자가 한 번 입력한 뒤에는
 *   setAttribute("value", "") 를 해도 화면의 글자가 지워지지 않는다. checked · selected 도 마찬가지다.
 * 그래서 이 세 이름은 속성과 함께 프로퍼티(el.value · el.checked · el.selected)도 바꾼다.
 *   value    : <input> · <textarea> · <select>. 이미 같은 값이면 건드리지 않는다 (입력 중인 커서 위치 유지)
 *   checked  : <input> (체크박스 · 라디오)
 *   selected : <option>
 * 값이 null · false (= 속성 제거)면 value 는 "", checked · selected 는 false 로 맞춘다.
 *
 * @param {Element} el
 * @param {string} name
 * @param {*} value
 */
function syncFormProperty(el, name, value) {
  const off = value == null || value === false; // 속성을 지우는 경우인가
  if (name === "value" && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) {
    const next = off || value === true ? "" : String(value);
    if (el.value !== next) el.value = next; // 같으면 그대로 두어야 커서가 튀지 않는다
  } else if (name === "checked" && el.tagName === "INPUT") el.checked = !off;
  else if (name === "selected" && el.tagName === "OPTION") el.selected = !off;
}

/**
 * 요소 VNode 모양인지 검사한다: 배열이 아닌 객체이고, type 이 비어 있지 않은 문자열
 * (createElement · validateVNode 가 쓴다. 노드 하나만 보고 자식은 보지 않는다)
 *
 * @param {*} value
 * @returns {boolean}
 */
export function isElementVNode(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) && typeof value.type === "string" && value.type !== "";
}

/**
 * VNode 트리 전체가 올바른 모양인지 검사한다. 잘못되면 "어디가 잘못됐는지" 위치를 담은 TypeError.
 * (diff 와 FunctionComponent.mount 가 입력 검사로 쓴다)
 *
 * 올바른 VNode
 *   - 문자열 (텍스트 노드)
 *   - 요소: isElementVNode 이고
 *       props    : 없음(undefined · null) 또는 평범한 객체. 값은 문자열 · 숫자 · 불리언 · null · undefined
 *                  (객체를 넣으면 setAttribute 가 "[object Object]" 를 속성 값으로 써 버린다)
 *       children : 없음(undefined · null) 또는 배열. 각 자식도 올바른 VNode
 *   ※ 숫자 · null · true 같은 자식은 h() 가 정리해 주지만, VNode 안에 그대로 들어 있으면 잘못된 것으로 본다.
 * 같은 객체를 여러 자리에서 쓰는 것(공유)은 허용한다.
 *
 * @param {*} vnode 검사할 값
 * @param {string} [where] 오류 메시지 앞에 붙일 이름 (예: "diff 새 VDOM")
 * @param {string} [at] 트리 안의 위치 설명 (재귀로 내려가면서 "루트.children[0].children[2]" 처럼 붙인다)
 * @throws {TypeError} 잘못된 노드를 찾았을 때
 */
export function validateVNode(vnode, where = "VNode", at = "루트") {
  if (typeof vnode === "string") return; // 텍스트는 항상 올바르다
  if (!isElementVNode(vnode)) throw new TypeError(`[${where}] ${at}: 올바른 VNode 가 아닙니다: ${describeValue(vnode)}`);
  checkProps(vnode.props, `[${where}] ${at} <${vnode.type}>`);
  const { children } = vnode;
  if (children == null) return; // 자식 없음
  if (!Array.isArray(children)) {
    throw new TypeError(`[${where}] ${at} <${vnode.type}>: children 은 배열이어야 합니다: ${describeValue(children)}`);
  }
  // forEach 는 배열의 빈 칸(hole, 예: [a, , b])을 건너뛰어 검사가 빠지므로 인덱스로 돈다
  for (let i = 0; i < children.length; i++) validateVNode(children[i], where, `${at}.children[${i}]`);
}

/**
 * props 객체를 검사한다. (validateVNode 가 노드마다 부른다)
 *   - 없음(undefined · null) 이면 통과
 *   - 배열 · Date 처럼 "평범한 객체" 가 아니면 TypeError
 *   - 값이 문자열 · 숫자 · 불리언 · null · undefined 가 아니면 TypeError (setProp 이 처리할 수 있는 값만)
 *
 * @param {*} props
 * @param {string} where 오류 메시지 앞부분 (위치 설명)
 * @throws {TypeError}
 */
export function checkProps(props, where) {
  if (props == null) return;
  // 평범한 객체 = 프로토타입이 Object.prototype 이거나 null 인 객체
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

/**
 * 오류 메시지에 넣으려고 값을 짧은 글자로 바꾼다.
 * 함수는 "함수", JSON 으로 바꿀 수 있으면 JSON, 안 되면(순환 객체 등) String(value).
 *
 * @param {*} value
 * @returns {string}
 */
function describeValue(value) {
  if (typeof value === "function") return "함수";
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}
