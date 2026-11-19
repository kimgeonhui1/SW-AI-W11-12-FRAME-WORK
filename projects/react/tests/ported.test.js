// [ported.test.js] 팀원(김준우) 테스트 중 "내 코드와 형식이 달라서" 실패한 것을, 같은 상황 · 같은 의도로 내 형식에 맞게 옮긴 테스트
//
// 원본은 "준우 님 방식으로 생겼는가"(평평한 패치 배열, path, [] 반환, 에러 문구 등)를 검사해서 내 코드로는 통과할 수 없었다.
// 여기서는 같은 입력으로 "내 방식으로 맞게 동작하는가"를 검사한다. 이름 앞의 [#번호]는 원본 테스트 번호다.
// 옮기지 않은 것: 내 코드에 없는 기능(toHtml, history.reset/go, onCommit, flush, renderCount, 이벤트 위임 data-on-*, 준우 님 페이지 구조)

import { h, createElement, domToVdom } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import { FunctionComponent } from "../src/core/component.js";
import { useState, useEffect, useMemo } from "../src/core/hooks.js";

const tests = [];
const test = (name, fn) => tests.push({ name, fn });
const tick = () => new Promise((resolve) => setTimeout(resolve));

function stableStringify(value) {
  return JSON.stringify(value, (key, v) =>
    v && typeof v === "object" && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]])) : v
  );
}
function assertEqual(actual, expected, msg = "") {
  const a = stableStringify(actual);
  const e = stableStringify(expected);
  if (a !== e) throw new Error(`${msg}\n  기대: ${e}\n  실제: ${a}`);
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}
function assertThrows(fn, msg = "에러가 나야 함") {
  try {
    fn();
  } catch (e) {
    if (!(e instanceof TypeError)) throw new Error(`${msg}: TypeError가 아님 — ${e}`);
    return e;
  }
  throw new Error(msg);
}

// ── 도우미 (내 형식) ──
const root = (...children) => h("div", null, ...children);
const li = (text, props = null) => h("li", props, text);
const list = (...texts) => root(h("ul", null, ...texts.map((t) => li(t))));
// 내 patch 규약: container의 첫 자식이 루트
function render(vroot) {
  const box = document.createElement("div");
  box.appendChild(createElement(vroot));
  return box;
}
// A를 그리고 patch(diff(A, B)) → 결과 화면이 B를 새로 그린 것과 같은지
function roundTrip(a, b) {
  const box = render(a);
  const tree = diff(a, b);
  patch(box, tree);
  assertEqual(domToVdom(box.firstChild), domToVdom(createElement(b)), "patch 결과 화면이 새로 그린 화면과 다름");
  return { box, tree };
}
// 패치 트리에서 실제 변경만 앞에서부터 모은다 (속성 변경이 없는 UPDATE는 "자식으로 내려가는 길"이라 빼고, 속성이 바뀐 UPDATE는 넣음)
function ops(tree, out = []) {
  if (tree === null) return out;
  if (tree.type !== "UPDATE") return out.push(tree.type), out;
  if (tree.props.length > 0) out.push("UPDATE");
  tree.children.forEach((c) => ops(c, out));
  return out;
}
const texts = (box) => [...box.firstChild.children].map((el) => el.textContent);
const abc = () => render(root(h("p", null, "a"), h("p", null, "b"), h("p", null, "c")));
const deepTree = (depth, leaf) => {
  let node = leaf;
  for (let i = 0; i < depth; i++) node = h("div", null, node);
  return node;
};
// 루트(div) 아래 i번째 자식에게만 패치를 주는 트리
const at = (count, map) => ({ type: "UPDATE", props: [], children: Array.from({ length: count }, (_, i) => map[i] ?? null) });
const kids = (...children) => h("p", null, ...children).children;

// ── Diff (#081~#115) ──

test("[#081] 완전히 같은 VDOM → null (변경 없음)", () => {
  const a = root(h("div", { id: "x" }, h("p", null, "a", h("b", null, "b"))));
  assertEqual(diff(a, structuredClone(a)), null);
});
test("[#082] 루트 태그 변경 → REPLACE 하나, patch하면 루트가 갈아 끼워짐 (내 규약: container 안의 루트)", () => {
  const tree = diff(h("p", null, "a"), h("div", null, "a"));
  assertEqual(tree, { type: "REPLACE", node: h("div", null, "a") });
  const box = render(h("p", null, "a"));
  patch(box, tree);
  assertEqual(box.innerHTML, "<div>a</div>");
});
test("[#083] 루트가 텍스트일 때 변경 → TEXT", () => assertEqual(diff("a", "b"), { type: "TEXT", text: "b" }));
test("[#084] 텍스트 → 요소 → REPLACE", () => assertEqual(ops(roundTrip(root("a"), root(h("b", null, "a"))).tree), ["REPLACE"]));
test("[#085] 요소 → 텍스트 → REPLACE", () => assertEqual(ops(roundTrip(root(h("b", null, "a")), root("a")).tree), ["REPLACE"]));
test("[#086] 빈 트리 → 요소 생성 (CREATE)", () =>
  assertEqual(roundTrip(root(), root(h("p", null, "x"))).tree, at(1, { 0: { type: "CREATE", node: h("p", null, "x") } })));
