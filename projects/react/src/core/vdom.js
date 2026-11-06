// [vdom.js] Virtual DOM 생성 및 변환 (실제 DOM ↔ Virtual DOM)

/**
 * [팀 공통] Virtual DOM 노드 형식
 * 요소: { type: "div", props: { id: "box" }, children: [VNode, ...] }
 * 텍스트: "문자열"
 *
 * - type    : 태그 이름 (항상 소문자)
 * - props   : 속성 이름 → 값(문자열). 실제 HTML 속성 이름을 그대로 쓴다 (class, style, data-* ...)
 * - children: 자식 VNode 배열. 요소 VNode 또는 문자열(텍스트 노드)
 */

// DOM 노드 종류 상수 (Node.ELEMENT_NODE 등과 같은 값)
const ELEMENT_NODE = 1;
const TEXT_NODE = 3;

/**
 * Virtual DOM 생성 헬퍼
 *
 * 사용 예) h("ul", { class: "list" }, h("li", null, "하나"), ["둘", "셋"].map(t => h("li", null, t)))
 *
 * 정규화 규칙
 * 1. props 가 null / undefined 이면 {} 로 바꾼다.
 *    (매개변수 기본값 `props = {}` 는 undefined 일 때만 동작하고 null 일 때는 동작하지 않기 때문)
 * 2. children 안의 배열은 평탄화한다. (map 결과를 그대로 넣을 수 있게)
 * 3. null / undefined / true / false 는 화면에 아무것도 그리지 않으므로 제거한다.
 *    (조건부 렌더링 `cond && h(...)` 을 지원하기 위함)
 * 4. 숫자는 텍스트 노드이므로 문자열로 바꾼다.
 */
export function h(type, props = {}, ...children) {
  return {
    type: String(type).toLowerCase(),
    props: props == null ? {} : { ...props }, // 원본 객체를 공유하지 않도록 얕은 복사
    children: normalizeChildren(children),
  };
}

/**
 * children 배열을 위 규칙대로 정리한다. (h 내부에서 사용)
 * 재귀적으로 배열을 펼치면서 유효한 VNode 만 모은다.
 */
function normalizeChildren(children, result = []) {
  for (const child of children) {
    if (Array.isArray(child)) {
      normalizeChildren(child, result); // 중첩 배열 평탄화
    } else if (child == null || typeof child === "boolean") {
      continue; // 렌더링하지 않는 값
    } else if (typeof child === "number") {
      result.push(String(child));
    } else {
      result.push(child); // 문자열 또는 요소 VNode
    }
  }
  return result;
}

/**
 * 이 DOM 노드를 Virtual DOM 에서 무시해야 하는지 판단한다.
 *
 * 무시하는 것
 * - 주석, 처리 명령 등 요소/텍스트가 아닌 노드
 * - "줄바꿈이 들어 있는 공백만으로 된" 텍스트 노드
 *   → HTML 소스를 들여쓰기하면서 생긴 공백이다. 화면에 의미가 없는데 남겨 두면
 *     소스 모양만 바꿔도 Diff 가 변경으로 인식해 버린다.
 *
 * 남기는 것
 * - `<b>a</b> <i>b</i>` 사이의 " " 처럼 줄바꿈 없는 공백 → 화면에 실제로 띄어쓰기가 보이므로 유지
 *
 * ※ domToVdom 과 patch 가 반드시 이 함수 하나를 같이 써야
 *   "DOM 의 n번째 자식" 과 "VNode 의 n번째 자식" 이 같은 노드를 가리킨다.
 */
export function isIgnorableNode(node) {
  if (node.nodeType === ELEMENT_NODE) return false;
  if (node.nodeType !== TEXT_NODE) return true;
  const text = node.nodeValue;
  const isIndentation = /^[ \t\r\n]*$/.test(text) && /[\r\n]/.test(text);
  if (!isIndentation) return false;
  // <pre>, <textarea>, <listing> 안에서는 줄바꿈 · 공백이 화면에 그대로 보이므로 들여쓰기로 보지 않는다.
  // (예: <pre><b>x</b>\n\n<b>y</b></pre> 의 "\n\n" 은 빈 줄 두 개)
  const parent = node.parentElement;
  return !(parent && parent.closest("pre, textarea, listing"));
}

/**
 * VNode 로 변환될 자식 DOM 노드만 골라 배열로 반환한다.
 * (el.childNodes 에서 isIgnorableNode 인 것을 뺀 목록)
 */
export function vdomChildNodes(el) {
  return Array.from(el.childNodes).filter((child) => !isIgnorableNode(child));
}

