// [hooks.test.js] FunctionComponent / useState / useEffect / useMemo 단위 테스트 (브라우저에서 hooks.test.html로 실행)

import { h, domToVdom } from "../src/core/vdom.js";
import { FunctionComponent } from "../src/core/component.js";
import { useState, useEffect, useMemo, useRef } from "../src/core/hooks.js";

const results = [];
const tests = [];
// setState는 다시 그리기를 마이크로태스크로 미루므로(Batching) 테스트는 async로 쓰고 tick()으로 기다린다
const test = (name, fn) => tests.push({ name, fn });
const tick = () => new Promise((resolve) => setTimeout(resolve));

function assertEqual(actual, expected, msg = "") {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${msg}\n  기대: ${e}\n  실제: ${a}`);
}
function assertThrows(fn, msg) {
  try {
    fn();
  } catch {
    return;
  }
  throw new Error(`에러가 나야 함: ${msg}`);
}

// 컴포넌트를 새 컨테이너에 마운트하고 [컨테이너, 인스턴스]를 돌려준다
function mount(App, props) {
  const container = document.createElement("div");
  const instance = new FunctionComponent(App, container, props);
  instance.mount();
  return [container, instance];
}

// ── FunctionComponent ──

test("mount: 컴포넌트 결과를 컨테이너에 그림", () => {
  const [c] = mount((props) => h("p", { id: "x" }, "안녕 ", props.name), { name: "철수" });
  assertEqual(c.innerHTML, '<p id="x">안녕 철수</p>');
});

test("자식 컴포넌트: h(Child, props) 실행 + children 전달 + null은 안 그림", () => {
  const Item = ({ text, children }) => h("li", null, text, children);
  const Nothing = () => null;
  const [c] = mount(() => h("ul", null, h(Item, { text: "A" }, "!"), h(Nothing), h(Item, { text: "B" })));
  assertEqual(c.innerHTML, "<ul><li>A!</li><li>B</li></ul>");
});

test("자식 반환값 정리: 텍스트는 이웃과 합치고, 배열은 펼치고, ''/숫자도 h 규칙대로 (2차 리뷰)", () => {
  const Text = () => "안녕";
  const Empty = () => "";
  const List = () => [h("b", null, "1"), 2];
  const [c, inst] = mount(() => h("p", null, "앞 ", h(Text), h(Empty), " 뒤", h(List)));
  // 자식 목록이 VDOM 규약(텍스트 합침, 빈 문자열 없음, 숫자는 문자열)과 같아야 index 기반 diff가 실제 DOM과 어긋나지 않는다
  // inst.vdom은 container를 뜻하는 루트 div → 그 첫 자식이 컴포넌트가 돌려준 <p>
  assertEqual(inst.vdom.children[0].children, ["앞 안녕 뒤", { type: "b", props: {}, children: ["1"] }, "2"]);
  assertEqual(c.innerHTML, "<p>앞 안녕 뒤<b>1</b>2</p>");
});

test("루트 컴포넌트는 노드 하나 · 여러 개(배열) · 문자열 · null 무엇을 돌려줘도 됨 (React의 Fragment / null), 개수가 바뀌어도 update", async () => {
  let setMode;
  const [c] = mount(() => {
    const [mode, set] = useState("many");
    setMode = set;
    if (mode === "many") return [h("p", null, "a"), h("p", null, "b")];
    if (mode === "text") return "글자";
    if (mode === "none") return null;
    return h("span", null, "x");
  });
  assertEqual(c.innerHTML, "<p>a</p><p>b</p>");
  for (const [mode, html] of [["text", "글자"], ["none", ""], ["one", "<span>x</span>"], ["many", "<p>a</p><p>b</p>"]]) {
    setMode(mode);
    await tick();
    assertEqual(c.innerHTML, html, mode);
  }
  const Child = () => h("span", null, "x");
  const [c2] = mount(() => h(Child));
  assertEqual(c2.innerHTML, "<span>x</span>");
});

test("4차 리뷰: FunctionComponent는 잘못된 인자를 만들 때 바로 TypeError, mount()는 자기 자신을 돌려줌", () => {
  assertThrows(() => new FunctionComponent(null, document.createElement("div")), "component가 함수 아님");
  assertThrows(() => new FunctionComponent(() => null, null), "container 없음");
  assertThrows(() => new FunctionComponent(() => null, document.createTextNode("x")), "container가 요소 아님");
  const inst = new FunctionComponent(() => h("p"), document.createElement("div"));
  assertEqual(inst.mount() === inst, true);
});

test("update: 바뀐 노드만 고치고 나머지 DOM 노드는 그대로 (같은 객체)", async () => {
  let setN;
  const [c] = mount(() => {
    const [n, set] = useState(0);
    setN = set;
    return h("div", null, h("h1", null, "제목"), h("p", null, String(n)));
  });
  const h1 = c.querySelector("h1");
  const text = c.querySelector("p").firstChild;
  setN(5);
  await tick();
  assertEqual(c.innerHTML, "<div><h1>제목</h1><p>5</p></div>");
  if (c.querySelector("h1") !== h1) throw new Error("h1이 다시 만들어짐");
  if (c.querySelector("p").firstChild !== text) throw new Error("텍스트 노드가 교체됨 (TEXT 패치여야 함)");
});

// ── useState ──

test("useState: 초기값 / 상태 유지 / 지연 초기화 함수는 처음 한 번만", async () => {
  let initCalls = 0;
  let setA;
  const [c] = mount(() => {
    const [a, set] = useState(1);
    const [b] = useState(() => (initCalls++, "lazy"));
    setA = set;
    return h("p", null, `${a}-${b}`);
  });
  setA(2);
  await tick();
  setA(3);
  await tick();
  assertEqual([c.textContent, initCalls], ["3-lazy", 1]);
});

test("useState: Batching — 한 번에 여러 setState → 렌더링 1번", async () => {
  let renders = 0;
  let setA, setB;
  const [c] = mount(() => {
    renders++;
    const [a, sa] = useState(0);
    const [b, sb] = useState(0);
    setA = sa;
    setB = sb;
    return h("p", null, `${a},${b}`);
  });
  setA(1);
  setB(2);
  setA(3);
  await tick();
  assertEqual([c.textContent, renders], ["3,2", 2]);
});

test("useState: 함수형 업데이트는 누적 (c => c + 1 두 번 = +2)", async () => {
  let setN;
  const [c] = mount(() => {
    const [n, set] = useState(0);
    setN = set;
    return h("p", null, String(n));
  });
  setN((n) => n + 1);
  setN((n) => n + 1);
  await tick();
  assertEqual(c.textContent, "2");
});

test("useState: 같은 값이면 다시 렌더링하지 않음", async () => {
  let renders = 0;
  let setN;
  mount(() => {
    renders++;
    const [n, set] = useState(1);
    setN = set;
    return h("p", null, String(n));
  });
  setN(1);
  await tick();
  assertEqual(renders, 1);
});

test("useState: setState 함수는 렌더링마다 같은 함수 (deps에 넣어도 effect가 다시 돌지 않음)", async () => {
  const setters = [];
  let effectRuns = 0;
  let setOther;
  mount(() => {
    const [n, setN] = useState(0);
    const [other, so] = useState(0);
    setters.push(setN);
    setOther = so;
    useEffect(() => {
      effectRuns++;
    }, [setN]);
    return h("p", null, `${n}${other}`);
  });
  setOther(1);
  await tick();
  assertEqual([setters.length, setters[0] === setters[1], effectRuns], [2, true, 1]);
});

test("Hook 호출 개수가 렌더링마다 달라지면 에러", () => {
  const inst = new FunctionComponent(() => {
    const [flag] = useState(false);
    if (flag) useMemo(() => 1, []); // 조건부 Hook (잘못된 사용)
    return h("p");
  }, document.createElement("div"));
  inst.mount();
  // setState 대신 칸을 직접 바꾼다 (setState는 update를 예약해서, 그 예약된 렌더링의 에러가 테스트 밖으로 새어 나간다)
  inst.hooks[0].state = true;
  assertThrows(() => inst.update(), "Hook 개수 변경");
});

test("이벤트: 다시 렌더링 후 클릭하면 최신 상태를 쓰는 새 핸들러가 실행됨", async () => {
  const [c] = mount(() => {
    const [n, set] = useState(0);
    return h("button", { onClick: () => set(n + 1) }, String(n));
  });
  const btn = c.querySelector("button");
  btn.click();
  await tick();
  btn.click();
  await tick();
  assertEqual(btn.textContent, "2");
});

// ── useEffect ──

test("useEffect: 화면 반영 뒤 실행 / [] 은 한 번 / deps 바뀌면 cleanup 후 재실행 / deps 없으면 매번", async () => {
  const log = [];
  let setN, setOther;
  // effect는 mount() 안에서 실행되므로, 화면을 읽을 컨테이너를 먼저 만들어 둔다
  const c = document.createElement("div");
  new FunctionComponent(() => {
    const [n, sn] = useState(0);
    const [other, so] = useState(0);
    setN = sn;
    setOther = so;
    useEffect(() => log.push("once"), []);
    useEffect(() => {
      log.push(`n=${n} dom=${c.textContent}`);
      return () => log.push(`cleanup n=${n}`);
    }, [n]);
    useEffect(() => log.push("every"));
    return h("p", null, `${n}/${other}`);
  }, c).mount();
  setOther(1); // n 그대로 → [n] effect는 안 돎
  await tick();
  setN(1);
  await tick();
  assertEqual(log, ["once", "n=0 dom=0/0", "every", "every", "cleanup n=0", "n=1 dom=1/1", "every"]);
});

test("useEffect: 모든 cleanup을 먼저, 그다음 새 effect들 (React 순서)", async () => {
  const log = [];
  let setN;
  mount(() => {
    const [n, set] = useState(0);
    setN = set;
    useEffect(() => (log.push(`A${n}`), () => log.push(`cleanA${n}`)), [n]);
    useEffect(() => (log.push(`B${n}`), () => log.push(`cleanB${n}`)), [n]);
    return h("p");
  });
  setN(1);
  await tick();
  assertEqual(log, ["A0", "B0", "cleanA0", "cleanB0", "A1", "B1"]);
});

test("useEffect: 렌더링이 중간에 실패하면 그 effect는 다음 렌더링에서 실행됨 (2차 리뷰)", async () => {
  const log = [];
  let setN;
  let allow = false;
  const inst = new FunctionComponent(() => {
    const [n, set] = useState(0);
    setN = set;
    useEffect(() => log.push(`effect ${n}`), [n]);
    if (n === 1 && !allow) throw new Error("렌더링 실패");
    return h("p", null, String(n));
  }, document.createElement("div"));
  inst.mount();
  setN(1); // 예약된 update는 아래 tick에서 실행된다
  assertThrows(() => inst.update(), "n=1 렌더링 실패"); // effect 1은 등록만 되고 실행되지 않음
  allow = true;
  await tick(); // 같은 deps [1]로 다시 렌더링 → 이번엔 실행되어야 함
  assertEqual(log, ["effect 0", "effect 1"]);
});

test("useEffect: 하나가 에러를 내도 나머지 cleanup/effect는 실행되고, 에러는 알림 (3차 리뷰)", () => {
  const log = [];
  let n = 0;
  const inst = new FunctionComponent(() => {
    useEffect(() => {
      log.push(`A${n}`);
      if (n === 0) throw new Error("A 실패");
      return () => log.push("cleanA");
    }, [n]);
    useEffect(() => {
      log.push(`B${n}`);
      const made = n; // 이 cleanup을 만든 렌더링 번호
      return () => {
        log.push(`cleanB${made}`);
        if (made === 0) throw new Error("cleanB0 실패");
      };
    }, [n]);
    return h("p");
  }, document.createElement("div"));
  assertThrows(() => inst.mount(), "A0의 에러가 mount 밖으로 알려져야 함");
  n = 1;
  assertThrows(() => inst.update(), "cleanB0의 에러가 알려져야 함");
  n = 2;
  inst.update();
  // 렌더링0: A0 실패해도 B0 실행 / 렌더링1: cleanB0 실패해도 A1, B1 실행 / 렌더링2: cleanA, cleanB1 → A2, B2
  assertEqual(log, ["A0", "B0", "cleanB0", "A1", "B1", "cleanA", "cleanB1", "A2", "B2"]);
});

test("Hook 안(useMemo 계산 함수, useState 초기값 함수)에서 Hook 호출 → 에러 (3차 리뷰)", () => {
  assertThrows(() => mount(() => (useMemo(() => useState(0), []), h("p"))), "useMemo 안 useState");
  assertThrows(() => mount(() => (useState(() => useMemo(() => 1, [])), h("p"))), "useState 초기값 안 useMemo");
  // 에러 뒤에도 잠금이 풀려 있어야 정상 컴포넌트가 동작한다
  const [c] = mount(() => h("p", null, String(useMemo(() => 7, []))));
  assertEqual(c.textContent, "7");
});

test("첫 mount가 실패해도, 원인을 고치고 다시 mount하면 정상 동작 (3차 리뷰)", async () => {
  let broken = true;
  let setN;
  const Child = ({ n }) => {
    if (broken) throw new Error("자식 실패");
    return h("b", null, String(n));
  };
  const container = document.createElement("div");
  const inst = new FunctionComponent(() => {
    const [n, set] = useState(1);
    setN = set;
    return h("p", null, h(Child, { n }));
  }, container);
  assertThrows(() => inst.mount(), "첫 mount 실패");
  broken = false;
  inst.mount();
  setN(2);
  await tick();
  assertEqual(container.innerHTML, "<p><b>2</b></p>");
});

test("useEffect 안의 setState → 다시 렌더링", async () => {
  const [c] = mount(() => {
    const [loaded, set] = useState(false);
    useEffect(() => set(true), []);
    return h("p", null, loaded ? "완료" : "로딩");
  });
  assertEqual(c.textContent, "로딩");
  await tick();
  assertEqual(c.textContent, "완료");
});

// ── useMemo ──

test("useMemo: deps가 같으면 다시 계산하지 않고, 바뀌면 다시 계산", async () => {
  let calls = 0;
  let setN, setOther;
  const [c] = mount(() => {
    const [n, sn] = useState(2);
    const [other, so] = useState(0);
    setN = sn;
    setOther = so;
    const square = useMemo(() => (calls++, n * n), [n]);
    return h("p", null, `${square}/${other}`);
  });
  setOther(1);
  await tick();
  assertEqual([c.textContent, calls], ["4/1", 1]);
  setN(3);
  await tick();
  assertEqual([c.textContent, calls], ["9/1", 2]);
});

test("자식 컴포넌트의 key: h(Item, { key })의 key는 결과 요소로 옮겨지고, 컴포넌트 props에는 안 들어감", () => {
  let seenKey = "없음";
  const Item = (props) => {
    if ("key" in props) seenKey = props.key;
    return h("li", null, props.text);
  };
  const [, inst] = mount(() => h("ul", null, h(Item, { key: "a", text: "A" })));
  assertEqual([inst.vdom.children[0].children[0].props.key, seenKey], ["a", "없음"]);
});

// ── useRef ──

test("useRef: 렌더링마다 같은 객체, current를 바꿔도 다시 렌더링 안 함, ref prop으로 DOM 요소 받기", async () => {
  const refs = [];
  let renders = 0;
  let setN;
  const [c] = mount(() => {
    renders++;
    const [n, set] = useState(0);
    setN = set;
    const inputRef = useRef(null);
    const counter = useRef(0);
    refs.push(inputRef);
    counter.current++; // 화면과 상관없는 값 보관
    return h("div", null, h("input", { ref: inputRef }), String(n));
  });
  setN(1);
  await tick();
  assertEqual([refs[0] === refs[1], refs[0].current === c.querySelector("input"), renders], [true, true, 2]);
});

// ── 제약 / 제어 컴포넌트 ──

test("Hook 제약: 자식 컴포넌트·렌더링 밖에서 호출하면 에러", () => {
  const Child = () => (useState(0), h("p"));
  assertThrows(() => mount(() => h("div", null, h(Child))), "자식에서 useState");
  assertThrows(() => useState(0), "렌더링 밖에서 useState");
});

test("제어 컴포넌트: State가 그대로면 사용자가 바꾼 화면 값을 State로 되돌림", async () => {
  let setOther;
  const [c] = mount(() => {
    const [other, so] = useState(0);
    setOther = so;
    return h("div", null, h("input", { value: "고정" }), h("input", { type: "checkbox", checked: true }), String(other));
  });
  const [text, box] = c.querySelectorAll("input");
  text.value = "사용자 입력";
  box.checked = false;
  setOther(1);
  await tick();
  assertEqual([text.value, box.checked], ["고정", true]);
});

// ── 실행 ──
// ── 개선 1~5 (팀 코드 비교 후 보완) ──

test("개선 1: 무한 렌더링(effect 안에서 deps 없이 setState)은 50번에서 멈추고 에러, 탭이 굳지 않음", async () => {
  let renders = 0;
  const errors = [];
  // 마이크로태스크에서 던진 에러는 window의 error 이벤트로 온다. preventDefault로 콘솔에 빨간 줄이 남지 않게 한다
  const onError = (e) => {
    errors.push(e.message);
    e.preventDefault();
  };
  window.addEventListener("error", onError);
  try {
    mount(() => {
      const [n, setN] = useState(0);
      renders++;
      useEffect(() => setN(n + 1));
      return h("p", null, String(n));
    });
    // 멈추지 않으면 마이크로태스크가 끝없이 이어져 이 setTimeout(tick)이 영영 실행되지 않는다
    await tick();
    await tick();
  } finally {
    window.removeEventListener("error", onError);
  }
  if (!errors.some((m) => m.includes("연달아"))) throw new Error(`무한 렌더링 에러가 안 남: ${errors}`);
  assertEqual(renders, 51, "mount 1번 + update 50번에서 멈춰야 함");
});

test("개선 1 보완: await를 끼운 정상 반복문에서 setState 60번은 막지 않음 (무한 렌더링으로 오해 금지)", async () => {
  let set;
  const [c] = mount(() => {
    const [n, s] = useState(0);
    set = s;
    return h("p", null, String(n));
  });
  // 마이크로태스크만 사이에 끼므로 setTimeout 기준으로 세면 50번에서 멈춘다 (실제로 그랬던 버그)
  for (let i = 1; i <= 60; i++) {
    set(i);
    await Promise.resolve();
    await Promise.resolve();
  }
  await tick();
  assertEqual(c.textContent, "60");
});

test("개선 2: Hook 개수는 같고 종류만 바뀌어도 에러 (useState 자리에 useMemo)", () => {
  let mode = "state";
  const inst = new FunctionComponent(() => {
    useState("유지돼야 할 값");
    if (mode === "state") useState(0);
    else useMemo(() => 1, []);
    return h("p", null, "x");
  }, document.createElement("div"));
  inst.mount();
  mode = "memo";
  try {
    inst.update();
  } catch (e) {
    if (!e.message.includes("2번째 Hook") || !e.message.includes("useState") || !e.message.includes("useMemo")) throw new Error(`메시지가 이상함: ${e.message}`);
    return;
  }
  throw new Error("에러가 나야 함");
});

test("개선 3: patch가 중간에 실패해도 화면과 VDOM이 어긋나지 않음 (마지막 성공 상태로 복구)", () => {
  let label = "A";
  let fileValue = "";
  // file input에 빈 값이 아닌 value를 넣으면 브라우저가 InvalidStateError를 던진다 (검사로는 못 막는 실패)
  const [c, inst] = mount(() => h("div", null, h("p", null, label), h("input", { type: "file", value: fileValue })));
  label = "B";
  fileValue = "x";
  assertThrows(() => inst.update(), "file input에 value");
  // 실패 전에 p는 이미 "B"로 바뀌었었다. 복구하지 않으면 DOM은 "B", 기억한 VDOM은 "A"로 어긋난다
  assertEqual(c.querySelector("p").textContent, "A", "마지막 성공 상태로 복구");
  // 어긋나 있었다면 A → A 는 "변경 없음"이라 화면에 B가 남는다
  label = "A";
  fileValue = "";
  inst.update();
  assertEqual(c.querySelector("p").textContent, "A");
});

test("개선 4: 잘못된 VNode는 화면을 건드리기 전에, 위치가 담긴 에러", () => {
  const cases = [
    [() => h("ul", null, h("li", null, {})), "루트.children[0].children[0]"],
    [() => h("p", { title: { a: 1 } }), "title"],
    [() => h("button", { onClick: "alert(1)" }), "onClick"],
    [() => h("a b"), "태그 이름"],
  ];
  for (const [App, word] of cases) {
    const c = document.createElement("div");
    c.innerHTML = "<i>원래 화면</i>";
    try {
      new FunctionComponent(App, c).mount();
    } catch (e) {
      if (!e.message.includes(word)) throw new Error(`메시지에 "${word}"가 없음: ${e.message}`);
      assertEqual(c.innerHTML, "<i>원래 화면</i>", "DOM은 그대로");
      continue;
    }
    throw new Error(`에러가 나야 함: ${word}`);
  }
});

test("개선 5: unmount — effect cleanup 실행, ref 해제, DOM 비움, 이후 setState는 무시", async () => {
  const log = [];
  let setN;
  let ref;
  const [c, inst] = mount(() => {
    const [n, set] = useState(0);
    setN = set;
    ref = useRef(null);
    useEffect(() => () => log.push("cleanup"), []);
    return h("p", { ref }, String(n));
  });
  inst.unmount();
  assertEqual(log, ["cleanup"]);
  assertEqual(c.innerHTML, "");
  if (ref.current !== null) throw new Error("ref가 지운 요소를 계속 가리킴");
  setN(1);
  await tick();
  assertEqual(c.innerHTML, "", "unmount 후에는 다시 그리지 않음");
});

test("3차 개선: key는 문자열·숫자만, ref는 함수·객체만 (잘못 넣으면 화면을 건드리기 전에 에러)", () => {
  for (const [props, word] of [[{ key: { id: 1 } }, "key"], [{ ref: "abc" }, "ref"]]) {
    const c = document.createElement("div");
    try {
      new FunctionComponent(() => h("ul", null, h("li", props)), c).mount();
    } catch (e) {
      if (!e.message.includes(word)) throw new Error(`메시지에 "${word}"가 없음: ${e.message}`);
      assertEqual(c.innerHTML, "", "DOM은 그대로");
      continue;
    }
    throw new Error(`에러가 나야 함: ${word}`);
  }
});

test("3차 개선: 이미 mount된 컴포넌트를 또 mount하면 에러, unmount 후에는 다시 mount 가능", () => {
  const [c, inst] = mount(() => h("p", null, "x"));
  assertThrows(() => inst.mount(), "두 번째 mount");
  inst.unmount();
  inst.mount();
  assertEqual(c.innerHTML, "<p>x</p>");
});

test("3차 개선: 같은 이벤트의 핸들러 하나(onInput)가 에러를 내도 다른 핸들러(onChange)는 실행됨", () => {
  const log = [];
  const [c] = mount(() =>
    h("input", {
      onInput: () => {
        throw new Error("onInput 실패");
      },
      onChange: () => log.push("onChange"),
    })
  );
  const errors = [];
  const onError = (e) => {
    errors.push(e.message);
    e.preventDefault();
  };
  window.addEventListener("error", onError);
  c.firstChild.dispatchEvent(new Event("input"));
  window.removeEventListener("error", onError);
  assertEqual(log, ["onChange"]);
  if (!errors.some((m) => m.includes("onInput 실패"))) throw new Error("에러가 알려지지 않음");
});

test("퍼즈 1,000회 (Phase 2): 사용자 입력과 setState를 섞어도, 제어 컴포넌트 화면은 항상 state를 새로 그린 것과 같음", async () => {
  let seed = 31337;
  const r = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const pick = (a) => a[Math.floor(r() * a.length)];
  // state → 화면. 모든 폼은 제어 컴포넌트(value / checked prop이 있음)
  const view = (s) =>
    h(
      "div",
      null,
      h("ul", null, ...s.items.map((it) => h("li", { key: it.id, className: it.done ? "done" : "" }, h("input", { type: "checkbox", checked: it.done }), h("input", { value: it.text }), it.text))),
      h("select", { value: s.sel }, ...["o1", "o2", "o3"].map((o) => h("option", { value: o }, o))),
      h("textarea", { value: s.ta }),
      h("input", { type: "range", max: s.max, value: s.range }),
      s.flag ? h("p", null, "켜짐") : "꺼짐"
    );
  const randomState = () => ({
    items: [1, 2, 3, 4, 5].filter(() => r() < 0.6).sort(() => r() - 0.5).map((id) => ({ id, text: `t${id}${pick(["", "x"])}`, done: r() < 0.5 })),
    sel: pick(["o1", "o2", "o3"]),
    ta: pick(["", "aa", "bb"]),
    max: pick(["50", "500"]),
    range: pick(["10", "40", "300"]),
    flag: r() < 0.5,
  });
  const screen = (el) => JSON.stringify(domToVdom(el.firstChild)) + [...el.querySelectorAll("input, textarea, select")].map((f) => (f.type === "checkbox" ? f.checked : f.value)).join("|");

  let setS;
  const [c] = mount(() => {
    const [s, set] = useState(randomState);
    setS = set;
    return view(s);
  });
  for (let n = 0; n < 1000; n++) {
    // 사용자가 화면을 건드린다 (state는 그대로)
    for (const f of c.querySelectorAll("input, textarea, select")) {
      if (r() >= 0.3) continue;
      if (f.type === "checkbox") f.checked = !f.checked;
      else if (f.tagName === "SELECT") f.value = pick(["o1", "o2", "o3"]);
      else f.value = pick(["zz", "7", ""]);
    }
    const next = randomState();
    setS(next);
    await Promise.resolve();
    await Promise.resolve();
    const [fresh] = mount(() => view(next));
    if (screen(c) !== screen(fresh)) throw new Error(`${n}번째: 화면이 state와 다름 ${JSON.stringify(next)}`);
  }
});

test("4차 리뷰: useEffect / useMemo 인자가 잘못되면 부른 자리에서 TypeError", () => {
  for (const [App, word] of [
    [() => (useEffect(5, []), h("p")), "useEffect에는 함수"],
    [() => (useEffect(() => {}, "x"), h("p")), "useEffect의 deps"],
    [() => (useMemo(() => 1, "x"), h("p")), "useMemo의 deps"],
  ]) {
    try {
      new FunctionComponent(App, document.createElement("div")).mount();
    } catch (e) {
      if (!(e instanceof TypeError) || !e.message.includes(word)) throw new Error(`기대: "${word}", 실제: ${e.message}`);
      continue;
    }
    throw new Error(`에러가 나야 함: ${word}`);
  }
});

test("4차 리뷰: 첫 mount가 실패하면 그때 만든 Hook 칸을 버림 (다시 mount하면 초기값을 새로 계산)", () => {
  let fail = true;
  let inits = 0;
  const inst = new FunctionComponent(() => {
    useState(() => ++inits);
    if (fail) throw new Error("boom");
    return h("p");
  }, document.createElement("div"));
  assertThrows(() => inst.mount(), "첫 mount 실패");
  assertEqual(inst.hooks.length, 0, "실패한 시도의 Hook 칸이 남음");
  fail = false;
  inst.mount();
  assertEqual(inits, 2, "다시 mount할 때 초기값 함수가 다시 실행돼야 함");
});

for (const { name, fn } of tests) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, message: e.message });
  }
}

const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const passed = results.filter((r) => r.ok).length;
document.getElementById("results").innerHTML =
  `<h2>${passed} / ${results.length} passed</h2>` +
  results
    .map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`)
    .join("");
console.table(results);
