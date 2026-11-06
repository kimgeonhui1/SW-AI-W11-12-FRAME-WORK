// [tests/cases-deep.test.js] 깊은 VDOM 안정성 — 깊이 100 · 1,000 · 5,000 · 10,000
//
// 재귀로 짠 함수는 트리 깊이만큼 호출이 쌓여, 순환이 없는 정상 트리도 깊이 약 5,000 단계에서
// RangeError(Chrome) / InternalError(Firefox) 로 멈췄다. (createElement · domToVdom · diff · toHtml ·
// History 의 structuredClone · runner 의 deepEqual) → 모두 명시적 스택으로 바꿨다.
//
// 실행 시간 · 메모리를 위해
//   - 깊이마다 트리를 한 번씩만 만들어 여러 테스트가 같이 쓴다.
//   - 비교는 재귀가 없는 assertSameTree (helpers.js) 로 한다.
//   - 들여쓰기 있는 toHtml 출력은 깊이 d 에서 크기가 약 2·d² 글자라 (깊이 10,000 이면 약 2억 글자)
//     들여쓰기 형식은 1,000 까지만 글자 그대로 확인하고, 그보다 깊은 트리는 들여쓰기가 없는 모양으로 확인한다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { createElement, containerToVdom } from "../src/core/vdom.js";
import { diff, PATCH } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import * as history from "../src/phase1/history.js";
import { toHtml } from "../src/phase1/main.js";
import { root, render, deepTree, assertThrows, assertSameTree } from "./helpers.js";

const DEPTHS = [100, 1000, 5000, 10000];

/** 깊이마다 한 번만 만드는 트리 */
const cache = new Map();
function treesOf(depth) {
  if (!cache.has(depth)) {
    cache.set(depth, {
      a: root(deepTree(depth, "a")), // 맨 아래 텍스트 "a"
      b: root(deepTree(depth, "b")), // 맨 아래 텍스트만 "b" 로 다름
    });
  }
  return cache.get(depth);
}

/** DOM 을 반복문으로 따라 내려가 깊이와 맨 아래 텍스트를 잰다 */
function measureDom(box) {
  let node = box;
  let depth = 0;
  while (node.firstChild && node.firstChild.nodeType === 1) {
    node = node.firstChild;
    depth++;
  }
  return { depth, leaf: node.textContent };
}

/** 모든 단계에 텍스트가 섞인 사슬: <div>x<div>x…leaf…</div></div> (toHtml 이 들여쓰기를 넣지 않는 모양) */
function mixedChain(depth) {
  let node = "leaf";
  for (let i = 0; i < depth; i++) node = { type: "div", props: {}, children: ["x", node] };
  return node;
}

/** 요소만 이어진 사슬의 toHtml 기대값 (main.js 의 들여쓰기 규칙을 반복문으로 직접 계산) */
function expectedIndentedHtml(depth) {
  const lines = [];
  for (let k = 0; k < depth - 1; k++) lines.push("  ".repeat(k) + "<div>");
  lines.push("  ".repeat(depth - 1) + "<div>leaf</div>");
  for (let k = depth - 2; k >= 0; k--) lines.push("  ".repeat(k) + "</div>");
  return lines.join("\n");
}

