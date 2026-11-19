// [htmlText.js] 테스트 영역용 변환: HTML 문자열 ↔ Virtual DOM
//
// 테스트 영역은 HTML 코드를 보여 주는 textarea다.
//   - 로드 / 뒤로가기 때: VDOM → HTML 문자열(vdomToHtml)로 테스트 영역을 "렌더링"한다
//   - Patch 때        : 사용자가 고친 HTML 문자열 → VDOM(htmlToVdom)으로 읽는다
// 둘 다 루트를 <div> 하나로 감싼 VDOM을 다룬다. (여러 최상위 태그를 쓸 수 있게, 그리고 patch는 루트가 하나여야 해서)

import { domToVdom, styleValueToCss } from "../core/vdom.js";

// 닫는 태그가 없는 태그 (<input>, <br> ...). </input>을 쓰면 브라우저가 무시하거나 엉뚱하게 해석한다
const VOID_TAGS = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
// 공백·줄바꿈이 곧 내용인 태그. 이 안에서는 보기 좋게 줄바꿈/들여쓰기를 넣으면 내용이 바뀐다
const RAW_TAGS = new Set(["pre", "textarea"]);
// 파서가 안쪽을 "글자 그대로" 읽는 태그 (&lt; 같은 엔티티를 해석하지 않음). 여기서 이스케이프하면 &lt;가 그대로 글자로 남는다
// (HTML 표준 직렬화 규칙의 목록. noscript는 스크립트가 켜진 브라우저 기준)
const RAW_TEXT_TAGS = new Set(["style", "script", "xmp", "iframe", "noembed", "noframes", "plaintext", "noscript"]);
// props 이름 → HTML 속성 이름 (vdom.js와 같은 규칙)
const PROP_TO_ATTR = { __proto__: null, className: "class", htmlFor: "for" };

/**
 * ■ htmlToVdom : HTML 문자열 → 루트 <div>로 감싼 VDOM
 * 브라우저 파서(innerHTML)에 맡겨서 닫히지 않은 태그 등도 브라우저와 똑같이 고쳐 읽는다.
 * (실제 영역에 그려지는 내용이라 사용자가 쓴 onerror 같은 속성도 실행될 수 있다. 자기 화면에서만 쓰는 도구라 허용)
 */
export function htmlToVdom(html) {
  const wrapper = document.createElement("div");
  wrapper.innerHTML = html;
  return domToVdom(wrapper);
}

/**
 * ■ vdomToHtml : 루트 <div> VDOM → 그 안쪽 HTML 문자열 (보기 좋게 들여쓰기)
 *
 * 지켜야 할 약속: htmlToVdom(vdomToHtml(v)) 가 v와 같아야 한다. (테스트 영역을 다시 Patch해도 "변경 없음"이 되게)
 * 그래서 줄바꿈/들여쓰기는 "자식이 전부 요소일 때만" 넣는다.
 *   - <ul><li>A</li><li>B</li></ul> → 줄바꿈해도 됨. 생기는 "\n  " 공백 노드는 domToVdom이 버린다
 *   - <p>총 <b>2</b>개</p>          → 줄바꿈하면 "총 \n" 처럼 글자 내용이 바뀐다 → 한 줄 그대로
 */
export function vdomToHtml(root) {
  return childrenToHtml(root.children, 0, false);
}

// 자식 목록을 HTML로. depth = 들여쓰기 단계, raw = <pre>/<textarea> 안쪽이면 true
function childrenToHtml(children, depth, raw) {
  const block = !raw && children.length > 0 && children.every((c) => typeof c !== "string");
  if (!block) return children.map((c) => nodeToHtml(c, depth, raw)).join("");
  const pad = "  ".repeat(depth);
  return children.map((c) => pad + nodeToHtml(c, depth, raw)).join("\n");
}

function nodeToHtml(node, depth, raw) {
  if (typeof node === "string") return escapeText(node);

  const open = `<${node.type}${attrsToHtml(node.props ?? {})}>`;
  if (VOID_TAGS.has(node.type)) return open;
  // 안쪽은 텍스트뿐이므로 이스케이프 없이 그대로 이어 붙인다
  // 단, <plaintext>는 닫는 태그가 없다. 파서가 그 뒤 끝까지를 전부 글자로 읽어서 </plaintext>를 붙이면 글자로 남는다
  if (RAW_TEXT_TAGS.has(node.type)) {
    const body = (node.children ?? []).join("");
    return node.type === "plaintext" ? `${open}${body}` : `${open}${body}</${node.type}>`;
  }

  const inRaw = raw || RAW_TAGS.has(node.type);
  const children = node.children ?? [];
  // 안쪽에 <plaintext>가 있으면 그 뒤 글자는 전부 plaintext의 텍스트로 먹힌다.
  // 그래서 이 요소의 닫는 태그와 마지막 줄바꿈을 쓰지 않는다 (파서도 원래 이 요소들을 닫지 않은 채로 끝났다)
  const swallowed = containsPlaintext(node);
  let inner;
  if (!inRaw && children.length > 0 && children.every((c) => typeof c !== "string")) {
    // 자식이 전부 요소 → 한 줄에 하나씩, 한 단계 들여쓰기
    inner = "\n" + childrenToHtml(children, depth + 1, false) + (swallowed ? "" : "\n" + "  ".repeat(depth));
  } else {
    inner = childrenToHtml(children, depth + 1, inRaw);
    // HTML 파서는 <pre>/<textarea> 바로 뒤의 줄바꿈 하나를 버린다. 내용이 줄바꿈으로 시작하면 하나 더 넣어 지켜 준다
    if (RAW_TAGS.has(node.type) && inner.startsWith("\n")) inner = "\n" + inner;
  }
  return swallowed ? `${open}${inner}` : `${open}${inner}</${node.type}>`;
}

// 자손 중에 <plaintext>가 있는지 (파서 규칙상 plaintext는 항상 문서의 맨 마지막이라 그 조상들은 닫히지 않는다)
function containsPlaintext(node) {
  return (node.children ?? []).some((c) => typeof c !== "string" && (c.type === "plaintext" || containsPlaintext(c)));
}

// props → ' id="a" class="b" checked' 형태. 함수(onClick)와 "속성 없음"(false / null / undefined)은 HTML로 쓸 수 없어서 뺀다
function attrsToHtml(props) {
  let out = "";
  for (const [name, value] of Object.entries(props)) {
    if (value == null || value === false || typeof value === "function") continue;
    const attr = PROP_TO_ATTR[name] ?? name;
    if (value === true) {
      out += ` ${attr}`; // boolean 속성은 이름만 있으면 켜진 것
      continue;
    }
    const text = name === "style" && typeof value === "object" ? styleToText(value) : String(value);
    out += ` ${attr}="${escapeAttr(text)}"`;
  }
  return out;
}

// { fontSize: "12px", "--gap": "4px" } → "font-size: 12px; --gap: 4px" (CSS 변수는 이름 그대로)
function styleToText(style) {
  return Object.entries(style)
    .map(([key, value]) => `${key.startsWith("--") ? key : key.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())}: ${key.startsWith("--") ? value : styleValueToCss(key, value)}`)
    .join("; ");
}

// 글자 그대로 보이도록 HTML 특수문자를 바꾼다. &를 먼저 바꿔야 이미 바꾼 &lt;의 &가 다시 바뀌지 않는다
function escapeText(text) {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function escapeAttr(text) {
  return text.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}
