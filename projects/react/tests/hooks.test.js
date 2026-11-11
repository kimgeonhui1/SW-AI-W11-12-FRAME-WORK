import { h } from "../src/core/vdom.js";
import { FunctionComponent } from "../src/core/component.js";
import { useState, useEffect, useMemo } from "../src/core/hooks.js";

let passed = 0;
const results = document.querySelector("#results");
const assert = (value, message) => { if (!value) throw new Error(message); };
function rejects(run, message) {
  let rejected = false;
  try { run(); } catch (error) { rejected = error.message.includes(message); }
  assert(rejected, `예외 누락: ${message}`);
}
function test(name, run) {
  const item = document.createElement("li");
  try { run(); passed++; item.textContent = `PASS — ${name}`; }
  catch (error) { item.textContent = `FAIL — ${name}: ${error.message}`; }
  results.appendChild(item);
}
function instance(render) {
  const box = document.createElement("div");
  const component = new FunctionComponent(render, box);
  component.mount();
  return { box, component };
}

test("최초 마운트, 상태 보존, 함수형 갱신 및 p/Text identity", () => {
  let set;
  let initializations = 0;
  const { box, component } = instance(() => {
    const [count, setter] = useState(() => { initializations++; return 0; });
    set = setter;
    return h("p", {}, String(count));
  });
  const p = box.firstChild;
  const text = p.firstChild;
  const firstSetter = set;
  assert(box.textContent === "0", "최초 렌더 오류");
  set(2); set(previous => previous + 3); component.update();
  assert(box.textContent === "5" && initializations === 1, "State 재초기화/함수형 갱신 오류");
  assert(p === box.firstChild && text === p.firstChild && set === firstSetter, "DOM/setter identity 손실");
});
test("같은 값은 렌더 생략, Object.is로 NaN과 signed zero 구분", () => {
  let set;
  let renders = 0;
  instance(() => {
    const [value, setter] = useState(NaN); set = setter; renders++;
    return h("p", {}, String(value));
  });
  set(NaN); assert(renders === 1, "NaN 동일 값 재렌더");
  set(0); set(-0); assert(renders === 3, "signed zero 미구분");
});
test("서로 다른 인스턴스와 여러 State 슬롯 격리", () => {
  const setters = [];
  function render() {
    const [a, setA] = useState(0);
    const [b, setB] = useState(10);
    setters.push([setA, setB]);
    return h("p", {}, `${a}:${b}`);
  }
  const first = instance(render);
  const firstSet = setters[0];
  const second = instance(render);
  const secondSet = setters[1];
  firstSet[0](3); secondSet[1](20); firstSet[1](previous => previous + 1);
  assert(first.box.textContent === "3:11" && second.box.textContent === "0:20", "인스턴스/슬롯 오염");
});
test("혼합 Hook 인덱스, Memo 캐시, Effect DOM 반영 후 cleanup 순서", () => {
  let setCount, setLabel;
  let calculations = 0;
  const log = [];
  const box = document.createElement("div");
  const component = new FunctionComponent(() => {
    const [count, a] = useState(0); setCount = a;
    useEffect(() => {
      log.push(`effect:${count}:${box.textContent}`);
      return () => log.push(`cleanup:${count}:${box.textContent}`);
    }, [count]);
    const memo = useMemo(() => { calculations++; return { value: count * 2 }; }, [count]);
    const [label, b] = useState("A"); setLabel = b;
    return h("p", {}, `${count}/${memo.value}/${label}`);
  }, box);
  component.mount();
  const cached = component.hooks[2].value;
  setLabel("B");
  assert(calculations === 1 && component.hooks[2].value === cached && log.length === 1, "의존성 유지 시 재계산/Effect 실행");
  setCount(1);
  assert(calculations === 2 && box.textContent === "1/2/B", "혼합 슬롯 충돌");
  assert(JSON.stringify(log) === JSON.stringify([
    "effect:0:0/0/A", "cleanup:0:1/2/B", "effect:1:1/2/B"
  ]), "DOM 반영/cleanup/Effect 순서 오류");
});
test("빈 의존성은 최초만, 생략은 매 렌더와 cleanup", () => {
  let once = 0, always = 0, cleanups = 0, memoOnce = 0, memoAlways = 0;
  const { component } = instance(() => {
    useEffect(() => { once++; }, []);
    useEffect(() => { always++; return () => cleanups++; });
    useMemo(() => { memoOnce++; return undefined; }, []);
    useMemo(() => { memoAlways++; return undefined; });
    return h("p", {}, "same");
  });
  component.update(); component.update();
  assert(once === 1 && always === 3 && cleanups === 2 && memoOnce === 1 && memoAlways === 3, "빈/생략 의존성 또는 undefined 캐시 오류");
});
test("의존성 배열 복사, 길이 변화 및 Object.is 비교", () => {
  let deps = [NaN, 0];
  let effects = 0, memos = 0;
  const { component } = instance(() => {
    useEffect(() => { effects++; }, deps);
    useMemo(() => ++memos, deps);
    return h("p");
  });
  component.update(); assert(effects === 1 && memos === 1, "NaN 의존성 비교 오류");
  deps[1] = -0; component.update();
  assert(effects === 2 && memos === 2, "배열 참조를 저장해 변경 누락");
  deps = [NaN]; component.update();
  assert(effects === 3 && memos === 3, "배열 길이 변경 누락");
});
test("렌더 예외 후 실행 문맥 정리, Effect 미실행, 다른 인스턴스 정상", () => {
  let effects = 0;
  const box = document.createElement("div");
  const broken = new FunctionComponent(() => {
    useState(1); useEffect(() => { effects++; }, []);
    throw new Error("render failed");
  }, box);
  rejects(() => broken.mount(), "render failed");
  assert(!broken.busy && box.childNodes.length === 0 && effects === 0, "실패 렌더 반영/문맥 잠금");
  rejects(() => useState(0), "component render");
  rejects(() => useEffect(() => {}), "component render");
  rejects(() => useMemo(() => 1), "component render");
  const normal = instance(() => h("p", {}, String(useState(7)[0])));
  assert(normal.box.textContent === "7", "이전 실행 문맥 유출");
});
test("Hook 종류/개수 변경 및 렌더 중 setter는 명시적 오류", () => {
  let mode = "state";
  const { component } = instance(() => {
    if (mode === "state") useState(0);
    else if (mode === "memo") useMemo(() => 0, []);
    return h("p");
  });
  mode = "memo"; rejects(() => component.update(), "Hook order changed");
  mode = "none"; rejects(() => component.update(), "Hook count changed");
  rejects(() => instance(() => {
    const [, set] = useState(0); set(1); return h("p");
  }), "during render");
});
test("Effect 내부 State 갱신은 현재 Effect 처리 후 다시 렌더", () => {
  const events = [];
  const { box } = instance(() => {
    const [count, set] = useState(0);
    useEffect(() => {
      events.push(`first:${count}`);
      if (count === 0) set(previous => previous + 1);
    }, [count]);
    useEffect(() => { events.push(`second:${count}`); }, [count]);
    return h("p", {}, String(count));
  });
  assert(box.textContent === "1" && events.join() === "first:0,second:0,first:1,second:1", "Effect 중 재진입");
});
test("Effect 예외 후 busy와 활성 문맥 정리", () => {
  const box = document.createElement("div");
  const broken = new FunctionComponent(() => {
    useEffect(() => { throw new Error("effect failed"); }, []);
    return h("p", {}, "committed");
  }, box);
  rejects(() => broken.mount(), "effect failed");
  assert(!broken.busy && box.textContent === "committed", "Effect 예외 처리 시점 오류");
  rejects(() => useState(0), "component render");
});

