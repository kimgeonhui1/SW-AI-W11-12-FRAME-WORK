// [tests/cases-invalid.test.js] 잘못된 입력 — diff 의 VNode, patch 의 Patch 객체 · 경로 · 종류별 필드
//
// 원칙
//   - diff  : 두 트리 중 하나라도 잘못되면 TypeError (브라우저마다 다른 기본 오류 문구가 아니라 우리 문구)
//   - patch : 입력이 하나라도 잘못되면 TypeError, 실제 DOM 은 전혀 바뀌지 않는다 (전부 적용되거나 전혀 안 되거나)
// "DOM 이 전혀 바뀌지 않음" 은 HTML 문자열뿐 아니라 노드 객체가 그대로인지(같은 참조)까지 확인한다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, createElement, containerToVdom } from "../src/core/vdom.js";
import { diff, PATCH } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import { root, render, assertThrows, captureConsole, openIndex, deepTree } from "./helpers.js";

// ── 공통 도구 ──────────────────────────────────────────────────────────

/** 기본 실제 영역: <p title="t">a</p><p>b</p><ul><li>x</li></ul> */
const BASE = () => root(h("p", { title: "t" }, "a"), h("p", null, "b"), h("ul", null, h("li", null, "x")));

/** DOM 상태를 찍어 둔다: HTML 문자열 + 모든 노드 참조 */
function snapshot(box) {
  const nodes = [];
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_ALL);
  for (let n = walker.currentNode; n; n = walker.nextNode()) nodes.push(n);
  return { html: box.outerHTML, nodes, parent: box.parentNode };
}

/** 찍어 둔 상태와 똑같은지 (글자 · 노드 참조 · 컨테이너 위치) */
function assertUnchanged(box, before, message = "") {
  const after = snapshot(box);
  assertEqual(after.html, before.html, `${message} HTML 이 바뀜`);
  assertEqual(after.nodes.length, before.nodes.length, `${message} 노드 수가 바뀜`);
  assert(after.nodes.every((n, i) => n === before.nodes[i]), `${message} 노드가 다른 객체로 바뀜`);
  assert(after.parent === before.parent, `${message} 컨테이너가 떨어져 나감`);
}

/** 컨테이너를 부모 안에 넣어 그린다 (컨테이너가 떨어져 나가는지도 볼 수 있게) */
function mount(vroot = BASE()) {
  const wrapper = document.createElement("section");
  const box = render(vroot);
  wrapper.append(box);
  return box;
}

/**
 * 정상 패치(TEXT · PROPS · CREATE · REMOVE · REPLACE 하나씩) 뒤에 잘못된 패치를 붙여 patch 를 부른다.
 * → TypeError 이고 DOM 이 전혀 바뀌지 않아야 한다. (앞의 정상 패치도 적용되면 안 됨)
 */
function assertRejectedAtomically(badPatch, label = JSON.stringify(badPatch)) {
  const validPrefix = [
    { type: PATCH.TEXT, path: [0, 0], value: "A" },
    { type: PATCH.PROPS, path: [0], set: { id: "new" }, remove: ["title"] },
    { type: PATCH.CREATE, path: [2], index: 1, node: h("li", null, "y") },
    { type: PATCH.REMOVE, path: [1] },
    { type: PATCH.REPLACE, path: [2, 0], node: h("li", null, "z") },
  ];
  for (const where of ["끝", "처음"]) {
    const box = mount();
    const before = snapshot(box);
    const list = where === "끝" ? [...validPrefix, badPatch] : [badPatch, ...validPrefix];
    const err = assertThrows(() => patch(box, list), TypeError, `TypeError 여야 함 (${where}): ${label}`);
    assert(err.message.startsWith("[patch]"), `우리 문구여야 함: ${err.message}`);
    assertUnchanged(box, before, `${label} (${where}):`);
  }
}

/** 순환 VNode */
function cyclic() {
  const node = { type: "b", props: {}, children: [] };
  node.children.push({ type: "i", props: {}, children: [node] });
  return node;
}

// ── diff ───────────────────────────────────────────────────────────────

