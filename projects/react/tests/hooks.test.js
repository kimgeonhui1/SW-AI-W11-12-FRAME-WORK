// [tests/hooks.test.js] Phase 2 — useState · useEffect · useMemo 단위 테스트

import { describe, test, assert, assertEqual } from "./runner.js";
import { h } from "../src/core/vdom.js";
import { FunctionComponent, MAX_NESTED_UPDATES } from "../src/core/component.js";
import { useState, useEffect, useMemo } from "../src/core/hooks.js";
import { assertThrows, captureConsole } from "./helpers.js";

/**
 * 테스트용 컴포넌트를 마운트한다.
 * body(api) 가 컴포넌트 본문. api.renders 로 렌더 횟수, api.box 로 컨테이너를 본다.
 */
function setup(body, props) {
  const box = document.createElement("div");
  const api = { renders: 0, box };
  api.comp = new FunctionComponent((p) => {
    api.renders += 1;
    return body(api, p);
  }, box, props).mount();
  return api;
}

/** useState 하나만 쓰는 컴포넌트를 마운트한다. view(값) 이 렌더 결과. → { api, set } */
function withState(initial, view) {
  let set;
  const api = setup(() => {
    const [value, setValue] = useState(initial);
    set = setValue;
    return view(value);
  });
  return { api, set: (next) => set(next) };
}

/** 예약된 렌더가 끝날 때까지 */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("Phase 2 · useState", () => {
  test("초깃값으로 시작, hooks 배열에 저장", () => {
    const api = setup(() => h("p", null, String(useState(3)[0])));
    assertEqual(api.box.textContent, "3");
    assertEqual(api.comp.hooks.length, 1);
    assertEqual(api.comp.hooks[0].kind, "state");
    assertEqual(api.comp.hooks[0].value, 3);
  });

  test("함수를 넘기면 첫 렌더에서 한 번만 실행 (지연 초기화)", async () => {
    let calls = 0;
    const { set } = withState(() => (calls++, "init"), (v) => v);
    set("next");
    await settle();
    assertEqual(calls, 1);
  });

  test("setState 하면 다시 렌더되고, 함수는 다시 실행돼도 값이 유지된다", async () => {
    const { api, set } = withState(0, (n) => h("p", null, String(n)));
    set(5);
    await settle();
    assertEqual(api.box.textContent, "5");
    assertEqual(api.renders, 2);
    api.comp.update(); // 다른 이유로 다시 렌더해도 5 유지
    assertEqual(api.box.textContent, "5");
  });

  test("setState 함수는 렌더가 바뀌어도 같은 함수", async () => {
    const setters = [];
    setup(() => {
      const [, set] = useState(0);
      setters.push(set);
      if (setters.length === 1) queueMicrotask(() => set(1));
      return null;
    });
    await settle();
    assertEqual(setters.length, 2);
    assert(setters[0] === setters[1]);
  });

  test("같은 값(Object.is)이면 다시 렌더하지 않음 — NaN 도 같은 값", async () => {
    const { api, set } = withState(NaN, (_) => null);
    set(NaN);
    await settle();
    assertEqual(api.renders, 1);
  });

  test("객체는 내용이 같아도 새 객체면 다시 렌더 (참조 비교)", async () => {
    const { api, set } = withState({ a: 1 }, (_) => null);
    set({ a: 1 });
    await settle();
    assertEqual(api.renders, 2);
  });

  test("배칭: setState 를 3번 불러도 렌더는 1번", async () => {
    const { api, set } = withState(0, (n) => String(n));
    set(1);
    set(2);
    set(3);
    assertEqual(api.renders, 1, "바로 렌더하지 않음");
    await settle();
    assertEqual(api.renders, 2);
    assertEqual(api.box.textContent, "3");
  });

  test("함수형 업데이트 3번 → +3, 값 업데이트 3번 → +1 (React 와 같음)", async () => {
    let n;
    let set;
    const api = setup(() => {
      [n, set] = useState(0);
      return String(n);
    });
    set((v) => v + 1);
    set((v) => v + 1);
    set((v) => v + 1);
    await settle();
    assertEqual(api.box.textContent, "3");
    set(n + 1);
    set(n + 1);
    set(n + 1);
    await settle();
    assertEqual(api.box.textContent, "4");
  });

  test("서로 다른 상태 여러 개를 바꿔도 렌더는 1번", async () => {
    let setA;
    let setB;
    const api = setup(() => {
      const [a, sa] = useState("a");
      const [b, sb] = useState("b");
      setA = sa;
      setB = sb;
      return a + b;
    });
    setA("A");
    setB("B");
    await settle();
    assertEqual([api.box.textContent, api.renders], ["AB", 2]);
  });

  test("렌더 도중 setState → 오류 (무한 렌더 방지), DOM 그대로", () => {
    let first = true;
    const api = setup(() => {
      const [n, set] = useState(0);
      if (!first) set(n + 1);
      first = false;
      return String(n);
    });
    assertThrows(() => api.comp.update());
    assertEqual(api.box.textContent, "0");
  });

  test("렌더 밖에서 Hook 을 부르면 오류", () => {
    assertThrows(() => useState(0));
    assertThrows(() => useEffect(() => {}));
    assertThrows(() => useMemo(() => 1, []));
  });

  test("비동기(setTimeout)에서 setState 해도 반영", async () => {
    const { api, set } = withState("전", (v) => v);
    await new Promise((resolve) => setTimeout(() => (set("후"), resolve()), 5));
    await settle();
    assertEqual(api.box.textContent, "후");
  });

  test("flush() 로 예약된 렌더를 바로 실행 · 예약이 없으면 아무것도 안 함", () => {
    const { api, set } = withState(0, (v) => String(v));
    api.comp.flush();
    assertEqual(api.renders, 1);
    set(9);
    api.comp.flush();
    assertEqual([api.renders, api.box.textContent], [2, "9"]);
  });
});

