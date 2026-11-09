// [tests/cases-all-tags.test.js] 모든 HTML 태그 테스트 — Phase 1(VDOM · Diff · Patch · toHtml) 과 Phase 2(컴포넌트)
//
// HTML 표준(WHATWG HTML Living Standard)의 HTML 요소 112개를 하나씩 검사한다. 태그마다 테스트 1개씩.
//   Phase 1: ① VNode → createElement → domToVdom 이 원래 VNode 와 같다
//            ② toHtml → HTML 파서 → domToVdom 이 원래 VNode 와 같다 (html · head · body 는 제외, 아래 설명)
//            ③ 속성 · 글자를 바꾼 diff → patch: 요소는 그대로 재사용, 결과 = 새 VNode
//            ④ 다른 태그로 REPLACE → 다시 원래 태그로 REPLACE
//   Phase 2: 상태를 가진 컴포넌트가 그 태그를 그리고, 클릭(이벤트 위임) → setState → 다시 렌더 →
//            같은 요소를 재사용하면서 속성 · 글자가 바뀐다
//
// 빠진 것: <svg> · <math> 는 HTML 이 아니라 다른 이름공간(namespace)의 요소라 지원하지 않는다 (#059 의 한계).
//          <frameset> · <marquee> 같은 폐지된 태그도 넣지 않았다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, createElement, containerToVdom } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import { toHtml, VOID_TAGS } from "../src/phase1/main.js";
import { FunctionComponent } from "../src/core/component.js";
import { useState } from "../src/core/hooks.js";

/** HTML 표준의 모든 HTML 요소 (알파벳 순, 112개) */
export const HTML_TAGS = Object.freeze([
  "a", "abbr", "address", "area", "article", "aside", "audio",
  "b", "base", "bdi", "bdo", "blockquote", "body", "br", "button",
  "canvas", "caption", "cite", "code", "col", "colgroup",
  "data", "datalist", "dd", "del", "details", "dfn", "dialog", "div", "dl", "dt",
  "em", "embed",
  "fieldset", "figcaption", "figure", "footer", "form",
  "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr", "html",
  "i", "iframe", "img", "input", "ins",
  "kbd",
  "label", "legend", "li", "link",
  "main", "map", "mark", "menu", "meta", "meter",
  "nav", "noscript",
  "object", "ol", "optgroup", "option", "output",
  "p", "picture", "pre", "progress",
  "q",
  "rp", "rt", "ruby",
  "s", "samp", "script", "search", "section", "select", "slot", "small", "source", "span", "strong", "style", "sub", "summary", "sup",
  "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "time", "title", "tr", "track",
  "u", "ul",
  "var", "video",
  "wbr",
]);

/**
 * 글자 자식을 넣지 않는 태그.
 *   - 빈 요소(void: br, img …): 닫는 태그가 없어 자식을 HTML 로 표현할 수 없다
 *   - 표 구조 요소: HTML 파서가 그 안의 글자를 표 바깥으로 옮겨 버린다 (foster parenting)
 */
const NO_TEXT = new Set([...VOID_TAGS, "table", "thead", "tbody", "tfoot", "tr", "colgroup"]);

/**
 * HTML 파서로 왕복 검사를 하지 않는 태그.
 * <html> · <head> · <body> 는 문서에 하나뿐인 요소라, 파서가 조각(fragment) 안에서는 태그를 버리고 내용만 남긴다.
 * createElement · diff · patch 로는 정상 동작한다 (①③④ 는 검사).
 */
const NO_PARSE = new Set(["html", "head", "body"]);

/** 태그 하나의 샘플 VNode. 글자는 버전(n)마다 다르다 */
const sample = (tag, n, props = {}) => h(tag, { title: `제목 ${n}`, "data-n": String(n), ...props }, NO_TEXT.has(tag) ? [] : [`내용 ${n}`]);

/** 루트(가상의 div) 아래에 노드 하나 */
const root = (node) => ({ type: "div", props: {}, children: [node] });

/** 루트 VNode 를 실제 컨테이너(div)에 그린다 (문서에 붙이지 않음 → script · base 등이 동작하지 않음) */
function render(vroot) {
  const box = document.createElement("div");
  box.append(...vroot.children.map(createElement));
  return box;
}

/**
 * HTML 문자열을 파싱한다.
 * <template> 의 innerHTML 로 파싱하면 <td> · <tr> · <caption> 처럼 놓일 자리가 정해진 태그도
 * 혼자 있을 때 버려지지 않는다 (template 내용은 어떤 자리로도 쓰일 수 있어서 파서가 받아 준다).
 */
function parse(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html;
  const box = document.createElement("div");
  box.append(tpl.content);
  return box;
}

const json = (value) => JSON.stringify(value);