describe("diff 에 잘못된 VNode", () => {
  const good = BASE();
  const invalid = {
    "null": null,
    "undefined": undefined,
    "숫자": 5,
    "불리언": true,
    "배열": [],
    "빈 객체": {},
    "type 빈 문자열": { type: "", props: {}, children: [] },
    "type 숫자": { type: 1, props: {}, children: [] },
    "함수": () => {},
    "props 가 문자열": { type: "p", props: "x", children: [] },
    "props 가 배열": { type: "p", props: ["x"], children: [] },
    "props 가 Date": { type: "p", props: new Date(), children: [] },
    "props 값이 객체": { type: "p", props: { a: {} }, children: [] },
    "props 값이 함수": { type: "p", props: { onclick: () => {} }, children: [] },
    "props 값이 Symbol": { type: "p", props: { a: Symbol("x") }, children: [] },
    "children 이 문자열": { type: "p", props: {}, children: "abc" },
    "children 이 객체": { type: "p", props: {}, children: { 0: "a" } },
    "순환 참조": cyclic(),
  };

  for (const [name, bad] of Object.entries(invalid)) {
    test(`${name} → 이전 · 새 · 자식 어느 자리에 있어도 TypeError`, () => {
      for (const [side, call] of [
        ["새", () => diff(good, bad)],
        ["이전", () => diff(bad, good)],
        // root()/h() 는 null · 숫자 · 배열을 정리해 버리므로 자식 배열을 직접 만든다
        ["자식", () => diff(good, { type: "div", props: {}, children: [h("p", { title: "t" }, "a"), bad] })],
      ]) {
        const err = assertThrows(call, TypeError, `${side} 자리`);
        assert(err.message.startsWith("[diff"), `${side}: 우리 문구여야 함 — ${err.message}`);
      }
    });
  }

  test("자식 배열 안의 null · 숫자 · 불리언 · {} → TypeError, 메시지에 위치", () => {
    for (const child of [null, undefined, 3, false, {}]) {
      const err = assertThrows(() => diff(good, root(h("ul", null, { type: "li", props: {}, children: ["ok", child] }))), TypeError);
      assert(err.message.includes("children[0].children[1]"), `위치가 있어야 함: ${err.message}`);
    }
  });

  test("REPLACE 로 통째로 넘어갈 하위 트리 안쪽도 검사 (예전에는 그대로 패치에 실림)", () => {
    const bad = { type: "section", props: {}, children: [{ type: "b", props: {}, children: [{}] }] };
    assertThrows(() => diff(root(h("p")), root(bad)), TypeError);
  });

  test("CREATE 로 넘어갈 새 자식 안쪽도 검사", () => {
    const bad = { type: "p", props: { a: [] }, children: [] };
    assertThrows(() => diff(root(), root(h("div", null, bad))), TypeError);
  });

  test("깊이 10,000 아래의 잘못된 노드도 스택 오류 없이 TypeError", () => {
    const tree = deepTree(10000, "leaf");
    let node = tree;
    while (typeof node.children[0] === "object") node = node.children[0];
    node.children.push(null);
    assertThrows(() => diff(root(tree), root(deepTree(10000, "leaf"))), TypeError);
  });

  test("올바른 입력은 그대로 통과: props 없음 · null, children 없음 · null, 숫자 · 불리언 · null 속성값", () => {
    const loose = { type: "p" };
    assertEqual(diff(root(loose), root({ type: "p", props: null, children: null })), []);
    const patches = diff(root(h("input")), root(h("input", { tabindex: 3, disabled: true, hidden: false, title: null })));
    assertEqual(patches.length, 1);
    assertEqual(diff("a", "b"), [{ type: PATCH.TEXT, path: [], value: "b" }]);
  });

  test("공유 객체는 순환이 아니므로 통과", () => {
    const shared = h("i", null, "s");
    assertEqual(diff(root(shared, shared), root(shared, shared)), []);
  });
});

// ── patch: 패치 객체 자체가 잘못됨 ─────────────────────────────────────

