// [tests/random.test.js] 무작위 왕복 검증: render(A) → patch(diff(A, B)) → containerToVdom == B

import { describe, test, assertEqual } from "./runner.js";
import { createElement, containerToVdom } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import { toHtml } from "../src/phase1/main.js";

export const ITERATIONS = 400; // 반복 횟수 (각 방식마다)

/**
 * 재현 가능한 의사 난수 (mulberry32). 실패하면 같은 seed 로 다시 돌려 볼 수 있다.
 */
function makeRandom(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TAGS = ["div", "p", "span", "ul", "li", "b", "i", "section", "em", "strong"];
// innerHTML 로 파싱하는 경우에는 p · li 를 뺀다.
// HTML 파서는 <p> 안에 <div> 가 오면 p 를 자동으로 닫고, <li> 안의 <li> 도 자동으로 닫아서
// 트리 모양 자체가 바뀌기 때문이다. (diff/patch 문제가 아니라 HTML 문법상 불가능한 트리)
const PARSER_SAFE_TAGS = TAGS.filter((t) => t !== "p" && t !== "li");
const TEXTS = ["가", "나다", "hello", " ", "a b", "&amp", "<x>", " nbsp", "끝."];
const PROP_NAMES = ["class", "id", "title", "data-x", "style"];
const PROP_VALUES = ["a", "b", "c d", 'q"uote', "color: red;", ""];

function makeGenerator(rand, tags = TAGS) {
  const pick = (arr) => arr[Math.floor(rand() * arr.length)];

  function randomProps() {
    const props = {};
    const count = Math.floor(rand() * 3);
    for (let i = 0; i < count; i++) props[pick(PROP_NAMES)] = pick(PROP_VALUES);
    return props;
  }

  /**
   * 무작위 자식 목록. 텍스트끼리 붙지 않게 한다.
   * (붙어 있는 텍스트 두 개는 HTML 로 다시 파싱하면 하나로 합쳐지기 때문 — innerHTML 방식 검증용)
   */
  function randomChildren(depth) {
    const children = [];
    const count = depth > 3 ? 0 : Math.floor(rand() * 4);
    for (let i = 0; i < count; i++) {
      const prevIsText = typeof children[children.length - 1] === "string";
      if (!prevIsText && rand() < 0.4) children.push(pick(TEXTS));
      else children.push(randomElement(depth + 1));
    }
    return children;
  }

  function randomElement(depth = 0) {
    return { type: pick(tags), props: randomProps(), children: randomChildren(depth) };
  }

  function randomRoot() {
    return { type: "div", props: {}, children: randomChildren(0) };
  }

  /**
   * A 를 조금 고친 B 를 만든다 (실제 편집과 비슷한 작은 변경)
   * 텍스트 변경 · 속성 변경 · 자식 추가/삭제 · 태그 교체 중 몇 가지를 무작위로 적용
   */
  function mutate(vroot) {
    const copy = structuredClone(vroot);
    const edits = 1 + Math.floor(rand() * 3);
    for (let e = 0; e < edits; e++) {
      // 무작위 요소 하나 고르기 (루트 포함)
      const elements = [];
      (function collect(node) {
        if (typeof node === "string") return;
        elements.push(node);
        node.children.forEach(collect);
      })(copy);
      const target = pick(elements);
      const r = rand();
      if (r < 0.2 && target !== copy) {
        target.type = pick(tags); // 태그 교체
      } else if (r < 0.4 && target !== copy) {
        // 속성 변경. 루트는 컨테이너 자체(containerToVdom 이 속성을 무시)라 항상 props {} 로 둔다
        target.props = randomProps();
      } else if (r < 0.6) {
        // 텍스트 자식 내용 바꾸기 (없으면 그냥 넘어감)
        const i = target.children.findIndex((c) => typeof c === "string");
        if (i >= 0) target.children[i] = pick(TEXTS) + "!";
      } else if (r < 0.8) {
        target.children.push(randomElement(3)); // 자식 추가 (뒤)
      } else if (target.children.length) {
        target.children.splice(Math.floor(rand() * target.children.length), 1); // 자식 삭제
      }
      // 삭제 때문에 텍스트끼리 붙었으면 하나로 합친다
      (function merge(node) {
        if (typeof node === "string") return;
        node.children = node.children.reduce((acc, c) => {
          if (typeof c === "string" && typeof acc[acc.length - 1] === "string") acc[acc.length - 1] += c;
          else acc.push(c);
          return acc;
        }, []);
        node.children.forEach(merge);
      })(copy);
    }
    return copy;
  }

  return { randomRoot, mutate };
}

/**
 * 한 번 검증. renderMode
 *   "dom"  : createElement 로 그린 컨테이너
 *   "html" : toHtml 로 들여쓰기한 HTML 을 innerHTML 로 파싱한 컨테이너 (공백 노드가 섞인 실제 영역과 같은 상황)
 */
function roundTrip(a, b, renderMode) {
  const box = document.createElement("div");
  if (renderMode === "dom") box.append(...a.children.map(createElement));
  else {
    // index.html 의 #real-area 처럼 앞뒤에 줄바꿈을 두고 들여쓴다.
    // 단, 최상위에 텍스트가 섞여 있으면 줄바꿈이 텍스트 내용이 되어 버리므로 붙이지 않는다.
    const allElements = a.children.every((c) => typeof c !== "string");
    box.innerHTML = allElements ? "\n" + toHtml(a.children, 1) + "\n" : toHtml(a.children);
  }

  assertEqual(containerToVdom(box), a, "렌더링 직후 A 와 같아야 함");
  patch(box, diff(a, b));
  assertEqual(containerToVdom(box), b, "patch 후 B 와 같아야 함");
}

describe(`무작위 왕복 검증 (각 ${ITERATIONS}회)`, () => {
  const cases = [
    ["독립된 무작위 트리 A, B · createElement 렌더링", "dom", false],
    ["A 를 조금 고친 B · createElement 렌더링", "dom", true],
    ["독립된 무작위 트리 A, B · 들여쓴 HTML 렌더링", "html", false],
    ["A 를 조금 고친 B · 들여쓴 HTML 렌더링", "html", true],
  ];
  cases.forEach(([name, mode, small], caseIndex) => {
    test(name, () => {
      for (let i = 0; i < ITERATIONS; i++) {
        const seed = caseIndex * 100000 + i;
        const gen = makeGenerator(makeRandom(seed), mode === "html" ? PARSER_SAFE_TAGS : TAGS);
        const a = gen.randomRoot();
        const b = small ? gen.mutate(a) : gen.randomRoot();
        try {
          roundTrip(a, b, mode);
        } catch (err) {
          err.message = `seed=${seed} 에서 실패\nA=${JSON.stringify(a)}\nB=${JSON.stringify(b)}\n${err.message}`;
          throw err;
        }
      }
    });
  });
});
