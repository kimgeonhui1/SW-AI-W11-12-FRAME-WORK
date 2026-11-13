// [tests/cases-security.test.js] 테스트 항목 #291 ~ #315 — 안정성 및 보안
//
// 위험한 문자열은 "텍스트" 로 들어오면 반드시 이스케이프되어 태그 · 스크립트가 되지 않아야 한다.
// "속성" 으로 들어온 이벤트 핸들러 · javascript: URL 은 그대로 설정된다 (사용자 본인 화면에서만 쓰는 도구라
// 막지 않음 — 보고서 한계에 기록). 그래서 여기서는 실행되지 않는 요소(div 등)로만 확인한다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, createElement, domToVdom, containerToVdom } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import * as history from "../src/phase1/history.js";
import { toHtml } from "../src/phase1/main.js";
import { root, render, fromHtml, roundTrip, assertThrows } from "./helpers.js";

/** 텍스트를 toHtml → 파싱했을 때 요소 없이 같은 글자로 돌아오는지 */
function textStaysText(text) {
  const html = toHtml([h("p", null, text)]);
  const box = fromHtml(html);
  assertEqual(box.querySelectorAll("p *").length, 0, `태그가 생기면 안 됨: ${html}`);
  assertEqual(box.textContent, text);
  return html;
}

describe("안정성 및 보안 (#291~#315)", () => {
  test("#291 <script> 문자열은 텍스트로 이스케이프", () =>
    assertEqual(textStaysText("<script>alert(1)</script>"), "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"));
  test("#292 onerror 가 든 문자열: 텍스트로는 이스케이프, 속성값으로는 따옴표 이스케이프", () => {
    textStaysText('<img src=x onerror="alert(1)">');
    assertEqual(toHtml([h("div", { title: '" onerror="alert(1)' })]), '<div title="&quot; onerror=&quot;alert(1)"></div>');
  });
  test("#293 onclick 이 든 문자열은 텍스트로 이스케이프, 속성 밖으로 탈출 불가", () => {
    textStaysText('<b onclick="alert(1)">x</b>');
    const box = fromHtml(toHtml([h("div", { "data-x": '"><b onclick="alert(1)">' })]));
    assertEqual(box.querySelectorAll("b").length, 0);
  });
  test("#294 javascript: URL — 텍스트는 안전, href 속성값은 그대로 설정됨 (차단하지 않는 한계)", () => {
    textStaysText("javascript:alert(1)");
    const el = createElement(h("a", { href: "javascript:void(0)" }, "x"));
    assertEqual(el.getAttribute("href"), "javascript:void(0)");
  });
  test("#297 이미 이스케이프된 문자열(&amp;)은 한 번 더 이스케이프 → 원래 글자 그대로 보존", () => {
    assertEqual(textStaysText("&amp; &lt;"), "<p>&amp;amp; &amp;lt;</p>");
  });
  test("#298 직렬화 → 파싱 → 다시 직렬화하면 같은 문자열 (안정)", () => {
    const tree = root(h("p", { title: `a"&<` }, "x < y & z"), h("ul", null, h("li", null, "&nbsp; ")));
    const once = toHtml(tree.children);
    const twice = toHtml(containerToVdom(fromHtml(once)).children);
    assertEqual(twice, once);
  });
  test("#307 순환 참조 VDOM: 무한 루프에 빠지지 않고 오류로 끝남, 공유 노드는 허용", () => {
    const loop = { type: "div", props: {}, children: [] };
    loop.children.push(loop);
    // 재귀가 호출 스택 한도에 걸려 멈춘다 (오류 종류는 브라우저마다 다름: Chrome RangeError, Firefox InternalError)
    assertThrows(() => createElement(loop));
    assertThrows(() => diff(loop, loop));
    // 같은 객체를 형제 자리에 두 번 쓰는 것은 순환이 아니다
    const shared = h("i", null, "x");
    roundTrip(root(h("p")), root(shared, shared));
  });
  test("#308 structuredClone 할 수 없는 값(함수)이 든 VDOM 은 저장 거부, History 그대로", () => {
    history.reset();
    history.push(root("ok"));
    const err = assertThrows(() => history.push({ type: "div", props: { onclick: () => {} }, children: [] }));
    assertEqual(err.name, "DataCloneError");
    assertEqual(history.position(), { index: 0, length: 1 });
  });
  test("#310 Object.prototype 에 있는 이름(toString, hasOwnProperty)도 속성으로 추가 · 삭제", () => {
    const withProps = root(h("p", { tostring: "a", hasownproperty: "b" }));
    roundTrip(root(h("p")), withProps);
    roundTrip(withProps, root(h("p")));
    const patches = diff(root(h("p", { toString: "a" })), root(h("p")));
    assertEqual(patches[0].remove, ["toString"]);
  });
  test("#311 __proto__ 속성: 읽기 · 비교 · 적용 모두 일반 속성처럼, 프로토타입은 오염되지 않음", () => {
    const el = document.createElement("p");
    el.setAttribute("__proto__", "x");
    const vnode = domToVdom(el);
    assert(Object.hasOwn(vnode.props, "__proto__"), "자기 속성으로 있어야 함");
    assertEqual(vnode.props.__proto__, "x");
    assertEqual(Object.getPrototypeOf(vnode.props), Object.prototype);

    const newProps = JSON.parse('{"__proto__": "y"}');
    const patches = diff(root(h("p", null)), root({ type: "p", props: newProps, children: [] }));
    assert(Object.hasOwn(patches[0].set, "__proto__"), "set 에도 자기 속성으로");
    const box = render(root(h("p")));
    patch(box, patches);
    assertEqual(box.firstChild.getAttribute("__proto__"), "y");
    assertEqual({}.y, undefined);
  });
  test("#315 예외가 난 뒤에도 History 일관성 유지 (Redo 기록이 사라지지 않음)", () => {
    history.reset();
    ["a", "b", "c"].forEach((t) => history.push(root(t)));
    history.undo();
    history.undo();
    assertThrows(() => history.push({ type: "div", props: { bad: Symbol("x") }, children: [] }));
    assertEqual(history.position(), { index: 0, length: 3 });
    assertEqual(history.redo().children, ["b"]);
    assertEqual(history.redo().children, ["c"]);
  });
});