describe("patch 에 잘못된 Patch 객체", () => {
  test("patches 가 배열이 아님 → TypeError, DOM 그대로", () => {
    for (const bad of [null, undefined, {}, "TEXT", 1, { length: 0 }]) {
      const box = mount();
      const before = snapshot(box);
      assertThrows(() => patch(box, bad), TypeError);
      assertUnchanged(box, before);
    }
  });

  test("container 가 DOM 요소가 아님 → TypeError", () => {
    for (const bad of [null, undefined, {}, "div", document.createTextNode("x")]) {
      assertThrows(() => patch(bad, []), TypeError);
    }
  });

  test("빈 패치 목록은 아무것도 하지 않음", () => {
    const box = mount();
    const before = snapshot(box);
    assertEqual(patch(box, []), []);
    assertUnchanged(box, before);
  });

  const badObjects = {
    "null": null,
    "undefined": undefined,
    "문자열": "TEXT",
    "숫자": 0,
    "type 없음": { path: [0] },
    "알 수 없는 type": { type: "MOVE", path: [0] },
    "type 소문자": { type: "text", path: [0, 0], value: "x" },
    "path 없음": { type: PATCH.REMOVE },
    "path 가 문자열": { type: PATCH.REMOVE, path: "0" },
    "path 에 음수": { type: PATCH.REMOVE, path: [-1] },
    "path 에 소수": { type: PATCH.REMOVE, path: [0.5] },
    "path 에 NaN": { type: PATCH.REMOVE, path: [NaN] },
    "path 에 문자열": { type: PATCH.REMOVE, path: ["0"] },
  };
  for (const [name, bad] of Object.entries(badObjects)) {
    test(`${name} → TypeError, 앞뒤의 정상 패치도 적용 안 됨`, () => assertRejectedAtomically(bad, name));
  }

  test("배열의 빈 칸(hole) → TypeError, DOM 그대로", () => {
    const box = mount();
    const before = snapshot(box);
    const list = [{ type: PATCH.TEXT, path: [0, 0], value: "A" }];
    list[2] = { type: PATCH.REMOVE, path: [1] }; // list[1] 은 빈 칸
    assertThrows(() => patch(box, list), TypeError);
    assertUnchanged(box, before);
  });
});

// ── patch: 존재하지 않는 경로 ──────────────────────────────────────────

describe("patch 에 존재하지 않는 경로", () => {
  const missing = {
    "범위 밖 자식": [9],
    "범위 밖 손자": [0, 5],
    "텍스트 노드 아래로 내려감": [0, 0, 0],
    "아주 깊은 경로": Array(50).fill(0),
  };
  for (const [name, path] of Object.entries(missing)) {
    test(`${name} ${JSON.stringify(path)} → 모든 종류에서 TypeError, DOM 그대로`, () => {
      for (const p of [
        { type: PATCH.TEXT, path, value: "x" },
        { type: PATCH.PROPS, path, set: { a: "1" }, remove: [] },
        { type: PATCH.CREATE, path, index: 0, node: "x" },
        { type: PATCH.REMOVE, path },
        { type: PATCH.REPLACE, path, node: "x" },
      ]) assertRejectedAtomically(p, `${p.type} ${JSON.stringify(path)}`);
    });
  }

  test("DOM 이 바깥에서 바뀌어 경로가 어긋나면 → TypeError, 바꾼 그대로 둠", () => {
    const old = BASE();
    const box = mount(old);
    box.lastChild.remove(); // 누군가 실제 영역을 직접 고침
    const before = snapshot(box);
    const patches = diff(old, root(h("p", { title: "t" }, "A"), h("p", null, "b"), h("ul", null, h("li", null, "X"))));
    assertThrows(() => patch(box, patches), TypeError);
    assertUnchanged(box, before);
  });

  test("경고(console.warn)로 넘어가지 않고 예외로 알림", () => {
    const box = mount();
    const { warns } = captureConsole(() => assertThrows(() => patch(box, [{ type: PATCH.REMOVE, path: [9] }]), TypeError));
    assertEqual(warns.length, 0);
  });
});

// ── patch: 종류별로 잘못된 패치 ────────────────────────────────────────

