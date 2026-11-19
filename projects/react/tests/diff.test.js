// [diff.test.js] diff / patch 단위 테스트 (브라우저에서 diff.test.html로 실행)
// 테스트 도구(test / assertEqual / 결과 출력)는 vdom.test.js와 같은 방식이다.

import { h, domToVdom, createElement, commitLiveState } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";

const results = [];

function test(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, message: e.message });
  }
}

// 키 순서가 달라도 내용이 같으면 같은 문자열이 되도록 정렬해서 직렬화
function stableStringify(value) {
  return JSON.stringify(value, (key, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]]))
      : v
  );
}

function assertEqual(actual, expected, msg = "") {
  const a = stableStringify(actual);
  const e = stableStringify(expected);
  if (a !== e) throw new Error(`${msg}\n  기대: ${e}\n  실제: ${a}`);
}

/**
 * patch 검증 도우미: oldVNode로 그린 DOM에 diff → patch를 적용한 뒤,
 * 그 DOM을 다시 읽은 VDOM이 newVNode와 같은지 확인한다. (patch 후 화면 = 새 VDOM 이어야 한다)
 * 확인 후 container를 돌려줘서 테스트가 노드 재사용 여부 등을 추가로 볼 수 있게 한다.
 */
function patchAndCheck(oldVNode, newVNode) {
  const container = document.createElement("div");
  container.appendChild(createElement(oldVNode));
  patch(container, diff(oldVNode, newVNode));
  assertEqual(domToVdom(container.firstChild), newVNode, "patch 결과가 새 VDOM과 다름");
  assertEqual(container.childNodes.length, 1, "루트가 하나가 아님");
  return container;
}

// ======================================================================
// diff: 반환 형식
// ======================================================================

test("diff: 같으면 null", () => {
  const vnode = () => h("div", { id: "a", style: { color: "red" } }, "hi", h("b", null, "!"));
  assertEqual(diff(vnode(), vnode()), null);
});

test("diff: 텍스트만 바뀌면 TEXT", () => {
  assertEqual(diff("a", "b"), { type: "TEXT", text: "b" });
});

test("diff: 태그가 다르면 REPLACE", () => {
  const next = h("p", null, "x");
  assertEqual(diff(h("div", null, "x"), next), { type: "REPLACE", node: next });
});

test("diff: 텍스트 ↔ 요소는 REPLACE", () => {
  const el = h("b", null, "x");
  assertEqual(diff("x", el), { type: "REPLACE", node: el });
  assertEqual(diff(el, "x"), { type: "REPLACE", node: "x" });
});

test("diff: 속성 추가/변경/삭제 (oldValue 포함)", () => {
  const p = diff(h("div", { id: "a", title: "t" }), h("div", { id: "b", className: "c" }));
  assertEqual(p.type, "UPDATE");
  assertEqual(p.props, [
    { name: "id", value: "b", oldValue: "a" },
    { name: "className", value: "c" },
    { name: "title", oldValue: "t" },
  ]);
});

test("diff: style 객체는 내용이 같으면 변경 아님", () => {
  assertEqual(diff(h("div", { style: { color: "red" } }), h("div", { style: { color: "red" } })), null);
});

test("diff: 자식이 늘면 끝에 CREATE, 줄면 끝에 REMOVE", () => {
  const a = h("ul", null, h("li", null, "1"));
  const b = h("ul", null, h("li", null, "1"), h("li", null, "2"));
  assertEqual(diff(a, b).children, [null, { type: "CREATE", node: h("li", null, "2") }]);
  assertEqual(diff(b, a).children, [null, { type: "REMOVE" }]);
});

// ======================================================================
// patch: 실제 DOM 반영
// ======================================================================

test("patch: 텍스트 변경 시 노드를 재사용", () => {
  const container = document.createElement("div");
  const old = h("p", null, "a");
  container.appendChild(createElement(old));
  const textNode = container.firstChild.firstChild;
  patch(container, diff(old, h("p", null, "b")));
  assertEqual([container.innerHTML, container.firstChild.firstChild === textNode], ["<p>b</p>", true]);
});

test("patch: 속성 추가/변경/삭제", () => {
  patchAndCheck(h("div", { id: "a", title: "t" }), h("div", { id: "b", className: "c" }));
});

test("patch: disabled true → false 면 속성 제거", () => {
  // disabled: false 는 "속성 없음"이라 다시 읽으면 props에 아예 없다 → { disabled: false } 대신 {} 와 비교
  const container = document.createElement("div");
  const old = h("button", { disabled: true }, "x");
  container.appendChild(createElement(old));
  patch(container, diff(old, h("button", { disabled: false }, "x")));
  assertEqual([container.firstChild.disabled, container.firstChild.hasAttribute("disabled")], [false, false]);
});

test("patch: style 키 제거", () => {
  patchAndCheck(h("div", { style: { color: "red", fontSize: "12px" } }), h("div", { style: { color: "blue" } }));
});