test("[#087] 요소 → 빈 트리 (REMOVE)", () => assertEqual(roundTrip(root(h("p", null, "x")), root()).tree, at(1, { 0: { type: "REMOVE" } })));
test("[#088] 자식 하나 추가 → CREATE", () => assertEqual(ops(roundTrip(list("1"), list("1", "2")).tree), ["CREATE"]));
test("[#090] 자식 여러 개 추가 → CREATE 3개", () => assertEqual(ops(roundTrip(list("1"), list("1", "2", "3", "4")).tree), ["CREATE", "CREATE", "CREATE"]));
test("[#091] 자식 여러 개 삭제 → REMOVE 3개", () => assertEqual(ops(roundTrip(list("1", "2", "3", "4"), list("1")).tree), ["REMOVE", "REMOVE", "REMOVE"]));
test("[#092] 첫 번째 자식 삭제 (key 없으면 위치 비교라 뒤 형제 TEXT + 마지막 REMOVE)", () =>
  assertEqual(ops(roundTrip(list("1", "2", "3"), list("2", "3")).tree), ["TEXT", "TEXT", "REMOVE"]));
test("[#093] 마지막 자식 삭제 → REMOVE 하나", () => assertEqual(ops(roundTrip(list("1", "2", "3"), list("1", "2")).tree), ["REMOVE"]));
test("[#097] 앞에 자식 삽입 (key 없으면 모든 형제 TEXT + CREATE)", () =>
  assertEqual(ops(roundTrip(list("1", "2", "3"), list("0", "1", "2", "3")).tree), ["TEXT", "TEXT", "TEXT", "CREATE"]));
test("[#097 + key] 같은 상황에서 key가 있으면 CREATE 하나만 (내 코드에만 있는 key 비교)", () => {
  const keyed = (...ts) => root(h("ul", null, ...ts.map((t) => li(t, { key: t }))));
  assertEqual(ops(roundTrip(keyed("1", "2", "3"), keyed("0", "1", "2", "3")).tree), ["CREATE"]);
});
test("[#099] 마지막에 자식 삽입 → CREATE 하나", () => assertEqual(ops(roundTrip(list("1", "2"), list("1", "2", "3")).tree), ["CREATE"]));
test("[#101] 형제 요소를 모두 다른 태그로 → 각각 REPLACE", () =>
  assertEqual(ops(roundTrip(root(h("p"), h("p"), h("p")), root(h("div"), h("span"), h("em"))).tree), ["REPLACE", "REPLACE", "REPLACE"]));
test("[#103] 같은 태그, 다른 속성 → 속성 변경만 (자식 패치 없음)", () => {
  const { tree } = roundTrip(root(h("p", { id: "a" }, "x")), root(h("p", { class: "b" }, "x")));
  assertEqual(tree, at(1, { 0: { type: "UPDATE", props: [{ name: "class", value: "b" }, { name: "id", value: undefined, oldValue: "a" }], children: [null] } }));
});
test("[#104] 속성 하나 추가", () =>
  assertEqual(diff(root(h("p")), root(h("p", { title: "t" }))).children[0].props, [{ name: "title", value: "t" }]));
test("[#105] 속성 하나 삭제 (value: undefined = 삭제)", () =>
  assertEqual(diff(root(h("p", { title: "t" })), root(h("p"))).children[0].props, [{ name: "title", value: undefined, oldValue: "t" }]));
test("[#106] 속성 하나 변경", () =>
  assertEqual(diff(root(h("p", { title: "a" })), root(h("p", { title: "b" }))).children[0].props, [{ name: "title", value: "b", oldValue: "a" }]));
test("[#107] 여러 속성 동시 변경", () => {
  const { tree } = roundTrip(root(h("p", { a: "1", b: "2", c: "3" })), root(h("p", { a: "x", b: "y", c: "z" })));
  assertEqual(tree.children[0].props.map((p) => [p.name, p.value]), [["a", "x"], ["b", "y"], ["c", "z"]]);
});
test("[#108] 속성 추가와 삭제가 동시에", () => {
  const { tree } = roundTrip(root(h("p", { old: "1", keep: "k" })), root(h("p", { keep: "k", new: "2" })));
  assertEqual(tree.children[0].props.map((p) => [p.name, p.value]), [["new", "2"], ["old", undefined]]);
});
test("[#110] 속성값을 null로 → 속성 변경에 null, patch하면 속성이 지워짐", () => {
  const old = root(h("p", { title: "a" }));
  const tree = diff(old, root(h("p", { title: null })));
  assertEqual(tree.children[0].props, [{ name: "title", value: null, oldValue: "a" }]);
  const box = render(old);
  patch(box, tree);
  assertEqual(box.firstChild.firstChild.hasAttribute("title"), false);
});
test("[#111] 부모와 자식 속성이 동시에 변경 → 속성 변경 두 군데", () =>
  assertEqual(ops(roundTrip(root(h("div", { id: "a" }, h("p", { id: "b" }))), root(h("div", { id: "A" }, h("p", { id: "B" })))).tree), ["UPDATE", "UPDATE"]));
