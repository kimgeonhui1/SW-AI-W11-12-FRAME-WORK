// [tests/component.test.js] Phase 2 — FunctionComponent · stateless · 이벤트 위임 단위 테스트

import { describe, test, assert, assertEqual } from "./runner.js";
import { h, containerToVdom } from "../src/core/vdom.js";
import { FunctionComponent, stateless, eventNameOf, extractHandlers } from "../src/core/component.js";
import { useState, useEffect } from "../src/core/hooks.js";
import { assertThrows, captureConsole, deepTree } from "./helpers.js";

/** 컨테이너를 만들고 컴포넌트를 마운트 */
function mountTest(component, props) {
  const box = document.createElement("div");
  const comp = new FunctionComponent(component, box, props).mount();
  return { comp, box };
}

/** 예약된 렌더(마이크로태스크)가 끝날 때까지 기다림 */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

/** 클릭 이벤트 (버블링) */
const click = (el) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

describe("Phase 2 · FunctionComponent 기본", () => {
  test("component 가 함수가 아니거나 container 가 요소가 아니면 TypeError", () => {
    assertThrows(() => new FunctionComponent(null, document.createElement("div")), TypeError);
    assertThrows(() => new FunctionComponent(() => null, null), TypeError);
    assertThrows(() => new FunctionComponent(() => null, document.createTextNode("x")), TypeError);
  });

  test("만들 때 hooks 는 빈 배열, mount() 는 자기 자신을 돌려주고 렌더 횟수 1", () => {
    const box = document.createElement("div");
    const comp = new FunctionComponent(() => h("p", null, "hi"), box);
    assertEqual(comp.hooks, []);
    assert(comp.mount() === comp);
    assertEqual(comp.renderCount, 1);
    assertEqual(box.innerHTML, "<p>hi</p>");
  });

  test("mount 는 컨테이너에 원래 있던 내용을 바꿔 넣는다", () => {
    const box = document.createElement("div");
    box.innerHTML = "<span>old</span>";
    new FunctionComponent(() => h("b", null, "new"), box).mount();
    assertEqual(box.innerHTML, "<b>new</b>");
  });

  test("컴포넌트가 돌려주는 값: 문자열 · 숫자 · 배열 · 중첩 배열 · null · false", () => {
    const cases = [
      [() => "글자", "글자"],
      [() => 42, "42"],
      [() => [h("i", null, "a"), "b"], "<i>a</i>b"],
      [() => [[h("i")], [null, [h("b")]]], "<i></i><b></b>"],
      [() => null, ""],
      [() => false, ""],
    ];
    for (const [component, html] of cases) assertEqual(mountTest(component).box.innerHTML, html);
  });

  test("루트 컴포넌트는 세 번째 인자 props 를 받는다", () => {
    const { box } = mountTest(({ name }) => h("p", null, `안녕 ${name}`), { name: "미니" });
    assertEqual(box.textContent, "안녕 미니");
  });

  test("이미 마운트했으면 mount() 오류, 마운트 전 update() 오류", () => {
    const { comp } = mountTest(() => h("p"));
    assertThrows(() => comp.mount());
    assertThrows(() => new FunctionComponent(() => h("p"), document.createElement("div")).update());
  });

  test("update 는 Diff/Patch 로 바뀐 텍스트만 고치고 나머지 노드는 그대로 재사용", () => {
    let label = "a";
    const { comp, box } = mountTest(() => h("ul", null, h("li", null, "고정"), h("li", null, label)));
    const [first, second] = box.querySelectorAll("li");
    const text = second.firstChild;
    label = "b";
    const patches = comp.update();
    assertEqual(patches.map((p) => p.type), ["TEXT"]);
    const [first2, second2] = box.querySelectorAll("li");
    assert(first === first2 && second === second2 && second.firstChild === text, "같은 노드 객체여야 함");
    assertEqual(text.nodeValue, "b");
  });

  test("바뀐 것이 없으면 패치 0개, DOM 그대로", () => {
    const { comp, box } = mountTest(() => h("p", { class: "x" }, "같음"));
    const before = box.firstChild;
    assertEqual(comp.update(), []);
    assert(box.firstChild === before);
  });

  test("렌더 결과 VDOM 은 Phase 1 형식 그대로 (containerToVdom 과 같음)", () => {
    const { comp, box } = mountTest(() => h("section", { id: "s" }, h("p", null, "a"), "b"));
    assertEqual(comp.vdom, containerToVdom(box));
  });

  test("여러 루트는 서로 독립 (hooks · 렌더 횟수 따로)", async () => {
    let setA;
    const A = () => {
      const [n, set] = useState(0);
      setA = set;
      return h("p", null, String(n));
    };
    const B = () => h("p", null, String(useState(100)[0]));
    const a = mountTest(A);
    const b = mountTest(B);
    setA(1);
    await settle();
    assertEqual(a.box.textContent, "1");
    assertEqual(b.box.textContent, "100");
    assertEqual([a.comp.renderCount, b.comp.renderCount], [2, 1]);
  });

  test("렌더 도중 다른 루트를 렌더하면 오류", () => {
    const inner = new FunctionComponent(() => h("i"), document.createElement("div"));
    const box = document.createElement("div");
    const outer = new FunctionComponent(() => {
      inner.mount();
      return h("p");
    }, box);
    assertThrows(() => outer.mount());
    assertEqual(box.childNodes.length, 0);
  });

  test("깊이 10,000 트리를 렌더 · 갱신해도 스택 오류 없음", () => {
    let leaf = "a";
    const { comp, box } = mountTest(() => deepTree(10000, leaf));
    leaf = "b";
    assertEqual(comp.update().length, 1);
    let node = box;
    while (node.firstElementChild) node = node.firstElementChild;
    assertEqual(node.textContent, "b");
  });

  test("순환 참조된 VNode 를 돌려주면 TypeError, 컨테이너 그대로", () => {
    const loop = { type: "div", props: {}, children: [] };
    loop.children.push(loop);
    const box = document.createElement("div");
    box.innerHTML = "<p>원래</p>";
    assertThrows(() => new FunctionComponent(() => loop, box).mount(), TypeError);
    assertEqual(box.innerHTML, "<p>원래</p>");
  });
});