test("patch: 태그 교체 (REPLACE)", () => {
  patchAndCheck(h("div", null, h("p", null, "x")), h("div", null, h("section", null, "x")));
});

test("patch: 자식 여러 개 추가 (순서 유지)", () => {
  patchAndCheck(
    h("ul", null, h("li", null, "1")),
    h("ul", null, h("li", null, "1"), h("li", null, "2"), h("li", null, "3"), "끝")
  );
});

test("patch: 자식 여러 개 삭제 (인덱스 당겨짐에 안 꼬임)", () => {
  patchAndCheck(
    h("ul", null, h("li", null, "1"), h("li", null, "2"), h("li", null, "3"), "끝"),
    h("ul", null, h("li", null, "1"))
  );
});

test("patch: 앞 항목 삭제 (같은 위치끼리 비교 → 내용 갱신 + 끝 삭제)", () => {
  patchAndCheck(
    h("ul", null, h("li", null, "1"), h("li", null, "2"), h("li", null, "3")),
    h("ul", null, h("li", null, "2"), h("li", null, "3"))
  );
});

test("patch: 깊은 중첩 변경", () => {
  patchAndCheck(
    h("div", null, h("section", null, h("p", { id: "x" }, "a", h("b", null, "b")))),
    h("div", null, h("section", null, h("p", { id: "y" }, "a", h("i", null, "b"), "c")))
  );
});

test("patch: input value/checked 변경이 화면 값에 반영", () => {
  const c = patchAndCheck(
    h("div", null, h("input", { value: "a" }), h("input", { type: "checkbox", checked: true })),
    h("div", null, h("input", { value: "b" }), h("input", { type: "checkbox" }))
  );
  assertEqual([c.firstChild.children[0].value, c.firstChild.children[1].checked], ["b", false]);
});

test("patch: 이벤트 핸들러 교체 시 최신 것만 실행", () => {
  const calls = [];
  const container = document.createElement("div");
  const old = h("button", { onClick: () => calls.push("old") });
  container.appendChild(createElement(old));
  patch(container, diff(old, h("button", { onClick: () => calls.push("new") })));
  container.firstChild.click();
  assertEqual(calls, ["new"]);
});

// [회귀] 리뷰에서 발견: 속성을 자식보다 먼저 바꾸면 아직 없는 option을 고르려 해서 무시됐다
// (domToVdom은 선택 상태를 option의 selected로 기록해서 select value 방식 VDOM과 모양이 달라 patchAndCheck 대신 화면 값을 직접 본다)
test("patch: select에 option 추가 + value 변경을 함께 반영", () => {
  const old = h("select", { value: "a" }, h("option", { value: "a" }, "A"));
  const container = document.createElement("div");
  container.appendChild(createElement(old));
  patch(container, diff(old, h("select", { value: "b" }, h("option", { value: "a" }, "A"), h("option", { value: "b" }, "B"))));
  assertEqual([container.firstChild.value, container.firstChild.options.length], ["b", 2]);
});

// [회귀] 화면에서 읽은 VDOM(option에 selected)을 select value 방식 VDOM으로 patch해도 선택이 유지돼야 한다
test("patch: domToVdom으로 읽은 select를 같은 h로 patch해도 선택 유지", () => {
  const vnode = h("select", { value: "b" }, h("option", { value: "a" }, "A"), h("option", { value: "b" }, "B"));
  const container = document.createElement("div");
  container.appendChild(createElement(vnode));
  patch(container, diff(domToVdom(container.firstChild), vnode));
  assertEqual(container.firstChild.value, "b");
});

// [회귀] 리뷰에서 발견: 값이 undefined인 키와 "키 없음"을 같다고 봐서 style 변경을 놓쳤다
test("diff: style 키가 바뀌면 값이 undefined여도 변경으로 판단", () => {
  const p = diff(h("div", { style: { color: undefined } }), h("div", { style: { fontSize: "12px" } }));
  assertEqual(p === null ? null : p.type, "UPDATE");
});

// [회귀] select value는 그대로인데 선택돼 있던 option의 value가 바뀌면 select가 따라 바뀌던 문제
test("patch: select value 그대로 + 자식 option 변경 시 value 유지", () => {
  const old = h("select", { value: "b" }, h("option", { value: "a" }, "A"), h("option", { value: "b" }, "B"));
  const next = h("select", { value: "b" }, h("option", { value: "a" }, "A"), h("option", { value: "c" }, "C"), h("option", { value: "b" }, "B"));
  const container = document.createElement("div");
  container.appendChild(createElement(old));
  patch(container, diff(old, next));
  assertEqual(container.firstChild.value, "b");
});

// [회귀] value를 넣은 적 있는 textarea(dirty)는 자식 텍스트만 바꾸면 화면 값이 안 바뀌던 문제
test("patch: value를 뺀 textarea의 자식 텍스트 변경이 화면 값에 반영", () => {
  const v1 = h("textarea", { value: "임시" }, "초기1");
  const v2 = h("textarea", null, "초기1");
  const v3 = h("textarea", null, "초기2");
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  patch(container, diff(v1, v2));
  patch(container, diff(v2, v3));
  assertEqual(container.firstChild.value, "초기2");
});