describe("Phase 2 · Hook 규칙", () => {
  test("조건에 따라 Hook 순서가 바뀌면 오류, DOM 그대로", () => {
    let swap = false;
    const api = setup(() => {
      if (swap) {
        useMemo(() => 1, []);
        useState(0);
      } else {
        useState(0);
        useMemo(() => 1, []);
      }
      return "x";
    });
    swap = true;
    const err = assertThrows(() => api.comp.update());
    assert(err.message.includes("순서"), err.message);
    assertEqual(api.box.textContent, "x");
  });

  test("이전보다 Hook 을 적게 부르면 오류", () => {
    let fewer = false;
    const api = setup(() => {
      useState(0);
      if (!fewer) useState(1);
      return null;
    });
    fewer = true;
    assertThrows(() => api.comp.update());
  });

  test("이전보다 Hook 을 많이 부르면 오류", () => {
    let more = false;
    const api = setup(() => {
      useState(0);
      if (more) useState(1);
      return null;
    });
    more = true;
    assertThrows(() => api.comp.update());
  });

  test("오류 뒤에도 원래 순서로 렌더하면 정상 동작", () => {
    let swap = false;
    const api = setup(() => {
      const [a] = swap ? [useMemo(() => "m", [])] : useState("s");
      return a;
    });
    swap = true;
    assertThrows(() => api.comp.update());
    swap = false;
    api.comp.update();
    assertEqual(api.box.textContent, "s");
  });
});

