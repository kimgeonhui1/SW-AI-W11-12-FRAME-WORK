// [tests/cases-history-html.test.js] 테스트 항목 #171 ~ #230
//   #171 ~ #200 History (phase1/history.js)
//   #201 ~ #230 Serialize — VDOM → HTML 문자열 (phase1/main.js 의 toHtml)

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, containerToVdom } from "../src/core/vdom.js";
import * as history from "../src/phase1/history.js";
import { toHtml } from "../src/phase1/main.js";
import { root, fromHtml, deepTree } from "./helpers.js";

/** n 개의 서로 다른 VDOM 을 차례로 push 한 상태로 시작 */
function fill(n) {
  history.reset();
  for (let i = 0; i < n; i++) history.push(root(h("p", null, `v${i}`)), { label: `L${i}` });
}
/** 현재 위치의 VDOM 에 들어 있는 글자 (v0, v1 …) */
const currentText = () => history.current().children[0].children[0];

describe("History (#171~#200)", () => {
  test("#171 빈 History: 위치 -1, 개수 0, current() 는 null", () => {
    history.reset();
    assertEqual(history.position(), { index: -1, length: 0 });
    assertEqual(history.current(), null);
  });
  test("#172 빈 History 에서 Undo → null", () => {
    history.reset();
    assertEqual(history.undo(), null);
    assertEqual(history.position().index, -1);
  });
  test("#173 빈 History 에서 Redo → null", () => {
    history.reset();
    assertEqual(history.redo(), null);
  });
  test("#174 첫 번째 항목에서 Undo → null, 위치 그대로", () => {
    fill(1);
    assertEqual(history.undo(), null);
    assertEqual(history.position().index, 0);
  });
  test("#175 마지막 항목에서 Redo → null, 위치 그대로", () => {
    fill(3);
    assertEqual(history.redo(), null);
    assertEqual(history.position().index, 2);
  });
  test("#176 여러 번 연속 Undo", () => {
    fill(5);
    for (let i = 3; i >= 0; i--) assertEqual(history.undo().children[0].children[0], `v${i}`);
    assertEqual(history.undo(), null);
  });
  test("#177 여러 번 연속 Redo", () => {
    fill(5);
    history.go(0);
    for (let i = 1; i <= 4; i++) assertEqual(history.redo().children[0].children[0], `v${i}`);
    assertEqual(history.redo(), null);
  });
  test("#178 Undo 후 새 항목 추가 → 그 뒤에 붙음", () => {
    fill(3);
    history.undo();
    history.push(root("new"));
    assertEqual(history.position(), { index: 2, length: 3 });
  });
  test("#179 Undo 후 push 하면 기존 Redo 기록이 사라짐 (분기)", () => {
    fill(4);
    history.undo();
    history.undo();
    history.push(root("branch"));
    assertEqual(history.position(), { index: 2, length: 3 });
    assertEqual(history.canRedo(), false);
    assertEqual(history.entries().map((e) => e.label).slice(0, 2), ["L0", "L1"]);
  });
  test("#180 같은 VDOM 을 여러 번 저장해도 각각 기록 (중복 제거는 main.js 의 \"변경 없음\" 이 담당)", () => {
    history.reset();
    const v = root("same");
    history.push(v);
    history.push(v);
    history.push(v);
    assertEqual(history.position().length, 3);
  });
  test("#181 빈 VDOM 저장", () => {
    history.reset();
    history.push(root());
    assertEqual(history.current(), root());
  });
  test("#182 깊은 VDOM(500단계) 저장", () => {
    history.reset();
    history.push(root(deepTree(500)));
    assertEqual(history.current(), root(deepTree(500)));
  });
  test("#183 저장 후 원본을 고쳐도 기록은 그대로 (깊은 복사)", () => {
    history.reset();
    const v = root(h("p", { id: "a" }, "x"));
    history.push(v);
    v.children[0].props.id = "changed";
    v.children[0].children.push("added");
    assertEqual(history.current(), root(h("p", { id: "a" }, "x")));
  });
  test("#184 꺼낸 VDOM 을 고쳐도 기록은 그대로", () => {
    fill(1);
    history.current().children.length = 0;
    assertEqual(currentText(), "v0");
  });
  test("#185 entries() 로 내부 데이터를 바꿀 수 없음 (VDOM 도 노출하지 않음)", () => {
    fill(2);
    const list = history.entries();
    assert(!("vdom" in list[0]), "entries 에 VDOM 이 없어야 함");
    list[0].label = "해킹";
    list.length = 0;
    assertEqual(history.entries()[0].label, "L0");
    assertEqual(history.position().length, 2);
  });
  test("#186 잘못된 값으로 go() → null, 위치 그대로", () => {
    fill(3);
    for (const bad of [undefined, null, {}, [], true]) assertEqual(history.go(bad), null);
    assertEqual(history.position().index, 2);
  });
  test("#187 음수 인덱스 go(-1) → null", () => {
    fill(3);
    assertEqual(history.go(-1), null);
  });
  test("#188 범위를 넘는 go(99) → null", () => {
    fill(3);
    assertEqual(history.go(3), null);
    assertEqual(history.go(99), null);
  });
  test("#189 소수 인덱스 go(1.5) → null", () => {
    fill(3);
    assertEqual(history.go(1.5), null);
  });
  test("#190 문자열 인덱스 go(\"1\") → null (자동 변환하지 않음)", () => {
    fill(3);
    assertEqual(history.go("1"), null);
    assertEqual(history.position().index, 2);
  });
  test("#191 reset() 후 Undo → null", () => {
    fill(3);
    history.reset();
    assertEqual(history.undo(), null);
  });
  test("#192 reset() 후 Redo → null", () => {
    fill(3);
    history.go(0);
    history.reset();
    assertEqual(history.redo(), null);
  });
  test("#193 reset() 후 새 항목 저장 → 0번부터", () => {
    fill(3);
    history.reset();
    assertEqual(history.push(root("x")), 0);
    assertEqual(history.position(), { index: 0, length: 1 });
  });
  test("#194 메타데이터 없이 저장 → 패치 수 0, 기본 이름", () => {
    history.reset();
    history.push(root());
    const [entry] = history.entries();
    assertEqual(entry.patchCount, 0);
    assert(typeof entry.label === "string" && entry.label.length > 0, "기본 이름이 있어야 함");
  });
  test("#195 메타데이터가 빈 객체 → 기본값", () => {
    history.reset();
    history.push(root(), {});
    assertEqual(history.entries()[0].patchCount, 0);
  });
  test("#196 잘못된 메타데이터(null, 문자열, 잘못된 타입) → 오류 없이 기본값", () => {
    history.reset();
    for (const meta of [null, "x", 5, { patchCount: "많음", label: 42 }]) history.push(root(), meta);
    for (const entry of history.entries()) {
      assertEqual(entry.patchCount, 0);
      assertEqual(typeof entry.label, "string");
    }
    assertEqual(history.position().length, 4);
  });
  test("#197 대량 저장(10,000개)", () => {
    history.reset();
    for (let i = 0; i < 10000; i++) history.push(root(String(i)));
    assertEqual(history.position(), { index: 9999, length: 10000 });
    assertEqual(history.go(5000).children, ["5000"]);
  });
  test("#198 최대 크기 제한은 없음 — 20,000개에서도 처음/끝 이동 정상", () => {
    history.reset();
    for (let i = 0; i < 20000; i++) history.push(root(String(i)));
    assertEqual(history.go(0).children, ["0"]);
    assertEqual(history.undo(), null);
    assertEqual(history.go(19999).children, ["19999"]);
    assertEqual(history.redo(), null);
  });
  test("#199 현재 위치로 반복 이동 → 같은 VDOM, 위치 그대로", () => {
    fill(3);
    for (let i = 0; i < 5; i++) assertEqual(history.go(1).children[0].children, ["v1"]);
    assertEqual(history.position().index, 1);
  });
  test("#200 entries() 반환값을 고쳐도 다음 호출에는 영향 없음", () => {
    fill(2);
    const first = history.entries();
    first[0].patchCount = 999;
    first[1].active = false;
    first.push({ fake: true });
    const again = history.entries();
    assertEqual(again.length, 2);
    assertEqual(again[0].patchCount, 0);
    assertEqual(again[1].active, true);
  });
});