// value가 바뀌면서 자식도 바뀌는 경우 value 항목이 한 번만 들어가야 한다
test("diff: select 자식+value 동시 변경 시 value 항목은 하나", () => {
  const p = diff(
    h("select", { value: "a" }, h("option", { value: "a" }, "A")),
    h("select", { value: "b" }, h("option", { value: "a" }, "A"), h("option", { value: "b" }, "B"))
  );
  assertEqual(p.props.filter((x) => x.name === "value").length, 1);
});

// value prop이 없는 select도 자식이 바뀌면 "기본 선택으로 되돌리기"(value: undefined) 항목을 넣는다
// (option이 바뀌면 브라우저가 이전 선택을 그대로 두어서, 새로 그린 결과와 달라질 수 있기 때문)
test("diff: value 없는 select도 자식이 바뀌면 value: undefined 재동기화", () => {
  const p = diff(h("select", null, h("option", null, "A")), h("select", null, h("option", null, "A"), h("option", null, "B")));
  assertEqual(p.props, [{ name: "value" }]);
});

// [회귀] { value: undefined }는 "value 없음"이라 선택이 ""로 풀리면 안 된다
test("patch: select value가 undefined면 자식 변경 시 선택 유지", () => {
  const old = h("select", { value: undefined }, h("option", { value: "a" }, "A"));
  const next = h("select", { value: undefined }, h("option", { value: "a" }, "A"), h("option", { value: "b" }, "B"));
  const container = document.createElement("div");
  container.appendChild(createElement(old));
  patch(container, diff(old, next));
  assertEqual(container.firstChild.value, "a");
});

// [회귀] value "b" → 없음 으로 바꾼 select가 "b"로 남아 새로 그린 결과("a")와 달랐던 문제
test("patch: select value를 빼면 새로 그린 것과 같은 선택", () => {
  const opts = (attrs = {}) => [h("option", { value: "a", ...attrs.a }, "A"), h("option", { value: "b" }, "B"), h("option", { value: "c", ...attrs.c }, "C")];
  const cases = [
    h("select", null, ...opts()),                                             // 기본 → 첫 option
    h("select", null, ...opts({ c: { selected: true } })),                    // selected 붙은 option
    h("select", null, ...opts({ a: { disabled: true } })),                    // 첫 option이 disabled → 다음 option
  ];
  for (const next of cases) {
    const old = h("select", { value: "b" }, ...next.children);
    const container = document.createElement("div");
    container.appendChild(createElement(old));
    patch(container, diff(old, next));
    assertEqual(container.firstChild.value, createElement(next).value);
  }
});

// ======================================================================
// 핵심 약속 검사: "old → new 로 patch한 화면 = new를 처음부터 그린 화면"
// 사례를 하나씩 적는 대신, 여러 VDOM 샘플의 "모든 쌍"을 patch해서 createElement(new)와 비교한다.
// 화면 비교는 domToVdom으로 한다 (input value / checked / select 선택 / textarea 값 같은 현재 상태까지 읽기 때문)
// ======================================================================