test("[#112] 같은 위치에서 텍스트 ↔ 요소 맞바꿈 → REPLACE 둘", () =>
  assertEqual(ops(roundTrip(root("a", h("b", null, "b")), root(h("b", null, "b"), "a")).tree), ["REPLACE", "REPLACE"]));
test("[#114] 1,000단계 깊이 트리 비교 → 맨 아래 TEXT 하나 (깊이 1,001)", () => {
  let tree = diff(root(deepTree(1000, "a")), root(deepTree(1000, "b")));
  assertEqual(ops(tree), ["TEXT"]);
  let depth = 0;
  while (tree.type === "UPDATE") (tree = tree.children[0]), depth++;
  assertEqual([tree.type, depth], ["TEXT", 1001]);
});
test("[#115] 형제 5,000개 중 10개마다 변경 → TEXT 500개", () => {
  const ts = Array.from({ length: 5000 }, (_, i) => String(i));
  assertEqual(ops(roundTrip(list(...ts), list(...ts.map((t, i) => (i % 10 === 0 ? `${t}!` : t)))).tree).length, 500);
});

// ── Patch (#116~#145): 손으로 만든 패치 트리를 적용 ──

test("[#116] CREATE 적용", () => {
  const box = abc();
  patch(box, at(4, { 3: { type: "CREATE", node: h("p", null, "d") } }));
  assertEqual(texts(box), ["a", "b", "c", "d"]);
});
test("[#117] REMOVE 적용 (가운데)", () => {
  const box = abc();
  patch(box, at(3, { 1: { type: "REMOVE" } }));
  assertEqual(texts(box), ["a", "c"]);
});
test("[#118] REPLACE 적용", () => {
  const box = abc();
  patch(box, at(3, { 1: { type: "REPLACE", node: h("h2", null, "B") } }));
  assertEqual(box.firstChild.children[1].outerHTML, "<h2>B</h2>");
});
test("[#119] TEXT 적용", () => {
  const box = abc();
  patch(box, at(3, { 2: { type: "UPDATE", props: [], children: [{ type: "TEXT", text: "C" }] } }));
  assertEqual(texts(box), ["a", "b", "C"]);
});
test("[#120] 속성 변경 적용 (넣기 · 바꾸기 · 지우기)", () => {
  const box = render(root(h("p", { id: "x", title: "t" })));
  patch(box, at(1, { 0: { type: "UPDATE", props: [{ name: "id", value: "y", oldValue: "x" }, { name: "class", value: "c" }, { name: "title", value: undefined, oldValue: "t" }], children: [] } }));
  assertEqual(box.firstChild.innerHTML, '<p id="y" class="c"></p>');
});
test("[#121] 빈 패치(null) → 아무것도 바뀌지 않음", () => {
  const box = abc();
  const before = box.innerHTML;
  patch(box, null);
  assertEqual(box.innerHTML, before);
});
test("[#122] 같은 패치를 두 번: TEXT는 같은 결과, REMOVE는 다른 노드를 지움 (패치는 한 번만 적용해야 함)", () => {
  const box = abc();
  const textPatch = at(1, { 0: { type: "UPDATE", props: [], children: [{ type: "TEXT", text: "A" }] } });
  patch(box, textPatch);
  patch(box, textPatch);
  assertEqual(texts(box), ["A", "b", "c"]);
  const removePatch = at(1, { 0: { type: "REMOVE" } });
  patch(box, removePatch);
  patch(box, removePatch);
  assertEqual(texts(box), ["c"]);
});
test("[#123] 연속 CREATE는 순서대로 붙음", () => {
  const box = render(root());
  patch(box, at(3, { 0: { type: "CREATE", node: h("p", null, "0") }, 1: { type: "CREATE", node: h("p", null, "1") }, 2: { type: "CREATE", node: h("p", null, "2") } }));
  assertEqual(texts(box), ["0", "1", "2"]);
});
test("[#124] 연속 REMOVE", () => {
  const box = abc();
  patch(box, at(3, { 1: { type: "REMOVE" }, 2: { type: "REMOVE" } }));
  assertEqual(texts(box), ["a"]);
});
test("[#125] 연속 REPLACE", () => {
  const box = abc();
  patch(box, at(3, { 0: { type: "REPLACE", node: h("b", null, "0") }, 1: { type: "REPLACE", node: h("b", null, "1") }, 2: { type: "REPLACE", node: h("b", null, "2") } }));
  assertEqual(box.firstChild.innerHTML, "<b>0</b><b>1</b><b>2</b>");
});
test("[#127·#128] 첫 번째와 마지막 삭제 (트리는 이전 위치 기준이라 순서와 상관없음)", () => {
  const box = abc();
  patch(box, at(3, { 0: { type: "REMOVE" }, 2: { type: "REMOVE" } }));
  assertEqual(texts(box), ["b"]);
});
test("[#129] 중첩 요소를 만든 뒤 그 안을 수정", () => {
  const v1 = root();
  const v2 = root(h("ul", null, li("a")));
  const v3 = root(h("ul", null, li("A", { class: "on" })));
  const box = render(v1);
  patch(box, diff(v1, v2));
  patch(box, diff(v2, v3));
  assertEqual(domToVdom(box.firstChild), domToVdom(createElement(v3)));
});
test("[#130] 부모 교체와 자식 수정이 동시에 → 부모 REPLACE 하나만", () =>
  assertEqual(ops(roundTrip(root(h("p", null, h("b", null, "a"))), root(h("div", null, h("b", null, "A")))).tree), ["REPLACE"]));