/**
 * 실제 DOM → Virtual DOM
 *
 * - 텍스트 노드 → 문자열 그대로
 * - 요소 노드   → { type, props: 모든 속성, children: 자식들을 차례로 변환 (명시적 스택, 재귀 없음) }
 *
 * 주의: 사용자가 input 에 입력한 값(value 프로퍼티)처럼 "속성(attribute)이 아닌 상태"는
 *       HTML 에 나타나지 않으므로 변환되지 않는다. Phase 1 은 HTML 구조 비교가 목적이다.
 */
export function domToVdom(node) {
  if (node.nodeType === TEXT_NODE) {
    return node.nodeValue;
  }
  if (node.nodeType !== ELEMENT_NODE) {
    return null; // 주석 등은 VNode 가 없다. (vdomChildNodes 를 쓰면 여기까지 오지 않음)
  }

  // 재귀 대신 명시적 스택(stack)으로 내려간다.
  // 재귀로 짜면 트리 깊이만큼 함수 호출이 쌓여서, 깊이 수천 단계의 DOM 에서
  // 브라우저 호출 스택이 넘친다 (Chrome 기준 약 5,000 단계에서 RangeError).
  //
  // 스택 항목 = { node: 변환할 DOM 노드, siblings: 결과를 넣을 부모의 children 배열 }
  // 자식을 "역순" 으로 쌓으면 pop 순서가 원래 순서(앞 → 뒤)가 되어,
  // 재귀 버전과 같은 순서(깊이 우선, 앞의 형제 먼저)로 children 배열이 채워진다.
  const rootResult = [];
  const stack = [{ node, siblings: rootResult }];
  while (stack.length > 0) {
    const { node: current, siblings } = stack.pop();
    if (current.nodeType === TEXT_NODE) {
      siblings.push(current.nodeValue);
      continue;
    }

    // 속성 목록(NamedNodeMap)을 평범한 객체로 옮긴다.
    // Object.fromEntries 는 "__proto__" 같은 이름도 평범한 자기 속성으로 만든다.
    // (props[name] = value 로 넣으면 "__proto__" 는 속성이 아니라 프로토타입 설정으로 처리되어 사라진다)
    const props = Object.fromEntries(Array.from(current.attributes, (attr) => [attr.name, attr.value]));
    const vnode = { type: current.tagName.toLowerCase(), props, children: [] };
    siblings.push(vnode);

    // <template> 은 내용이 childNodes 가 아니라 content(DocumentFragment)에 들어 있다.
    const childSource = current.tagName === "TEMPLATE" ? current.content : current;
    const childNodes = vdomChildNodes(childSource);
    for (let i = childNodes.length - 1; i >= 0; i--) {
      stack.push({ node: childNodes[i], siblings: vnode.children });
    }
  }
  return rootResult[0];
}

/**
 * 영역(컨테이너) → 루트 VNode
 *
 * 실제 영역(#real-area)과 테스트 영역(#test-area)은 id·class 가 서로 다르다.
 * 컨테이너 자체까지 비교하면 "id 가 바뀌었다" 는 엉뚱한 패치가 생기므로,
 * 컨테이너는 속성이 없는 가상의 div 로 취급하고 "내용(자식)" 만 비교 대상으로 삼는다.
 *
 * 반환 예) { type: "div", props: {}, children: [ ...영역 안의 노드들 ] }
 */
export function containerToVdom(container) {
  return {
    type: "div",
    props: {},
    children: vdomChildNodes(container).map(domToVdom),
  };
}

/**
 * Virtual DOM → 실제 DOM
 *
 * - 문자열 → Text 노드
 * - 요소   → document.createElement + 속성 설정 + 자식 생성 (명시적 스택, 재귀 없음)
 */