describe("잘못된 CREATE", () => {
  const cases = {
    "index 없음": { type: PATCH.CREATE, path: [2], node: "x" },
    "index 음수": { type: PATCH.CREATE, path: [2], index: -1, node: "x" },
    "index 소수": { type: PATCH.CREATE, path: [2], index: 1.5, node: "x" },
    "index 문자열": { type: PATCH.CREATE, path: [2], index: "1", node: "x" },
    "index 가 자식 수보다 작음 (중간 끼워 넣기는 지원 안 함)": { type: PATCH.CREATE, path: [2], index: 0, node: "x" },
    "index 가 자식 수보다 큼": { type: PATCH.CREATE, path: [2], index: 99, node: "x" },
    "node 없음": { type: PATCH.CREATE, path: [2], index: 1 },
    "node 가 숫자": { type: PATCH.CREATE, path: [2], index: 1, node: 5 },
    "node 가 null": { type: PATCH.CREATE, path: [2], index: 1, node: null },
    "node 가 {}": { type: PATCH.CREATE, path: [2], index: 1, node: {} },
    "node 안쪽 자식이 잘못됨": { type: PATCH.CREATE, path: [2], index: 1, node: { type: "li", props: {}, children: [{}] } },
    "node 의 속성값이 객체": { type: PATCH.CREATE, path: [2], index: 1, node: { type: "li", props: { a: {} }, children: [] } },
    "node 가 순환 참조": { type: PATCH.CREATE, path: [2], index: 1, node: cyclic() },
    "node 의 태그 이름에 공백": { type: PATCH.CREATE, path: [2], index: 1, node: h("a b") },
    "부모가 텍스트 노드": { type: PATCH.CREATE, path: [0, 0], index: 0, node: "x" },
  };
  for (const [name, p] of Object.entries(cases)) test(`${name} → TypeError, DOM 그대로`, () => assertRejectedAtomically(p, name));

  test("올바른 연속 CREATE (index 가 차례로 늘어남)는 그대로 동작", () => {
    const box = mount();
    patch(box, [1, 2].map((i) => ({ type: PATCH.CREATE, path: [2], index: i, node: h("li", null, String(i)) })));
    assertEqual([...box.querySelectorAll("li")].map((li) => li.textContent), ["x", "1", "2"]);
  });

  test("연속 CREATE 에서 index 를 건너뛰면 → TypeError, 앞의 CREATE 도 적용 안 됨", () => {
    const box = mount();
    const before = snapshot(box);
    assertThrows(() => patch(box, [1, 3].map((i) => ({ type: PATCH.CREATE, path: [2], index: i, node: "x" }))), TypeError);
    assertUnchanged(box, before);
  });
});

describe("잘못된 REMOVE", () => {
  test("컨테이너 자신(경로 []) → TypeError, 컨테이너가 떨어져 나가지 않음", () => assertRejectedAtomically({ type: PATCH.REMOVE, path: [] }, "REMOVE []"));
  test("없는 노드 → TypeError", () => assertRejectedAtomically({ type: PATCH.REMOVE, path: [7] }, "REMOVE [7]"));
});

describe("잘못된 REPLACE", () => {
  const cases = {
    "컨테이너 자신(경로 [])": { type: PATCH.REPLACE, path: [], node: h("div") },
    "node 없음": { type: PATCH.REPLACE, path: [1] },
    "node 가 숫자": { type: PATCH.REPLACE, path: [1], node: 5 },
    "node 가 배열": { type: PATCH.REPLACE, path: [1], node: [h("p")] },
    "node 의 type 이 빈 문자열": { type: PATCH.REPLACE, path: [1], node: { type: "" } },
    "node 안쪽 자식이 잘못됨": { type: PATCH.REPLACE, path: [1], node: { type: "p", props: {}, children: [null] } },
    "node 의 children 이 문자열": { type: PATCH.REPLACE, path: [1], node: { type: "p", props: {}, children: "abc" } },
    "node 가 순환 참조": { type: PATCH.REPLACE, path: [1], node: cyclic() },
    "node 의 태그 이름에 공백": { type: PATCH.REPLACE, path: [1], node: h("a b") },
  };
  for (const [name, p] of Object.entries(cases)) test(`${name} → TypeError, DOM 그대로`, () => assertRejectedAtomically(p, name));
});

describe("잘못된 TEXT", () => {
  const cases = {
    "value 없음": { type: PATCH.TEXT, path: [0, 0] },
    "value 가 숫자": { type: PATCH.TEXT, path: [0, 0], value: 1 },
    "value 가 null": { type: PATCH.TEXT, path: [0, 0], value: null },
    "대상이 요소 (예전에는 조용히 무시됨)": { type: PATCH.TEXT, path: [1], value: "x" },
    "대상이 컨테이너(경로 [])": { type: PATCH.TEXT, path: [], value: "x" },
  };
  for (const [name, p] of Object.entries(cases)) test(`${name} → TypeError, DOM 그대로`, () => assertRejectedAtomically(p, name));
});

