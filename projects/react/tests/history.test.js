// [tests/history.test.js] State History push / undo / redo / go / 분기

import { describe, test, assert, assertEqual } from "./runner.js";
import * as history from "../src/phase1/history.js";

const v = (name) => ({ type: "div", props: {}, children: [name] });

describe("history", () => {
  test("처음에는 비어 있다", () => {
    history.reset();
    assertEqual(history.current(), null);
    assertEqual(history.position(), { index: -1, length: 0 });
    assert(!history.canUndo() && !history.canRedo());
    assertEqual(history.undo(), null);
    assertEqual(history.redo(), null);
  });

  test("push → current 는 마지막 기록", () => {
    history.reset();
    history.push(v("A"));
    history.push(v("B"));
    assertEqual(history.current(), v("B"));
    assertEqual(history.position(), { index: 1, length: 2 });
  });

  test("undo / redo 는 한 칸씩 이동, 끝에서는 null", () => {
    history.reset();
    ["A", "B", "C"].forEach((n) => history.push(v(n)));
    assertEqual(history.undo(), v("B"));
    assertEqual(history.undo(), v("A"));
    assertEqual(history.undo(), null, "맨 앞에서는 null");
    assertEqual(history.current(), v("A"), "null 일 때 위치는 그대로");
    assertEqual(history.redo(), v("B"));
    assertEqual(history.redo(), v("C"));
    assertEqual(history.redo(), null, "맨 뒤에서는 null");
  });

  test("뒤로 간 상태에서 push 하면 앞쪽 기록이 사라진다 (분기)", () => {
    history.reset();
    ["A", "B", "C"].forEach((n) => history.push(v(n)));
    history.undo();
    history.undo(); // 현재 A
    history.push(v("D"));
    assertEqual(history.position(), { index: 1, length: 2 });
    assertEqual(history.entries().length, 2);
    assert(!history.canRedo(), "앞으로가기 기록이 없어야 함");
    assertEqual(history.undo(), v("A"));
    assertEqual(history.redo(), v("D"));
  });

  test("go(i) 로 바로 이동, 범위 밖이면 null", () => {
    history.reset();
    ["A", "B", "C"].forEach((n) => history.push(v(n)));
    assertEqual(history.go(0), v("A"));
    assertEqual(history.position().index, 0);
    assertEqual(history.go(5), null);
    assertEqual(history.go(-1), null);
    assertEqual(history.go(1.5), null);
    assertEqual(history.position().index, 0, "실패한 go 는 위치를 바꾸지 않음");
    assertEqual(history.go(2), v("C"));
  });

  test("저장 · 반환 모두 깊은 복사", () => {
    history.reset();
    const a = v("A");
    history.push(a);
    a.children[0] = "바뀜";
    assertEqual(history.current(), v("A"), "push 후 원본을 바꿔도 기록은 그대로");
    const got = history.current();
    got.children.push("추가");
    assertEqual(history.current(), v("A"), "반환값을 바꿔도 기록은 그대로");
  });

  test("entries 는 메타 정보와 현재 위치를 알려 준다", () => {
    history.reset();
    history.push(v("A"), { label: "초기 상태", patchCount: 0 });
    history.push(v("B"), { label: "Patch #1", patchCount: 3 });
    history.undo();
    const list = history.entries();
    assertEqual(list.map((e) => [e.index, e.label, e.patchCount, e.active]), [
      [0, "초기 상태", 0, true],
      [1, "Patch #1", 3, false],
    ]);
    assert(typeof list[0].time === "number");
  });

  test("canUndo / canRedo", () => {
    history.reset();
    history.push(v("A"));
    assert(!history.canUndo() && !history.canRedo(), "기록 1개");
    history.push(v("B"));
    assert(history.canUndo() && !history.canRedo(), "맨 뒤");
    history.undo();
    assert(!history.canUndo() && history.canRedo(), "맨 앞");
  });
});
