// [vdom.js] Virtual DOM 생성 및 변환 (실제 DOM ↔ Virtual DOM) + 속성 적용 규칙(setProp / removeProp)

/**
 * [팀 공통] Virtual DOM 노드 형식
 * 요소: { type: "div", props: { id: "box" }, children: [VNode, ...] }
 * 텍스트: "문자열"
 *
 * 예) <div id="box">안녕<b>!</b></div> 는 아래 객체로 표현된다.
 *   {
 *     type: "div",                 // 태그 이름
 *     props: { id: "box" },        // 속성들
 *     children: [                  // 자식들 (순서대로)
 *       "안녕",                     // 텍스트 노드 → 그냥 문자열
 *       { type: "b", props: {}, children: ["!"] }  // 요소 노드 → 또 같은 모양의 객체
 *     ]
 *   }
 *
 * [이 파일의 VDOM 정규화 규칙] diff가 "같은 화면이면 같은 객체"로 비교할 수 있도록 형태를 통일한다.
 *   - 이웃한 텍스트는 하나의 문자열로 합친다       ("점수: ", "100" → "점수: 100")
 *   - 빈 문자열 텍스트는 버린다
 *   - style은 항상 camelCase 객체                 ("font-size: 12px" → { fontSize: "12px" })
 *   - checked / selected 는 true 이거나 아예 없음  (없으면 false라는 뜻)
 *
 * ── 이 파일에서 쓰는 브라우저 DOM API 사전 ───────────────────────────────
 * document.createElement("div")  : <div> "요소"를 새로 만든다. 아직 화면(문서)에는 안 붙어 있는 상태.
 * document.createTextNode("hi")  : 글자만 담긴 "텍스트 노드"를 새로 만든다. (태그 없는 순수 글자)
 * parent.appendChild(child)      : parent의 맨 마지막 자식으로 child를 붙인다. (자식 추가)
 * el.setAttribute("id", "a")     : HTML 속성을 쓴다. → <div id="a">
 * el.removeAttribute("id")       : HTML 속성을 지운다.
 * el.addEventListener("click", f): 클릭 같은 이벤트가 일어나면 함수 f를 실행하도록 등록한다.
 * el.removeEventListener(...)    : addEventListener로 등록한 것을 해제한다. (등록할 때와 "같은 함수"를 넘겨야 함)
 * el.style                       : 요소의 인라인 스타일 객체. el.style.color = "red" 처럼 쓴다.
 * node.nodeType                  : 노드 종류 번호. 1=요소(ELEMENT_NODE), 3=텍스트(TEXT_NODE), 8=주석
 * node.tagName                   : 요소의 태그 이름. HTML에서는 대문자로 나온다("DIV").
 * node.attributes                : 요소에 붙은 속성 목록. 각각 { name, value }를 가진다.
 * node.childNodes                : 자식 노드 목록 (텍스트·주석 노드까지 전부 포함)
 * node.textContent               : 노드 안의 글자
 * ─────────────────────────────────────────────────────────────────────
 */

// 공백을 그대로 보존해야 하는 태그 목록. Set은 "중복 없는 목록"이고, .has(x)로 들어 있는지 빠르게 확인할 수 있다.
// <pre>는 공백·줄바꿈 자체가 화면 내용이고, <textarea>는 자식 텍스트가 곧 입력값이라 하나라도 지우면 결과가 달라진다.
const WHITESPACE_PRESERVING_TAGS = new Set(["pre", "textarea"]);

// DOM에 attribute가 아니라 property로 넣어야 하는 props 목록.
// - attribute: HTML 태그에 적힌 글자 (<input value="a">). 처음 값(초기값)만 정한다.
// - property : 자바스크립트 객체의 값 (input.value). 지금 화면에 보이는 실제 값이다.
// 사용자가 input에 입력한 뒤에는 setAttribute("value")로 바꿔도 화면 값이 바뀌지 않기 때문에 property를 써야 한다.
const PROPERTY_PROPS = new Set(["value", "checked", "selected"]);

// HTML attribute 이름 → props 이름으로 바꾸는 표.
// JS에서 class / for는 예약어(문법에 쓰이는 단어)라서 React처럼 className / htmlFor라는 이름을 쓴다.
const ATTR_TO_PROP = { class: "className", for: "htmlFor" };
// 위 표의 반대 방향. props 이름 → HTML attribute 이름. (createElement에서 실제 DOM에 쓸 때 사용)
const PROP_TO_ATTR = { className: "class", htmlFor: "for" };

// 요소별로 "지금 등록된 이벤트 핸들러"를 기억해 두는 저장소.
// WeakMap: 키(DOM 요소)가 화면에서 사라져 더 이상 쓰이지 않으면 저장된 값도 자동으로 정리되는 Map.
// 구조: listenerStore.get(input) → { input: { onInput: 함수, onChange: 함수 }, click: { onClick: 함수 } }
// (이벤트 종류 → prop 이름 → 함수. onChange와 onInput이 같은 input 이벤트를 써도 서로 덮어쓰지 않게 prop 이름별로 나눈다)
const listenerStore = new WeakMap();