describe("Phase 2 · 렌더 오류와 원자성", () => {
  test("렌더 중 예외 → update 가 예외, 실제 DOM 그대로, 다음 렌더는 정상", () => {
    let mode = "ok";
    const { comp, box } = mountTest(() => {
      if (mode === "throw") throw new Error("의도된 오류");
      return h("p", null, mode);
    });
    mode = "throw";
    assertThrows(() => comp.update());
    assertEqual(box.innerHTML, "<p>ok</p>");
    mode = "again";
    comp.update();
    assertEqual(box.innerHTML, "<p>again</p>");
  });

  test("잘못된 VNode(함수 prop) → TypeError, 실제 DOM 그대로", () => {
    let bad = false;
    const { comp, box } = mountTest(() => h("p", bad ? { render: () => 1 } : null, "x"));
    bad = true;
    assertThrows(() => comp.update(), TypeError);
    assertEqual(box.innerHTML, "<p>x</p>");
  });

  test("첫 렌더 실패 → 컨테이너 그대로, hooks 비워 둠", () => {
    const box = document.createElement("div");
    box.textContent = "원래";
    const comp = new FunctionComponent(() => {
      useState(1);
      throw new Error("x");
    }, box);
    assertThrows(() => comp.mount());
    assertEqual(box.textContent, "원래");
    assertEqual(comp.hooks, []);
  });

  test("렌더 실패 시 그 렌더에서 예약된 effect 는 실행되지 않음", () => {
    let runs = 0;
    let fail = false;
    let dep = 0;
    const { comp } = mountTest(() => {
      useEffect(() => {
        runs += 1;
      }, [dep]);
      if (fail) throw new Error("x");
      return h("p");
    });
    dep = 1;
    fail = true;
    assertThrows(() => comp.update());
    fail = false;
    dep = 0; // 처음과 같은 값으로 돌아왔으므로 effect 는 다시 실행되면 안 된다
    comp.update();
    assertEqual(runs, 1);
  });
});