const option = (value, props = {}) => h("option", { value, ...props }, value.toUpperCase());
const SAMPLES = [
  h("div", null),
  h("div", { id: "x", className: "a" }, "text"),
  h("div", { style: { color: "red", fontSize: "12px" } }, h("p", null, "a"), h("p", null, "b")),
  h("div", { title: "t" }, h("ul", null, h("li", null, "1"), h("li", null, "2"), h("li", null, "3"))),
  h("div", null, h("input", { value: "a" }), h("input", { type: "checkbox", checked: true })),
  h("div", null, h("input", { value: "b", disabled: true }), h("input", { type: "checkbox" })),
  h("div", null, h("select", { value: "b" }, option("a"), option("b"), option("c"))),
  h("div", null, h("select", null, option("a"), option("b", { selected: true }))),
  h("div", null, h("select", { value: "c" }, option("a"), option("c"))),
  h("div", null, h("select", null, option("a", { disabled: true }), option("b"), option("c"))),
  h("div", null, h("select", null, option("a"), option("b"), option("c"))),
  h("div", null, h("select", { multiple: true }, option("a", { selected: true }), option("b"), option("c", { selected: true }))),
  h("div", null, h("select", { multiple: true }, option("a"), option("b", { selected: true }))),
  // 아래는 2차 리뷰(Gemini)가 "아직 깨질 것"이라고 제안한 샘플들
  h("div", null, h("select", null, option("a", { selected: true }), option("b"), option("c", { selected: true }))),
  h("div", null, h("select", null, h("optgroup", { label: "G", disabled: true }, option("a")), option("b"))),
  h("div", null, h("select", { value: "b" }, h("optgroup", { label: "G", disabled: true }, option("a")), option("b"))),
  h("div", null, h("select", { size: 3 }, option("a"), option("b"), option("c"))),
  h("div", null, h("input", { type: "checkbox", checked: true }), h("input", { value: "a" })),
  h("div", null, h("input", { type: "checkbox" }), h("input", null)),
  h("div", null, h("input", { type: "radio", name: "g", value: "1", checked: true }), h("input", { type: "radio", name: "g", value: "2" })),
  h("div", null, h("input", { type: "radio", name: "g", value: "1" }), h("input", { type: "radio", name: "g", value: "2", checked: true })),
  // 3차 리뷰(Gemini) 제안 샘플
  h("div", null, h("select", { size: 3, value: "b" }, option("a"), option("b"), option("c"))),
  h("div", null, h("input", { type: "radio", name: "g", value: "1", checked: true }), h("input", { type: "radio", name: "g", value: "2" }), h("input", { type: "radio", name: "g", value: "3", checked: true })),
  h("div", null, h("input", { type: "range", max: "200", value: "150" })),
  h("div", null, h("input", { type: "range", value: "300", max: "500" })),
  h("div", null, h("textarea", { value: "v" }, "init")),
  h("div", null, h("textarea", null, "init2")),
  h("div", null, "text", h("b", null, "bold"), "tail"),
  h("span", null, "x"),
  // key 리스트 (보강): 삭제 / 순서 변경 / 앞 삽입 / key 없는 자식이 섞인 경우 / 텍스트가 섞인 경우
  h("ul", null, keyed("a"), keyed("b"), keyed("c")),
  h("ul", null, keyed("c"), keyed("a")),
  h("ul", null, keyed("d"), keyed("b"), "텍스트", keyed("a", { value: "x" })),
  h("ul", null, h("li", null, "키 없음"), keyed("a"), keyed("a")),
  h("ul", null, keyed("b"), h("p", { key: "a" }, "태그가 다른 같은 key")),
  // SVG (보강)
  h("div", null, h("svg", { viewBox: "0 0 10 10" }, h("circle", { r: "1", fill: "red" }))),
  h("div", null, h("svg", null, h("rect", { width: "2" }), h("foreignObject", null, h("p", null, "html")))),
];
// key가 있는 li. value는 li의 value 속성(번호)이 아니라 구분용 title로 쓴다
function keyed(key, { value } = {}) {
  return h("li", { key, title: value ?? key }, key.toUpperCase());
}

// container 안의 현재 화면과 createElement(expected)가 같은지 비교. 다르면 어느 전환인지 알려 준다
function assertSameAsFresh(container, expected, label) {
  assertEqual(domToVdom(container.firstChild), domToVdom(createElement(expected)), label);
}

test("약속: 모든 샘플 쌍에서 patch 결과 = 새로 그린 결과", () => {
  // 실패를 전부 모아서 보여 준다 (첫 실패에서 멈추면 같은 원인의 다른 경우를 못 보기 때문)
  const failures = [];
  SAMPLES.forEach((old, i) =>
    SAMPLES.forEach((next, j) => {
      const container = document.createElement("div");
      container.appendChild(createElement(old));
      patch(container, diff(old, next));
      try {
        assertSameAsFresh(container, next, "");
      } catch {
        failures.push(`${i}→${j}`);
      }
    })
  );
  if (failures.length) throw new Error(`실패한 전환 ${failures.length}개: ${failures.join(", ")}`);
});

// 한 컨테이너에서 계속 patch하면 textarea dirty flag처럼 "이전 patch가 남긴 상태"가 쌓인다. 그 상태에서도 약속이 지켜져야 한다
test("약속: 한 화면에서 모든 전환을 연속으로 patch해도 결과 = 새로 그린 결과", () => {
  const container = document.createElement("div");
  let current = SAMPLES[0];
  container.appendChild(createElement(current));
  SAMPLES.forEach((_, i) =>
    SAMPLES.forEach((next, j) => {
      patch(container, diff(current, next));
      assertSameAsFresh(container, next, `연속 전환 중 (${i}, ${j})`);
      current = next;
    })
  );
});

// [회귀] patch에서도 value가 max보다 먼저 적용되면 이전 max에 걸려 값이 잘리던 문제
test("patch: range의 max와 value가 함께 바뀌어도 값이 안 잘림", () => {
  const old = h("input", { type: "range", max: "200", value: "150" });
  const container = document.createElement("div");
  container.appendChild(createElement(old));
  patch(container, diff(old, h("input", { type: "range", value: "300", max: "500" })));
  assertEqual(container.firstChild.value, "300");
});

test("patch: 루트 교체", () => {
  patchAndCheck(h("div", null, "a"), h("span", null, "a"));
});

test("patch: null 패치는 아무것도 안 함", () => {
  const container = document.createElement("div");
  container.innerHTML = "<p>a</p>";
  patch(container, null);
  assertEqual(container.innerHTML, "<p>a</p>");
});

// ======================================================================
// 결과 출력
// ======================================================================

// ======================================================================
// 보강: key / SVG / ref
// ======================================================================

