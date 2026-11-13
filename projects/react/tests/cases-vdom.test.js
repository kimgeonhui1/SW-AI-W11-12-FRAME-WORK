// [tests/cases-vdom.test.js] 테스트 항목 #001 ~ #080
//   #001 ~ #030 VDOM 생성 및 정규화 (h)
//   #031 ~ #060 DOM → VDOM 변환 (domToVdom / containerToVdom)
//   #061 ~ #080 VDOM → DOM 변환 (createElement)

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, domToVdom, createElement, containerToVdom } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { root, fromHtml, assertThrows, captureConsole, deepTree } from "./helpers.js";

/** h("p", null, child) 의 children 만 꺼낸다 */
const kids = (...children) => h("p", null, ...children).children;

/** 중첩 깊이 세기 (요소 → 첫 자식 → …) */
function depthOf(node) {
  let depth = 0;
  while (node && typeof node === "object") {
    depth += 1;
    node = node.children[0];
  }
  return depth;
}

describe("VDOM 생성 및 정규화 (#001~#030)", () => {
  test("#001 null 자식은 제거", () => assertEqual(kids(null), []));
  test("#002 undefined 자식은 제거", () => assertEqual(kids(undefined), []));
  test("#003 true 자식은 제거", () => assertEqual(kids(true), []));
  test("#004 false 자식은 제거", () => assertEqual(kids(false), []));
  test("#005 숫자 0 은 \"0\" 으로 유지 (falsy 라도 지우지 않음)", () => assertEqual(kids(0), ["0"]));
  test("#006 음수는 문자열로", () => assertEqual(kids(-3), ["-3"]));
  test("#007 소수는 문자열로", () => assertEqual(kids(1.5), ["1.5"]));
  test("#008 NaN 은 \"NaN\"", () => assertEqual(kids(NaN), ["NaN"]));
  test("#009 Infinity 는 \"Infinity\"", () => assertEqual(kids(Infinity, -Infinity), ["Infinity", "-Infinity"]));
  test("#010 빈 문자열은 유지 (빈 텍스트 노드)", () => assertEqual(kids(""), [""]));
  test("#011 공백 문자열은 그대로 유지", () => assertEqual(kids(" "), [" "]));
  test("#012 여러 공백이 든 문자열도 그대로", () => assertEqual(kids("a   b  "), ["a   b  "]));
  test("#013 여러 단계 중첩 배열 평탄화", () => assertEqual(kids([[["a", [["b"]]]], [[["c"]]]]), ["a", "b", "c"]));
  test("#014 빈 배열은 아무것도 만들지 않음", () => assertEqual(kids([]), []));
  test("#015 배열 안의 null 제거", () => assertEqual(kids(["a", null, undefined, "b"]), ["a", "b"]));
  test("#016 배열 안의 불리언 제거", () => assertEqual(kids([true, "a", false]), ["a"]));
  test("#017 배열 안의 숫자는 문자열로", () => assertEqual(kids([1, "a", 2.5]), ["1", "a", "2.5"]));
  test("#018 배열 안의 문자열은 합치지 않고 각각 유지", () => assertEqual(kids(["a", "b"]), ["a", "b"]));
  test("#019 배열 안의 중첩된 빈 배열 무시", () => assertEqual(kids(["a", [], [[]], [[[]]], "b"]), ["a", "b"]));
  test("#020 props 가 null 이면 {}", () => assertEqual(h("p", null).props, {}));
  test("#021 props 가 undefined 이면 {}", () => assertEqual(h("p", undefined).props, {}));
  test("#022 빈 props 는 복사본 {} (원본 공유 안 함)", () => {
    const props = {};
    const node = h("p", props);
    assertEqual(node.props, {});
    assert(node.props !== props, "원본과 다른 객체여야 함");
  });
  test("#023 숫자 props 값은 VNode 에 그대로, DOM 에는 문자열로", () => {
    const node = h("div", { tabindex: 3 });
    assertEqual(node.props.tabindex, 3);
    assertEqual(createElement(node).getAttribute("tabindex"), "3");
  });
  test("#024 불리언 props: true → 값 없는 속성, false → 속성 없음", () => {
    const node = h("input", { disabled: true, readonly: false });
    assertEqual(node.props, { disabled: true, readonly: false });
    const el = createElement(node);
    assertEqual(el.getAttribute("disabled"), "");
    assertEqual(el.hasAttribute("readonly"), false);
  });
  test("#025 특수문자가 든 속성명(data-a.b_c:d)도 그대로", () => {
    const node = h("div", { "data-a.b_c:d": "1" });
    assertEqual(Object.keys(node.props), ["data-a.b_c:d"]);
    assertEqual(createElement(node).getAttribute("data-a.b_c:d"), "1");
  });
  test("#026 중복 속성명: 객체는 마지막 값, HTML 파서는 첫 값", () => {
    assertEqual(h("div", Object.assign({ id: "a" }, { id: "b" })).props, { id: "b" });
    assertEqual(domToVdom(fromHtml('<div id="a" id="b"></div>').firstChild).props, { id: "a" });
  });
  test("#027 children 을 props 로 주면 일반 속성으로 취급 (자식이 되지 않음)", () => {
    const node = h("div", { children: "x" }, "y");
    assertEqual(node.props, { children: "x" });
    assertEqual(node.children, ["y"]);
  });
  test("#028 매우 긴 문자열(100,000자)도 그대로", () => {
    const long = "가".repeat(100000);
    assertEqual(kids(long)[0].length, 100000);
  });
  test("#029 1,000단계 중첩 트리 생성", () => {
    let node = "leaf";
    for (let i = 0; i < 1000; i++) node = h("div", null, node);
    assertEqual(depthOf(node), 1000);
  });
  test("#030 같은 객체를 여러 자식으로 재사용해도 DOM 은 각각 생성", () => {
    const child = h("i", null, "x");
    const node = h("p", null, child, child);
    assert(node.children[0] === node.children[1], "VNode 는 같은 참조");
    const el = createElement(node);
    assertEqual(el.children.length, 2);
    assert(el.children[0] !== el.children[1], "DOM 노드는 서로 달라야 함");
    assertEqual(diff(root(node), root(node)), []);
  });
});

