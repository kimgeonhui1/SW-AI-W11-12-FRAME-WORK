// [tests/main.test.js] VNode → HTML 직렬화와 왕복 변환

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, containerToVdom } from "../src/core/vdom.js";
import { toHtml, escapeText, escapeAttr } from "../src/phase1/main.js";

/** toHtml 결과를 다시 파싱해 루트 VNode 로 */
function reparse(html) {
  const box = document.createElement("div");
  box.innerHTML = html;
  return containerToVdom(box);
}

/** 왕복 검증: 루트 VNode → HTML → 루트 VNode */
function roundTrip(vroot) {
  const html = toHtml(vroot.children);
  assertEqual(reparse(html), vroot, `HTML:\n${html}`);
  return html;
}

describe("main.js toHtml()", () => {
  test("요소만 있는 형제는 줄바꿈 + 들여쓰기", () => {
    const html = toHtml([h("ul", null, h("li", null, "a"), h("li", null, "b"))]);
    assertEqual(html, "<ul>\n  <li>a</li>\n  <li>b</li>\n</ul>");
  });

  test("텍스트가 섞인 형제는 한 줄", () => {
    const html = toHtml([h("p", null, "안녕 ", h("b", null, "세상"), "!")]);
    assertEqual(html, "<p>안녕 <b>세상</b>!</p>");
  });

  test("void 태그는 닫지 않는다", () => {
    assertEqual(toHtml([h("p", null, "a", h("br", null), "b")]), "<p>a<br>b</p>");
    assertEqual(toHtml([h("img", { src: "x.png", alt: "" })]), '<img src="x.png" alt>');
  });

  test("텍스트 이스케이프: & < > nbsp", () => {
    assertEqual(escapeText("a & b < c > d e"), "a &amp; b &lt; c &gt; d&nbsp;e");
  });

  test("속성 이스케이프: & \"", () => {
    assertEqual(escapeAttr('say "hi" & bye'), "say &quot;hi&quot; &amp; bye");
  });

  test("왕복: 들여쓰기 · 혼합 텍스트 · 속성 · 특수문자", () => {
    roundTrip(
      h(
        "div",
        null,
        h(
          "section",
          { class: "card", "data-id": "1", style: "color: red;" },
          h("h1", null, "제목 <&>"),
          h("p", { title: 'q"uote & amp' }, "글 ", h("strong", null, "굵게"), " 끝"),
          h("ul", null, h("li", null, "a"), h("li", null, h("em", null, "b"))),
          h("hr", null),
        ),
      ),
    );
  });

  test("왕복: 최상위에 텍스트가 섞인 경우", () => {
    const html = roundTrip(h("div", null, "앞 ", h("b", null, "x"), " 뒤"));
    assert(!html.includes("\n"), "줄바꿈이 없어야 함");
  });

  test("왕복: <pre> 는 들여쓰지 않는다 (첫 줄바꿈이 파서에서 사라지는 태그)", () => {
    const vroot = h("div", null, h("pre", null, h("b", null, "x"), h("i", null, "y")));
    const html = roundTrip(vroot);
    assertEqual(html, "<pre><b>x</b><i>y</i></pre>");
  });

  test("왕복: 빈 요소와 값 없는 속성", () => {
    roundTrip(h("div", null, h("div", { hidden: "" }), h("span", null)));
  });
});