// key 있는 리스트를 그리고, 이전→새로 patch한 뒤 [컨테이너, 이전 li 노드들]을 돌려준다
function keyedPatch(oldKeys, newKeys) {
  const list = (keys) => h("ul", null, ...keys.map((k) => h("li", { key: k }, k)));
  const container = document.createElement("div");
  container.appendChild(createElement(list(oldKeys)));
  const before = [...container.firstChild.childNodes];
  patch(container, diff(list(oldKeys), list(newKeys)));
  assertEqual(domToVdom(container.firstChild), domToVdom(createElement(list(newKeys))), "patch 결과");
  return [container, before];
}

test("key: 앞 항목 삭제 → 나머지 노드는 재사용되고 내용 변경 없음", () => {
  const [c, [, b, cc]] = keyedPatch(["a", "b", "c"], ["b", "c"]);
  const now = [...c.firstChild.childNodes];
  assertEqual([now[0] === b, now[1] === cc], [true, true]);
});

test("key: 앞에 삽입 / 순서 뒤집기 → 기존 노드를 그대로 옮김", () => {
  const [c1, [a, b]] = keyedPatch(["a", "b"], ["new", "a", "b"]);
  const n1 = [...c1.firstChild.childNodes];
  const [c2, [x, y, z]] = keyedPatch(["x", "y", "z"], ["z", "y", "x"]);
  const n2 = [...c2.firstChild.childNodes];
  assertEqual([n1[1] === a, n1[2] === b, n2[0] === z, n2[1] === y, n2[2] === x], [true, true, true, true, true]);
});

test("key: 노드에 붙은 상태(직접 입력한 값)가 항목을 따라감 (index 비교에서는 다른 항목에 남던 문제)", () => {
  const list = (keys) => h("ul", null, ...keys.map((k) => h("li", { key: k }, h("input", null))));
  const container = document.createElement("div");
  container.appendChild(createElement(list(["a", "b"])));
  container.querySelectorAll("input")[1].value = "b에 입력";
  patch(container, diff(list(["a", "b"]), list(["b"])));
  assertEqual(container.querySelector("input").value, "b에 입력");
});

test("key: 순서도 내용도 그대로면 null, key만 다르면(속성 변경 아님) 순서 패치", () => {
  const list = (...keys) => h("ul", null, ...keys.map((k) => h("li", { key: k }, "x")));
  assertEqual(diff(list("a", "b"), list("a", "b")), null);
  const p = diff(list("a", "b"), list("b", "a"));
  assertEqual([p.props, p.order, p.removed], [[], [1, 0], []]);
});

test("SVG: patch로 새로 만든 요소(CREATE / REPLACE / key 삽입)도 SVG 이름공간", () => {
  const SVG = "http://www.w3.org/2000/svg";
  const container = document.createElement("div");
  const v1 = h("svg", null, h("rect"));
  const v2 = h("svg", null, h("circle"), h("g", null, h("path", { key: "p" })), h("line"));
  container.appendChild(createElement(v1));
  patch(container, diff(v1, v2));
  const names = [...container.firstChild.querySelectorAll("*")].map((el) => `${el.localName}:${el.namespaceURI === SVG}`);
  assertEqual(names, ["circle:true", "g:true", "path:true", "line:true"]);
});

test("ref: REMOVE / REPLACE 되면 null, 같은 ref를 새 요소가 받으면 새 요소를 가리킴", () => {
  const ref = { current: null };
  const container = document.createElement("div");
  const v1 = h("div", null, h("input", { ref }));
  const v2 = h("div", null, h("textarea", { ref })); // 태그가 달라 REPLACE
  const v3 = h("div", null);
  container.appendChild(createElement(v1));
  patch(container, diff(v1, v2));
  const afterReplace = ref.current?.tagName;
  patch(container, diff(v2, v3));
  assertEqual([afterReplace, ref.current], ["TEXTAREA", null]);
});

// ======================================================================
// 4차 리뷰 재현 테스트
// ======================================================================

test("ref: 같은 함수 ref가 뒤 형제 → 앞 형제로 옮겨가도 마지막 값은 새 요소 (해제가 연결보다 먼저)", () => {
  let saved = "초기값";
  const fnRef = (el) => (saved = el);
  const v1 = h("div", null, h("p", null, "A"), h("p", { ref: fnRef }, "B"));
  const v2 = h("div", null, h("p", { ref: fnRef }, "A"), h("p", null, "B"));
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  patch(container, diff(v1, v2));
  assertEqual(saved === container.firstChild.firstChild, true, "saved가 첫 번째 p여야 함");
});

test("key 섞임: 앞에 key 항목이 추가돼도 key 없는 자식은 재사용 (key 없는 것끼리의 순번으로 짝지음)", () => {
  const v1 = h("div", null, h("p", { key: "k1" }, "고정"), h("span", null, "유지"));
  const v2 = h("div", null, h("b", { key: "k0" }, "새항목"), h("p", { key: "k1" }, "고정"), h("span", null, "유지"));
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  const span = container.querySelector("span");
  patch(container, diff(v1, v2));
  assertEqual([container.querySelector("span") === span, domToVdom(container.firstChild)], [true, domToVdom(createElement(v2))]);
});