describe(`모든 HTML 태그 · Phase 1 (${HTML_TAGS.length}개)`, () => {
  test("태그 목록: 112개, 겹치는 것 없음, 모두 브라우저가 아는 HTML 요소 (HTMLUnknownElement 아님)", () => {
    assertEqual(HTML_TAGS.length, 112);
    assertEqual(new Set(HTML_TAGS).size, HTML_TAGS.length);
    const unknown = HTML_TAGS.filter((tag) => document.createElement(tag) instanceof HTMLUnknownElement);
    assertEqual(unknown, []);
  });

  for (const tag of HTML_TAGS) {
    test(`<${tag}> 만들기 · 읽기 · 직렬화 · Diff · Patch · REPLACE`, () => {
      const v1 = root(sample(tag, 1));
      const v2 = root(sample(tag, 2));

      // ① createElement → domToVdom
      const box = render(v1);
      assertEqual(json(containerToVdom(box)), json(v1), "① 만든 DOM 을 다시 읽으면 같은 VNode");

      // ② toHtml → 파서 → domToVdom
      const html = toHtml(v1.children);
      assert(html.startsWith(`<${tag} `), `② toHtml 이 <${tag} 로 시작: ${html}`);
      assertEqual(html.includes(`</${tag}>`), !VOID_TAGS.has(tag), "② 빈 요소만 닫는 태그가 없음");
      if (!NO_PARSE.has(tag)) assertEqual(json(containerToVdom(parse(html))), json(v1), `② 파서 왕복: ${html}`);

      // ③ 속성 · 글자 변경 → 요소는 그대로, PROPS (+ 글자가 있으면 TEXT)
      const el = box.firstChild;
      const patches = diff(v1, v2);
      assertEqual(patches.map((p) => p.type), NO_TEXT.has(tag) ? ["PROPS"] : ["PROPS", "TEXT"], "③ 패치 종류");
      patch(box, patches);
      assert(box.firstChild === el, "③ 같은 요소를 재사용");
      assertEqual(json(containerToVdom(box)), json(v2), "③ patch 결과 = 새 VNode");

      // ④ 다른 태그로 바꿨다가 다시 원래 태그로 (REPLACE 두 번)
      const other = root(h(tag === "div" ? "span" : "div", null, "다른 태그"));
      patch(box, diff(v2, other));
      assertEqual(box.firstChild.tagName.toLowerCase(), tag === "div" ? "span" : "div", "④ 다른 태그로");
      patch(box, diff(other, v1));
      assertEqual(json(containerToVdom(box)), json(v1), "④ 다시 원래 태그로");
    });
  }

  test("<template> 의 자식은 content 안에 생기고(화면에 그리지 않음), CREATE 도 content 에 붙음", () => {
    const v1 = root(h("template", null, h("p", null, "안")));
    const box = render(v1);
    const tpl = box.firstChild;
    assertEqual(tpl.childNodes.length, 0, "template 자신에는 자식이 없음");
    assertEqual(tpl.content.firstChild.textContent, "안");
    const v2 = root(h("template", null, h("p", null, "안"), h("p", null, "추가")));
    const patches = diff(v1, v2);
    assertEqual(patches.map((p) => p.type), ["CREATE"]);
    patch(box, patches);
    assertEqual(tpl.content.childNodes.length, 2);
    assertEqual(tpl.childNodes.length, 0);
    assertEqual(json(containerToVdom(box)), json(v2));
  });

  test("112개 태그를 한 영역에 모두 넣고, 전부 한 번에 바꿔도 patch 결과가 새 VNode 와 같음", () => {
    const v1 = { type: "div", props: {}, children: HTML_TAGS.map((tag) => sample(tag, 1)) };
    const v2 = { type: "div", props: {}, children: HTML_TAGS.map((tag) => sample(tag, 2)) };
    const box = render(v1);
    const before = [...box.children];
    patch(box, diff(v1, v2));
    assert([...box.children].every((el, i) => el === before[i]), "모든 요소 재사용");
    assertEqual(json(containerToVdom(box)), json(v2));
  });
});

describe(`모든 HTML 태그 · Phase 2 (${HTML_TAGS.length}개)`, () => {
  for (const tag of HTML_TAGS) {
    test(`<${tag}> 컴포넌트: 클릭 → setState → 같은 요소에서 속성 · 글자만 바뀜`, async () => {
      // 루트 컴포넌트 하나: 상태 n 을 그 태그의 속성 · 글자로 그리고, 클릭하면 n + 1
      const App = () => {
        const [n, setN] = useState(1);
        return h("div", { class: "wrap" }, sample(tag, n, { onClick: () => setN((x) => x + 1) }));
      };
      const box = document.createElement("div"); // 문서에 붙이지 않음
      const app = new FunctionComponent(App, box).mount();
      const el = box.firstChild.firstChild;
      assertEqual(el.tagName.toLowerCase(), tag);
      assert(el.hasAttribute("data-on-click"), "이벤트는 위임용 data-on-click 으로");

      el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0)); // 예약된 렌더(마이크로태스크)

      assertEqual(app.renderCount, 2, "렌더 2번");
      assert(box.firstChild.firstChild === el, "같은 요소를 재사용");
      assertEqual(el.getAttribute("data-n"), "2");
      assertEqual(el.getAttribute("title"), "제목 2");
      if (!NO_TEXT.has(tag)) assertEqual(tag === "template" ? el.content.textContent : el.textContent, "내용 2");
      app.unmount();
    });
  }
});
