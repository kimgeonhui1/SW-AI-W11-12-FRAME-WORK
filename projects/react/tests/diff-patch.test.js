import { h, domToVdom, createElement } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";

const results = document.querySelector("#results");
let passed = 0;
function assert(value, message) {
  if (!value) throw new Error(message);
}
function test(name, run) {
  const item = document.createElement("li");
  try {
    run();
    passed++;
    item.textContent = `PASS — ${name}`;
  } catch (error) {
    item.textContent = `FAIL — ${name}: ${error.message}`;
  }
  results.appendChild(item);
}
function fixture(vnode) {
  const container = document.createElement("div");
  if (vnode !== null) container.appendChild(createElement(vnode));
  return container;
}
function apply(container, before, after) {
  const snapshot = JSON.stringify([before, after]);
  const changes = diff(before, after);
  const root = patch(container, changes);
  assert(snapshot === JSON.stringify([before, after]), "입력 VDOM이 변경됨");
  assert(root === container.firstChild, "반환 root 불일치");
  assert(after === null ? root === null : root.isEqualNode(createElement(after)), "결과 DOM이 목표와 다름");
  return changes;
}

test("동일 VDOM: mutation 0, 모든 DOM identity 유지", () => {
  const before = h("div", { id: "x" }, h("p", {}, "A"), " ");
  const box = fixture(before);
  const root = box.firstChild;
  const text = root.firstChild.firstChild;
  const observer = new MutationObserver(() => {});
  observer.observe(box, { subtree: true, childList: true, characterData: true, attributes: true });
  assert(apply(box, before, structuredClone(before)).length === 0, "빈 diff가 아님");
  assert(observer.takeRecords().length === 0, "불필요한 DOM 조작");
  observer.disconnect();
  assert(box.firstChild === root && root.firstChild.firstChild === text, "identity 손실");
});
test("<p>A</p> → B: p와 Text identity, listener 유지", () => {
  const before = h("p", {}, "A");
  const box = fixture(before);
  const p = box.firstChild;
  const text = p.firstChild;
  let clicked = 0;
  p.addEventListener("click", () => clicked++);
  apply(box, before, h("p", {}, "B"));
  p.click();
  assert(p === box.firstChild && text === p.firstChild && text.data === "B" && clicked === 1, "identity/listener 오류");
});
test("props 추가·수정·제거, 빈 문자열, 변경 없는 속성", () => {
  const before = h("p", { id: "a", title: "remove", class: "keep" });
  const after = h("p", { id: "b", "data-empty": "", class: "keep" });
  const box = fixture(before);
  const p = box.firstChild;
  const observer = new MutationObserver(() => {});
  observer.observe(p, { attributes: true });
  apply(box, before, after);
  const records = observer.takeRecords();
  observer.disconnect();
  assert(records.length === 3 && records.every(r => r.attributeName !== "class"), "불필요한 속성 갱신");
  assert(box.firstChild === p, "요소가 교체됨");
});
test("요소 type 변경: 대상만 교체, 형제 유지", () => {
  const before = h("div", {}, h("p", {}, "A"), h("b", {}, "stay"));
  const box = fixture(before);
  const root = box.firstChild;
  const sibling = root.lastChild;
  const changed = root.firstChild;
  apply(box, before, h("div", {}, h("span", {}, "A"), h("b", {}, "stay")));
  assert(root === box.firstChild && sibling === root.lastChild && changed !== root.firstChild, "교체 범위 오류");
});
test("중간에 여러 자식 추가·삭제: 후속 형제 identity 유지", () => {
  const a = h("i", {}, "A");
  const z = h("b", {}, "Z");
  const before = h("div", {}, a, z);
  const after = h("div", {}, a, "X", h("br"), z);
  const box = fixture(before);
  const first = box.firstChild.firstChild;
  const last = box.firstChild.lastChild;
  apply(box, before, after);
  assert(box.firstChild.firstChild === first && box.firstChild.lastChild === last, "추가 시 identity 손실");
  apply(box, after, before);
  assert(box.firstChild.firstChild === first && box.firstChild.lastChild === last, "삭제 시 identity 손실");
});
test("깊은 변경과 연속 삭제: 이전 트리의 경로 유지", () => {
  const before = h("div", {}, h("section", {}, "a", "b", "c"), h("p", {}, h("b", {}, "old")), "tail");
  const after = h("div", {}, h("section", {}, "a"), h("p", {}, h("b", {}, "new")), "tail");
  const box = fixture(before);
  const nested = box.firstChild.childNodes[1].firstChild.firstChild;
  const tail = box.firstChild.lastChild;
  const changes = apply(box, before, after);
  assert(changes.some(c => c.type === "text" && JSON.stringify(c.path) === "[1,0,0]"), "중첩 path 오류");
  assert(nested === box.firstChild.childNodes[1].firstChild.firstChild && nested.data === "new", "잘못된 Text 갱신");
  assert(tail === box.firstChild.lastChild, "형제가 교체됨");
});
test("빈 children, 끝에 추가·전체 삭제, 빈 Text와 공백", () => {
  const before = h("div");
  const after = h("div", {}, "", " \n", h("br"), "end");
  const box = fixture(before);
  apply(box, before, after);
  apply(box, after, before);
});
test("Text ↔ Element 및 root 교체·삽입·삭제", () => {
  const box = fixture(null);
  const states = [null, "", "text", h("p", {}, "A"), h("section"), "last", null];
  for (let i = 1; i < states.length; i++) apply(box, states[i - 1], states[i]);
});
test("domToVdom이 생략하는 주석이 형제 위치에 영향을 주지 않음", () => {
  const box = document.createElement("div");
  box.innerHTML = "<section>A<!-- keep --><b>B</b>C</section>";
  const root = box.firstChild;
  const comment = root.childNodes[1];
  const b = root.childNodes[2];
  const before = domToVdom(root);
  const after = h("section", {}, "A", h("b", {}, "new"), "C");
  patch(box, diff(before, after));
  assert(root.childNodes[1] === comment && root.childNodes[2] === b && b.textContent === "new", "주석에 의한 위치 오류");
  assert(JSON.stringify(domToVdom(root)) === JSON.stringify(after), "결과 불일치");
});
test("잘못된 후속 경로: 첫 변경도 적용하기 전에 거부", () => {
  const box = fixture(h("p", {}, "A"));
  let rejected = false;
  try {
    patch(box, [{ type: "text", path: [0], value: "B" }, { type: "remove", path: [5] }]);
  } catch { rejected = true; }
  assert(rejected && box.textContent === "A", "부분 적용 발생");
});