describe("Serialize — toHtml (#201~#230)", () => {
  /** toHtml 결과를 다시 파싱하면 원래 VDOM 이 나오는지 확인 */
  function reparse(children) {
    const html = toHtml(children);
    assertEqual(containerToVdom(fromHtml(html)), root(...children), `다시 파싱한 결과가 달라요:\n${html}`);
    return html;
  }

  test("#201 빈 텍스트 → 빈 문자열", () => assertEqual(toHtml([""]), ""));
  test("#202 빈 요소", () => assertEqual(toHtml([h("div")]), "<div></div>"));
  test("#203 일반 텍스트", () => assertEqual(toHtml(["hello"]), "hello"));
  test("#204 & → &amp;", () => assertEqual(toHtml(["a&b"]), "a&amp;b"));
  test("#205 < → &lt;", () => assertEqual(toHtml(["a<b"]), "a&lt;b"));
  test("#206 > → &gt;", () => assertEqual(toHtml(["a>b"]), "a&gt;b"));
  test("#207 텍스트의 \" 는 그대로 (텍스트에서는 안전)", () => assertEqual(toHtml(['a"b']), 'a"b'));
  test("#208 텍스트의 ' 는 그대로", () => assertEqual(toHtml(["a'b"]), "a'b"));
  test("#209 여러 특수문자 혼합", () => assertEqual(reparse([h("p", null, `<a href="x">&amp;'"`)]), `<p>&lt;a href="x"&gt;&amp;amp;'"</p>`));
  test("#210 속성값의 특수문자 (& 와 \" 만 바꿈)", () => assertEqual(reparse([h("p", { title: `&"<>'` })]), `<p title="&amp;&quot;<>'"></p>`));
  test("#211 요소 안 텍스트의 특수문자", () => assertEqual(reparse([h("p", null, "1 < 2 && 3 > 2")]), "<p>1 &lt; 2 &amp;&amp; 3 &gt; 2</p>"));
  test("#212 빈 속성 → 이름만", () => assertEqual(reparse([h("p", { title: "" })]), "<p title></p>"));
  test("#213 불리언 속성: true → 이름만, false/null → 출력 안 함", () =>
    assertEqual(toHtml([h("input", { disabled: true, readonly: false, hidden: null })]), "<input disabled>"));
  test("#214 void element 는 닫는 태그 없음", () => assertEqual(reparse([h("br"), h("img", { src: "a.png", alt: "" })]), '<br>\n<img src="a.png" alt>'));
  test("#215 void element 의 자식은 출력하지 않음 (HTML 로 표현 불가)", () => assertEqual(toHtml([{ type: "br", props: {}, children: ["x"] }]), "<br>"));
  test("#216 중첩 요소 → 들여쓰기", () =>
    assertEqual(reparse([h("ul", null, h("li", null, "a"), h("li", null, "b"))]), "<ul>\n  <li>a</li>\n  <li>b</li>\n</ul>"));
  test("#217 형제 요소 → 줄바꿈으로 구분", () => assertEqual(reparse([h("p", null, "a"), h("p", null, "b")]), "<p>a</p>\n<p>b</p>"));
  test("#218 인라인 요소가 텍스트와 섞이면 한 줄", () => assertEqual(reparse([h("p", null, "안녕 ", h("b", null, "세상"), "!")]), "<p>안녕 <b>세상</b>!</p>"));
  test("#219 자식이 모두 블록 요소면 여러 줄", () => assert(reparse([h("section", null, h("div"), h("div"))]).includes("\n  <div>"), "들여쓰기"));
  test("#220 텍스트와 요소 혼합 왕복", () => reparse(["앞", h("b", null, "굵게"), " 뒤 ", h("i", null, h("u", null, "밑줄"))]));
  test("#221 줄바꿈이 든 텍스트", () => reparse([h("p", null, "첫 줄\n둘째 줄")]));
  test("#222 탭이 든 텍스트", () => reparse([h("p", null, "a\tb\t")]));
  test("#223 NBSP → &nbsp;", () => assertEqual(reparse([h("p", null, "a b")]), "<p>a&nbsp;b</p>"));
  test("#224 <pre> 는 항상 한 줄 (공백만 있는 텍스트도 보존)", () => {
    const html = reparse([h("pre", null, h("b", null, "x"), "\n\n", h("div", null, h("i", null, "y")))]);
    assertEqual(html, "<pre><b>x</b>\n\n<div><i>y</i></div></pre>");
  });
  test("#225 <textarea> 내용 보존", () => reparse([h("textarea", null, "  a\n b  ")]));
  test("#226 빈 props", () => assertEqual(toHtml([{ type: "p", props: {}, children: [] }]), "<p></p>"));
  test("#227 null props 도 오류 없이", () => assertEqual(toHtml([{ type: "p", props: null, children: [] }]), "<p></p>"));
  test("#228 속성 순서가 다르면 출력 순서도 다르지만 다시 파싱하면 같은 VDOM", () => {
    const a = toHtml([h("p", { a: "1", b: "2" })]);
    const b = toHtml([h("p", { b: "2", a: "1" })]);
    assert(a !== b, "출력은 입력 순서를 따름");
    assertEqual(containerToVdom(fromHtml(a)), containerToVdom(fromHtml(b)));
  });
  test("#229 잘못된 태그명은 검사하지 않고 그대로 출력 (createElement 는 오류)", () =>
    assertEqual(toHtml([{ type: "a b", props: {}, children: [] }]), "<a b></a b>"));
  test("#230 매우 긴 문자열(200,000자, & 포함)", () => {
    const html = toHtml([h("p", null, "&".repeat(200000))]);
    assertEqual(html.length, "<p></p>".length + 200000 * "&amp;".length);
  });
});