describe("Phase 2 · useEffect", () => {
  test("렌더 중이 아니라 화면 반영 뒤에 실행 (effect 안에서 새 DOM 을 읽을 수 있음)", () => {
    const seen = [];
    const api = setup((a) => {
      useEffect(() => seen.push(a.box.textContent), []);
      seen.push("render");
      return "화면";
    });
    assertEqual(seen, ["render", "화면"]);
    assertEqual(api.renders, 1);
  });

  test("deps 없음 → 매 렌더 실행", () => {
    let runs = 0;
    const api = setup(() => {
      useEffect(() => {
        runs += 1;
      });
      return null;
    });
    api.comp.update();
    api.comp.update();
    assertEqual(runs, 3);
  });

  test("deps [] → 처음 한 번만", () => {
    let runs = 0;
    const api = setup(() => {
      useEffect(() => {
        runs += 1;
      }, []);
      return null;
    });
    api.comp.update();
    api.comp.update();
    assertEqual(runs, 1);
  });

  test("deps 값이 바뀔 때만 다시 실행 (Object.is 비교)", () => {
    let dep = 1;
    const runs = [];
    const api = setup(() => {
      useEffect(() => {
        runs.push(dep);
      }, [dep]);
      return null;
    });
    api.comp.update(); //  1 → 1 : 실행 안 함
    dep = 2;
    api.comp.update(); //  1 → 2 : 실행
    dep = NaN;
    api.comp.update(); //  2 → NaN : 실행
    api.comp.update(); //  NaN → NaN : 실행 안 함
    // runner 의 deepEqual 은 NaN !== NaN 이라 직접 비교
    assertEqual(runs.length, 3);
    assert(runs[0] === 1 && runs[1] === 2 && Number.isNaN(runs[2]), String(runs));
  });

  test("deps 길이가 바뀌어도 다시 실행", () => {
    let deps = [1];
    let runs = 0;
    const api = setup(() => {
      useEffect(() => {
        runs += 1;
      }, deps);
      return null;
    });
    deps = [1, 2];
    api.comp.update();
    assertEqual(runs, 2);
  });

  test("다시 실행하기 전에 이전 cleanup 먼저, 순서는 선언 순서", () => {
    let dep = "a";
    const log = [];
    const api = setup(() => {
      useEffect(() => {
        log.push(`effect1 ${dep}`);
        return () => log.push(`cleanup1 ${dep}`);
      }, [dep]);
      useEffect(() => {
        log.push(`effect2 ${dep}`);
        return () => log.push(`cleanup2 ${dep}`);
      }, [dep]);
      return null;
    });
    dep = "b";
    api.comp.update();
    // cleanup 안의 dep 는 부를 때의 바깥 변수 값("b")을 읽는다. 순서가 핵심: 각 effect 마다 cleanup → effect
    assertEqual(log, ["effect1 a", "effect2 a", "cleanup1 b", "effect1 b", "cleanup2 b", "effect2 b"]);
  });

  test("cleanup 은 이전 렌더의 값을 기억한다 (클로저)", () => {
    let dep = "a";
    const log = [];
    const api = setup(() => {
      const captured = dep;
      useEffect(() => () => log.push(captured), [dep]);
      return null;
    });
    dep = "b";
    api.comp.update();
    assertEqual(log, ["a"]);
  });

  test("언마운트하면 모든 cleanup 실행", () => {
    const log = [];
    const api = setup(() => {
      useEffect(() => () => log.push("1"), []);
      useEffect(() => () => log.push("2"));
      useEffect(() => undefined, []); // cleanup 없음
      return null;
    });
    api.comp.unmount();
    assertEqual(log, ["1", "2"]);
  });

  test("effect 가 함수가 아닌 값을 돌려주면 cleanup 으로 쓰지 않음", () => {
    const api = setup(() => {
      useEffect(() => 42, []);
      return null;
    });
    api.comp.unmount(); // 오류 없이 끝나야 함
    assertEqual(api.comp.hooks[0].cleanup, null);
  });

  test("effect 안에서 setState → 렌더 1번 더 (deps 로 멈춤)", async () => {
    const api = setup(() => {
      const [n, set] = useState(0);
      useEffect(() => {
        if (n < 3) set(n + 1);
      }, [n]);
      return String(n);
    });
    await settle();
    assertEqual(api.box.textContent, "3");
    assertEqual(api.renders, 4);
  });

  test(`effect 에서 끝없이 setState → ${MAX_NESTED_UPDATES}번 넘으면 멈추고 오류`, async () => {
    const errors = [];
    const onError = (event) => {
      errors.push(event.message || String(event.error));
      event.preventDefault(); // 의도된 오류 → 콘솔에 빨갛게 남기지 않음
    };
    window.addEventListener("error", onError);
    let api;
    try {
      api = setup(() => {
        const [n, set] = useState(0);
        useEffect(() => set(n + 1)); // deps 없음 → 매번 실행 → 무한 반복
        return String(n);
      });
      await new Promise((resolve) => setTimeout(resolve, 50));
    } finally {
      window.removeEventListener("error", onError);
      api?.comp.unmount();
    }
    assert(errors.some((m) => m.includes(String(MAX_NESTED_UPDATES))), `오류가 나야 함: ${errors}`);
    assert(api.renders <= MAX_NESTED_UPDATES + 1, `렌더 ${api.renders}번`);
  });

  test("effect 하나가 오류를 내도 다음 effect 는 실행, 오류는 콘솔에", () => {
    let second = false;
    const { errors } = captureConsole(() =>
      setup(() => {
        useEffect(() => {
          throw new Error("effect 오류");
        }, []);
        useEffect(() => {
          second = true;
        }, []);
        return null;
      }),
    );
    assert(second);
    assertEqual(errors.length, 1);
  });

  test("잘못된 인자: callback 이 함수 아님 · deps 가 배열 아님 → TypeError", () => {
    assertThrows(() => setup(() => (useEffect(null), null)), TypeError);
    assertThrows(() => setup(() => (useEffect(() => {}, "a"), null)), TypeError);
  });
});