describe("Phase 2 · stateless 자식 컴포넌트", () => {
  test("자식은 props 를 받아 VNode 를 돌려주는 함수, 이름 유지", () => {
    const Hello = stateless(function Hello({ name }) {
      return h("b", null, name);
    });
    assertEqual(Hello.name, "Hello");
    const { box } = mountTest(() => h("p", null, Hello({ name: "철수" })));
    assertEqual(box.innerHTML, "<p><b>철수</b></p>");
  });

  test("props 없이 불러도 빈 객체", () => {
    const Child = stateless((props) => h("i", null, String(Object.keys(props).length)));
    assertEqual(mountTest(() => Child()).box.textContent, "0");
  });

  test("함수가 아니면 TypeError", () => assertThrows(() => stateless("x"), TypeError));

  test("자식 안에서 Hook 을 부르면 오류 (Hook 은 최상위에서만), 컨테이너 그대로", () => {
    const Bad = stateless(() => {
      useState(0);
      return h("p");
    });
    const box = document.createElement("div");
    const err = assertThrows(() => new FunctionComponent(() => Bad(), box).mount());
    assert(err.message.includes("최상위"), err.message);
    assertEqual(box.childNodes.length, 0);
  });

  test("자식이 끝난 뒤에는 루트에서 Hook 을 계속 쓸 수 있음", () => {
    const Child = stateless(() => h("i"));
    const { comp } = mountTest(() => {
      const kid = Child();
      const [n] = useState(5);
      return h("p", null, kid, String(n));
    });
    assertEqual(comp.hooks.length, 1);
  });

  test("자식 안에서 예외가 나도 '자식 렌더 중' 표시가 풀려 다음 렌더는 정상", () => {
    let fail = true;
    const Child = stateless(() => {
      if (fail) throw new Error("x");
      return h("i");
    });
    const box = document.createElement("div");
    const comp = new FunctionComponent(() => {
      useState(0);
      return Child();
    }, box);
    assertThrows(() => comp.mount());
    fail = false;
    comp.mount();
    assertEqual(box.innerHTML, "<i></i>");
  });

  test("Lifting State Up: 자식이 부모의 콜백을 불러 부모 상태를 바꾼다", async () => {
    const Counter = stateless(({ value, onAdd }) => h("button", { onClick: onAdd }, String(value)));
    const { box } = mountTest(() => {
      const [n, setN] = useState(0);
      return Counter({ value: n, onAdd: () => setN((v) => v + 1) });
    });
    click(box.querySelector("button"));
    click(box.querySelector("button"));
    await settle();
    assertEqual(box.textContent, "2");
  });
});