describe("깊은 VDOM 안정성", () => {
  for (const depth of DEPTHS) {
    test(`깊이 ${depth}: createElement 로 DOM 생성`, () => {
      const box = render(treesOf(depth).a);
      assertEqual(measureDom(box), { depth, leaf: "a" });
    });

    test(`깊이 ${depth}: DOM → VDOM (containerToVdom) 왕복`, () => {
      const { a } = treesOf(depth);
      assertSameTree(containerToVdom(render(a)), a);
    });

    test(`깊이 ${depth}: diff — 같은 트리는 패치 없음, 맨 아래 텍스트만 다르면 TEXT 하나`, () => {
      const { a, b } = treesOf(depth);
      assertEqual(diff(a, a).length, 0);
      const patches = diff(a, b);
      assertEqual(patches.length, 1);
      assertEqual(patches[0].type, PATCH.TEXT);
      assertEqual(patches[0].value, "b");
      // 경로 = 루트에서 맨 아래 텍스트까지: 요소 depth 개 + 텍스트 1개, 모두 첫째 자식(0)
      assertEqual(patches[0].path.length, depth + 1);
      assert(patches[0].path.every((i) => i === 0), "경로가 모두 0 이어야 함");
    });

    test(`깊이 ${depth}: patch — 경로를 따라 맨 아래 텍스트만 바꿈`, () => {
      const { a, b } = treesOf(depth);
      const box = render(a);
      const before = box.firstChild;
      const touched = patch(box, diff(a, b));
      assertEqual(touched.length, 1);
      assertEqual(touched[0].nodeValue, "b");
      assert(box.firstChild === before, "위쪽 요소는 그대로 재사용되어야 함");
      assertSameTree(containerToVdom(box), b);
    });

    test(`깊이 ${depth}: 깊은 하위 트리를 통째로 넣는 CREATE · REPLACE 패치`, () => {
      const { a } = treesOf(depth);
      const created = root(deepTree(depth, "a"), deepTree(2, "new"));
      const box = render(root(deepTree(depth, "a")));
      patch(box, diff(root(deepTree(depth, "a")), created));
      assertSameTree(containerToVdom(box), created);

      const replaced = root({ type: "section", props: {}, children: a.children[0].children });
      const box2 = render(a);
      const patches = diff(a, replaced);
      assertEqual(patches.map((p) => p.type), [PATCH.REPLACE]);
      patch(box2, patches);
      assertSameTree(containerToVdom(box2), replaced);
    });

    test(`깊이 ${depth}: History push · undo · redo`, () => {
      const { a, b } = treesOf(depth);
      history.reset();
      history.push(a);
      history.push(b);
      const now = history.current();
      assert(now !== b, "복사본이어야 함");
      assertSameTree(now, b);
      assertSameTree(history.undo(), a);
      assertSameTree(history.redo(), b);
      assertEqual(history.position(), { index: 1, length: 2 });
      history.reset();
    });
  }

  test("toHtml: 깊이 100 · 1,000 은 들여쓰기 형식이 예전과 글자 하나까지 같음", () => {
    for (const depth of [100, 1000]) {
      assertEqual(toHtml([deepTree(depth, "leaf")]), expectedIndentedHtml(depth), `깊이 ${depth}`);
    }
  });

  test("toHtml: 깊이 5,000 · 10,000 (텍스트가 섞여 한 줄로 쓰는 사슬)", () => {
    for (const depth of [5000, 10000]) {
      const html = toHtml([mixedChain(depth)]);
      assertEqual(html, "<div>x".repeat(depth) + "leaf" + "</div>".repeat(depth), `깊이 ${depth}`);
    }
  });

  test("toHtml: 깊이 10,000 · 요소만 이어진 사슬도 오류 없이 끝까지 (<pre> 안이라 한 줄)", () => {
    const tree = { type: "pre", props: {}, children: [deepTree(10000, "leaf")] };
    assertEqual(toHtml([tree]), "<pre>" + "<div>".repeat(10000) + "leaf" + "</div>".repeat(10000) + "</pre>");
  });

  test("공유 객체: 깊이 10,000 트리 맨 아래에서 같은 객체를 두 번 써도 됨, History 복사본도 공유 유지", () => {
    const shared = { type: "i", props: {}, children: ["s"] };
    let node = { type: "p", props: {}, children: [shared, shared] };
    for (let i = 0; i < 10000; i++) node = { type: "div", props: {}, children: [node] };
    const tree = root(node);
    const box = render(tree);
    assertSameTree(containerToVdom(box), tree);
    assertEqual(diff(tree, tree).length, 0);

    history.reset();
    history.push(tree);
    let copy = history.current().children[0];
    for (let i = 0; i < 10000; i++) copy = copy.children[0];
    assert(copy.children[0] === copy.children[1], "structuredClone 처럼 공유 관계를 유지");
    assert(copy.children[0] !== shared, "원본과는 다른 객체");
    history.reset();
  });

  test("순환 참조: 깊이 10,000 아래에서 루트로 되돌아와도 스택 오류 없이 TypeError", () => {
    const top = { type: "div", props: {}, children: [] };
    let node = top;
    for (let i = 0; i < 10000; i++) {
      const child = { type: "div", props: {}, children: [] };
      node.children.push(child);
      node = child;
    }
    node.children.push(top); // 맨 아래에서 맨 위로
    assert(/순환/.test(assertThrows(() => createElement(top), TypeError).message));
    assert(/순환/.test(assertThrows(() => diff(top, top), TypeError).message));
  });

  test("History: 함수 · Symbol 이 깊은 곳에 있어도 예전처럼 DataCloneError, 기록은 그대로", () => {
    history.reset();
    history.push(root("ok"));
    for (const bad of [() => {}, Symbol("x")]) {
      const tree = deepTree(10000, "a");
      let node = tree;
      while (typeof node.children[0] === "object") node = node.children[0];
      node.props.bad = bad;
      const err = assertThrows(() => history.push(tree));
      assertEqual(err.name, "DataCloneError");
      assertEqual(history.position(), { index: 0, length: 1 });
    }
    history.reset();
  });
});
