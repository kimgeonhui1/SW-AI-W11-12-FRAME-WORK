// [tests/vdom.test.js] h 정규화 · domToVdom 공백 규칙 · createElement 왕복 변환

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, domToVdom, createElement, containerToVdom, isIgnorableNode } from "../src/core/vdom.js";

/** HTML 문자열로 임시 컨테이너를 만든다 (문서에 붙이지 않아도 파싱된다) */
function fromHtml(html) {
  const box = document.createElement("div");
  box.innerHTML = html;
  return box;
}

describe("h() 정규화", () => {
  test("props 가 null 이면 {} 로 바뀐다", () => {
    assertEqual(h("div", null), { type: "div", props: {}, children: [] });
  });

  test("props 를 생략해도 {}", () => {
    assertEqual(h("span").props, {});
  });

  test("태그 이름은 소문자", () => {
    assertEqual(h("DIV", null).type, "div");
  });

  test("중첩 배열은 평탄화된다", () => {
    const vnode = h("ul", null, [h("li", null, "a"), [h("li", null, "b"), ["c"]]]);
    assertEqual(vnode.children, [
      { type: "li", props: {}, children: ["a"] },
      { type: "li", props: {}, children: ["b"] },
      "c",
    ]);
  });

  test("null / undefined / true / false 는 제거된다", () => {
    assertEqual(h("p", null, "a", null, undefined, true, false, "b").children, ["a", "b"]);
  });

  test("숫자는 문자열이 된다 (0 포함)", () => {
    assertEqual(h("p", null, 0, 42).children, ["0", "42"]);
  });

  test("props 원본 객체를 공유하지 않는다", () => {
    const props = { id: "x" };
    const vnode = h("div", props);
    props.id = "y";
    assertEqual(vnode.props.id, "x");
  });
});

describe("domToVdom() 공백 규칙", () => {
  test("들여쓰기(줄바꿈 포함 공백) 텍스트는 무시된다", () => {
    const box = fromHtml("<ul>\n  <li>a</li>\n  <li>b</li>\n</ul>");
    assertEqual(domToVdom(box.firstChild), {
      type: "ul",
      props: {},
      children: [
        { type: "li", props: {}, children: ["a"] },
        { type: "li", props: {}, children: ["b"] },
      ],
    });
  });

  test("요소 사이 줄바꿈 없는 공백 한 칸은 유지된다", () => {
    const box = fromHtml("<p><b>a</b> <i>b</i></p>");
    assertEqual(domToVdom(box.firstChild).children, [
      { type: "b", props: {}, children: ["a"] },
      " ",
      { type: "i", props: {}, children: ["b"] },
    ]);
  });

  test("글자가 있는 텍스트는 줄바꿈이 있어도 그대로 유지된다", () => {
    const box = fromHtml("<p>\n  안녕\n</p>");
    assertEqual(domToVdom(box.firstChild).children, ["\n  안녕\n"]);
  });

  test("주석은 무시된다", () => {
    const box = fromHtml("<div><!-- 주석 --><span>x</span></div>");
    assertEqual(domToVdom(box.firstChild).children.length, 1);
  });

  test("isIgnorableNode 판단", () => {
    assert(isIgnorableNode(document.createTextNode("\n   ")), "줄바꿈 공백은 무시");
    assert(!isIgnorableNode(document.createTextNode("   ")), "줄바꿈 없는 공백은 유지");
    assert(!isIgnorableNode(document.createTextNode("")), "빈 문자열은 유지");
    assert(isIgnorableNode(document.createComment("x")), "주석은 무시");
    assert(!isIgnorableNode(document.createElement("b")), "요소는 유지");
  });

  test("속성은 모두 문자열로 옮겨진다 (class, style, data-*, 값 없는 속성)", () => {
    const box = fromHtml('<input class="a b" style="color: red;" data-x="1" disabled>');
    assertEqual(domToVdom(box.firstChild).props, {
      class: "a b",
      style: "color: red;",
      "data-x": "1",
      disabled: "",
    });
  });

  test("containerToVdom 은 컨테이너 속성을 무시하고 가상 div 로 감싼다", () => {
    const box = fromHtml("\n  <p>x</p>\n");
    box.id = "anything";
    box.className = "whatever";
    assertEqual(containerToVdom(box), {
      type: "div",
      props: {},
      children: [{ type: "p", props: {}, children: ["x"] }],
    });
  });
});

describe("createElement() 왕복 변환", () => {
  test("VNode → DOM → VNode 가 원래와 같다", () => {
    const vnode = h(
      "section",
      { class: "card", "data-id": "7" },
      h("h1", null, "제목"),
      h("p", null, "글 ", h("b", null, "굵게"), " & <꺾쇠>"),
      h("ul", null, [1, 2, 3].map((n) => h("li", { "data-n": n }, n))),
      h("br", null),
    );
    // h 는 숫자 prop 을 그대로 두지만 DOM 속성은 문자열이므로 비교용 기댓값을 문자열로 맞춘다
    const expected = JSON.parse(JSON.stringify(vnode, (k, v) => (typeof v === "number" ? String(v) : v)));
    assertEqual(domToVdom(createElement(vnode)), expected);
  });

  test("텍스트 VNode 는 Text 노드가 된다", () => {
    const node = createElement("hello");
    assertEqual(node.nodeType, Node.TEXT_NODE);
    assertEqual(node.nodeValue, "hello");
  });

  test("불리언 props: true 는 빈 속성, false 는 속성 없음", () => {
    const el = createElement(h("input", { disabled: true, hidden: false }));
    assert(el.hasAttribute("disabled"), "disabled 가 있어야 함");
    assert(!el.hasAttribute("hidden"), "hidden 은 없어야 함");
  });
});