// 요소별로 연결된 ref를 기억해 두는 저장소 (요소가 화면에서 빠질 때 ref.current를 null로 되돌리기 위해)
const refStore = new WeakMap();

// patch 도중 미뤄 둔 ref 연결 목록 ([ref, el]). null이면 지금은 patch 중이 아님 → 바로 연결한다
// 이유: patch는 자식을 앞에서부터 고친다. 같은 ref가 뒤 형제 → 앞 형제로 옮겨가면 "앞 형제에 연결" 다음에 "뒤 형제에서 해제"가 실행되어
//       함수 ref가 마지막에 null을 받는다. 그래서 patch 중에는 해제는 바로 하고 연결은 모아 뒀다가 맨 끝에 한다 (React도 해제 → 연결 순서)
let pendingRefs = null;

// SVG 요소는 일반 HTML 요소와 "이름공간(namespace)"이 달라서 document.createElementNS로 만들어야 그려진다
export const SVG_NS = "http://www.w3.org/2000/svg";

// "on + 이름"을 소문자로 바꾼 것과 실제 브라우저 이벤트 이름이 다른 경우 (onDoubleClick → "doubleclick"이 아니라 "dblclick")
const EVENT_NAME_FIX = { doubleclick: "dblclick" };

// 숫자를 그대로 쓰는 CSS 속성 (React와 같은 목록 중 자주 쓰는 것). 그 외 숫자 값에는 px를 붙인다 ({ width: 100 } → "100px")
const UNITLESS_STYLES = new Set([
  "animationIterationCount", "aspectRatio", "columnCount", "fillOpacity", "flex", "flexGrow", "flexShrink",
  "fontWeight", "gridColumn", "gridColumnEnd", "gridColumnStart", "gridRow", "gridRowEnd", "gridRowStart",
  "lineHeight", "opacity", "order", "orphans", "scale", "stopOpacity", "strokeOpacity", "strokeWidth",
  "tabSize", "widows", "zIndex", "zoom",
]);

/**
 * ■ h : Virtual DOM 객체를 "만드는" 함수 (JSX 대신 쓰는 도구)
 *
 * 사용 예)
 *   h("ul", { id: "list" },
 *     h("li", null, "A"),            // 자식 1
 *     items.map(i => h("li", {}, i)), // 자식 여러 개를 배열로 한 번에
 *     isOpen && h("p", {}, "열림")     // 조건부 렌더링 (false면 안 그림)
 *   )
 *
 * @param type      태그 이름 ("div", "li" ...)
 * @param props     속성 객체. 생략하면 기본값 {}
 * @param children  ...(나머지 매개변수) → 3번째 인자부터 끝까지를 전부 배열로 모아 받는다
 */
export function h(type, props = {}, ...children) {
  // 팀 규약 모양 { type, props, children } 객체를 만들어 돌려준다
  return {
    // 태그 이름은 그대로 저장
    type,
    // ?? 는 "왼쪽이 null 또는 undefined일 때만 오른쪽 값을 쓴다"는 연산자.
    // h("div", null) 처럼 null이 들어와도 이후 코드가 props.xxx에 안전하게 접근하도록 빈 객체로 맞춘다
    props: props ?? {},
    // 자식 배열은 아래 normalizeChildren으로 깔끔하게 정리해서 저장
    children: normalizeChildren(children),
  };
}

/**
 * children 배열을 팀 규약(VNode 객체 또는 문자열만)으로 정리하는 내부 도우미 함수 (export 안 함)
 *
 * 입력 예) [ "점수: ", [ {li}, [ {li} ] ], null, false, 3 ]
 * 출력 예) [ "점수: ", {li}, {li}, "3" ]
 */
function normalizeChildren(children) {
  const flat = children
    // .flat(Infinity): 배열 안의 배열을 몇 겹이든 전부 펼쳐 한 줄짜리 배열로 만든다.
    // items.map(...)의 결과(배열)가 자식으로 그대로 들어오는 경우를 처리하기 위해
    .flat(Infinity)
    // .filter: 조건이 true인 것만 남긴다.
    // null/undefined(child != null 로 둘 다 걸러짐)와 true/false는 버린다.
    // → cond && h(...) 에서 cond가 false면 false가 들어오는데, 이걸 "아무것도 안 그림"으로 처리하기 위해
    .filter((child) => child != null && typeof child !== "boolean")
    // .map: 각 항목을 바꿔서 새 배열을 만든다.
    // 숫자는 문자열로 바꾼다. "텍스트 노드는 문자열" 규약을 지켜야 diff에서 typeof === "string"으로 텍스트를 판별할 수 있다
    .map((child) => (typeof child === "number" ? String(child) : child));
  // 이웃한 텍스트 합치기 + 빈 문자열 제거
  return mergeAdjacentText(flat);
}