describe("Phase 2 · 이벤트 위임", () => {
  test("이벤트 이름 변환: onClick→click, onKeyDown→keydown, onFocus→focusin, onBlur→focusout, onDoubleClick→dblclick", () => {
    assertEqual(
      ["onClick", "onKeyDown", "onFocus", "onBlur", "onDoubleClick", "onInput"].map(eventNameOf),
      ["click", "keydown", "focusin", "focusout", "dblclick", "input"],
    );
  });

  test("VDOM 에는 함수 대신 data-on-click 문자열, 실제 DOM 에 onclick 속성 없음", () => {
    const { comp, box } = mountTest(() => h("button", { onClick: () => {} }, "x"));
    const btn = box.querySelector("button");
    assertEqual(comp.vdom.children[0].props, { "data-on-click": "0" });
    assertEqual(btn.getAttribute("onclick"), null);
    assertEqual(btn.onclick, null);
  });

  test("클릭하면 핸들러가 이벤트 객체와 함께 불림", () => {
    let got = null;
    const { box } = mountTest(() => h("button", { onClick: (e) => (got = e) }, "x"));
    click(box.querySelector("button"));
    assert(got && got.type === "click" && got.target === box.querySelector("button"));
  });

  test("안쪽 요소를 클릭해도 바깥 핸들러가 불림 (버블링), 안쪽부터", () => {
    const calls = [];
    const { box } = mountTest(() =>
      h("div", { onClick: () => calls.push("바깥") }, h("button", { onClick: () => calls.push("안쪽") }, h("span", null, "x"))),
    );
    click(box.querySelector("span"));
    assertEqual(calls, ["안쪽", "바깥"]);
  });

  test("stopPropagation() 을 부르면 바깥 핸들러는 불리지 않음", () => {
    const calls = [];
    const { box } = mountTest(() =>
      h("div", { onClick: () => calls.push("바깥") }, h("button", { onClick: (e) => (calls.push("안쪽"), e.stopPropagation()) }, "x")),
    );
    click(box.querySelector("button"));
    assertEqual(calls, ["안쪽"]);
  });

  test("핸들러는 항상 최신 렌더의 함수 (최신 상태를 봄)", async () => {
    const seen = [];
    let setter;
    const { box } = mountTest(() => {
      const [n, setN] = useState(0);
      setter = setN;
      return h("button", { onClick: () => seen.push(n) }, "x");
    });
    click(box.querySelector("button"));
    setter(7);
    await settle();
    click(box.querySelector("button"));
    assertEqual(seen, [0, 7]);
  });

  test("핸들러가 매 렌더 새 함수여도 패치는 생기지 않음 (번호가 같음)", () => {
    const { comp } = mountTest(() => h("div", null, h("button", { onClick: () => 1 }), h("input", { onInput: () => 2 })));
    assertEqual(comp.update(), []);
  });

  test("이벤트 종류마다 컨테이너 리스너는 하나 (요소가 많아도)", () => {
    const box = document.createElement("div");
    const added = [];
    const original = box.addEventListener.bind(box);
    box.addEventListener = (type, fn, opts) => (added.push(type), original(type, fn, opts));
    const comp = new FunctionComponent(() => h("ul", null, [1, 2, 3].map((i) => h("li", { onClick: () => i, onKeyDown: () => i }))), box).mount();
    comp.update();
    assertEqual(added.sort(), ["click", "keydown"]);
  });

  test("onClick 이 null · undefined · false 면 핸들러 없음 (속성도 없음)", () => {
    const { comp } = mountTest(() => h("div", null, h("b", { onClick: null }), h("i", { onClick: undefined }), h("u", { onClick: false })));
    assertEqual(comp.vdom.children[0].children.map((c) => c.props), [{}, {}, {}]);
  });

  test("onClick 이 문자열이면 TypeError (문자열 코드를 실행하지 않음)", () => {
    assertThrows(() => mountTest(() => h("button", { onClick: "alert(1)" })), TypeError);
  });

  test("on 으로 시작해도 대문자가 아니면 일반 속성 (oncology 같은 이름)", () => {
    const { comp } = mountTest(() => h("p", { online: "yes" }));
    assertEqual(comp.vdom.children[0].props, { online: "yes" });
  });

  test("이벤트가 일어난 요소가 사라진 뒤에도 오류 없음", async () => {
    let setShow;
    const { box } = mountTest(() => {
      const [show, set] = useState(true);
      setShow = set;
      return show ? h("button", { onClick: () => setShow(false) }, "x") : h("p", null, "사라짐");
    });
    const btn = box.querySelector("button");
    click(btn);
    await settle();
    click(btn); // 떨어져 나간 버튼 → 컨테이너까지 올라가지 않으므로 아무 일도 없음
    assertEqual(box.textContent, "사라짐");
  });

  test("extractHandlers 는 원래 트리를 바꾸지 않는다 (useMemo 로 재사용하는 VNode 보호)", () => {
    const fn = () => {};
    const original = h("div", null, h("button", { onClick: fn }));
    const { vdom } = extractHandlers(original);
    assertEqual(original.children[0].props.onClick, fn);
    assertEqual(vdom.children[0].props, { "data-on-click": "0" });
  });
});

