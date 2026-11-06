// [tests/cases-diff-patch.test.js] 테스트 항목 #081 ~ #170
//   #081 ~ #115 Diff
//   #116 ~ #145 Patch
//   #146 ~ #170 Props 및 HTML 속성

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, createElement, containerToVdom } from "../src/core/vdom.js";
import { diff, PATCH } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import { root, render, roundTrip, assertThrows, captureConsole, deepTree } from "./helpers.js";

const li = (text, props = null) => h("li", props, text);
const list = (...texts) => root(h("ul", null, ...texts.map((t) => li(t))));
const types = (patches) => patches.map((p) => p.type);

describe("Diff (#081~#115)", () => {
  test("#081 완전히 같은 VDOM → 빈 배열", () => {
    const a = root(h("div", { id: "x" }, h("p", null, "a", h("b", null, "b"))));
    assertEqual(diff(a, structuredClone(a)), []);
  });
  test("#082 루트 태그 변경 → 경로 [] 의 REPLACE. 컨테이너 자신은 바꿀 수 없으므로 patch 는 TypeError, DOM 그대로", () => {
    const patches = diff(h("p", null, "a"), h("div", null, "a"));
    assertEqual(patches, [{ type: PATCH.REPLACE, path: [], node: h("div", null, "a") }]);
    const wrapper = document.createElement("section");
    const box = createElement(h("p", null, "a"));
    wrapper.append(box);
    assertThrows(() => patch(box, patches), TypeError);
    assert(wrapper.firstChild === box, "컨테이너가 그대로 있어야 함 (예전에는 통째로 바뀌어 실제 영역이 사라졌다)");
    assertEqual(box.outerHTML, "<p>a</p>");
  });
  test("#083 루트가 텍스트일 때 변경 → 경로 [] 의 TEXT", () => assertEqual(diff("a", "b"), [{ type: PATCH.TEXT, path: [], value: "b" }]));
  test("#084 텍스트 → 요소", () => {
    const { patches } = roundTrip(root("a"), root(h("b", null, "a")));
    assertEqual(types(patches), [PATCH.REPLACE]);
  });
  test("#085 요소 → 텍스트", () => {
    const { patches } = roundTrip(root(h("b", null, "a")), root("a"));
    assertEqual(types(patches), [PATCH.REPLACE]);
  });
  test("#086 빈 트리 → 요소 생성 (CREATE)", () => {
    const { patches } = roundTrip(root(), root(h("p", null, "x")));
    assertEqual(patches, [{ type: PATCH.CREATE, path: [], index: 0, node: h("p", null, "x") }]);
  });
  test("#087 요소 → 빈 트리 (REMOVE)", () => {
    const { patches } = roundTrip(root(h("p", null, "x")), root());
    assertEqual(patches, [{ type: PATCH.REMOVE, path: [0] }]);
  });
  test("#088 자식 하나 추가", () => assertEqual(types(roundTrip(list("1"), list("1", "2")).patches), [PATCH.CREATE]));
  test("#089 자식 하나 삭제", () => assertEqual(roundTrip(list("1", "2"), list("1")).patches, [{ type: PATCH.REMOVE, path: [0, 1] }]));
  test("#090 자식 여러 개 추가", () => {
    const { patches } = roundTrip(list("1"), list("1", "2", "3", "4"));
    assertEqual(patches.map((p) => [p.type, p.index]), [[PATCH.CREATE, 1], [PATCH.CREATE, 2], [PATCH.CREATE, 3]]);
  });
  test("#091 자식 여러 개 삭제", () => {
    const { patches } = roundTrip(list("1", "2", "3", "4"), list("1"));
    assertEqual(patches.map((p) => p.path), [[0, 1], [0, 2], [0, 3]]);
  });
  test("#092 첫 번째 자식 삭제 (인덱스 비교라 뒤 형제 TEXT 변경 + 마지막 REMOVE)", () => {
    const { patches } = roundTrip(list("1", "2", "3"), list("2", "3"));
    assertEqual(types(patches), [PATCH.TEXT, PATCH.TEXT, PATCH.REMOVE]);
  });
  test("#093 마지막 자식 삭제 → REMOVE 하나", () => assertEqual(types(roundTrip(list("1", "2", "3"), list("1", "2")).patches), [PATCH.REMOVE]));
  test("#094 중간 자식 삭제", () => roundTrip(list("1", "2", "3"), list("1", "3")));
  test("#095 연속된 자식 삭제", () => roundTrip(list("1", "2", "3", "4", "5"), list("1", "5")));
  test("#096 하나 건너 하나씩 삭제", () => roundTrip(list("0", "1", "2", "3", "4", "5"), list("1", "3", "5")));
  test("#097 앞에 자식 삽입 (모든 형제가 한 칸씩 밀림 — key 가 없는 한계)", () => {
    const { patches } = roundTrip(list("1", "2", "3"), list("0", "1", "2", "3"));
    assertEqual(types(patches), [PATCH.TEXT, PATCH.TEXT, PATCH.TEXT, PATCH.CREATE]);
  });
  test("#098 중간에 자식 삽입", () => roundTrip(list("1", "3"), list("1", "2", "3")));
  test("#099 마지막에 자식 삽입 → CREATE 하나", () => assertEqual(types(roundTrip(list("1", "2"), list("1", "2", "3")).patches), [PATCH.CREATE]));
  test("#100 자식 순서만 변경", () => roundTrip(list("1", "2", "3", "4"), list("4", "3", "2", "1")));
  test("#101 형제 요소를 모두 다른 태그로 교체 → 각각 REPLACE", () => {
    const { patches } = roundTrip(root(h("p"), h("p"), h("p")), root(h("div"), h("span"), h("em")));
    assertEqual(types(patches), [PATCH.REPLACE, PATCH.REPLACE, PATCH.REPLACE]);
  });
  test("#102 깊이가 다른 트리 비교", () => roundTrip(root(deepTree(3, "a")), root(deepTree(6, "b"))));
  test("#103 같은 태그, 다른 속성 → PROPS 만 (자식 패치 없음)", () => {
    const { patches } = roundTrip(root(h("p", { id: "a" }, "x")), root(h("p", { class: "b" }, "x")));
    assertEqual(patches, [{ type: PATCH.PROPS, path: [0], set: { class: "b" }, remove: ["id"] }]);
  });
  test("#104 속성 하나 추가", () => assertEqual(diff(root(h("p")), root(h("p", { title: "t" })))[0], { type: PATCH.PROPS, path: [0], set: { title: "t" }, remove: [] }));
  test("#105 속성 하나 삭제", () => assertEqual(diff(root(h("p", { title: "t" })), root(h("p")))[0], { type: PATCH.PROPS, path: [0], set: {}, remove: ["title"] }));
  test("#106 속성 하나 변경", () => assertEqual(diff(root(h("p", { title: "a" })), root(h("p", { title: "b" })))[0].set, { title: "b" }));
  test("#107 여러 속성 동시 변경", () => {
    const { patches } = roundTrip(root(h("p", { a: "1", b: "2", c: "3" })), root(h("p", { a: "x", b: "y", c: "z" })));
    assertEqual(patches[0].set, { a: "x", b: "y", c: "z" });
  });
  test("#108 속성 추가와 삭제가 동시에", () => {
    const { patches } = roundTrip(root(h("p", { old: "1", keep: "k" })), root(h("p", { keep: "k", new: "2" })));
    assertEqual([patches[0].set, patches[0].remove], [{ new: "2" }, ["old"]]);
  });
  test("#109 속성값을 빈 문자열로", () => roundTrip(root(h("p", { title: "a" })), root(h("p", { title: "" }))));
  test("#110 속성값을 null 로 → set 에 null, patch 하면 속성이 지워짐", () => {
    const old = root(h("p", { title: "a" }));
    const patches = diff(old, root(h("p", { title: null })));
    assertEqual(patches[0].set, { title: null });
    const box = render(old);
    patch(box, patches);
    assertEqual(box.firstChild.hasAttribute("title"), false);
  });
  test("#111 부모와 자식 속성이 동시에 변경", () => {
    const { patches } = roundTrip(root(h("div", { id: "a" }, h("p", { id: "b" }))), root(h("div", { id: "A" }, h("p", { id: "B" }))));
    assertEqual(patches.map((p) => [p.type, p.path]), [[PATCH.PROPS, [0]], [PATCH.PROPS, [0, 0]]]);
  });
  test("#112 같은 위치에서 텍스트 ↔ 요소 맞바꿈", () => {
    const { patches } = roundTrip(root("a", h("b", null, "b")), root(h("b", null, "b"), "a"));
    assertEqual(types(patches), [PATCH.REPLACE, PATCH.REPLACE]);
  });
  test("#113 중첩된 여러 노드가 동시에 변경", () =>
    roundTrip(
      root(h("section", null, h("h2", null, "제목"), h("ul", null, li("a"), li("b")), h("p", { class: "n" }, "끝"))),
      root(h("section", { id: "s" }, h("h3", null, "제목"), h("ul", null, li("A"), li("b"), li("c")), "끝")),
    ));
  test("#114 1,000단계 깊이 트리 비교 → 맨 아래 TEXT 하나", () => {
    const patches = diff(root(deepTree(1000, "a")), root(deepTree(1000, "b")));
    assertEqual(patches.length, 1);
    assertEqual(patches[0].type, PATCH.TEXT);
    assertEqual(patches[0].path.length, 1001);
  });
  test("#115 형제가 매우 많은 트리 (5,000개, 10개마다 변경)", () => {
    const texts = Array.from({ length: 5000 }, (_, i) => String(i));
    const changed = texts.map((t, i) => (i % 10 === 0 ? `${t}!` : t));
    const { patches } = roundTrip(list(...texts), list(...changed));
    assertEqual(patches.length, 500);
  });
});