test("diff는 입력을 변경하지 않고 이전 트리의 정확한 경로를 반환", () => {
  function freeze(node) {
    if (typeof node === "string") return node;
    node.children.forEach(freeze);
    Object.freeze(node.props);
    Object.freeze(node.children);
    return Object.freeze(node);
  }
  const before = freeze(h("main", {}, h("p", {}, "A"), h("b", {}, "B")));
  const after = freeze(h("main", {}, h("p", {}, "Z")));
  assert(JSON.stringify(diff(before, after)) === JSON.stringify([
    { type: "text", path: [0, 0], value: "Z" }, { type: "remove", path: [1] }
  ]), "diff 경로/연산 불일치");
});
test("앞쪽 삽입·삭제와 마지막 형제 보존", () => {
  const before = h("div", {}, h("b", {}, "keep"));
  const after = h("div", {}, "first", h("i", {}, "second"), h("b", {}, "keep"));
  const box = fixture(before);
  const keep = box.firstChild.firstChild;
  apply(box, before, after);
  assert(box.firstChild.lastChild === keep, "앞쪽 삽입 시 형제 손실");
  apply(box, after, before);
  assert(box.firstChild.firstChild === keep, "앞쪽 삭제 시 형제 손실");
});
test("HTML을 문자열로 유지하고 독립적인 DOM 기대값으로 검증", () => {
  const before = h("p", { title: "old" }, "A");
  const box = fixture(before);
  patch(box, diff(before, h("p", { "data-x": "" }, "<b>B</b>")));
  assert(box.innerHTML === '<p data-x="">&lt;b&gt;B&lt;/b&gt;</p>', "독립 HTML 기대값 불일치");
  assert(box.firstChild.childNodes.length === 1 && box.firstChild.firstChild.nodeType === 3, "문자열이 HTML로 해석됨");
});
test("속성 삽입 순서는 무관하고 prototype 이름도 일반 속성으로 처리", () => {
  const before = h("p", { id: "x", title: "y" });
  const reordered = h("p", { title: "y", id: "x" });
  assert(diff(before, reordered).length === 0, "속성 순서에 따라 diff 발생");
  const after = h("p", JSON.parse('{"__proto__":"safe","constructor":"value"}'));
  const box = fixture(before);
  apply(box, before, after);
  assert(box.firstChild.getAttribute("__proto__") === "safe", "prototype 이름 누락");
  apply(box, after, h("p"));
});
test("앞쪽 삽입과 뒤쪽 텍스트 변경이 겹쳐도 변경 없는 중간 형제 유지", () => {
  const before = h("div", {}, h("i", {}, "A"), h("b", {}, "B"));
  const after = h("div", {}, h("u", {}, "X"), h("i", {}, "A"), h("b", {}, "B2"));
  const box = fixture(before);
  const unchanged = box.firstChild.firstChild;
  apply(box, before, after);
  assert(box.firstChild.childNodes[1] === unchanged, "이동된 변경 없는 i 노드의 identity 손실");
});
test("고정 시드 200회 연속 트리 변경 회귀", () => {
  let seed = 20261110;
  function next(n) {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed % n;
  }
  function tree(depth) {
    if (depth === 0 || next(3) === 0) return ["", "A", "B", " ", "<x>"][next(5)];
    const children = Array.from({ length: next(5) }, () => tree(depth - 1));
    return h(["div", "p", "span"][next(3)], next(2) ? { title: String(next(4)) } : {}, ...children);
  }
  let before = tree(3);
  const box = fixture(before);
  for (let i = 0; i < 200; i++) {
    const after = tree(3);
    apply(box, before, after);
    before = after;
  }
});