// ── 2차 개선 (버그 검거 후 보완) ──

const keyedList = (keys) => h("ul", null, ...keys.map((k) => h("li", { key: k }, h("input", { id: `in-${k}` }), k)));

test("key 이동 최소화: 첫 항목을 맨 뒤로 → 1개만 옮기고, 입력 중인 다른 항목의 포커스 유지", () => {
  const container = document.createElement("div");
  document.body.appendChild(container); // 포커스는 문서에 붙은 요소에서만 동작한다
  try {
    const v1 = keyedList(["A", "B", "C", "D"]);
    container.appendChild(createElement(v1));
    const ul = container.firstChild;
    let moves = 0;
    const insertBefore = ul.insertBefore.bind(ul);
    ul.insertBefore = (n, r) => (moves++, insertBefore(n, r));
    container.querySelector("#in-C").focus();
    patch(container, diff(v1, keyedList(["B", "C", "D", "A"])));
    assertEqual([moves, document.activeElement?.id, domToVdom(ul)], [1, "in-C", domToVdom(createElement(keyedList(["B", "C", "D", "A"])))]);
  } finally {
    container.remove();
  }
});

test("key 무작위 300회: 삽입·삭제·섞기를 섞어도 patch 결과 = 새로 그린 결과, 남은 항목은 같은 노드 재사용", () => {
  let seed = 7;
  const rand = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const randomKeys = () => {
    const keys = [..."abcdefgh"].filter(() => rand() < 0.6);
    for (let i = keys.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1));
      [keys[i], keys[j]] = [keys[j], keys[i]];
    }
    return keys;
  };
  for (let n = 0; n < 300; n++) {
    const [k1, k2] = [randomKeys(), randomKeys()];
    const [v1, v2] = [keyedList(k1), keyedList(k2)];
    const container = document.createElement("div");
    container.appendChild(createElement(v1));
    const before = new Map([...container.firstChild.children].map((li, i) => [k1[i], li]));
    patch(container, diff(v1, v2));
    const after = [...container.firstChild.children];
    assertEqual(domToVdom(container.firstChild), domToVdom(createElement(v2)), `${k1} → ${k2}`);
    k2.forEach((k, i) => {
      if (before.has(k) && before.get(k) !== after[i]) throw new Error(`${k1} → ${k2}: ${k}가 재사용되지 않음`);
    });
  }
});

test("ref 교체: current가 우연히 같은 다른 ref 객체로 바꿔도 새 ref가 연결됨 (얕은 비교는 style만)", () => {
  const r1 = { current: null };
  const r2 = { current: null };
  const v1 = h("div", null, h("p", { ref: r1 }));
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  r1.current = null; // r1과 r2의 내용이 같아지는 상황을 만든다
  patch(container, diff(v1, h("div", null, h("p", { ref: r2 }))));
  assertEqual(r2.current === container.querySelector("p"), true, "r2가 p를 가리켜야 함");
});

test("<template>: 내용(content)까지 읽고, 만들고, patch로 고침", () => {
  const w = document.createElement("div");
  w.innerHTML = "<template><p>x</p></template>";
  const v1 = domToVdom(w.firstChild);
  assertEqual(v1, h("template", null, h("p", null, "x")), "domToVdom이 content를 읽음");
  const v2 = h("template", null, h("p", null, "y"), h("b", null, "z"));
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  patch(container, diff(v1, v2));
  assertEqual(domToVdom(container.firstChild), v2);
});

test("Phase 1 흐름: 사용자가 select 선택을 바꾼 뒤 Patch해도 새로 그린 화면과 같음 (commitLiveState, 무작위 테스트로 발견)", () => {
  // 사용자가 o2를 골랐다 (property만 바뀌고 selected attribute는 없음)
  const v1 = h("div", null, h("select", null, h("option", { value: "o1" }, "o1"), h("option", { value: "o2" }, "o2"), h("option", { value: "o3" }, "o3")));
  const v2 = h("div", null, h("select", null, h("option", { value: "o2" }, "o2"), h("option", { value: "o3", selected: true }, "o3")));
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  container.querySelector("select").value = "o2";
  commitLiveState(container.firstChild);
  patch(container, diff(domToVdom(container.firstChild), v2));
  const fresh = createElement(v2);
  assertEqual(container.querySelector("select").value, fresh.querySelector("select").value, "선택된 값");
});

// ── 4차 리뷰 (팀원 테스트 722개로 발견) ──

test("4차 리뷰: 대소문자만 다른 속성으로 바뀌어도 사라지지 않음 ({ Title } → { title })", () => {
  const v1 = h("div", null, h("p", { Title: "a" }));
  const v2 = h("div", null, h("p", { title: "a" }));
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  patch(container, diff(v1, v2));
  assertEqual(container.querySelector("p").getAttribute("title"), "a", "삭제를 먼저 해야 방금 넣은 속성이 안 지워짐");
});