describe("Patch (#116~#145)", () => {
  const abc = () => render(root(h("p", null, "a"), h("p", null, "b"), h("p", null, "c")));
  const texts = (box) => [...box.children].map((el) => el.textContent);

  test("#116 CREATE 적용", () => {
    const box = abc();
    patch(box, [{ type: PATCH.CREATE, path: [], index: 3, node: h("p", null, "d") }]);
    assertEqual(texts(box), ["a", "b", "c", "d"]);
  });
  test("#117 REMOVE 적용", () => {
    const box = abc();
    patch(box, [{ type: PATCH.REMOVE, path: [1] }]);
    assertEqual(texts(box), ["a", "c"]);
  });
  test("#118 REPLACE 적용", () => {
    const box = abc();
    patch(box, [{ type: PATCH.REPLACE, path: [1], node: h("h2", null, "B") }]);
    assertEqual(box.children[1].outerHTML, "<h2>B</h2>");
  });
  test("#119 TEXT 적용", () => {
    const box = abc();
    patch(box, [{ type: PATCH.TEXT, path: [2, 0], value: "C" }]);
    assertEqual(texts(box), ["a", "b", "C"]);
  });
  test("#120 PROPS 적용", () => {
    const box = render(root(h("p", { id: "x", title: "t" })));
    patch(box, [{ type: PATCH.PROPS, path: [0], set: { id: "y", class: "c" }, remove: ["title"] }]);
    assertEqual(box.innerHTML, '<p id="y" class="c"></p>');
  });
  test("#121 빈 패치 배열 → 아무것도 바뀌지 않고 [] 반환", () => {
    const box = abc();
    const before = box.innerHTML;
    assertEqual(patch(box, []), []);
    assertEqual(box.innerHTML, before);
  });
  test("#122 같은 패치를 두 번 적용: TEXT/PROPS 는 같은 결과, REMOVE 는 다른 노드를 지움 (패치는 한 번만 적용해야 함)", () => {
    const box = abc();
    const textPatch = [{ type: PATCH.TEXT, path: [0, 0], value: "A" }];
    patch(box, textPatch);
    patch(box, textPatch);
    assertEqual(texts(box), ["A", "b", "c"]);
    const removePatch = [{ type: PATCH.REMOVE, path: [0] }];
    patch(box, removePatch);
    patch(box, removePatch);
    assertEqual(texts(box), ["c"]);
  });
  test("#123 연속 CREATE 는 순서대로 붙음", () => {
    const box = render(root());
    patch(box, [0, 1, 2].map((i) => ({ type: PATCH.CREATE, path: [], index: i, node: h("p", null, String(i)) })));
    assertEqual(texts(box), ["0", "1", "2"]);
  });
  test("#124 연속 REMOVE", () => {
    const box = abc();
    patch(box, [{ type: PATCH.REMOVE, path: [1] }, { type: PATCH.REMOVE, path: [2] }]);
    assertEqual(texts(box), ["a"]);
  });
  test("#125 연속 REPLACE", () => {
    const box = abc();
    patch(box, [0, 1, 2].map((i) => ({ type: PATCH.REPLACE, path: [i], node: h("b", null, String(i)) })));
    assertEqual(box.innerHTML, "<b>0</b><b>1</b><b>2</b>");
  });
  test("#126 같은 부모의 여러 자식 삭제", () => roundTrip(list("1", "2", "3", "4"), list("1", "2")));
  test("#127 첫 번째 삭제 후 마지막 삭제 (경로는 변경 전 기준)", () => {
    const box = abc();
    patch(box, [{ type: PATCH.REMOVE, path: [0] }, { type: PATCH.REMOVE, path: [2] }]);
    assertEqual(texts(box), ["b"]);
  });
  test("#128 마지막 삭제 후 첫 번째 삭제", () => {
    const box = abc();
    patch(box, [{ type: PATCH.REMOVE, path: [2] }, { type: PATCH.REMOVE, path: [0] }]);
    assertEqual(texts(box), ["b"]);
  });
  test("#129 중첩 요소를 만든 뒤 그 안을 수정", () => {
    const v1 = root();
    const v2 = root(h("ul", null, li("a")));
    const v3 = root(h("ul", null, li("A", { class: "on" })));
    const box = render(v1);
    patch(box, diff(v1, v2));
    patch(box, diff(v2, v3));
    assertEqual(containerToVdom(box), v3);
  });
  test("#130 부모 교체와 자식 수정이 동시에 → 부모 REPLACE 하나만", () => {
    const { patches } = roundTrip(root(h("p", null, h("b", null, "a"))), root(h("div", null, h("b", null, "A"))));
    assertEqual(types(patches), [PATCH.REPLACE]);
  });
  test("#131 형제 생성과 삭제가 동시에 (서로 다른 부모)", () =>
    roundTrip(root(h("ul", null, li("1"), li("2")), h("ol", null, li("x"))), root(h("ul", null, li("1")), h("ol", null, li("x"), li("y")))));
  test("#132 같은 노드의 여러 속성 변경 → PROPS 하나", () => {
    const { patches } = roundTrip(root(h("p", { a: "1" })), root(h("p", { a: "2", b: "3", c: "4" })));
    assertEqual(patches.length, 1);
  });
  test("#133 없는 경로 → TypeError, 앞의 정상 패치도 적용하지 않음 (예전: 경고 후 건너뜀)", () => {
    const box = abc();
    assertThrows(() => patch(box, [{ type: PATCH.TEXT, path: [0, 0], value: "A" }, { type: PATCH.TEXT, path: [5, 0], value: "x" }]), TypeError);
    assertEqual(texts(box), ["a", "b", "c"]);
  });
  test("#134 범위를 넘는 index 의 CREATE → TypeError, DOM 그대로 (예전: 끝에 붙음)", () => {
    const box = abc();
    assertThrows(() => patch(box, [{ type: PATCH.CREATE, path: [], index: 99, node: h("p", null, "z") }]), TypeError);
    assertEqual(texts(box), ["a", "b", "c"]);
  });
  test("#135 범위를 넘는 경로의 REMOVE → TypeError, DOM 그대로 (예전: 경고 후 건너뜀)", () => {
    const box = abc();
    assertThrows(() => patch(box, [{ type: PATCH.REMOVE, path: [1] }, { type: PATCH.REMOVE, path: [9] }]), TypeError);
    assertEqual(texts(box), ["a", "b", "c"]);
  });
  test("#136 빈 경로 [] 는 컨테이너 자신 (PROPS 를 주면 컨테이너 속성이 바뀜)", () => {
    const box = abc();
    patch(box, [{ type: PATCH.PROPS, path: [], set: { "data-x": "1" }, remove: [] }]);
    assertEqual(box.dataset.x, "1");
  });
  test("#137 잘못된 패치 종류 → TypeError, 앞의 정상 패치도 적용하지 않음", () => {
    const box = abc();
    assertThrows(() => patch(box, [{ type: PATCH.TEXT, path: [0, 0], value: "A" }, { type: "MOVE", path: [0] }]), TypeError);
    assertEqual(texts(box), ["a", "b", "c"]);
  });
  test("#138 필드가 빠진 패치 → TypeError, DOM 그대로", () => {
    const box = abc();
    const broken = [
      { type: PATCH.TEXT, path: [0, 0] }, //                 value 없음
      { type: PATCH.CREATE, path: [], index: 3 }, //         node 없음
      { type: PATCH.CREATE, path: [], node: "x" }, //        index 없음
      { type: PATCH.PROPS, path: [0], remove: [] }, //       set 없음
      { type: PATCH.PROPS, path: [0], set: {} }, //          remove 없음
      { type: PATCH.REMOVE }, //                             path 없음
      { type: PATCH.REMOVE, path: [-1] }, //                 음수 인덱스
      { type: PATCH.REMOVE, path: ["0"] }, //                문자열 인덱스
      null,
    ];
    for (const p of broken) assertThrows(() => patch(box, [p]), TypeError, `TypeError 여야 함: ${JSON.stringify(p)}`);
    assertThrows(() => patch(box, null), TypeError);
    assertEqual(texts(box), ["a", "b", "c"]);
  });
  test("#139 잘못된 노드 참조(REPLACE 의 node 가 VNode 가 아님) → TypeError, DOM 그대로", () => {
    const box = abc();
    for (const node of [{}, null, 5, { type: "" }]) {
      assertThrows(() => patch(box, [{ type: PATCH.REPLACE, path: [0], node }]), TypeError);
    }
    assertEqual(texts(box), ["a", "b", "c"]);
  });
  test("#140 Patch 후 DOM → VDOM 이 새 VDOM 과 일치", () =>
    roundTrip(root(h("div", { id: "a" }, "x", h("i", null, "y"))), root(h("div", { id: "b" }, h("i", null, "Y"), "x", "z"))));
  test("#141 바뀌지 않은 노드는 참조가 그대로 유지", () => {
    const old = list("1", "2", "3");
    const box = render(old);
    const [first, second] = box.querySelectorAll("li");
    patch(box, diff(old, list("1", "2", "3", "4")));
    const now = box.querySelectorAll("li");
    assert(now[0] === first && now[1] === second, "기존 li 재사용");
  });
  test("#142 삭제된 노드는 문서에서 떨어져 나감", () => {
    const box = abc();
    document.body.append(box);
    const removed = box.children[2];
    patch(box, [{ type: PATCH.REMOVE, path: [2] }]);
    assertEqual(removed.isConnected, false);
    box.remove();
  });
  test("#143 연속 20번 Patch 후에도 인덱스 정합성 유지", () => {
    let current = list("0");
    const box = render(current);
    for (let step = 1; step <= 20; step++) {
      const next = list(...Array.from({ length: (step * 7) % 9 + 1 }, (_, i) => `${step}-${i}`));
      patch(box, diff(current, next));
      assertEqual(containerToVdom(box), next, `${step}번째`);
      current = next;
    }
  });
  test("#144 깊은 중첩 구조(300단계)에 Patch → 맨 아래 텍스트 노드를 재사용", () => {
    const old = root(deepTree(300, "a"));
    const box = render(old);
    let leaf = box;
    while (leaf.firstChild) leaf = leaf.firstChild;
    const touched = patch(box, diff(old, root(deepTree(300, "b"))));
    assert(touched[0] === leaf, "같은 Text 노드");
    assertEqual(leaf.nodeValue, "b");
  });
  test("#145 대량 Patch(2,000개) 한 번에 적용", () => {
    const n = 2000;
    const { patches } = roundTrip(list(...Array.from({ length: n }, (_, i) => `a${i}`)), list(...Array.from({ length: n }, (_, i) => `b${i}`)));
    assertEqual(patches.length, n);
  });
});