test("중복 형제: 앞에서부터 일대일 대응하고 삭제 시 첫 객체 보존", () => {
  const item = () => h("i", {}, "A");
  const before = h("div", {}, item(), item(), h("b", {}, "B"));
  const after = h("div", {}, h("u", {}, "X"), item(), item(), h("b", {}, "B2"));
  const box = fixture(before);
  const [first, second, b] = box.firstChild.childNodes;
  const calls = [];
  first.addEventListener("click", () => calls.push("first"));
  second.addEventListener("click", () => calls.push("second"));
  apply(box, before, after);
  assert(box.firstChild.childNodes[1] === first && box.firstChild.childNodes[2] === second,
    "중복 노드를 뒤바꾸거나 하나를 두 번 재사용함");
  box.firstChild.childNodes[1].click();
  box.firstChild.childNodes[2].click();
  assert(calls.join() === "first,second", "중복 노드 listener가 잘못 대응됨");
  const next = h("div", {}, h("u", {}, "X"), item(), h("b", {}, "B3"));
  apply(box, after, next);
  assert(box.firstChild.childNodes[1] === first && second.parentNode === null,
    "중복 삭제의 결정적 대응 규칙 위반");
  assert(box.firstChild.lastChild === b && b.textContent === "B3", "중복 뒤 형제 잘못 갱신");
});
test("유사 서브트리: 속성·중첩 텍스트·자식 순서까지 같은 노드만 앵커", () => {
  const exact = () => h("section", { title: "right" }, h("b", {}, "A"), "tail");
  const variants = [
    h("section", { title: "wrong" }, h("b", {}, "A"), "tail"),
    h("section", { title: "right" }, h("b", {}, "different"), "tail"),
    h("section", { title: "right" }, "tail", h("b", {}, "A"))
  ];
  for (const similar of variants) {
    const before = h("div", {}, similar, exact(), h("p", {}, "B"));
    const after = h("div", {}, h("u", {}, "new"), exact(), h("p", {}, "B2"));
    const box = fixture(before);
    const [wrong, right, p] = box.firstChild.childNodes;
    const nested = right.firstChild.firstChild;
    apply(box, before, after);
    assert(box.firstChild.childNodes[1] === right && right.firstChild.firstChild === nested,
      "유사한 노드를 동일한 서브트리로 오인");
    assert(wrong.parentNode === null && box.firstChild.lastChild === p, "잘못된 DOM 재사용");
  }
});
test("삽입 후 중첩 수정, 역방향 삭제 후 수정: 이전 경로와 참조 유지", () => {
  const anchor = () => h("i", {}, "A");
  const section = value => h("section", {}, h("b", {}, value));
  const before = h("div", {}, anchor(), section("old"));
  const after = h("div", {}, h("u", {}, "X"), anchor(), section("new"));
  const box = fixture(before);
  const [i, sectionNode] = box.firstChild.childNodes;
  const text = sectionNode.firstChild.firstChild;
  assert(JSON.stringify(apply(box, before, after)) === JSON.stringify([
    { type: "insert", path: [0], vnode: h("u", {}, "X") },
    { type: "text", path: [1, 0, 0], value: "new" }
  ]), "삽입 뒤 변경 경로가 새 인덱스로 바뀜");
  assert(box.firstChild.childNodes[1] === i && box.firstChild.childNodes[2] === sectionNode &&
    sectionNode.firstChild.firstChild === text && text.data === "new", "삽입 뒤 잘못된 참조 갱신");
  assert(JSON.stringify(apply(box, after, before)) === JSON.stringify([
    { type: "remove", path: [0] },
    { type: "text", path: [2, 0, 0], value: "old" }
  ]), "삭제 뒤 변경 경로가 밀림");
  assert(box.firstChild.firstChild === i && box.firstChild.lastChild === sectionNode &&
    sectionNode.firstChild.firstChild === text && text.data === "old", "삭제 뒤 잘못된 참조 갱신");
});
test("여러 앵커 사이의 추가·삭제·교체 후에도 뒤쪽 Text 참조 유지", () => {
  const a = () => h("i", {}, "A");
  const z = () => h("i", {}, "Z");
  const before = h("div", {}, h("del"), a(), h("em"), h("br"), z(), h("p", {}, "old"));
  const after = h("div", {}, a(), h("u"), z(), h("p", {}, "new"), "tail");
  const box = fixture(before);
  const oldNodes = Array.from(box.firstChild.childNodes);
  const text = oldNodes[5].firstChild;
  const changes = apply(box, before, after);
  assert(JSON.stringify(changes.map(c => [c.type, c.path])) === JSON.stringify([
    ["remove", [0]], ["replace", [2]], ["remove", [3]], ["text", [5, 0]], ["insert", [6]]
  ]), "여러 구간의 이전 경로 오류");
  assert(box.firstChild.childNodes[0] === oldNodes[1] && box.firstChild.childNodes[2] === oldNodes[4] &&
    box.firstChild.childNodes[3] === oldNodes[5] && oldNodes[5].firstChild === text && text.data === "new",
    "여러 구간 적용 후 객체 참조 오류");
});
test("주석과 같은 텍스트 중복: 삽입 후 중첩 위치 유지", () => {
  const box = document.createElement("div");
  box.innerHTML = '<div><!--start--><i>A</i><!--middle--><b>B</b></div>';
  const root = box.firstChild;
  const i = root.childNodes[1];
  const b = root.childNodes[3];
  const comments = [root.childNodes[0], root.childNodes[2]];
  const before = domToVdom(root);
  const after = h("div", {}, "", "", h("i", {}, "A"), h("b", {}, "B2"));
  patch(box, diff(before, after));
  assert(JSON.stringify(domToVdom(root)) === JSON.stringify(after), "주석 포함 결과 불일치");
  assert(root.contains(i) && root.contains(b) && b.textContent === "B2" &&
    comments.every(comment => root.contains(comment)), "주석 또는 형제 참조 손실");
  assert(root.childNodes[1] !== root.childNodes[2] && root.childNodes[1].nodeType === 3 &&
    root.childNodes[2].nodeType === 3, "중복 빈 Text를 하나로 재사용함");
});

test("중복 추가 뒤 같은 type 수정: 삽입 앵커인 기존 b와 Text 유지", () => {
  const before = h("div", {}, h("i", {}, "A"), h("b", {}, "B"));
  const after = h("div", {}, h("i", {}, "A"), h("i", {}, "A"), h("b", {}, "B2"));
  const box = fixture(before);
  const [first, b] = box.firstChild.childNodes;
  const text = b.firstChild;
  const changes = apply(box, before, after);
  assert(JSON.stringify(changes) === JSON.stringify([
    { type: "insert", path: [1], vnode: h("i", {}, "A") },
    { type: "text", path: [1, 0], value: "B2" }
  ]), "삽입 앵커와 후속 수정의 이전 경로 불일치");
  assert(box.firstChild.firstChild === first && box.firstChild.childNodes[1] !== first &&
    box.firstChild.lastChild === b && b.firstChild === text && text.data === "B2", "삽입 앵커 참조 손실");
});

const summary = document.querySelector("#summary");
summary.textContent = `${passed}/${results.children.length} PASS`;
summary.dataset.status = passed === results.children.length ? "pass" : "fail";