describe("Phase 2 · useMemo", () => {
  test("처음 계산한 값을 deps 가 같으면 재사용 (factory 한 번)", () => {
    let calls = 0;
    const values = [];
    const api = setup(() => {
      values.push(useMemo(() => (calls++, { big: true }), [1]));
      return null;
    });
    api.comp.update();
    api.comp.update();
    assertEqual(calls, 1);
    assert(values[0] === values[2], "같은 객체(참조)를 돌려줘야 함");
  });

  test("deps 가 바뀌면 다시 계산", () => {
    let n = 2;
    const api = setup(() => h("p", null, String(useMemo(() => n * n, [n]))));
    n = 3;
    api.comp.update();
    assertEqual(api.box.textContent, "9");
  });

  test("deps 없음 → 매 렌더 다시 계산, [] → 한 번", () => {
    let every = 0;
    let once = 0;
    const api = setup(() => {
      useMemo(() => every++);
      useMemo(() => once++, []);
      return null;
    });
    api.comp.update();
    assertEqual([every, once], [2, 1]);
  });

  test("상태가 바뀌어도 관련 없는 memo 는 재계산하지 않음", async () => {
    let calls = 0;
    let setOther;
    setup(() => {
      const [list] = useState([1, 2, 3]);
      const [, so] = useState("");
      setOther = so;
      useMemo(() => (calls++, list.reduce((a, b) => a + b, 0)), [list]);
      return null;
    });
    setOther("타이핑");
    await settle();
    assertEqual(calls, 1);
  });

  test("factory 가 undefined 를 돌려줘도 재사용 (계산 여부를 따로 기억)", () => {
    let calls = 0;
    const api = setup(() => (useMemo(() => void calls++, []), null));
    api.comp.update();
    assertEqual(calls, 1);
  });

  test("잘못된 인자 → TypeError", () => {
    assertThrows(() => setup(() => (useMemo(5, []), null)), TypeError);
    assertThrows(() => setup(() => (useMemo(() => 1, { length: 0 }), null)), TypeError);
  });
});
