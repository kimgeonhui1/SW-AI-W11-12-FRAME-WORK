// [tests/cases-security.test.js] 테스트 항목 #291 ~ #315 — 안정성 및 보안
//
// 위험한 문자열은 "텍스트" 로 들어오면 반드시 이스케이프되어 태그 · 스크립트가 되지 않아야 한다.
// "속성" 으로 들어온 이벤트 핸들러 · javascript: URL 은 그대로 설정된다 (사용자 본인 화면에서만 쓰는 도구라
// 막지 않음 — 보고서 한계에 기록). 그래서 여기서는 실행되지 않는 요소(div 등)로만 확인한다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, createElement, domToVdom, containerToVdom } from "../src/core/vdom.js";
import { diff, PATCH } from "../src/core/diff.js";
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

/** 모든 경로(렌더링, DOM→VDOM, Diff/Patch, 직렬화)에서 글자가 바뀌지 않는지 */
function preservedEverywhere(text) {
  const tree = root(h("p", { title: text }, text));
  assertEqual(containerToVdom(render(tree)), tree, "render → VDOM");
  roundTrip(root(h("p", { title: "x" }, "x")), tree);
  assertEqual(containerToVdom(fromHtml(toHtml(tree.children))), tree, "toHtml → 파싱");
}

/** 객체 트리를 깊게 얼린다 */
function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
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
  test("#295 <iframe> 문자열은 텍스트로", () => textStaysText('<iframe src="https://example.com"></iframe>'));
  test("#296 <img> 문자열은 텍스트로", () => textStaysText("<img src=x>"));
  test("#297 이미 이스케이프된 문자열(&amp;)은 한 번 더 이스케이프 → 원래 글자 그대로 보존", () => {
    assertEqual(textStaysText("&amp; &lt;"), "<p>&amp;amp; &amp;lt;</p>");
  });
  test("#298 직렬화 → 파싱 → 다시 직렬화하면 같은 문자열 (안정)", () => {
    const tree = root(h("p", { title: `a"&<` }, "x < y & z"), h("ul", null, h("li", null, "&nbsp; ")));
    const once = toHtml(tree.children);
    const twice = toHtml(containerToVdom(fromHtml(once)).children);
    assertEqual(twice, once);
  });
  test("#299 잘못된 Unicode(짝 없는 서로게이트)도 오류 없이 그대로", () => {
    const text = "a\uD800b\uDFFFc";
    assertEqual(containerToVdom(render(root(text))).children, [text]);
    roundTrip(root("x"), root(text));
    assert(toHtml([text]).includes("\uD800"), "그대로 출력");
  });
  test("#300 이모지(피부색 · 가족 결합 문자) 보존", () => preservedEverywhere("👍🏽 👨‍👩‍👧 🇰🇷"));
  test("#301 조합형(완성형, NFC) 한글 보존", () => preservedEverywhere("한글 테스트".normalize("NFC")));
  test("#302 분해형(NFD) 한글 보존 — NFC 로 바꾸지 않으며, NFC 와는 다른 문자열로 비교", () => {
    const nfd = "한글".normalize("NFD");
    preservedEverywhere(nfd);
    assertEqual(diff(root(nfd), root(nfd.normalize("NFC")))[0].type, PATCH.TEXT);
  });
  test("#303 서로게이트 쌍(𝒜, 𠀀) 보존", () => {
    preservedEverywhere("𝒜𠀀");
    assertEqual(containerToVdom(render(root("𝒜"))).children[0].length, 2);
  });
  test("#304 제로 너비 문자(ZWSP, ZWJ, BOM) 보존", () => preservedEverywhere("a​b‍c﻿d"));
  test("#305 방향 제어 문자(RLO, PDF) 보존", () => preservedEverywhere("‮abc‬ 끝"));
  test("#306 매우 큰 숫자: 자식 1e21 → \"1e+21\", 속성 1e300 → \"1e+300\"", () => {
    assertEqual(h("p", null, 1e21).children, ["1e+21"]);
    assertEqual(h("p", null, Number.MAX_SAFE_INTEGER + 2).children, ["9007199254740992"]);
    assertEqual(createElement(h("p", { "data-n": 1e300 })).dataset.n, "1e+300");
  });
  test("#307 순환 참조 VDOM: 브라우저와 상관없이 같은 TypeError 로 실패, 공유 노드는 허용", () => {
    const loop = { type: "div", props: {}, children: [] };
    loop.children.push(loop);
    // 스택 초과에 맡기면 Chrome 은 RangeError, Firefox 는 InternalError → 직접 찾아 TypeError 로 통일
    assert(/순환/.test(assertThrows(() => createElement(loop), TypeError).message), "순환 참조라고 알려야 함");
    assert(/순환/.test(assertThrows(() => diff(loop, loop), TypeError).message), "순환 참조라고 알려야 함");
    const deep = { type: "p", props: {}, children: [{ type: "b", props: {}, children: [] }] };
    deep.children[0].children.push(deep); // 한 단계 아래에서 되돌아오는 순환
    assertThrows(() => createElement(deep), TypeError);
    assertThrows(() => diff(root(deep), root(deep)), TypeError);
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
  test("#309 Object.freeze() 된 VDOM 도 모든 함수에서 사용 가능", () => {
    const a = deepFreeze(root(h("p", { id: "a" }, "x")));
    const b = deepFreeze(root(h("p", { id: "b" }, "y")));
    roundTrip(a, b);
    assertEqual(h("p", a.children[0].props).props, { id: "a" });
    history.reset();
    history.push(a);
    assertEqual(history.current(), a);
    assertEqual(toHtml(b.children), '<p id="b">y</p>');
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
  test("#312 constructor 속성 추가 · 삭제", () => {
    assertEqual(diff(root(h("p")), root(h("p", { constructor: "x" })))[0].set, { constructor: "x" });
    assertEqual(diff(root(h("p", { constructor: "x" })), root(h("p")))[0].remove, ["constructor"]);
    roundTrip(root(h("p")), root(h("p", { constructor: "x" })));
  });
  test("#313 prototype 속성 추가 · 삭제", () => {
    roundTrip(root(h("p")), root(h("p", { prototype: "x" })));
    roundTrip(root(h("p", { prototype: "x" })), root(h("p")));
  });
  test("#314 메모리를 많이 쓰는 상황: 요소 50,000개 생성 · 변환 · 비교", () => {
    const big = root(...Array.from({ length: 50000 }, (_, i) => h("i", null, String(i))));
    const box = render(big);
    const back = containerToVdom(box);
    assertEqual(back.children.length, 50000);
    assertEqual(diff(big, back), []);
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