/**
 * 이웃한 문자열 자식을 하나로 합치고, 빈 문자열("")은 버리는 내부 도우미 함수
 *
 * 왜 필요한가?
 *   h("p", {}, "점수: ", 100) 은 children이 ["점수: ", "100"] 두 개가 된다.
 *   그런데 이걸 HTML 문자열로 바꿨다가 브라우저가 다시 읽으면 "점수: 100" 텍스트 노드 하나가 된다.
 *   같은 화면인데 VDOM 모양이 달라지면, diff가 자식 개수가 다르다고 착각해서 불필요한 변경을 만든다.
 *   그래서 처음부터 합쳐서 "같은 화면 = 같은 VDOM"이 되게 한다.
 *   (domToVdom에서 주석 노드를 버리면 "a<!--c-->b"가 ["a", "b"]가 되는 경우도 같은 이유로 합친다)
 *
 * 예) ["점수: ", "100", {b}, "", "끝"] → ["점수: 100", {b}, "끝"]
 */
function mergeAdjacentText(children) {
  const result = [];
  for (const child of children) {
    // 빈 문자열은 화면에 아무것도 없으므로 버린다 (브라우저도 빈 텍스트 노드는 만들지 않는다)
    if (child === "") continue;
    // result의 마지막 항목 (없으면 undefined)
    const last = result[result.length - 1];
    // 지금 것도 문자열, 바로 앞도 문자열이면 → 새로 넣지 않고 앞 문자열 뒤에 이어 붙인다
    if (typeof child === "string" && typeof last === "string") {
      result[result.length - 1] = last + child;
    } else {
      result.push(child);
    }
  }
  return result;
}

/**
 * ■ domToVdom : 실제 DOM → Virtual DOM (화면에 이미 있는 HTML을 객체로 "읽어 오는" 함수)
 *
 * 사용 예)
 *   <ul id="list">
 *     <li>A</li>
 *   </ul>
 *   domToVdom(document.getElementById("list"))
 *   → { type: "ul", props: { id: "list" }, children: [ { type: "li", props: {}, children: ["A"] } ] }
 *   (들여쓰기 때문에 생긴 "\n  " 텍스트 노드는 빠진다)
 *
 * ⚠️ 공백 제거·텍스트 합치기·주석 제거 때문에 VDOM의 자식 개수가 실제 DOM의 childNodes 개수와 다를 수 있다.
 *    patch는 "VDOM 자식 i번째 = 실제 DOM 자식 i번째"를 전제로 하므로,
 *    처음 화면을 읽은 뒤에는 createElement(vdom) 결과로 실제 DOM을 한 번 교체해 둘의 모양을 맞춰야 한다.
 *
 * @param {Node} node               변환할 실제 DOM 노드
 * @param {boolean} preserveWhitespace 상위에 <pre>/<textarea>가 있으면 true (재귀로 아래까지 전달)
 * @returns VNode 객체 | 문자열 | null  (null = 버려야 하는 노드라는 표시)
 */