test("중첩 인스턴스 렌더 후 바깥 Hook 실행 문맥 복구", () => {
  let nested;
  const outer = instance(() => {
    const [first] = useState("outer");
    nested = instance(() => h("p", {}, useState("inner")[0]));
    const [last] = useState("tail");
    return h("p", {}, first + last);
  });
  assert(outer.box.textContent === "outertail" && nested.box.textContent === "inner", "활성 인스턴스 복구 실패");
  assert(outer.component.hooks.length === 2 && nested.component.hooks.length === 1, "중첩 Hook 슬롯 오염");
  rejects(() => useState(0), "component render");
});
test("무한 Effect 갱신은 유한 횟수 후 오류로 중단하고 문맥 해제", () => {
  const box = document.createElement("div");
  let calls = 0;
  const component = new FunctionComponent(() => {
    const [count, set] = useState(0);
    useEffect(() => { calls++; set(previous => previous + 1); });
    return h("p", {}, String(count));
  }, box);
  rejects(() => component.mount(), "Too many effect-driven updates");
  assert(calls === 25 && !component.busy && !component.pendingUpdate, "무한 갱신 방어 실패");
  rejects(() => useState(0), "component render");
});

const summary = document.querySelector("#summary");
summary.textContent = `${passed}/${results.children.length} PASS`;
summary.dataset.status = passed === results.children.length ? "pass" : "fail";