describe("Phase 2 · 폼 요소 (제어 컴포넌트)", () => {
  test("사용자가 입력한 input 도 상태로 값을 바꾸면 화면 값이 바뀜 (value 프로퍼티 동기화)", () => {
    let value = "a";
    const { comp, box } = mountTest(() => h("input", { value }));
    const input = box.querySelector("input");
    input.value = "사용자가 친 글자"; // 사용자 입력 → 이제 value 속성만으로는 화면 값이 안 바뀜
    value = "";
    comp.update();
    assertEqual(input.value, "");
    assertEqual(input.getAttribute("value"), "");
  });

  test("checked: true → false 로 바뀌면 체크가 풀림", () => {
    let checked = true;
    const { comp, box } = mountTest(() => h("input", { type: "checkbox", checked }));
    const input = box.querySelector("input");
    assert(input.checked);
    checked = false;
    comp.update();
    assert(!input.checked);
  });

  test("checked 속성이 아예 사라지는 경우(PROPS remove)도 체크가 풀림", () => {
    let on = true;
    const { comp, box } = mountTest(() => h("input", on ? { type: "checkbox", checked: true } : { type: "checkbox" }));
    on = false;
    comp.update();
    assert(!box.querySelector("input").checked);
  });

  test("option 의 selected 로 select 의 선택이 바뀜", () => {
    let pick = "a";
    const { comp, box } = mountTest(() => h("select", null, ["a", "b"].map((v) => h("option", { value: v, selected: v === pick }, v))));
    assertEqual(box.querySelector("select").value, "a");
    pick = "b";
    comp.update();
    assertEqual(box.querySelector("select").value, "b");
  });

  test("값이 같으면 value 프로퍼티를 다시 쓰지 않음 (입력 중 커서 위치 유지)", () => {
    let cls = "a";
    const { comp, box } = mountTest(() => h("input", { value: "abc", class: cls }));
    const input = box.querySelector("input");
    // value 프로퍼티에 쓰는 횟수를 센다 (원래 동작은 그대로 유지)
    const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value");
    let writes = 0;
    Object.defineProperty(input, "value", {
      configurable: true,
      get: () => desc.get.call(input),
      set: (v) => {
        writes += 1;
        desc.set.call(input, v);
      },
    });
    cls = "b";
    comp.update(); // class 만 바뀜 → value 는 PROPS 패치에 없음
    assertEqual(writes, 0);
    delete input.value;
  });
});

describe("Phase 2 · unmount · onCommit", () => {
  test("unmount: effect 정리, 컨테이너 비움, 리스너 제거, 이후 setState 무시", async () => {
    const log = [];
    let setter;
    let clicks = 0;
    const { comp, box } = mountTest(() => {
      const [n, setN] = useState(0);
      setter = setN;
      useEffect(() => () => log.push("cleanup"), []);
      return h("button", { onClick: () => clicks++ }, String(n));
    });
    const btn = box.querySelector("button");
    comp.unmount();
    assertEqual(log, ["cleanup"]);
    assertEqual(box.childNodes.length, 0);
    box.append(btn);
    click(btn);
    assertEqual(clicks, 0, "리스너가 제거되어야 함");
    setter(5);
    await settle();
    assertEqual(comp.renderCount, 1);
    assertEqual(comp.update(), []);
  });

  test("unmount 를 두 번 불러도 정리는 한 번, 다시 mount 는 오류", () => {
    let cleanups = 0;
    const { comp } = mountTest(() => {
      useEffect(() => () => cleanups++, []);
      return null;
    });
    comp.unmount();
    comp.unmount();
    assertEqual(cleanups, 1);
    assertThrows(() => comp.mount());
  });

  test("onCommit: mount · update 때마다 정보 전달, 구독 해제 가능", () => {
    let text = "a";
    const box = document.createElement("div");
    const comp = new FunctionComponent(() => h("p", null, text), box);
    const seen = [];
    const off = comp.onCommit((info) => seen.push([info.reason, info.renderCount, info.patches && info.patches.length, info.touched.length, typeof info.ms]));
    comp.mount();
    text = "b";
    comp.update();
    off();
    comp.update();
    assertEqual(seen, [["mount", 1, null, 1, "number"], ["update", 2, 1, 1, "number"]]);
  });

  test("onCommit 구독자가 오류를 내도 렌더와 effect 는 계속", () => {
    let ran = false;
    const box = document.createElement("div");
    const comp = new FunctionComponent(() => {
      useEffect(() => {
        ran = true;
      }, []);
      return h("p");
    }, box);
    comp.onCommit(() => {
      throw new Error("구독자 오류");
    });
    const { errors } = captureConsole(() => comp.mount());
    assert(ran);
    assertEqual(errors.length, 1);
  });
});