test("[#132] 같은 노드의 여러 속성 변경 → 속성 변경 한 군데 (항목 3개)", () => {
  const { tree } = roundTrip(root(h("p", { a: "1" })), root(h("p", { a: "2", b: "3", c: "4" })));
  assertEqual([ops(tree), tree.children[0].props.length], [["UPDATE"], 3]);
});
test("[#133] 없는 위치 → TypeError, 앞의 정상 패치도 적용하지 않음", () => {
  const box = abc();
  const tree = at(6, { 0: { type: "UPDATE", props: [], children: [{ type: "TEXT", text: "A" }] }, 5: { type: "UPDATE", props: [], children: [{ type: "TEXT", text: "x" }] } });
  assertThrows(() => patch(box, tree));
  assertEqual(texts(box), ["a", "b", "c"]);
});
test("[#134] 범위를 넘는 자리의 CREATE → 끝에 붙음", () => {
  const box = abc();
  patch(box, at(10, { 9: { type: "CREATE", node: h("p", null, "z") } }));
  assertEqual(texts(box), ["a", "b", "c", "z"]);
});
test("[#135] 범위를 넘는 자리의 REMOVE → TypeError, DOM 그대로", () => {
  const box = abc();
  assertThrows(() => patch(box, at(10, { 1: { type: "REMOVE" }, 9: { type: "REMOVE" } })));
  assertEqual(texts(box), ["a", "b", "c"]);
});
test("[#136] 루트의 속성 변경 → 루트 요소 속성이 바뀜 (내 규약: 루트 = container의 첫 자식)", () => {
  const box = abc();
  patch(box, { type: "UPDATE", props: [{ name: "data-x", value: "1" }], children: [] });
  assertEqual(box.firstChild.dataset.x, "1");
});
test("[#137] 잘못된 패치 종류 → TypeError, 앞의 정상 패치도 적용하지 않음", () => {
  const box = abc();
  assertThrows(() => patch(box, at(2, { 0: { type: "UPDATE", props: [], children: [{ type: "TEXT", text: "A" }] }, 1: { type: "MOVE" } })));
  assertEqual(texts(box), ["a", "b", "c"]);
});
test("[#138] 대상을 찾을 수 없거나 모양이 깨진 패치 → TypeError, DOM 그대로", () => {
  const box = abc();
  for (const p of [at(4, { 3: { type: "CREATE" } }), at(1, { 0: { type: "TEXT", text: "x" } }), 5, { type: "UPDATE", props: [], children: [{ type: "REMOVE" }, null, null, null, { type: "REMOVE" }] }]) {
    assertThrows(() => patch(box, p), `TypeError여야 함: ${JSON.stringify(p)}`);
  }
  assertEqual(texts(box), ["a", "b", "c"]);
});
test("[#139] REPLACE의 새 노드가 VNode가 아님 → TypeError, DOM 그대로", () => {
  const box = abc();
  for (const node of [{}, null, { type: "" }]) assertThrows(() => patch(box, at(1, { 0: { type: "REPLACE", node } })), `node: ${JSON.stringify(node)}`);
  assertEqual(texts(box), ["a", "b", "c"]);
});
test("[#144] 깊은 중첩(300단계)에 Patch → 맨 아래 텍스트 노드를 재사용", () => {
  const old = root(deepTree(300, "a"));
  const box = render(old);
  let leaf = box;
  while (leaf.firstChild) leaf = leaf.firstChild;
  patch(box, diff(old, root(deepTree(300, "b"))));
  let now = box;
  while (now.firstChild) now = now.firstChild;
  assertEqual([now === leaf, leaf.nodeValue], [true, "b"]);
});

// ── Props (#160~#162) ──

test("[#160] 속성 순서만 다름 → 변경 없음 (null)", () => assertEqual(diff(root(h("p", { a: "1", b: "2" })), root(h("p", { b: "2", a: "1" }))), null));
test("[#161] 같은 값으로 다시 설정 → 변경 없음 (null)", () => assertEqual(diff(root(h("p", { a: "1" })), root(h("p", { a: "1" }))), null));
test("[#162] 없는 속성을 지워도 오류 없음", () => {
  const box = render(root(h("p")));
  patch(box, at(1, { 0: { type: "UPDATE", props: [{ name: "nope", value: undefined, oldValue: "x" }], children: [] } }));
  assertEqual(box.firstChild.firstChild.attributes.length, 0);
});

// ── VDOM 생성 · 변환 (#009~#069): 내 정규화 규칙 = "같은 화면이면 같은 VDOM" ──