test("4차 리뷰: DOM의 __proto__ 속성도 일반 속성으로 읽음 (프로토타입이 바뀌거나 사라지지 않음)", () => {
  const w = document.createElement("div");
  w.innerHTML = '<p __proto__="x">t</p>';
  const v = domToVdom(w.firstChild);
  assertEqual([Object.hasOwn(v.props, "__proto__"), v.props.__proto__ === "x", Object.getPrototypeOf(v.props) === Object.prototype], [true, true, true]);
});

test("4차 리뷰: setAttribute가 거부하는 속성 이름은 그 속성만 건너뛰고 나머지는 그림", () => {
  const warn = console.warn;
  const warned = [];
  console.warn = (m) => warned.push(m);
  try {
    const el = createElement(h("p", { "a b": "1", id: "ok" }, "x"));
    assertEqual([el.id, el.textContent, warned.length], ["ok", "x", 1]);
  } finally {
    console.warn = warn;
  }
});

test("4차 리뷰: h()는 props를 복사함 (만든 뒤 원본을 고쳐도 VNode는 그대로)", () => {
  const props = { id: "a" };
  const v = h("p", props);
  props.id = "b";
  assertEqual(v.props.id, "a");
});

test("4차 리뷰: diff에 잘못된 VNode(null · 숫자 · 배열 · 문자열 props)가 오면 TypeError", () => {
  for (const bad of [null, 5, [], { type: "p", props: "x", children: [] }]) {
    try {
      diff(h("p"), bad);
    } catch (e) {
      if (!(e instanceof TypeError)) throw new Error(`TypeError가 아님: ${e}`);
      continue;
    }
    throw new Error(`에러가 나야 함: ${JSON.stringify(bad)}`);
  }
});

test("4차 리뷰: DOM과 VDOM이 어긋나 대상이 없으면 아무것도 바꾸지 않고 TypeError (전부 적용되거나, 전혀 안 되거나)", () => {
  const v1 = h("div", null, h("p", null, "a"), h("ul", null, h("li", null, "x")));
  const v2 = h("div", null, h("p", null, "A"), h("ul", null, h("li", null, "y")));
  const container = document.createElement("div");
  container.appendChild(createElement(v1));
  container.querySelector("li").remove(); // 누군가 실제 영역을 직접 고쳤다
  const before = container.innerHTML;
  try {
    patch(container, diff(v1, v2));
  } catch (e) {
    if (!(e instanceof TypeError)) throw e;
    assertEqual(container.innerHTML, before, "앞쪽 p의 글자도 바뀌면 안 됨");
    return;
  }
  throw new Error("에러가 나야 함");
});

test("4차 리뷰: createElement에 요소 VNode가 아닌 값(true · {} · 배열)이 오면 TypeError (<undefined> 요소를 만들지 않음)", () => {
  for (const bad of [true, {}, []]) {
    try {
      createElement(bad);
    } catch (e) {
      if (!(e instanceof TypeError)) throw e;
      continue;
    }
    throw new Error(`에러가 나야 함: ${JSON.stringify(bad)}`);
  }
});

test("4차 리뷰: props · children이 없거나 null이어도 diff 통과, props가 Date 같은 객체면 TypeError", () => {
  diff({ type: "p" }, { type: "p", props: null, children: null });
  try {
    diff(h("p"), { type: "p", props: new Date(), children: [] });
  } catch (e) {
    if (e instanceof TypeError) return;
    throw e;
  }
  throw new Error("Date props는 에러가 나야 함");
});

test("4차 리뷰: patch에 모르는 패치 종류나 대상 없는 패치가 오면 TypeError", () => {
  const container = document.createElement("div");
  container.appendChild(createElement(h("p")));
  for (const [c, p] of [[container, { type: "NOPE" }], [document.createElement("div"), { type: "TEXT", text: "x" }]]) {
    try {
      patch(c, p);
    } catch (e) {
      if (!(e instanceof TypeError) || !e.message.startsWith("[patch]")) throw new Error(`기대한 에러가 아님: ${e.message}`);
      continue;
    }
    throw new Error(`에러가 나야 함: ${JSON.stringify(p)}`);
  }
});

// ── 무작위(퍼즈) 테스트: 사람이 떠올리지 못한 조합을 찾는다. 시드를 고정해서 매번 같은 화면 쌍으로 돈다 ──

