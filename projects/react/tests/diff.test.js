// [tests/diff.test.js] diff 패치 종류별 결과 + patch 적용 결과

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, createElement, containerToVdom } from "../src/core/vdom.js";
import { diff, PATCH } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";

/** 루트(가상 div) VNode 를 만들기 위한 줄임 함수 */
const root = (...children) => h("div", null, ...children);

/** 루트 VNode 를 실제 컨테이너로 렌더링 (containerToVdom 과 짝) */
function render(vroot) {
  const box = document.createElement("div");
  box.append(...vroot.children.map(createElement));
  return box;
}

/** diff → patch 후 컨테이너가 새 VNode 와 같은지 확인 */
function applyAndCheck(oldRoot, newRoot) {
  const box = render(oldRoot);
  patch(box, diff(oldRoot, newRoot));
  assertEqual(containerToVdom(box), newRoot);
}

describe("diff() 패치 종류", () => {
  test("같으면 빈 배열", () => {
    const a = root(h("p", { class: "x" }, "hi"));
    assertEqual(diff(a, structuredClone(a)), []);
  });

  test("TEXT: 텍스트만 바뀜", () => {
    const patches = diff(root(h("p", null, "a")), root(h("p", null, "b")));
    assertEqual(patches, [{ type: PATCH.TEXT, path: [0, 0], value: "b" }]);
  });

  test("PROPS: 속성 추가 · 변경 · 삭제", () => {
    const patches = diff(
      root(h("p", { class: "a", title: "t" }, "x")),
      root(h("p", { class: "b", "data-new": "1" }, "x")),
    );
    assertEqual(patches, [
      { type: PATCH.PROPS, path: [0], set: { class: "b", "data-new": "1" }, remove: ["title"] },
    ]);
  });

  test("REPLACE: 태그가 다르면 교체하고 더 내려가지 않음", () => {
    const patches = diff(root(h("p", null, "a")), root(h("div", null, "b")));
    assertEqual(patches, [{ type: PATCH.REPLACE, path: [0], node: h("div", null, "b") }]);
  });

  test("REPLACE: 텍스트 ↔ 요소 전환", () => {
    const patches = diff(root("text"), root(h("b", null, "text")));
    assertEqual(patches.map((p) => p.type), [PATCH.REPLACE]);
  });

  test("CREATE: 새 자식 추가 (부모 경로 + 위치)", () => {
    const patches = diff(root(h("ul", null, h("li", null, "1"))), root(h("ul", null, h("li", null, "1"), h("li", null, "2"))));
    assertEqual(patches, [{ type: PATCH.CREATE, path: [0], index: 1, node: h("li", null, "2") }]);
  });

  test("REMOVE: 사라진 자식 삭제", () => {
    const patches = diff(root(h("p", null, "a"), h("p", null, "b")), root(h("p", null, "a")));
    assertEqual(patches, [{ type: PATCH.REMOVE, path: [1] }]);
  });

  test("경로는 옛 트리 기준 · DFS 순서", () => {
    const patches = diff(
      root(h("div", null, h("span", null, "a"), h("span", null, "b"))),
      root(h("div", { id: "x" }, h("span", null, "A"), h("span", null, "B"))),
    );
    assertEqual(
      patches.map((p) => [p.type, p.path]),
      [
        [PATCH.PROPS, [0]],
        [PATCH.TEXT, [0, 0, 0]],
        [PATCH.TEXT, [0, 1, 0]],
      ],
    );
  });
});

describe("patch() 적용", () => {
  test("여러 REMOVE 가 있어도 인덱스가 밀리지 않는다 (대상 먼저 찾기)", () => {
    applyAndCheck(
      root(h("p", null, "0"), h("p", null, "1"), h("p", null, "2"), h("p", null, "3")),
      root(h("p", null, "0")),
    );
  });

  test("REMOVE 와 하위 TEXT 가 섞여도 정확히 반영", () => {
    applyAndCheck(
      root(h("ul", null, h("li", null, "a"), h("li", null, "b"), h("li", null, "c")), h("p", null, "end")),
      root(h("ul", null, h("li", null, "A"))),
    );
  });

  test("들여쓰기가 있는 컨테이너에서도 경로가 맞는다", () => {
    const box = document.createElement("div");
    box.innerHTML = "\n  <ul>\n    <li>a</li>\n    <li>b</li>\n  </ul>\n";
    const oldRoot = containerToVdom(box);
    const newRoot = root(h("ul", null, h("li", null, "a"), h("li", { class: "on" }, "B"), h("li", null, "c")));
    patch(box, diff(oldRoot, newRoot));
    assertEqual(containerToVdom(box), newRoot);
  });

  test("텍스트 노드는 새로 만들지 않고 재사용한다", () => {
    const box = render(root(h("p", null, "a")));
    const textNode = box.firstChild.firstChild;
    const touched = patch(box, diff(root(h("p", null, "a")), root(h("p", null, "b"))));
    assert(box.firstChild.firstChild === textNode, "같은 Text 노드여야 함");
    assert(touched[0] === textNode, "바뀐 노드로 반환되어야 함");
  });

  test("같은 태그의 요소도 재사용한다 (PROPS)", () => {
    const box = render(root(h("p", { class: "a" }, "x")));
    const el = box.firstChild;
    patch(box, diff(root(h("p", { class: "a" }, "x")), root(h("p", { class: "b" }, "x"))));
    assert(box.firstChild === el, "같은 요소여야 함");
    assertEqual(el.getAttribute("class"), "b");
  });
});