describe("잘못된 PROPS", () => {
  const cases = {
    "set 없음": { type: PATCH.PROPS, path: [1], remove: [] },
    "set 이 null": { type: PATCH.PROPS, path: [1], set: null, remove: [] },
    "set 이 배열": { type: PATCH.PROPS, path: [1], set: ["a"], remove: [] },
    "set 값이 객체 (예전에는 \"[object Object]\" 로 설정됨)": { type: PATCH.PROPS, path: [1], set: { a: { x: 1 } }, remove: [] },
    "set 값이 함수": { type: PATCH.PROPS, path: [1], set: { onclick: () => {} }, remove: [] },
    "set 값이 Symbol": { type: PATCH.PROPS, path: [1], set: { a: Symbol("x") }, remove: [] },
    "remove 없음": { type: PATCH.PROPS, path: [1], set: {} },
    "remove 가 문자열": { type: PATCH.PROPS, path: [1], set: {}, remove: "title" },
    "remove 에 숫자": { type: PATCH.PROPS, path: [1], set: {}, remove: [1] },
    "대상이 텍스트 노드": { type: PATCH.PROPS, path: [0, 0], set: { a: "1" }, remove: [] },
  };
  for (const [name, p] of Object.entries(cases)) test(`${name} → TypeError, DOM 그대로`, () => assertRejectedAtomically(p, name));

  test("쓸 수 없는 속성 이름(공백)은 예전처럼 그 속성만 건너뛰고 경고 (#074 와 같은 동작)", () => {
    const box = mount();
    const { warns } = captureConsole(() => patch(box, [{ type: PATCH.PROPS, path: [1], set: { "a b": "1", id: "ok" }, remove: [] }]));
    assertEqual(warns.length, 1);
    assertEqual(box.children[1].id, "ok");
  });

  test("컨테이너(경로 [])의 PROPS 는 예전처럼 허용 (#136)", () => {
    const box = mount();
    patch(box, [{ type: PATCH.PROPS, path: [], set: { "data-x": "1" }, remove: [] }]);
    assertEqual(box.dataset.x, "1");
  });
});

// ── 정상 입력은 그대로 ─────────────────────────────────────────────────

describe("입력 검사를 넣은 뒤에도 정상 패치는 그대로", () => {
  test("다섯 종류가 섞인 정상 패치 → 모두 적용, 결과가 새 VDOM 과 같음", () => {
    const next = root(h("p", { id: "new" }, "A"), h("ul", null, h("li", null, "z"), h("li", null, "y")));
    const old = BASE();
    const box = mount(old);
    patch(box, diff(old, next));
    assertEqual(containerToVdom(box), next);
  });
});

// ── 페이지: 입력 오류가 나면 실제 영역 · History 가 그대로 ──────────────

describe("페이지에서 patch 가 실패할 때", () => {
  test("실제 영역을 바깥에서 고친 뒤 Patch → 실패 안내, 실제 영역 · History 그대로", async () => {
    const page = await openIndex();
    const { $, win } = page;
    $("real-area").replaceChildren(); // 실제 영역을 바깥에서 비움 → History 의 경로가 맞지 않음
    const realBefore = $("real-area").innerHTML;
    $("test-source").value = $("test-source").value.replace("</ul>", "<li>추가</li></ul>");
    $("test-source").dispatchEvent(new win.Event("input"));
    const quiet = win.console.error;
    win.console.error = () => {}; // 의도된 오류 로그는 숨김
    $("patch-btn").click();
    win.console.error = quiet;
    assert($("status").textContent.includes("Patch 실패"), $("status").textContent);
    assertEqual($("real-area").innerHTML, realBefore);
    assertEqual($("history-list").children.length, 1, "History 에 저장되지 않아야 함");
    page.frame.remove();
  });

  test("뒤로가기에서 patch 가 실패하면 History 위치도 원래대로", async () => {
    const page = await openIndex();
    const { $, win } = page;
    $("test-source").value = $("test-source").value.replace("</ul>", "<li>추가</li></ul>");
    $("test-source").dispatchEvent(new win.Event("input"));
    $("patch-btn").click();
    assertEqual($("position-label").textContent, "현재 위치: 2 / 2");
    $("real-area").replaceChildren();
    const quiet = win.console.error;
    win.console.error = () => {};
    $("undo-btn").click();
    win.console.error = quiet;
    assert($("status").textContent.includes("Patch 실패"), $("status").textContent);
    assertEqual($("position-label").textContent, "현재 위치: 2 / 2");
    page.frame.remove();
  });
});