test("[#009·#017] 이웃한 텍스트는 하나로 합침 (Infinity, 숫자 포함) — 브라우저도 붙은 글자는 노드 하나", () => {
  assertEqual(kids(Infinity, -Infinity), ["Infinity-Infinity"]);
  assertEqual(kids([1, "a", 2.5]), ["1a2.5"]);
  const w = document.createElement("div");
  w.innerHTML = createElement(h("p", null, "1", "a", "2.5")).outerHTML;
  assertEqual(w.firstChild.childNodes.length, 1, "HTML로 옮기면 어차피 텍스트 노드 하나");
});
test("[#010] 빈 문자열은 버림 (브라우저도 빈 텍스트 노드를 만들지 않음)", () => assertEqual(kids(""), []));
test("[#013·#015·#018·#019] 배열은 펼치고, null · 빈 배열은 버리고, 남은 텍스트는 합침", () => {
  assertEqual(kids([[["a", [["b"]]]], [[["c"]]]]), ["abc"]);
  assertEqual(kids(["a", null, undefined, "b"]), ["ab"]);
  assertEqual(kids(["a", "b"]), ["ab"]);
  assertEqual(kids(["a", [], [[]], [[[]]], "b"]), ["ab"]);
  assertEqual(kids(["a", h("b", null, "x"), "c"]), ["a", { type: "b", props: {}, children: ["x"] }, "c"], "요소 사이 텍스트는 합치지 않음");
});
test("[#030] 같은 객체를 여러 자식으로 재사용해도 DOM은 각각 생성, 같으면 diff는 null", () => {
  const child = h("i", null, "x");
  const node = h("p", null, child, child);
  const el = createElement(node);
  assertEqual([el.children.length, el.children[0] !== el.children[1]], [2, true]);
  assertEqual(diff(root(node), root(node)), null);
});
test("[#059] SVG: 읽을 때 태그 대소문자 유지, 다시 만들면 SVG 요소 (내 코드는 SVG 지원)", () => {
  const w = document.createElement("div");
  w.innerHTML = '<svg viewBox="0 0 10 10"><circle r="1"></circle><foreignObject></foreignObject></svg>';
  const svg = domToVdom(w.firstChild);
  assertEqual(svg.children.map((c) => c.type), ["circle", "foreignObject"]);
  const el = createElement(svg);
  assertEqual([el.namespaceURI, el.firstChild.namespaceURI], ["http://www.w3.org/2000/svg", "http://www.w3.org/2000/svg"]);
});
test("[#069] className은 class 속성이 됨 (React와 같은 이름)", () => {
  const el = createElement(h("p", { className: "a" }));
  assertEqual([el.getAttribute("class"), el.hasAttribute("classname")], ["a", false]);
});

// ── diff에 잘못된 VNode ──

const GOOD = root(h("p", { title: "t" }, "a"), h("p", null, "b"));
const INVALID = {
  null: null, 숫자: 5, 불리언: true, 배열: [], "빈 객체": {}, "type 빈 문자열": { type: "", props: {}, children: [] },
  "type 숫자": { type: 1, props: {}, children: [] }, 함수: () => {}, "props 가 문자열": { type: "p", props: "x", children: [] },
  "props 가 배열": { type: "p", props: ["x"], children: [] }, "props 가 Date": { type: "p", props: new Date(), children: [] },
  "props 값이 객체": { type: "p", props: { a: {} }, children: [] }, "props 값이 함수": { type: "p", props: { onclick: () => {} }, children: [] },
  "props 값이 Symbol": { type: "p", props: { a: Symbol("x") }, children: [] }, "children 이 문자열": { type: "p", props: {}, children: "abc" },
  "children 이 객체": { type: "p", props: {}, children: { 0: "a" } },
};
for (const [name, bad] of Object.entries(INVALID)) {
  test(`[잘못된 VNode] ${name} → 이전 · 새 · 자식 어느 자리에 있어도 TypeError, 메시지에 diff와 위치`, () => {
    for (const [side, call, where] of [
      ["새", () => diff(GOOD, bad), "diff 새 VDOM"],
      ["이전", () => diff(bad, GOOD), "diff 이전 VDOM"],
      ["자식", () => diff(GOOD, { type: "div", props: {}, children: [h("p", null, "a"), bad] }), "children[1]"],
    ]) {
      const e = assertThrows(call, `${side} 자리`);
      assert(e.message.includes(where), `${side}: 메시지에 "${where}"가 없음 — ${e.message}`);
    }
  });
}
test("[잘못된 VNode] undefined: 자식 자리면 TypeError, 맨 위(이전 · 새)는 '노드 없음'이라 CREATE / REMOVE (내 규약)", () => {
  assertThrows(() => diff(GOOD, { type: "div", props: {}, children: [undefined] }), "자식 undefined");
  assertEqual(diff(undefined, GOOD).type, "CREATE");
  assertEqual(diff(GOOD, undefined).type, "REMOVE");
});
test("[잘못된 VNode] 자식 안의 null · 숫자 · 불리언 · {} → TypeError, 메시지에 위치", () => {
  for (const child of [null, 3, false, {}]) {
    const e = assertThrows(() => diff(GOOD, root(h("ul", null, { type: "li", props: {}, children: ["ok", child] }))));
    assert(e.message.includes("children[0].children[1]"), `위치가 있어야 함: ${e.message}`);
  }
});
test("[잘못된 VNode] 올바른 입력은 통과: props 없음 · null, children 없음 · null → 변경 없음(null)", () => {
  assertEqual(diff({ type: "p" }, { type: "p", props: null, children: null }), null);
});

// ── patch가 거부하는 입력 ──