describe("DOM → VDOM 변환 (#031~#060)", () => {
  const conv = (html) => containerToVdom(fromHtml(html)).children;
  const el = (type, props = {}, children = []) => ({ type, props, children });

  test("#031 빈 div", () => assertEqual(conv("<div></div>"), [el("div")]));
  test("#032 빈 span", () => assertEqual(conv("<span></span>"), [el("span")]));
  test("#033 빈 p", () => assertEqual(conv("<p></p>"), [el("p")]));
  test("#034 빈 텍스트 노드는 \"\" 로 유지", () => {
    const box = document.createElement("div");
    box.append(document.createTextNode(""));
    assertEqual(domToVdom(box.firstChild), "");
    assertEqual(containerToVdom(box).children, [""]);
  });
  test("#035 연속된 텍스트 노드는 각각 유지 (합치지 않음)", () => {
    const box = document.createElement("div");
    box.append(document.createTextNode("a"), document.createTextNode("b"));
    assertEqual(containerToVdom(box).children, ["a", "b"]);
  });
  test("#036 텍스트와 요소가 번갈아 나오는 구조", () =>
    assertEqual(conv("a<b>b</b>c<i>d</i>"), ["a", el("b", {}, ["b"]), "c", el("i", {}, ["d"])]));
  test("#037 HTML 주석은 무시", () => assertEqual(conv("<p>a<!-- 주석 -->b</p>"), [el("p", {}, ["a", "b"])]));
  test("#038 연속된 주석도 무시", () => assertEqual(conv("<!--1--><!--2--><!--3--><p>x</p>"), [el("p", {}, ["x"])]));
  test("#039 줄바꿈만 있는 텍스트 노드는 무시 (들여쓰기)", () => assertEqual(conv("<i>a</i>\n<i>b</i>"), [el("i", {}, ["a"]), el("i", {}, ["b"])]));
  test("#040 탭만 있는 텍스트 노드는 유지 (줄바꿈이 없으므로)", () => assertEqual(conv("<i>a</i>\t<i>b</i>")[1], "\t"));
  test("#041 일반 공백만 있는 텍스트 노드는 유지", () => assertEqual(conv("<i>a</i>  <i>b</i>")[1], "  "));
  test("#042 NBSP 만 있는 텍스트 노드는 유지", () => assertEqual(conv("<i>a</i>&nbsp;<i>b</i>")[1], " "));
  test("#043 일반 공백 + NBSP 혼합은 유지", () => assertEqual(conv("<i>a</i> &nbsp; <i>b</i>")[1], "   "));
  test("#044 줄바꿈 + 일반 공백 혼합은 무시", () => assertEqual(conv("<i>a</i>\n    <i>b</i>").length, 2));
  test("#045 깊게 들여쓴 HTML (20단계)", () => {
    let html = `${"  ".repeat(19)}<div>x</div>`; // 가장 안쪽: 글자는 태그와 같은 줄
    for (let i = 18; i >= 0; i--) html = `${"  ".repeat(i)}<div>\n${html}\n${"  ".repeat(i)}</div>`;
    assertEqual(containerToVdom(fromHtml(html)), root(deepTree(20, "x")));
  });
  test("#046 인라인 요소 사이 공백 한 칸 보존", () => assertEqual(conv("<b>a</b> <i>b</i>"), [el("b", {}, ["a"]), " ", el("i", {}, ["b"])]));
  test("#047 블록 요소 사이: 줄바꿈 공백은 무시, 같은 줄 공백은 유지", () => {
    assertEqual(conv("<div>a</div>\n<div>b</div>").length, 2);
    assertEqual(conv("<div>a</div> <div>b</div>")[1], " ");
  });
  test("#048 <pre> 안의 공백 보존 (줄바꿈만 있는 텍스트도 유지)", () => {
    assertEqual(conv("<pre>  a\n  b  </pre>"), [el("pre", {}, ["  a\n  b  "])]);
    assertEqual(conv("<pre><b>x</b>\n\n<b>y</b></pre>"), [el("pre", {}, [el("b", {}, ["x"]), "\n\n", el("b", {}, ["y"])])]);
  });
  test("#049 <textarea> 안의 공백 보존", () => {
    assertEqual(conv("<textarea>  a\n b </textarea>"), [el("textarea", {}, ["  a\n b "])]);
    // 파서는 여는 태그 바로 뒤 줄바꿈 하나를 지운다 → "  \n" 이 남고, 이것도 유지
    assertEqual(conv("<textarea>\n  \n</textarea>"), [el("textarea", {}, ["  \n"])]);
  });
  test("#050 대문자 태그명은 소문자로", () => assertEqual(conv('<DIV ID="X"></DIV>'), [el("div", { id: "X" })]));
  test("#051 사용자 정의 속성", () => assertEqual(conv('<p foo-bar="1"></p>')[0].props, { "foo-bar": "1" }));
  test("#052 data-* 속성", () => assertEqual(conv('<p data-user-id="7"></p>')[0].props, { "data-user-id": "7" }));
  test("#053 aria-* 속성", () => assertEqual(conv('<p aria-label="닫기" aria-hidden="true"></p>')[0].props, { "aria-label": "닫기", "aria-hidden": "true" }));
  test("#054 빈 속성값", () => assertEqual(conv('<p title=""></p>')[0].props, { title: "" }));
  test("#055 불리언 속성은 \"\" 로", () => assertEqual(conv("<input disabled checked>")[0].props, { disabled: "", checked: "" }));
  test("#056 중첩된 빈 요소", () => assertEqual(conv("<div><span></span><p></p></div>"), [el("div", {}, [el("span"), el("p")])]));
  test("#057 특수문자가 든 텍스트", () => assertEqual(conv("<p>a &lt; b &amp; c &gt; d \"'</p>")[0].children, ["a < b & c > d \"'"]));
  test("#058 HTML Entity 는 실제 문자로", () => assertEqual(conv("<p>&copy;&nbsp;&#x1F600;&#44032;</p>")[0].children, ["© 😀가"]));
  test("#059 SVG: 태그는 소문자로 읽지만 다시 만들면 HTML 요소가 됨 (SVG 미지원 한계)", () => {
    const [svg] = conv('<svg viewBox="0 0 10 10"><circle r="1"></circle><foreignObject></foreignObject></svg>');
    assertEqual(svg.type, "svg");
    assertEqual(svg.props, { viewBox: "0 0 10 10" });
    assertEqual(svg.children.map((c) => c.type), ["circle", "foreignobject"]);
    assertEqual(createElement(svg).namespaceURI, "http://www.w3.org/1999/xhtml");
  });
  test("#060 잘못된 HTML 은 브라우저 파서가 고친 모양 그대로", () =>
    assertEqual(conv("<p><div>x</div></p>"), [el("p"), el("div", {}, ["x"]), el("p")]));
});