export function domToVdom(node, preserveWhitespace = false) {
  // ── 1) 텍스트 노드인 경우 (nodeType === 3) ──
  if (node.nodeType === Node.TEXT_NODE) {
    // 텍스트 노드 안의 글자를 꺼낸다
    const text = node.textContent;
    // /^\s*$/ : 처음(^)부터 끝($)까지 공백 문자(\s: 스페이스, 탭, 줄바꿈)만 있는지 검사하는 정규식
    // text.includes("\n") : 줄바꿈 문자가 들어 있는지 검사
    // → "공백만 있고 + 줄바꿈이 있고 + <pre>/<textarea> 안이 아니면" 버린다.
    // HTML 들여쓰기 때문에 생긴 "\n    " 같은 노드는 화면에 의미가 없는데,
    // 남겨 두면 자식 인덱스가 밀려서 diff가 불필요한 변경을 찾아내기 때문이다.
    // 단, 줄바꿈이 없는 공백("<b>a</b> <i>b</i>"의 " ")은 단어 사이 띄어쓰기라서 화면에 보이므로 보존한다.
    // [의도된 한계] "<ul>  <li>A</li>  </ul>"처럼 줄바꿈 없이 스페이스로만 들여쓴 HTML은 "  " 노드가 남는다.
    //   인라인 띄어쓰기를 지키는 쪽을 택한 트레이드오프다. (실제 React의 JSX도 줄바꿈이 섞인 공백만 제거한다)
    if (!preserveWhitespace && /^\s*$/.test(text) && text.includes("\n")) {
      // null을 돌려주면 부모 쪽에서 "이 자식은 버려라"로 처리한다
      return null;
    }
    // 글자가 있는 텍스트는 원문 그대로 돌려준다 (팀 규약: 텍스트 = 문자열).
    // trim(앞뒤 공백 자르기)을 하면 "Hello <b>world</b>"가 "Helloworld"로 붙어 버려서 하지 않는다.
    return text;
  }

  // ── 2) 요소 노드가 아닌 경우 (주석 <!-- -->, 처리 명령 등) ──
  // 화면에 그려지지 않으므로 버린다
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  // ── 3) 요소 노드인 경우 (nodeType === 1) ──
  // localName: 태그 이름을 h()에 쓰는 모양 그대로 준다. HTML은 소문자("div"), SVG는 원래 대소문자("linearGradient").
  // (tagName은 HTML에서 대문자 "DIV"라서 소문자로 바꿔야 하고, 그러면 SVG의 "foreignObject"까지 "foreignobject"로 바뀌어 버린다)
  const type = node.localName;

  // 속성들을 담을 빈 객체
  const props = {};
  // node.attributes를 하나씩 돌면서, 각 속성에서 name(이름)과 value(값)를 꺼낸다 (구조 분해 할당)
  for (const { name, value } of node.attributes) {
    // style 속성은 문자열("color: red")을 객체({ color: "red" })로 바꿔 저장한다.
    // h()로 만든 VDOM의 style은 객체라서, 형식을 하나로 맞춰야 diff가 style을 키 단위로 비교할 수 있다
    if (name === "style") {
      const style = parseStyle(value);
      // style="" 처럼 내용이 비어 있으면 아예 넣지 않는다 (속성이 없는 것과 화면이 같으므로)
      if (Object.keys(style).length > 0) props.style = style;
      continue;
    }
    // 이름을 props 이름으로 바꿔서 저장. class → className, for → htmlFor, 나머지는 그대로(??)
    // 예) <div class="a" id="b"> → props = { className: "a", id: "b" }
    props[ATTR_TO_PROP[name] ?? name] = value;
  }

  // 사용자가 화면에서 직접 바꾼 입력 상태(property)를 props에 반영한다 (아래 readLiveState 참고)
  readLiveState(node, type, props);

  // 지금 요소가 <pre>/<textarea>이거나, 이미 그 안쪽이면 true.
  // 한 번 <pre> 안으로 들어가면 그 아래 모든 자손(예: <pre><span>...)도 공백을 보존해야 하므로 || 로 이어받는다
  const preserve = preserveWhitespace || WHITESPACE_PRESERVING_TAGS.has(type);
  // 변환된 자식들을 담을 배열
  const children = [];
  // 실제 자식 노드들(텍스트·주석 포함)을 하나씩 돈다
  for (const child of node.childNodes) {
    // 자기 자신(domToVdom)을 다시 호출 = 재귀. 자식의 자식의 자식... 까지 끝까지 내려가며 변환한다
    const vchild = domToVdom(child, preserve);
    // null(버릴 노드)이 아니면 자식 목록에 추가
    if (vchild !== null) children.push(vchild);
  }

  // 팀 규약 모양으로 묶어서 돌려준다. 이웃한 텍스트는 h()와 같은 규칙으로 합친다
  return { type, props, children: mergeAdjacentText(children) };
}

/**
 * 폼 요소의 "현재 상태(property)"를 props에 덮어쓰는 내부 도우미 함수
 *
 * 왜 필요한가?
 *   사용자가 <input>에 타이핑하거나 체크박스를 클릭하면 브라우저는 property(input.value, input.checked)만 바꾸고
 *   attribute(<input value="...">)는 그대로 둔다. attribute만 읽으면 사용자가 방금 바꾼 값이 사라진다.
 *
 * 규칙
 *   - input(체크박스/라디오) : 지금 체크돼 있으면 checked: true, 아니면 checked를 아예 뺀다
 *   - input(그 외)          : value 속성이 있었거나 지금 값이 비어 있지 않으면 현재 값을 value로
 *   - textarea              : 현재 값이 초기 내용(자식 텍스트)과 다를 때만 value로 (같으면 자식 텍스트로 충분)
 *   - option                : 지금 선택돼 있으면 selected: true, 아니면 selected를 아예 뺀다
 *     (첫 번째 option은 속성이 없어도 브라우저가 자동 선택하므로 selected: true가 붙을 수 있다. 화면 상태 그대로를 기록한 것)
 */
function readLiveState(node, type, props) {
  if (type === "input") {
    if (node.type === "checkbox" || node.type === "radio") {
      if (node.checked) props.checked = true;
      else delete props.checked;
    } else if (node.hasAttribute("value") || node.value !== "") {
      props.value = node.value;
    }
  } else if (type === "textarea") {
    // defaultValue = 태그 사이에 적힌 초기 텍스트, value = 지금 입력창에 보이는 값
    if (node.value !== node.defaultValue) props.value = node.value;
  } else if (type === "option") {
    if (node.selected) props.selected = true;
    else delete props.selected;
  }
}