test("[patch 거부] 범위 밖 자식 · 손자, 텍스트 노드 아래로 내려감 → TypeError, DOM 그대로", () => {
  const go = (count, map) => at(count, map);
  const below = (patch1) => ({ type: "UPDATE", props: [], children: [patch1] });
  for (const tree of [
    go(10, { 9: { type: "REMOVE" } }),
    go(1, { 0: { type: "UPDATE", props: [], children: [null, null, null, null, null, { type: "REMOVE" }] } }),
    go(1, { 0: below(below({ type: "TEXT", text: "x" })) }),
  ]) {
    const box = abc();
    assertThrows(() => patch(box, tree));
    assertEqual(texts(box), ["a", "b", "c"]);
  }
});
test("[patch 거부] CREATE · REPLACE의 새 노드가 잘못됨({} · 태그 이름 공백 · 안쪽 자식 잘못) → TypeError, DOM 그대로", () => {
  for (const node of [{}, { type: "a b", props: {}, children: [] }, { type: "li", props: {}, children: [{}] }]) {
    const box = abc();
    assertThrows(() => patch(box, at(3, { 0: { type: "UPDATE", props: [], children: [{ type: "TEXT", text: "A" }] }, 2: { type: "REPLACE", node } })));
    assertThrows(() => patch(box, at(4, { 0: { type: "UPDATE", props: [], children: [{ type: "TEXT", text: "A" }] }, 3: { type: "CREATE", node } })));
    assertEqual(texts(box), ["a", "b", "c"]);
  }
});
test("[patch 거부] 쓸 수 없는 속성 이름(공백)은 그 속성만 건너뛰고 경고, 나머지는 적용", () => {
  const box = abc();
  const warn = console.warn;
  const warned = [];
  console.warn = (m) => warned.push(m);
  try {
    patch(box, at(1, { 0: { type: "UPDATE", props: [{ name: "a b", value: "1" }, { name: "id", value: "ok" }], children: [] } }));
  } finally {
    console.warn = warn;
  }
  assertEqual([box.firstChild.firstChild.id, warned.length], ["ok", 1]);
});

// ── 랜덤 ──

test("[#256] 빈 트리 비교 (빈 ↔ 빈 = null, 빈 ↔ 무언가 = 새로 그린 것과 같음)", () => {
  assertEqual(diff(root(), root()), null);
  roundTrip(root(), root(h("p", null, "x"), "y"));
  roundTrip(root(h("p", null, "x"), "y"), root());
});

// ── Phase 2: FunctionComponent · Hook (내 API로) ──

function mountTest(App, props) {
  const box = document.createElement("div");
  const comp = new FunctionComponent(App, box, props).mount();
  return { comp, box };
}