describe("VDOM → DOM 변환 (#061~#080)", () => {
  test("#061 빈 VDOM(자식 없는 루트)", () => {
    const el = createElement(h("div"));
    assertEqual(el.outerHTML, "<div></div>");
  });
  test("#062 텍스트 VDOM → Text 노드", () => {
    const node = createElement("hi");
    assertEqual(node.nodeType, Node.TEXT_NODE);
    assertEqual(node.nodeValue, "hi");
  });
  test("#063 숫자 문자열 / 숫자 → Text 노드", () => {
    assertEqual(createElement("123").nodeValue, "123");
    assertEqual(createElement(123).nodeValue, "123");
  });
  test("#064 빈 자식 배열", () => assertEqual(createElement({ type: "ul", props: {}, children: [] }).childNodes.length, 0));
  test("#065 여러 자식", () => assertEqual(createElement(h("ul", null, h("li"), "t", h("li"))).childNodes.length, 3));
  test("#066 깊은 중첩 (300단계)", () => {
    let el = createElement(deepTree(300, "bottom"));
    let depth = 0;
    while (el.nodeType === Node.ELEMENT_NODE) {
      depth += 1;
      el = el.firstChild;
    }
    assertEqual(depth, 300);
    assertEqual(el.nodeValue, "bottom");
  });
  test("#067 props 키가 없는 VDOM", () => assertEqual(createElement({ type: "p", children: ["x"] }).outerHTML, "<p>x</p>"));
  test("#068 빈 props", () => assertEqual(createElement({ type: "p", props: {}, children: [] }).attributes.length, 0));
  test("#069 className 은 HTML 속성이 아니므로 class 가 되지 않음 (class 를 써야 함)", () => {
    const el = createElement(h("p", { className: "a" }));
    assertEqual(el.getAttribute("class"), null);
    assertEqual(el.getAttribute("classname"), "a");
  });
  test("#070 style 문자열 속성", () => {
    const el = createElement(h("p", { style: "color: red; margin-top: 2px" }));
    assertEqual(el.style.color, "red");
    assertEqual(el.style.marginTop, "2px");
  });
  test("#071 불리언 속성 true / false", () => {
    const el = createElement(h("button", { disabled: true, hidden: false }));
    assertEqual(el.disabled, true);
    assertEqual(el.hasAttribute("hidden"), false);
  });
  test("#072 빈 문자열 속성", () => assertEqual(createElement(h("p", { title: "" })).getAttribute("title"), ""));
  test("#073 null / undefined 속성은 만들지 않음", () => {
    const el = createElement(h("p", { title: null, id: undefined }));
    assertEqual(el.attributes.length, 0);
  });
  test("#074 쓸 수 없는 속성명(공백 포함)은 건너뛰고 경고, 나머지는 정상 생성", () => {
    const { result: el, warns } = captureConsole(() => createElement(h("p", { "a b": "1", id: "ok" })));
    assertEqual(el.getAttribute("id"), "ok");
    assertEqual(el.attributes.length, 1);
    assertEqual(warns.length, 1);
  });
  test("#075 data-* 속성 → dataset", () => assertEqual(createElement(h("p", { "data-user-id": "7" })).dataset.userId, "7"));
  test("#076 aria-* 속성", () => assertEqual(createElement(h("p", { "aria-label": "닫기" })).getAttribute("aria-label"), "닫기"));
  test("#077 사용자 정의 속성", () => assertEqual(createElement(h("p", { "my-attr": "x" })).getAttribute("my-attr"), "x"));
  test("#078 void element (br, img, input)", () => {
    assertEqual(createElement(h("br")).outerHTML, "<br>");
    assertEqual(createElement(h("img", { src: "a.png", alt: "" })).outerHTML, '<img src="a.png" alt="">');
    assertEqual(createElement(h("input", { type: "text" })).outerHTML, '<input type="text">');
  });
  test("#079 void element 에 자식을 주면 DOM 에는 붙지만 HTML 로는 표현되지 않음", () => {
    const el = createElement({ type: "br", props: {}, children: ["x"] });
    assertEqual(el.childNodes.length, 1);
    assertEqual(el.outerHTML, "<br>");
  });
  test("#080 잘못된 VDOM 은 TypeError, 잘못된 태그명은 DOMException", () => {
    for (const bad of [null, undefined, true, false, {}, { type: "" }, { type: 1 }, [], () => {}]) {
      assertThrows(() => createElement(bad), TypeError, `TypeError 여야 함: ${String(bad)}`);
    }
    const err = assertThrows(() => createElement({ type: "a b", props: {}, children: [] }));
    assertEqual(err.name, "InvalidCharacterError");
  });
});
