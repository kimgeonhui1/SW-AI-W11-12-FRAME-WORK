// [tests/cases-random.test.js] 테스트 항목 #256 ~ #290 — 랜덤 및 통합 · 대량 테스트
//
// 모든 무작위 테스트는 시드를 고정한 의사 난수(makeRandom)를 쓴다.
// 실패하면 같은 시드로 다시 돌려 똑같은 입력을 재현할 수 있다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, createElement, domToVdom, containerToVdom } from "../src/core/vdom.js";
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
  test("#257 무작위 단일 노드 비교", () =>
    repeat(257, 200, { maxDepth: 0 }, (gen) => roundTrip(root(gen.element(99)), root(gen.element(99)))));
  test("#258 무작위 깊은 트리 비교 (깊이 12)", () =>
    repeat(258, 60, { maxDepth: 12, maxChildren: 2 }, (gen) => roundTrip(gen.rootOf(), gen.rootOf())));
  test("#259 무작위 넓은 트리 비교 (형제 40개)", () =>
    repeat(259, 60, { maxDepth: 1, maxChildren: 40 }, (gen) => roundTrip(gen.rootOf(), gen.rootOf())));
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
  test("#266 무작위 특수문자 (createElement 렌더링 + HTML 왕복)", () =>
    repeat(266, 150, { texts: ["<", ">", "&", '"', "'", "&amp;", "<script>", "a&b<c>"], propValues: ['q"', "<>", "&amp;", "'"] }, (gen) => {
      const a = gen.rootOf();
      const b = gen.rootOf();
      roundTrip(a, b);
      assertEqual(containerToVdom(fromHtml(toHtml(b.children))), b);
    }));
  test("#267 무작위 공백 (줄바꿈 없는 공백 · 탭 · NBSP)", () =>
    repeat(267, 150, { texts: [" ", "  ", "\t", "a  b", " ", "   "] }, (gen) => roundTrip(gen.rootOf(), gen.rootOf())));
  test("#268 무작위 중첩 배열을 h() 에 넣어도 평탄한 결과와 같음", () =>
    repeat(268, 200, {}, (gen, rand) => {
      const flat = Array.from({ length: Math.floor(rand() * 6) }, () => gen.pick(["a", "b", h("i", null, "c")]));
      let nested = [...flat];
      for (let i = 0; i < 4; i++) nested = rand() < 0.5 ? [nested] : [[], nested, [[]], null, false];
      assertEqual(h("p", null, nested).children, flat);
    }));
  test("#269 무작위 빈 문자열 자식 (createElement 렌더링 기준으로 보존)", () =>
    repeat(269, 150, { texts: ["", "a", ""] }, (gen) => roundTrip(gen.rootOf(), gen.rootOf())));
  test("#270 무작위 불리언 속성: true → \"\", false → 없음", () =>
    repeat(270, 150, {}, (gen, rand) => {
      const props = {};
      for (const name of ["disabled", "hidden", "required"]) if (rand() < 0.7) props[name] = rand() < 0.5;
      const back = domToVdom(createElement(h("input", props))).props;
      const expected = Object.fromEntries(Object.entries(props).filter(([, v]) => v).map(([k]) => [k, ""]));
      assertEqual(back, expected);
    }));
  test("#271 무작위 void element 포함 (br · img · hr · input)", () =>
    repeat(271, 150, { voidTags: ["br", "img", "hr", "input"] }, (gen) => {
      const b = gen.rootOf();
      roundTrip(gen.rootOf(), b);
      assertEqual(containerToVdom(fromHtml(toHtml(b.children))), b);
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
  test("#274 무작위 History 분기 (Undo 후 새 Patch 가 잦음)", () => {
    const { length } = historyScenario(274, 200, { branchRate: 0.5 });
    assert(length >= 1);
  });
  test("#275 무작위 go() (범위 밖 인덱스 포함)", () => historyScenario(275, 200, { branchRate: 0.1 }));
  test("#276 무작위 직렬화 왕복 (toHtml → HTML 파싱 → VDOM)", () =>
    repeat(276, 200, {}, (gen) => {
      const tree = gen.rootOf();
      assertEqual(containerToVdom(fromHtml(toHtml(tree.children))), tree);
    }));
  test("#277 무작위 DOM → VDOM 왕복 (createElement → domToVdom)", () =>
    repeat(277, 200, {}, (gen) => {
      const node = gen.element();
      assertEqual(domToVdom(createElement(node)), node);
    }));
  test("#278 무작위 VDOM → DOM 왕복 (outerHTML 을 다시 파싱)", () =>
    repeat(278, 200, {}, (gen) => {
      const node = gen.element();
      assertEqual(containerToVdom(fromHtml(createElement(node).outerHTML)), root(node));
    }));
  test("#279 무작위 Diff → Patch 왕복 (조금 바꾼 트리)", () => repeat(279, 300, {}, (gen) => {
    const a = gen.rootOf();
    roundTrip(a, gen.mutate(a));
  }));
  test("#280 무작위 History → Patch 왕복 (기록 사이를 자유롭게 이동)", () => historyScenario(280, 300));
  test("#281 같은 트리를 100번 비교 → 항상 빈 배열", () =>
    repeat(281, 100, { maxDepth: 5 }, (gen) => {
      const tree = gen.rootOf();
      assertEqual(diff(tree, structuredClone(tree)), []);
    }));
  test("#282 서로 다른 트리 100번 비교", () => repeat(282, 100, {}, (gen) => roundTrip(gen.rootOf(), gen.rootOf())));
  test("#283 1,000번 연속 Diff → Patch (같은 영역)", () => {
    const rand = makeRandom(283);
    const gen = makeGenerator(rand, { maxDepth: 2, maxChildren: 3 });
    let current = gen.rootOf();
    const box = render(current);
    for (let i = 0; i < 1000; i++) {
      const next = gen.mutate(current);
      patch(box, diff(current, next));
      current = next;
    }
    assertEqual(containerToVdom(box), current);
  });
  test("#284 1,000번 연속 Undo / Redo", () => {
    history.reset();
    const versions = Array.from({ length: 10 }, (_, i) => root(h("p", null, `v${i}`)));
    versions.forEach((v) => history.push(v));
    const rand = makeRandom(284);
    let shown = versions[9];
    const box = render(shown);
    for (let i = 0; i < 1000; i++) {
      const target = rand() < 0.5 ? history.undo() : history.redo();
      if (target) {
        patch(box, diff(shown, target));
        shown = target;
      }
    }
    assertEqual(containerToVdom(box), history.current());
  });
  test("#285 자식 1,000개 처리", () => {
    const many = (prefix) => root(...Array.from({ length: 1000 }, (_, i) => h("span", { "data-i": String(i) }, `${prefix}${i}`)));
    roundTrip(many("a"), many("b"));
  });
  test("#286 텍스트 노드 10,000개 처리", () => {
    const texts = (prefix) => ({ type: "div", props: {}, children: Array.from({ length: 10000 }, (_, i) => `${prefix}${i}`) });
    const { box } = roundTrip(texts("a"), texts("b"));
    assertEqual(box.childNodes.length, 10000);
  });
  test("#287 1,000단계 중첩 구조 처리 (렌더링 · 변환 · Diff · Patch · 직렬화)", () => {
    roundTrip(root(deepTree(1000, "a")), root(deepTree(1000, "b")));
    const html = toHtml([deepTree(1000, "x")]);
    assert(html.startsWith("<div>\n  <div>"), "들여쓰기 출력");
  });
  test("#288 매우 긴 속성값 (100,000자)", () => roundTrip(root(h("p", { title: "a" })), root(h("p", { title: "가&\"".repeat(33334) }))));
  test("#289 매우 긴 텍스트 (1,000,000자)", () => roundTrip(root(h("p", null, "a")), root(h("p", null, "가".repeat(1000000)))));
  test("#290 대량 Patch 후 DOM 정합성 (li 3,000개 무작위 변경)", () => {
    const rand = makeRandom(290);
    const items = (fn) => root(h("ul", null, ...Array.from({ length: 3000 }, (_, i) => fn(i))));
    const a = items((i) => h("li", { class: "c" }, `${i}`));
    const b = items((i) => {
      const r = rand();
      if (r < 0.2) return h("li", { class: "changed" }, `${i}`);
      if (r < 0.4) return h("li", { class: "c" }, `${i}!`);
      if (r < 0.5) return h("p", null, `${i}`);
      return h("li", { class: "c" }, `${i}`);
    });
    roundTrip(a, b);
  });
});