test("[P2] 만들 때 hooks는 빈 배열, mount()는 자기 자신, 렌더링 1번", () => {
  let renders = 0;
  const box = document.createElement("div");
  const comp = new FunctionComponent(() => (renders++, h("p", null, "hi")), box);
  assertEqual(comp.hooks, []);
  assert(comp.mount() === comp, "mount는 자기 자신");
  assertEqual([renders, box.innerHTML], [1, "<p>hi</p>"]);
});
test("[P2] 이미 mount했으면 mount() 오류, mount 전 update()는 아무것도 안 함 (내 규약)", () => {
  const box = document.createElement("div");
  const comp = new FunctionComponent(() => h("p"), box);
  comp.update();
  assertEqual(box.innerHTML, "");
  comp.mount();
  let threw = false;
  try {
    comp.mount();
  } catch {
    threw = true;
  }
  assert(threw, "두 번째 mount는 오류");
});
test("[P2] update는 바뀐 텍스트만 고치고 나머지 노드는 재사용, 바뀐 게 없으면 DOM 변경 0", async () => {
  let set;
  const { box, comp } = mountTest(() => {
    const [n, s] = useState(0);
    set = s;
    return h("div", null, h("h1", null, "제목"), h("p", null, String(n)));
  });
  const [h1, text] = [box.querySelector("h1"), box.querySelector("p").firstChild];
  set(1);
  await tick();
  assertEqual([box.querySelector("h1") === h1, box.querySelector("p").firstChild === text, text.data], [true, true, "1"]);
  const mo = new MutationObserver(() => {});
  mo.observe(box, { subtree: true, childList: true, attributes: true, characterData: true });
  comp.update();
  assertEqual(mo.takeRecords().length, 0, "변경 없음");
  mo.disconnect();
});
test("[P2] 여러 루트는 서로 독립 (hooks · 렌더링 횟수 따로)", async () => {
  const renders = [0, 0];
  const sets = [];
  const make = (i) =>
    mountTest(() => {
      renders[i]++;
      const [n, s] = useState(0);
      sets[i] = s;
      return h("p", null, String(n));
    });
  const [a, b] = [make(0), make(1)];
  sets[0](5);
  await tick();
  assertEqual([a.box.textContent, b.box.textContent, renders], ["5", "0", [2, 1]]);
});
test("[P2] 렌더링 도중 다른 루트를 렌더링해도, 끝나면 바깥 컴포넌트의 Hook이 계속 동작 (내 규약: 오류 대신 복원)", () => {
  const { box } = mountTest(() => {
    const [a] = useState("바깥");
    mountTest(() => h("i", null, useState("안쪽")[0]));
    const [b] = useState("계속");
    return h("p", null, a + b);
  });
  assertEqual(box.textContent, "바깥계속");
});
test("[P2] 자식 컴포넌트: h(Child, props) → props를 받아 VNode, props 없으면 { children: [] }", () => {
  let seen;
  const Hello = (props) => ((seen = props), h("b", null, "Hello"));
  const { box } = mountTest(() => h("div", null, h(Hello)));
  assertEqual([box.textContent, seen], ["Hello", { children: [] }]);
});
test("[P2] 자식 타입이 함수도 문자열도 아니면 TypeError", () => {
  assertThrows(() => mountTest(() => h("div", null, h(5))));
});
test("[P2] 자식 안에서 Hook → 오류, 컨테이너 그대로 (Hook은 루트에서만)", () => {
  const box = document.createElement("div");
  box.innerHTML = "<i>원래</i>";
  const Bad = () => (useState(0), h("b"));
  let threw = false;
  try {
    new FunctionComponent(() => h("div", null, h(Bad)), box).mount();
  } catch {
    threw = true;
  }
  assertEqual([threw, box.innerHTML], [true, "<i>원래</i>"]);
});
test("[P2] Lifting State Up: 자식이 부모의 콜백을 불러 부모 상태를 바꿈", async () => {
  const Button = ({ onPick }) => h("button", { onClick: () => onPick(2) }, "pick");
  const { box } = mountTest(() => {
    const [n, set] = useState(0);
    return h("div", null, h("span", null, String(n)), h(Button, { onPick: set }));
  });
  box.querySelector("button").click();
  await tick();
  assertEqual(box.querySelector("span").textContent, "2");
});
test("[P2 이벤트] 핸들러는 항상 최신 렌더의 함수 (최신 상태를 봄)", async () => {
  const seen = [];
  let set;
  const { box } = mountTest(() => {
    const [n, s] = useState(0);
    set = s;
    return h("button", { onClick: () => seen.push(n) }, "x");
  });
  box.querySelector("button").click();
  set(7);
  await tick();
  box.querySelector("button").click();
  assertEqual(seen, [0, 7]);
});
test("[P2 이벤트] 매 렌더 새 함수여도 DOM 변경 없음, 리스너도 늘지 않음 (요소마다 이벤트 종류당 1개)", async () => {
  let set;
  const box = document.createElement("div");
  const added = [];
  const orig = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, ...rest) {
    added.push(type);
    return orig.call(this, type, ...rest);
  };
  try {
    new FunctionComponent(() => {
      const [n, s] = useState(0);
      set = s;
      return h("div", null, h("button", { onClick: () => n }), h("input", { onInput: () => n }));
    }, box).mount();
    const mo = new MutationObserver(() => {});
    mo.observe(box, { subtree: true, childList: true, attributes: true });
    for (let i = 1; i <= 3; i++) {
      set(i);
      await tick();
    }
    assertEqual([mo.takeRecords().length, added.sort()], [0, ["click", "input"]]);
    mo.disconnect();
  } finally {
    EventTarget.prototype.addEventListener = orig;
  }
});
test("[P2 이벤트] onClick이 null · undefined · false면 리스너도 속성도 없음", () => {
  const { box } = mountTest(() => h("div", null, h("a", { onClick: null }), h("b", { onClick: undefined }), h("i", { onClick: false })));
  for (const el of box.firstChild.children) {
    assertEqual(el.attributes.length, 0);
    el.click(); // 오류 없음
  }
});
test("[P2 이벤트] on으로 시작해도 다음 글자가 소문자면(oncology) 일반 속성", () => {
  const { box } = mountTest(() => h("p", { oncology: "yes" }));
  assertEqual(box.firstChild.getAttribute("oncology"), "yes");
});
test("[P2 이벤트] 이벤트가 일어난 요소가 사라진 뒤 다시 눌러도 오류 없음", async () => {
  let setShow;
  const { box } = mountTest(() => {
    const [show, set] = useState(true);
    setShow = set;
    return show ? h("button", { onClick: () => setShow(false) }, "x") : h("p", null, "사라짐");
  });
  const btn = box.querySelector("button");
  btn.click();
  await tick();
  btn.click(); // 떨어져 나간 버튼
  await tick();
  assertEqual(box.textContent, "사라짐");
});
test("[P2 unmount] effect 정리, 컨테이너 비움, 이후 setState 무시, 두 번 불러도 정리는 한 번, 다시 mount 가능 (내 규약)", async () => {
  const log = [];
  let set;
  const { box, comp } = mountTest(() => {
    const [n, s] = useState(0);
    set = s;
    useEffect(() => () => log.push("cleanup"), []);
    return h("p", null, String(n));
  });
  comp.unmount();
  comp.unmount();
  set(1);
  await tick();
  assertEqual([log, box.innerHTML], [["cleanup"], ""]);
  comp.mount();
  assertEqual(box.innerHTML, "<p>0</p>");
});
test("[P2 useState] 초깃값으로 시작, hooks 배열에 저장", () => {
  const { comp } = mountTest(() => h("p", null, String(useState(3)[0])));
  assertEqual(comp.hooks[0].state, 3);
});
test("[P2 useState] 배칭: setState 3번 → 렌더링 1번, 함수형 +3 / 값 3번은 +1 (React와 같음)", async () => {
  let renders = 0;
  let set;
  const { box } = mountTest(() => {
    renders++;
    const [n, s] = useState(0);
    set = s;
    return h("p", null, String(n));
  });
  renders = 0;
  set((c) => c + 1);
  set((c) => c + 1);
  set((c) => c + 1);
  await tick();
  assertEqual([box.textContent, renders], ["3", 1]);
  set(4);
  set(4);
  set(4);
  await tick();
  assertEqual(box.textContent, "4");
});
test("[P2 useState] 서로 다른 상태 여러 개를 바꿔도 렌더링 1번", async () => {
  let renders = 0;
  let sa, sb;
  const { box } = mountTest(() => {
    renders++;
    const [a, x] = useState("a");
    const [b, y] = useState("b");
    sa = x;
    sb = y;
    return h("p", null, a + b);
  });
  renders = 0;
  sa("A");
  sb("B");
  await tick();
  assertEqual([box.textContent, renders], ["AB", 1]);
});
test("[P2 useState] 비동기(setTimeout)에서 setState해도 반영", async () => {
  let set;
  const { box } = mountTest(() => {
    const [v, s] = useState("전");
    set = s;
    return h("p", null, v);
  });
  await new Promise((r) => setTimeout(() => (set("후"), r()), 0));
  await tick();
  assertEqual(box.textContent, "후");
});
test("[P2 useState] 렌더링 중 setState: 값이 수렴하면 허용 (React와 같음), 끝없으면 50번에서 멈춤 (내 규약)", async () => {
  const { box } = mountTest(() => {
    const [n, s] = useState(0);
    if (n < 3) s(n + 1);
    return h("p", null, String(n));
  });
  await tick();
  await tick();
  assertEqual(box.textContent, "3");
  const errors = [];
  const onError = (e) => (errors.push(e.message), e.preventDefault());
  window.addEventListener("error", onError);
  mountTest(() => {
    const [n, s] = useState(0);
    s(n + 1);
    return h("p", null, String(n));
  });
  await tick();
  await tick();
  window.removeEventListener("error", onError);
  assert(errors.some((m) => m.includes("연달아")), `무한 렌더링 에러가 나야 함: ${errors}`);
});
test("[P2 useEffect] 다시 실행 전 cleanup: 바뀐 effect의 cleanup을 모두 먼저, 그다음 effect (React 순서)", async () => {
  const log = [];
  let set;
  mountTest(() => {
    const [v, s] = useState("a");
    set = s;
    useEffect(() => (log.push(`effect1 ${v}`), () => log.push(`cleanup1 ${v}`)), [v]);
    useEffect(() => (log.push(`effect2 ${v}`), () => log.push(`cleanup2 ${v}`)), [v]);
    return h("p");
  });
  set("b");
  await tick();
  assertEqual(log, ["effect1 a", "effect2 a", "cleanup1 a", "cleanup2 a", "effect1 b", "effect2 b"]);
});
test("[P2 useEffect] effect가 함수가 아닌 값을 돌려주면 cleanup으로 쓰지 않음", async () => {
  let set;
  mountTest(() => {
    const [n, s] = useState(0);
    set = s;
    useEffect(() => 42, [n]);
    return h("p");
  });
  set(1);
  await tick(); // "42 is not a function" 같은 오류 없이 지나가야 함
});
test("[P2 useEffect] effect 안에서 setState → 렌더링 1번 더 (deps로 멈춤)", async () => {
  let renders = 0;
  const { box } = mountTest(() => {
    renders++;
    const [n, s] = useState(0);
    useEffect(() => {
      if (n < 3) s(n + 1);
    }, [n]);
    return h("p", null, String(n));
  });
  await tick();
  assertEqual([box.textContent, renders], ["3", 4]);
});
test("[P2 useEffect] effect 하나가 오류를 내도 다음 effect는 실행되고, 오류는 알림 (내 규약: 다 실행한 뒤 첫 오류를 던짐)", () => {
  const log = [];
  let threw = null;
  try {
    mountTest(() => {
      useEffect(() => {
        throw new Error("effect 오류");
      }, []);
      useEffect(() => log.push("다음 effect"), []);
      return h("p");
    });
  } catch (e) {
    threw = e.message;
  }
  assertEqual([log, threw], [["다음 effect"], "effect 오류"]);
});
test("[P2 useMemo] factory가 undefined를 돌려줘도 deps가 같으면 다시 계산하지 않음", async () => {
  let calls = 0;
  let set;
  mountTest(() => {
    const [n, s] = useState(0);
    set = s;
    useMemo(() => (calls++, undefined), []);
    return h("p", null, String(n));
  });
  set(1);
  await tick();
  assertEqual(calls, 1);
});

// ── 실행 ──
const results = [];
for (const { name, fn } of tests) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, message: e.message });
  }
}
const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const passed = results.filter((r) => r.ok).length;
document.getElementById("results").innerHTML =
  `<h2>${passed} / ${results.length} passed</h2>` +
  results.map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`).join("");
console.table(results);