/**
 * style 속성 문자열을 camelCase 객체로 바꾸는 내부 도우미 함수
 * 예) "color: red; font-size: 12px; --gap: 4px" → { color: "red", fontSize: "12px", "--gap": "4px" }
 *
 * 선언을 ";"로 나누고, 각 선언을 "첫 번째 :" 기준으로 이름/값으로 나눈다.
 * (값 안에 ":"가 들어가는 url(http://...) 같은 경우를 위해 첫 번째 ":"만 기준으로 삼는다)
 * [한계] url("a;b")처럼 값 안에 ";"가 들어간 경우는 잘못 나뉜다. 이번 과제 범위에서는 다루지 않는다.
 */
function parseStyle(cssText) {
  const style = {};
  for (const declaration of cssText.split(";")) {
    const colon = declaration.indexOf(":");
    // ":"가 없는 조각(맨 끝의 빈 문자열 등)은 건너뛴다
    if (colon === -1) continue;
    const name = declaration.slice(0, colon).trim();
    const value = declaration.slice(colon + 1).trim();
    if (name && value) style[toCamelCase(name)] = value;
  }
  return style;
}

// "font-size" → "fontSize". CSS 변수("--gap")는 이름 자체가 값이라 바꾸지 않는다
function toCamelCase(cssName) {
  if (cssName.startsWith("--")) return cssName;
  return cssName.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

/**
 * ■ createElement : Virtual DOM → 실제 DOM (객체를 보고 진짜 HTML 요소를 "만드는" 함수)
 *
 * 사용 예)
 *   const el = createElement(h("p", { className: "msg" }, "안녕"));
 *   // el 은 <p class="msg">안녕</p> 인 실제 DOM 요소
 *   document.body.appendChild(el);  // 이렇게 붙여야 비로소 화면에 보인다
 *
 * 자식까지 재귀로 만든 완성된 DOM 노드를 반환한다 (아직 문서에 붙이지는 않음).
 * ※ 이름이 document.createElement와 같지만 다른 함수다.
 *    - document.createElement("p") : 브라우저 기본 기능. 빈 <p> 하나만 만든다.
 *    - 우리 createElement(vnode)   : vnode 객체 전체(속성 + 자식 전부)를 실제 DOM 트리로 만든다.
 *      (내부에서 document.createElement를 사용한다)
 */
export function createElement(vnode, inSvg = false) {
  // ── 1) 텍스트인 경우 ──
  // 팀 규약상 문자열 = 텍스트 노드. 숫자가 섞여 들어와도 안전하게 String()으로 바꿔 처리
  if (typeof vnode === "string" || typeof vnode === "number") {
    // 글자만 담긴 텍스트 노드를 만들어 돌려준다
    return document.createTextNode(String(vnode));
  }

  // ── 2) 요소인 경우 ──
  // <svg>와 그 안쪽은 SVG 이름공간으로 만든다. document.createElement("circle")은 이름만 circle인 HTML 요소라서 화면에 안 그려진다.
  // inSvg: 부모가 SVG 안이면 true (재귀로 아래까지 전달). <foreignObject> 안은 다시 HTML이다
  const svg = inSvg || vnode.type === "svg";
  const el = svg ? document.createElementNS(SVG_NS, vnode.type) : document.createElement(vnode.type);
  const childInSvg = svg && vnode.type !== "foreignObject";

  // 자식을 "먼저" 만들어 붙인다 (children이 없으면 빈 배열로 대비)
  // 순서가 중요한 이유: <select>의 value는 <option>들이 붙어 있어야 고를 수 있다.
  // 속성을 먼저 넣으면 아직 option이 없어서 select.value = "b"가 무시된다.
  // 단, multiple은 예외로 먼저 넣는다. 단일 select 상태에서 selected option을 붙이면 마지막 하나만 선택으로 남기 때문이다.
  if (vnode.props?.multiple) setProp(el, "multiple", vnode.props.multiple);
  for (const child of vnode.children ?? []) {
    // 자식도 createElement로 실제 DOM을 만들고(재귀), el의 마지막 자식으로 붙인다
    el.appendChild(createElement(child, childInSvg));
  }

  // 그다음 속성을 넣는다 (props가 없을 수도 있으니 빈 객체로 대비)
  // Object.entries(obj): { id: "a", title: "b" } → [["id","a"], ["title","b"]] 처럼 [이름, 값] 쌍 배열로 바꾼다
  // value는 "맨 마지막"에 넣는다. min / max / step / multiple 같은 속성이 먼저 적용돼야 값이 잘리거나 풀리지 않는다.
  // 예) { type: "range", value: "300", max: "500" } 을 순서대로 넣으면 기본 max(100) 때문에 300이 100으로 잘린다
  const props = vnode.props ?? {};
  for (const [name, value] of Object.entries(props)) {
    // 속성 하나를 요소에 적용 (종류별 처리 규칙은 아래 setProp 참고)
    if (name !== "value") setProp(el, name, value);
  }
  if ("value" in props) setProp(el, "value", props.value);

  // 속성과 자식이 모두 채워진 완성된 요소를 돌려준다
  return el;
}

/**
 * ■ setProp : prop(속성) 하나를 실제 DOM 요소에 적용하는 함수 (처음 만들 때 + patch에서 바꿀 때 공통 사용)
 *
 * @param el       실제 DOM 요소
 * @param name     prop 이름 ("id", "onClick", "style" ...)
 * @param value    새 값. false / null / undefined 면 "이 속성 없음"으로 보고 제거한다
 * @param oldValue 이전 값 (patch에서만 넘김). style에서 "이전에는 있었는데 이번엔 없는 키"를 지우는 데 쓴다
 *
 * props 종류별로 넣는 방법이 다르다:
 *   onClick: fn          → 이벤트 핸들러 등록/교체 (값이 없으면 해제)
 *   style: { color }     → el.style에 키별로 적용 (이전 값에만 있던 키는 지움)
 *   value                → el.value = ...(property) + input이면 attribute도 맞추기
 *   checked / selected   → el.checked = true/false(property) + attribute도 맞추기
 *   disabled: true       → setAttribute("disabled", "")
 *   disabled: false/null → removeAttribute("disabled")
 *   className: "a"       → setAttribute("class", "a")
 *   그 외                → setAttribute(이름, 값)
 */
export function setProp(el, name, value, oldValue) {
  // ── 0) key / ref ── DOM 속성이 아니다. key는 diff가 리스트 항목을 짝짓는 데만 쓰고, ref는 요소를 담아 줄 그릇이다
  if (name === "key") return;
  if (name === "ref") {
    if (oldValue && oldValue !== value) detachRef(oldValue, el);
    if (value) {
      refStore.set(el, value);
      if (pendingRefs) pendingRefs.push([value, el]);
      else attachRef(value, el);
    } else refStore.delete(el);
    return;
  }

  // ── 1) 이벤트 ── onClick, onInput 처럼 "on + 대문자"로 시작하는 이름
  // (HTML에서 읽어 온 onclick="..." 같은 소문자 문자열 속성은 여기 걸리지 않고 아래 일반 속성으로 처리된다)
  if (/^on[A-Z]/.test(name)) {
    // "onClick" → slice(2)로 앞 두 글자 제거 → "Click" → toLowerCase() → "click"
    let eventType = name.slice(2).toLowerCase();
    eventType = EVENT_NAME_FIX[eventType] ?? eventType;
    // React의 onChange는 글자를 칠 때마다 실행된다. 브라우저 change 이벤트는 텍스트 입력에서 "포커스를 잃을 때"만 오므로
    // 텍스트를 입력하는 요소(textarea, checkbox/radio/file이 아닌 input)는 input 이벤트에 연결한다
    if (eventType === "change" && isTextEntry(el)) eventType = "input";
    updateListener(el, eventType, name, value);
    return;
  }

  // ── 2) 스타일 ──
  if (name === "style") {
    updateStyle(el, value, oldValue);
    return;
  }

  // ── 3) 입력 상태 (value / checked / selected) ── attribute가 아니라 property로 넣어야 현재 화면 상태가 바뀐다
  if (PROPERTY_PROPS.has(name)) {
    if (name === "value") {
      // input만 value attribute를 함께 맞춘다. domToVdom이 attribute도 읽기 때문에 맞춰 두면 왕복이 깔끔해진다.
      // (textarea는 value attribute가 없고 자식 텍스트가 초기값, select는 option의 selected가 상태를 가진다)
      if (el.tagName === "INPUT") {
        if (value == null || value === false) el.removeAttribute("value");
        else el.setAttribute("value", String(value));
      }
      // select는 defaultValue가 없어서 아래 줄이 el.value = ""가 되고 선택이 전부 풀린다.
      // 그래서 value가 없으면 "처음부터 그렸을 때(createElement)와 같은 선택"으로 맞춘다. (브라우저 기본 규칙)
      //   1) 각 option을 selected 속성(defaultSelected)대로 되돌린다 → multiple이면 여러 개, 아니면 마지막 표시가 남는다
      //   2) 단일 select인데 아무것도 안 골라졌으면 disabled가 아닌 첫 option을 고른다
      // 처음 그릴 때도 이 결과는 브라우저가 이미 골라 둔 상태와 같아서, 언제 호출돼도 안전하다.
      if (el.tagName === "SELECT" && (value == null || value === false)) {
        const options = [...el.options];
        for (const o of options) o.selected = o.defaultSelected;
        if (!el.multiple && el.selectedIndex === -1) el.selectedIndex = options.findIndex((o) => !o.disabled);
        return;
      }
      // 값이 없으면 초기값(defaultValue)으로 되돌린다. textarea라면 자식 텍스트로 돌아간다
      el.value = value == null || value === false ? (el.defaultValue ?? "") : String(value);
    } else {
      // checked / selected: HTML에서는 속성이 "있기만 하면" 켜진 것이라 빈 문자열("")도 true로 본다
      const on = value === "" || Boolean(value);
      // property에 직접 대입 → 화면에 보이는 실제 체크/선택 상태가 바뀐다
      el[name] = on;
      // attribute도 함께 맞춘다 (켜짐 → checked="", 꺼짐 → 속성 제거)
      if (on) el.setAttribute(name, "");
      else el.removeAttribute(name);
    }
    return;
  }

  // ── 4) 나머지 일반 속성 ──
  // className → class, htmlFor → for 로 바꾸고, 표에 없으면 이름 그대로 쓴다
  const attr = PROP_TO_ATTR[name] ?? name;
  // false/null/undefined는 "속성 없음"을 뜻한다 → 이미 붙어 있던 속성이 있으면 지운다
  // (patch에서 disabled: true → false 로 바뀌었을 때 실제로 비활성화가 풀려야 하므로)
  if (value === false || value == null) {
    el.removeAttribute(attr);
    return;
  }
  // disabled={true} → <input disabled="">. HTML의 boolean 속성은 "있느냐 없느냐"만 의미가 있어서 값은 빈 문자열로 둔다.
  // 그 외 값은 문자열로 바꿔서 속성에 쓴다 (속성 값은 항상 문자열이어야 함)
  el.setAttribute(attr, value === true ? "" : String(value));
}

/**
 * ■ removeProp : prop 하나를 실제 DOM 요소에서 제거하는 함수 (patch에서 "이전엔 있었는데 이번엔 없는 속성"에 사용)
 * setProp에 "값 없음(undefined)"을 넘기는 것과 같다. 제거 규칙을 한 곳(setProp)에서만 관리하기 위해 이렇게 만들었다.
 */
export function removeProp(el, name, oldValue) {
  setProp(el, name, undefined, oldValue);
}

/**
 * 이벤트 핸들러를 등록 / 교체 / 해제하는 내부 도우미 함수
 *
 * 왜 이렇게 하나?
 *   Phase 2에서는 렌더링할 때마다 onClick: () => setCount(count + 1) 이 "새 함수"로 만들어진다.
 *   매번 addEventListener만 하면 이전 함수가 해제되지 않고 쌓여서, 클릭 한 번에 여러 번 실행되는 버그가 생긴다.
 *
 * 방법: 요소마다 실제로 addEventListener하는 함수는 runLatestHandler 하나뿐이고,
 *       "지금 실행할 핸들러"는 listenerStore에 저장해 두고 교체만 한다.
 *       → 핸들러가 바뀔 때 add/remove를 반복할 필요가 없고, 중복 등록이 원천적으로 불가능하다.
 */
function updateListener(el, eventType, propName, handler) {
  // 이 요소의 핸들러 목록. 처음이면 빈 객체를 만들어 저장한다
  let handlers = listenerStore.get(el);
  if (!handlers) {
    handlers = {};
    listenerStore.set(el, handlers);
  }
  // 이 이벤트 종류의 핸들러 묶음 (prop 이름 → 함수)
  const group = handlers[eventType] ?? (handlers[eventType] = {});

  if (typeof handler === "function") {
    // 이 이벤트 종류를 처음 등록하는 경우에만 실제 리스너(runLatestHandler)를 붙인다
    if (Object.keys(group).length === 0) el.addEventListener(eventType, runLatestHandler);
    // 실행할 핸들러는 항상 최신 것으로 교체
    group[propName] = handler;
  } else if (propName in group) {
    // 값이 함수가 아니면(없어졌으면) 목록에서 지우고, 이 이벤트 종류에 남은 핸들러가 없으면 실제 리스너도 뗀다
    delete group[propName];
    if (Object.keys(group).length === 0) {
      el.removeEventListener(eventType, runLatestHandler);
      delete handlers[eventType];
    }
  }
}

// 모든 요소가 공유하는 "진짜" 이벤트 리스너. 이벤트가 오면 그 요소에 저장된 최신 핸들러들을 찾아 실행한다
// event.currentTarget = 지금 이 리스너가 붙어 있는 요소, event.type = "click" 같은 이벤트 이름
function runLatestHandler(event) {
  const group = listenerStore.get(event.currentTarget)?.[event.type];
  if (!group) return;
  for (const handler of Object.values(group)) handler(event);
}

// 글자를 입력하는 요소인지 (onChange를 input 이벤트로 연결할 대상)
function isTextEntry(el) {
  if (el.tagName === "TEXTAREA") return true;
  return el.tagName === "INPUT" && !["checkbox", "radio", "file"].includes(el.type);
}

// ref 연결을 끊는다. 객체 ref는 아직 이 요소를 가리킬 때만 null로 (그사이 다른 요소가 같은 ref를 받았을 수 있으므로)
function detachRef(ref, el) {
  if (typeof ref === "function") ref(null);
  else if (ref.current === el) ref.current = null;
}

function attachRef(ref, el) {
  if (typeof ref === "function") ref(el);
  else ref.current = el;
}

/**
 * ■ withDeferredRefs : fn 실행 중 생기는 ref 연결을 모아 뒀다가 fn이 끝난 뒤 한꺼번에 연결한다 (patch가 사용)
 * 해제(detach / clearRefs)는 그 자리에서 바로 일어나므로, 결과적으로 "모든 해제 → 모든 연결" 순서가 된다
 */
export function withDeferredRefs(fn) {
  if (pendingRefs) return fn(); // 이미 모으는 중이면(중첩 호출) 바깥에서 한 번에 연결한다
  pendingRefs = [];
  try {
    return fn();
  } finally {
    const refs = pendingRefs;
    pendingRefs = null;
    for (const [ref, el] of refs) attachRef(ref, el);
  }
}

/**
 * ■ clearRefs : 화면에서 빠지는 노드(와 그 자손)에 연결된 ref를 null로 되돌린다
 * patch가 노드를 지우거나(REMOVE) 갈아 끼우기(REPLACE) 직전에 부른다. (지운 요소를 ref가 계속 붙잡고 있지 않게)
 */
export function clearRefs(node) {
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  for (const el of [node, ...node.querySelectorAll("*")]) {
    const ref = refStore.get(el);
    if (ref) {
      detachRef(ref, el);
      refStore.delete(el);
    }
  }
}

/**
 * style을 적용하는 내부 도우미 함수
 *   - 객체면: 이전 값(oldValue)에만 있던 키는 지우고, 새 값의 키들을 적용한다
 *     예) { color: "red", fontSize: "12px" } → { color: "blue" } 면 fontSize를 지워야 한다
 *   - 문자열이면: style 속성 전체를 그 문자열로 바꾼다 (직접 h()에 문자열을 넘긴 경우 대비)
 *   - 없으면: style 속성 자체를 제거한다
 */
function updateStyle(el, value, oldValue) {
  // 이전 값이 문자열이었거나 새 값이 객체가 아니면, 기존 인라인 스타일을 통째로 비운다
  if (typeof oldValue === "string" || value == null || typeof value !== "object") {
    clearStyle(el);
  }

  if (typeof value === "string") {
    if (value) el.setAttribute("style", value);
    return;
  }
  if (value == null || typeof value !== "object") return;

  // 이전 객체에만 있고 새 객체에는 없는 키 → 지운다
  if (oldValue && typeof oldValue === "object") {
    for (const key of Object.keys(oldValue)) {
      if (!(key in value)) setStyleValue(el, key, "");
    }
  }
  // 새 객체의 키들을 적용한다
  for (const [key, styleValue] of Object.entries(value)) {
    setStyleValue(el, key, styleValue ?? "");
  }
  // 전부 지워져서 style=""만 남았다면 속성 자체를 없앤다 (domToVdom으로 다시 읽을 때 빈 style이 생기지 않게)
  if (el.style.length === 0) clearStyle(el);
}

// 인라인 스타일을 완전히 비우고 style 속성도 제거한다.
// el.style.xxx로 바꾼 내용은 브라우저가 style 속성에 "나중에 몰아서" 반영한다.
// 그 상태에서 바로 removeAttribute("style")를 하면 지운 뒤에 반영이 일어나 style=""가 남는다(크롬에서 실제로 확인).
// 그래서 setAttribute("style", "")로 속성을 먼저 확정해 두고 나서 지운다.
function clearStyle(el) {
  el.setAttribute("style", "");
  el.removeAttribute("style");
}

// 스타일 한 개를 적용. CSS 변수(--gap)는 el.style.xxx 로 쓸 수 없어서 setProperty를 써야 한다
function setStyleValue(el, key, value) {
  if (key.startsWith("--")) el.style.setProperty(key, value);
  else el.style[key] = styleValueToCss(key, value);
}

/**
 * ■ styleValueToCss : style 값 하나를 CSS 문자열로 (createElement와 htmlText의 vdomToHtml이 같은 규칙을 쓰도록 공유)
 * 숫자는 px를 붙인다 (단위 없는 속성과 0은 그대로). 숫자만 넣으면 브라우저가 무시한다 (el.style.width = 100 → 적용 안 됨)
 */
export function styleValueToCss(key, value) {
  return typeof value === "number" && value !== 0 && !UNITLESS_STYLES.has(key) ? `${value}px` : value;
}