function makeRandom(seed) {
  let s = seed;
  const r = () => (s = (s * 1103515245 + 12345) % 2147483648) / 2147483648;
  const pick = (a) => a[Math.floor(r() * a.length)];
  function formProps(tag) {
    const p = {};
    if (r() < 0.3) p.className = pick(["c1", "c2", ""]);
    if (r() < 0.2) p.style = pick([{ color: "red" }, { color: "blue", width: 10 }, { "--g": "2px" }, "margin: 1px"]);
    if (tag === "input") {
      p.type = pick(["text", "checkbox", "range", "radio"]);
      if (p.type === "checkbox" || p.type === "radio") {
        if (r() < 0.6) p.checked = true;
        if (p.type === "radio") p.name = "fuzz";
      } else {
        if (r() < 0.7) p.value = pick(["", "v", "30", "200"]);
        if (p.type === "range" && r() < 0.5) p.max = pick(["50", "500"]);
      }
    }
    if (tag === "textarea" && r() < 0.5) p.value = pick(["", "tv"]);
    if (tag === "select" && r() < 0.3) p.multiple = true;
    if (tag === "option" && r() < 0.4) p.selected = true;
    return p;
  }
  function node(depth) {
    if (depth > 2 || r() < 0.2) return pick(["a", "글", " "]);
    const tag = pick(["div", "p", "input", "textarea", "select", "ul", "pre", "svg", "template"]);
    if (tag === "input") return h("input", formProps(tag));
    if (tag === "textarea") return h("textarea", formProps(tag), r() < 0.5 ? "ta" : null);
    if (tag === "select") return h("select", formProps(tag), ...["o1", "o2", "o3"].filter(() => r() < 0.8).map((o) => h("option", { ...formProps("option"), value: o }, o)));
    if (tag === "pre") return h("pre", null, pick(["\n\nx", " y ", "z\n"]));
    if (tag === "svg") return h("svg", { viewBox: "0 0 9 9" }, ...Array.from({ length: Math.floor(r() * 3) }, () => h(pick(["circle", "rect"]), { r: pick(["1", "2"]) })));
    if (tag === "ul") {
      const keyed = r() < 0.7;
      const keys = [..."abcde"].filter(() => r() < 0.6).sort(() => r() - 0.5);
      return h("ul", null, ...keys.map((k) => h(pick(["li", "li", "p"]), keyed ? { key: k } : {}, k, r() < 0.4 ? h("input", { value: k }) : null)));
    }
    return h(tag, formProps(tag), ...Array.from({ length: Math.floor(r() * 3) }, () => node(depth + 1)));
  }
  // 사용자가 화면을 건드린다 (입력, 체크, 선택 변경)
  function touch(el) {
    for (const f of el.querySelectorAll("input, textarea, select")) {
      if (r() < 0.5) continue;
      if (f.type === "checkbox" || f.type === "radio") f.checked = !f.checked;
      else if (f.tagName === "SELECT") for (const o of f.options) o.selected = r() < 0.5;
      else f.value = pick(["typed", "77", ""]);
    }
  }
  return { tree: () => h("div", null, node(0), node(0)), touch };
}

// 화면 비교용: VDOM(속성 순서 무시) + 폼의 현재 상태 + template 내용 + SVG 이름공간
function screenOf(el) {
  const forms = [...el.querySelectorAll("input, textarea, select")].map((f) =>
    f.tagName === "SELECT" ? [...f.options].map((o) => o.selected).join() : f.type === "checkbox" || f.type === "radio" ? String(f.checked) : f.value
  );
  const templates = [...el.querySelectorAll("template")].map((t) => t.innerHTML);
  const namespaces = [...el.querySelectorAll("*")].map((e) => e.namespaceURI.slice(-3));
  return stableStringify(domToVdom(el)) + JSON.stringify([forms, templates, namespaces]);
}

// 한 쌍 검사. container는 문서에 붙여서 검사한다(라디오 그룹·포커스가 실제처럼 동작). 둘을 동시에 붙이면 라디오 그룹이 섞이므로 하나씩
function fuzzPair(a, b, prepare) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  container.appendChild(createElement(a));
  // prepare가 없으면 그린 VDOM(a) 그대로, 있으면 사용자가 건드린 화면을 다시 읽은 VDOM으로 diff (Phase 1 흐름)
  const old = prepare ? prepare(container) : a;
  patch(container, diff(old, b));
  const got = screenOf(container.firstChild);
  container.remove();
  const fresh = document.createElement("div");
  document.body.appendChild(fresh);
  fresh.appendChild(createElement(b));
  const want = screenOf(fresh.firstChild);
  fresh.remove();
  if (got !== want) throw new Error(`patch 결과가 새로 그린 화면과 다름\n  이전: ${stableStringify(a)}\n  새: ${stableStringify(b)}`);
}

test("퍼즈 3,000쌍: key · 폼 · SVG · template을 섞은 무작위 화면 A → B, patch 결과 = 새로 그린 결과", () => {
  const { tree } = makeRandom(12345);
  for (let n = 0; n < 3000; n++) fuzzPair(tree(), tree());
});

test("퍼즈 3,000쌍 (Phase 1 흐름): 사용자가 입력 · 체크 · 선택을 바꾼 뒤 화면을 다시 읽어 Patch해도 결과가 같음", () => {
  const { tree, touch } = makeRandom(999);
  for (let n = 0; n < 3000; n++) {
    fuzzPair(tree(), tree(), (container) => {
      touch(container);
      commitLiveState(container.firstChild);
      return domToVdom(container.firstChild);
    });
  }
});

const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const passed = results.filter((r) => r.ok).length;
document.getElementById("results").innerHTML =
  `<h2>${passed} / ${results.length} passed</h2>` +
  results
    .map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`)
    .join("");
console.table(results);