export function createElement(vnode) {
  // 재귀 대신 명시적 스택으로 만든다. (깊이 수천 단계에서도 호출 스택이 넘치지 않도록 — domToVdom 참고)
  //
  // 스택 항목 두 종류
  //   { vnode, parent } : vnode 로 DOM 노드를 만들어 parent 에 붙인다 (parent 가 null 이면 결과 루트)
  //   { leave: vnode }  : vnode 의 자식을 모두 만든 뒤 "조상 목록" 에서 뺀다 (재귀 버전의 함수 종료 시점)
  //
  // ancestors: 지금 만들고 있는 노드의 조상 VNode 들.
  // 자기 조상을 자식으로 다시 가진 VNode(순환 참조)는 끝없이 내려가므로 미리 찾아 TypeError 로 알린다.
  // (브라우저의 "호출 스택 초과" 오류에 맡기면 Chrome 은 RangeError, Firefox 는 InternalError 처럼 종류가 제각각이다)
  // 형제 하위 트리에서 같은 객체를 다시 쓰는 것(공유)은 순환이 아니므로, 자식을 다 만든 뒤 조상에서 빼서 허용한다.
  const ancestors = new Set();
  const stack = [{ vnode, parent: null }];
  let root = null;

  while (stack.length > 0) {
    const item = stack.pop();
    if (item.leave) {
      ancestors.delete(item.leave);
      continue;
    }
    const { vnode: current, parent } = item;
    const node = createOne(current, ancestors);
    if (parent) parent.appendChild(node);
    else root = node;
    if (node.nodeType !== ELEMENT_NODE) continue; // 텍스트 노드는 자식이 없다

    // 자식을 역순으로 쌓아야 앞의 자식부터 만들어져 appendChild 순서가 원래 순서가 된다.
    // leave 를 가장 먼저 쌓으면 자식(과 그 자손)이 모두 끝난 뒤에 실행된다.
    ancestors.add(current);
    stack.push({ leave: current });
    const children = current.children || [];
    for (let i = children.length - 1; i >= 0; i--) {
      stack.push({ vnode: children[i], parent: node });
    }
  }
  return root;
}

/**
 * VNode 하나로 DOM 노드 하나를 만든다. (자식은 만들지 않음 — createElement 의 스택이 처리)
 * 텍스트 → Text 노드, 요소 → 속성까지 설정한 Element
 */
function createOne(vnode, ancestors) {
  if (typeof vnode === "string" || typeof vnode === "number") {
    return document.createTextNode(String(vnode));
  }
  // 요소 VNode 는 { type: "태그 이름" } 이 반드시 있어야 한다.
  // 검사하지 않으면 true → <undefined> 요소처럼 엉뚱한 노드가 조용히 만들어진다.
  if (!isElementVNode(vnode)) {
    throw new TypeError(`[createElement] 올바른 VNode 가 아닙니다: ${describeValue(vnode)}`);
  }
  if (ancestors.has(vnode)) {
    throw new TypeError(`[createElement] 순환 참조된 VNode 입니다: <${vnode.type}> 가 자기 조상을 자식으로 가집니다`);
  }

  const el = document.createElement(vnode.type);
  for (const [name, value] of Object.entries(vnode.props || {})) {
    setProp(el, name, value);
  }
  return el;
}

/**
 * 속성 하나를 실제 DOM 에 설정한다. (createElement, patch 공용)
 *
 * - null / undefined / false → 속성 제거 (불리언 속성 disabled 등을 끄는 경우)
 * - true                     → 값 없는 속성 (예: <input disabled>)
 * - 그 밖의 값               → 문자열로 setAttribute
 *
 * Phase 1 의 props 는 domToVdom 에서 오므로 항상 문자열이지만,
 * h() 로 직접 만든 VNode 도 안전하게 처리하도록 분기를 둔다.
 */
export function setProp(el, name, value) {
  try {
    if (value == null || value === false) {
      el.removeAttribute(name);
    } else if (value === true) {
      el.setAttribute(name, "");
    } else {
      el.setAttribute(name, String(value));
    }
    syncFormProperty(el, name, value);
    return true;
  } catch (err) {
    // HTML 파서는 받아 주지만 setAttribute 는 거부하는 이름이 있다. (예: 공백이 든 "a b")
    // 여기서 예외를 그대로 던지면 patch 가 중간에 멈춰 실제 영역이 반쯤만 바뀐 상태가 되므로,
    // 그 속성 하나만 건너뛰고 경고한다. (main.js 의 자가 점검이 불일치를 화면에 표시한다)
    if (err && err.name === "InvalidCharacterError") {
      console.warn(`[setProp] 쓸 수 없는 속성 이름이라 건너뜁니다: "${name}"`);
      return false;
    }
    throw err;
  }
}

/**
 * 폼 요소의 "지금 상태(프로퍼티)" 를 속성값에 맞춘다. (Phase 2 의 제어 컴포넌트용)
 *
 * 속성(attribute)과 프로퍼티(property)는 다르다.
 *   <input value="a"> 의 value 속성은 "처음 값" 일 뿐이라, 사용자가 한 번 입력한 뒤에는
 *   setAttribute("value", "") 를 해도 화면의 글자가 지워지지 않는다. checked · selected 도 같다.
 * 그래서 이 세 이름은 속성과 함께 프로퍼티(el.value, el.checked, el.selected)도 바꾼다.
 *   - value    : <input> · <textarea> · <select> — 이미 같은 값이면 건드리지 않는다 (입력 중인 커서 위치 유지)
 *   - checked  : <input> (체크박스 · 라디오)
 *   - selected : <option>
 * 값이 null · false (속성 제거)면 value 는 "", checked · selected 는 false.
 */
