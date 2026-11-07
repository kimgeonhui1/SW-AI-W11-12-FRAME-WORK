// [tests/cases-random.test.js] 테스트 항목 #256 ~ #290 — 랜덤 및 통합 · 대량 테스트
//
// 모든 무작위 테스트는 시드를 고정한 의사 난수(makeRandom)를 쓴다.
// 실패하면 같은 시드로 다시 돌려 똑같은 입력을 재현할 수 있다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { containerToVdom } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import * as history from "../src/phase1/history.js";
import { toHtml } from "../src/phase1/main.js";
import { root, render, fromHtml, roundTrip, deepTree, makeRandom, makeGenerator } from "./helpers.js";

/** seed 마다 iterations 번 fn(gen, rand, i) 실행 */
function repeat(seed, iterations, opts, fn) {
  const rand = makeRandom(seed);
  const gen = makeGenerator(rand, opts);
  for (let i = 0; i < iterations; i++) fn(gen, rand, i);
}

/**
 * History 를 쓰는 화면 흐름을 그대로 흉내 낸다.
 * 이동할 때마다 실제 영역(box)에 diff/patch 를 적용하고, box 가 history.current() 와 같은지 확인한다.
 */
function historyScenario(seed, steps, { branchRate = 0.3 } = {}) {
  const rand = makeRandom(seed);
  const gen = makeGenerator(rand, { maxDepth: 3 });
  history.reset();
  let shown = gen.rootOf();
  history.push(shown);
  const box = render(shown);

  const moveTo = (target) => {
    if (!target) return;
    patch(box, diff(shown, target));
    shown = target;
  };

  for (let step = 0; step < steps; step++) {
    const roll = rand();
    if (roll < branchRate) {
      const next = gen.mutate(shown);
      patch(box, diff(shown, next));
      history.push(next);
      shown = next;
    } else if (roll < branchRate + 0.25) moveTo(history.undo());
    else if (roll < branchRate + 0.5) moveTo(history.redo());
    else moveTo(history.go(Math.floor(rand() * (history.position().length + 2)) - 1));
    assertEqual(containerToVdom(box), history.current(), `${seed}번 시드 ${step}번째 단계`);
  }
  return history.position();
}

describe("랜덤 및 통합 테스트 (#256~#290)", () => {
  test("#256 무작위 빈 트리 비교 (빈 ↔ 빈, 빈 ↔ 무작위)", () => {
    assertEqual(diff(root(), root()), []);
    repeat(256, 100, {}, (gen) => {
      const tree = gen.rootOf();
      roundTrip(root(), tree);
      roundTrip(tree, root());
    });
  });
  test("#260 무작위 속성만 변경", () =>
    repeat(260, 150, {}, (gen) => {
      const a = gen.rootOf();
      const b = structuredClone(a);
      const each = (node) => {
        if (typeof node === "string") return;
        node.props = gen.props();
        node.children.forEach(each);
      };
      b.children.forEach(each);
      roundTrip(a, b);
    }));
  test("#261 무작위 텍스트만 변경", () =>
    repeat(261, 150, {}, (gen) => {
      const a = gen.rootOf();
      const b = structuredClone(a);
      const each = (node) => node.children.forEach((c, i) => (typeof c === "string" ? (node.children[i] = gen.pick(["바뀜", "x", "y z"])) : each(c)));
      each(b);
      roundTrip(a, b);
    }));
  test("#262 무작위 노드 추가", () =>
    repeat(262, 150, {}, (gen) => {
      const a = gen.rootOf();
      const b = structuredClone(a);
      b.children.push(gen.element(1));
      b.children.splice(0, 0, gen.element(1));
      roundTrip(a, b);
    }));
  test("#263 무작위 노드 삭제", () =>
    repeat(263, 150, { maxChildren: 6 }, (gen, rand) => {
      const a = gen.rootOf();
      const b = structuredClone(a);
      b.children = b.children.filter(() => rand() < 0.5);
      roundTrip(a, b); // render 경로는 텍스트 노드를 따로 만들므로 붙은 문자열도 그대로 비교
    }));
  test("#264 무작위 노드 교체 (태그 변경)", () =>
    repeat(264, 150, {}, (gen) => {
      const a = gen.rootOf();
      const b = structuredClone(a);
      b.children = b.children.map((c) => (typeof c === "string" ? c : { ...c, type: gen.pick(["article", "aside", "mark"]) }));
      roundTrip(a, b);
    }));
  test("#265 무작위 형제 순서 변경", () =>
    repeat(265, 150, { maxChildren: 6 }, (gen, rand) => {
      const a = gen.rootOf();
      const b = structuredClone(a);
      b.children.sort(() => rand() - 0.5);
      roundTrip(a, b);
    }));
  test("#272 무작위 연속 Patch (같은 영역에 50번)", () =>
    repeat(272, 5, {}, (gen) => {
      let current = gen.rootOf();
      const box = render(current);
      for (let i = 0; i < 50; i++) {
        const next = gen.mutate(current);
        patch(box, diff(current, next));
        assertEqual(containerToVdom(box), next);
        current = next;
      }
    }));
  test("#273 무작위 Undo / Redo 반복", () => historyScenario(273, 200, { branchRate: 0.15 }));
  test("#276 무작위 직렬화 왕복 (toHtml → HTML 파싱 → VDOM)", () =>
    repeat(276, 200, {}, (gen) => {
      const tree = gen.rootOf();
      assertEqual(containerToVdom(fromHtml(toHtml(tree.children))), tree);
    }));
  test("#279 무작위 Diff → Patch 왕복 (조금 바꾼 트리)", () => repeat(279, 300, {}, (gen) => {
    const a = gen.rootOf();
    roundTrip(a, gen.mutate(a));
  }));
  test("#280 무작위 History → Patch 왕복 (기록 사이를 자유롭게 이동)", () => historyScenario(280, 300));
  test("#287 1,000단계 중첩 구조 처리 (렌더링 · 변환 · Diff · Patch · 직렬화)", () => {
    roundTrip(root(deepTree(1000, "a")), root(deepTree(1000, "b")));
    const html = toHtml([deepTree(1000, "x")]);
    assert(html.startsWith("<div>\n  <div>"), "들여쓰기 출력");
  });
});

