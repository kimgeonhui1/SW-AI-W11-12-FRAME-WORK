// [diff.test.js] diff / patch 단위 테스트 (브라우저에서 diff.test.html로 실행)
// 테스트 도구(test / assertEqual / 결과 출력)는 vdom.test.js와 같은 방식이다.

import { h, domToVdom, createElement } from "../src/core/vdom.js";
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

const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const passed = results.filter((r) => r.ok).length;
document.getElementById("results").innerHTML =
  `<h2>${passed} / ${results.length} passed</h2>` +
  results
    .map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`)
    .join("");
console.table(results);