function syncFormProperty(el, name, value) {
  const off = value == null || value === false;
  if (name === "value" && "value" in el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) {
    const next = off ? "" : value === true ? "" : String(value);
    if (el.value !== next) el.value = next;
  } else if (name === "checked" && el.tagName === "INPUT") {
    el.checked = !off;
  } else if (name === "selected" && el.tagName === "OPTION") {
    el.selected = !off;
  }
}

/**
 * 요소 VNode 모양인지 검사: 객체이고 type 이 비어 있지 않은 문자열
 * (patch 의 입력 검사에서도 쓴다)
 */
export function isElementVNode(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) &&
    typeof value.type === "string" && value.type !== "";
}

/**
 * VNode 트리 전체가 올바른 모양인지 검사한다. 잘못되면 TypeError. (diff, patch 의 입력 검사용)
 *
 * 올바른 VNode
 *   - 문자열 (텍스트 노드)
 *   - 요소: isElementVNode 이고
 *       props    : 없음(undefined · null) 또는 평범한 객체. 값은 문자열 · 숫자 · 불리언 · null · undefined
 *                  (setProp 이 처리할 수 있는 값. 객체를 넣으면 "[object Object]" 가 속성값이 되어 버린다)
 *       children : 없음(undefined · null) 또는 배열. 각 자식도 올바른 VNode
 *   ※ 숫자 · null · true 같은 값은 h() 가 정리해 주지만, VNode 안에 그대로 있으면 잘못된 것으로 본다.
 *     (patch 는 예전부터 숫자 노드를 거부했다 — #139)
 *
 * 순환 참조(자기 조상을 자식으로 가짐)도 TypeError. 같은 객체를 여러 자리에 쓰는 공유는 허용한다.
 * 깊은 트리에서도 호출 스택이 넘치지 않도록 명시적 스택으로 내려간다.
 *
 * @param {*} vnode 검사할 값
 * @param {string} where 오류 메시지 앞에 붙일 이름 (예: "diff 새 VDOM")
 */
export function validateVNode(vnode, where = "VNode") {
  const ancestors = new Set();
  // 스택 항목: { value, at: 위치 설명 } 또는 { leave: 요소 } (자식 검사가 끝나 조상 목록에서 뺌)
  const stack = [{ value: vnode, at: "루트" }];
  while (stack.length > 0) {
    const item = stack.pop();
    if (item.leave) {
      ancestors.delete(item.leave);
      continue;
    }
    const { value, at } = item;
    if (typeof value === "string") continue;
    if (!isElementVNode(value)) {
      throw new TypeError(`[${where}] ${at}: 올바른 VNode 가 아닙니다: ${describeValue(value)}`);
    }
    if (ancestors.has(value)) {
      throw new TypeError(`[${where}] ${at}: 순환 참조된 VNode 입니다 (<${value.type}> 가 자기 조상을 자식으로 가집니다)`);
    }
    checkProps(value.props, `[${where}] ${at} <${value.type}>`);
    const { children } = value;
    if (children == null) continue;
    if (!Array.isArray(children)) {
      throw new TypeError(`[${where}] ${at} <${value.type}>: children 은 배열이어야 합니다: ${describeValue(children)}`);
    }
    ancestors.add(value);
    stack.push({ leave: value });
    for (let i = children.length - 1; i >= 0; i--) {
      stack.push({ value: children[i], at: `${at}.children[${i}]` });
    }
  }
}

/**
 * props 객체 검사 (validateVNode, patch 의 PROPS.set 검사에서 같이 쓴다)
 * 없음(undefined · null) 또는 평범한 객체, 값은 isPropValue
 */
export function checkProps(props, where) {
  if (props == null) return;
  const proto = typeof props === "object" ? Object.getPrototypeOf(props) : undefined;
  if (Array.isArray(props) || (proto !== Object.prototype && proto !== null)) {
    throw new TypeError(`${where}: props 는 평범한 객체여야 합니다: ${describeValue(props)}`);
  }
  for (const [name, value] of Object.entries(props)) {
    if (!isPropValue(value)) {
      throw new TypeError(`${where}: 속성 "${name}" 의 값으로 쓸 수 없습니다 (${typeof value})`);
    }
  }
}

/** 속성값으로 쓸 수 있는가: 문자열 · 숫자 · 불리언 · null · undefined (setProp 이 처리하는 값) */
function isPropValue(value) {
  return value == null || ["string", "number", "boolean"].includes(typeof value);
}

/** 오류 메시지용으로 값을 짧게 보여 준다 */
function describeValue(value) {
  if (typeof value === "function") return "함수";
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}
