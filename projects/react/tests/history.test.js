// [history.test.js] push / undo / redo 단위 테스트 (브라우저에서 history.test.html로 실행)
// history.js는 모듈 안에 기록을 하나만 가지므로, 테스트들은 "위에서부터 순서대로" 같은 기록을 이어서 쓴다.

import { push, undo, redo } from "../src/phase1/history.js";

const results = [];

function test(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, message: e.message });
  }
}

function assertEqual(actual, expected, msg = "") {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${msg}\n  기대: ${e}\n  실제: ${a}`);
}

test("기록이 없으면 undo / redo 모두 null", () => {
  assertEqual([undo(), redo()], [null, null]);
});

test("기록이 하나뿐이면 undo는 null (첫 화면보다 더 뒤로 갈 수 없음)", () => {
  push("A");
  assertEqual(undo(), null);
});

test("undo는 한 칸씩 뒤로, 처음에 닿으면 null", () => {
  push("B");
  push("C");
  assertEqual([undo(), undo(), undo()], ["B", "A", null]);
});

test("redo는 한 칸씩 앞으로, 끝에 닿으면 null", () => {
  assertEqual([redo(), redo(), redo()], ["B", "C", null]);
});

test("뒤로 간 상태에서 push하면 앞으로가기 기록이 사라짐", () => {
  // 지금: [A, B, C], 위치 C
  undo(); // 위치 B
  push("D"); // [A, B, D], C는 버려짐
  assertEqual([redo(), undo(), undo(), undo()], [null, "B", "A", null]);
});

test("버려진 뒤에도 redo로 새 기록을 따라감", () => {
  // 지금: [A, B, D], 위치 A
  assertEqual([redo(), redo(), redo()], ["B", "D", null]);
});

const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const passed = results.filter((r) => r.ok).length;
document.getElementById("results").innerHTML =
  `<h2>${passed} / ${results.length} passed</h2>` +
  results
    .map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`)
    .join("");
console.table(results);