describe("Props 및 HTML 속성 (#146~#170)", () => {
  /** 속성만 바꿔서 왕복하고, 바뀐 요소를 돌려준다 */
  function propsTrip(tag, oldProps, newProps) {
    const { box } = roundTrip(root(h(tag, oldProps)), root(h(tag, newProps)));
    return box.firstChild;
  }

  test("#146 id 변경", () => assertEqual(propsTrip("p", { id: "a" }, { id: "b" }).id, "b"));
  test("#147 class 변경", () => assertEqual(propsTrip("p", { class: "a b" }, { class: "c" }).className, "c"));
  test("#148 title 변경", () => assertEqual(propsTrip("p", { title: "a" }, { title: "b" }).title, "b"));
  test("#149 style 변경", () => assertEqual(propsTrip("p", { style: "color: red;" }, { style: "color: blue;" }).style.color, "blue"));
  test("#150 data-* 변경", () => assertEqual(propsTrip("p", { "data-x": "1" }, { "data-x": "2" }).dataset.x, "2"));
  test("#151 aria-* 변경", () => assertEqual(propsTrip("p", { "aria-label": "a" }, { "aria-label": "b" }).getAttribute("aria-label"), "b"));
  test("#152 불리언 속성 추가", () => assertEqual(propsTrip("button", {}, { disabled: "" }).disabled, true));
  test("#153 불리언 속성 삭제", () => assertEqual(propsTrip("button", { disabled: "" }, {}).disabled, false));
  test("#154 빈 속성 추가", () => assertEqual(propsTrip("p", {}, { title: "" }).getAttribute("title"), ""));
  test("#155 빈 속성 삭제", () => assertEqual(propsTrip("p", { title: "" }, {}).hasAttribute("title"), false));
  test("#156 특수문자 속성값", () => assertEqual(propsTrip("p", { title: "a" }, { title: "<>&'\"/=" }).title, "<>&'\"/="));
  test("#157 따옴표가 든 속성값", () => assertEqual(propsTrip("p", {}, { title: `say "hi" & 'bye'` }).title, `say "hi" & 'bye'`));
  test("#158 역슬래시가 든 속성값", () => assertEqual(propsTrip("p", {}, { title: "C:\\temp\\n" }).title, "C:\\temp\\n"));
  test("#159 대소문자만 다른 속성명 (Title → title) 도 속성이 남아 있음", () => {
    const old = root(h("p", { title: "a" }));
    const box = render(old);
    patch(box, diff(old, root(h("p", { Title: "a" }))));
    assertEqual(box.firstChild.getAttribute("title"), "a");
  });
  test("#160 속성 순서만 다름 → 변경 없음", () => assertEqual(diff(root(h("p", { a: "1", b: "2" })), root(h("p", { b: "2", a: "1" }))), []));
  test("#161 같은 값으로 다시 설정 → 변경 없음", () => assertEqual(diff(root(h("p", { a: "1" })), root(h("p", { a: "1" }))), []));
  test("#162 없는 속성을 지워도 오류 없음", () => {
    const box = render(root(h("p")));
    patch(box, [{ type: PATCH.PROPS, path: [0], set: {}, remove: ["nope"] }]);
    assertEqual(box.firstChild.attributes.length, 0);
  });
  test("#163 value 속성 변경 (사용자가 입력하기 전이면 화면 값도 따라감)", () => assertEqual(propsTrip("input", { value: "a" }, { value: "b" }).value, "b"));
  test("#164 checked 속성 변경", () => {
    assertEqual(propsTrip("input", { type: "checkbox" }, { type: "checkbox", checked: "" }).checked, true);
    assertEqual(propsTrip("input", { type: "checkbox", checked: "" }, { type: "checkbox" }).checked, false);
  });
  test("#165 selected 속성 변경", () => {
    const opt = (v, sel) => h("option", sel ? { value: v, selected: "" } : { value: v }, v);
    const { box } = roundTrip(root(h("select", null, opt("a", true), opt("b"))), root(h("select", null, opt("a"), opt("b", true))));
    assertEqual(box.firstChild.value, "b");
  });
  test("#166 disabled 속성 변경", () => assertEqual(propsTrip("input", {}, { disabled: "" }).disabled, true));
  test("#167 이벤트 핸들러처럼 생긴 문자열도 그냥 텍스트 값", () => {
    window.__case167 = 0;
    const el = propsTrip("p", {}, { "data-handler": "window.__case167 = 1" });
    assertEqual(el.dataset.handler, "window.__case167 = 1");
    assertEqual(window.__case167, 0);
  });
  test("#168 onerror 속성 문자열은 속성으로 설정됨 (div 는 오류 이벤트가 없어 실행되지 않음)", () => {
    window.__case168 = 0;
    const el = propsTrip("div", {}, { onerror: "window.__case168 = 1" });
    assertEqual(el.getAttribute("onerror"), "window.__case168 = 1");
    assertEqual(window.__case168, 0);
  });
  test("#169 onclick 속성 문자열은 브라우저가 핸들러로 등록함 (patch 만으로는 실행되지 않음 — 보안 주의)", () => {
    window.__case169 = 0;
    const el = propsTrip("button", {}, { onclick: "window.__case169 = 1" });
    assertEqual(typeof el.onclick, "function");
    assertEqual(window.__case169, 0);
  });
  test("#170 잘못된 속성값: 객체 → \"[object Object]\", undefined → 제거, NaN → \"NaN\"", () => {
    const el = createElement(h("p", { a: { x: 1 }, b: undefined, c: NaN, d: 0 }));
    assertEqual(el.getAttribute("a"), "[object Object]");
    assertEqual(el.hasAttribute("b"), false);
    assertEqual(el.getAttribute("c"), "NaN");
    assertEqual(el.getAttribute("d"), "0");
  });
});
