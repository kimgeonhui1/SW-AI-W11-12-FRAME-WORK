// [hooks.js] 상태와 생명주기를 다루는 Hooks (useState / useEffect / useMemo)

/**
 * ── 핵심 질문: "함수는 매번 새로 실행되는데, 상태는 어떻게 유지할까?" ──────────
 *
 * 함수 컴포넌트 안의 지역 변수는 함수가 끝나면 사라진다. 그래서 상태를 함수 "바깥" 에 둔다.
 *
 *   FunctionComponent 인스턴스 (함수 바깥, 계속 살아 있음)
 *     hooks = [ {state: 3}, {memo: …}, {effect: …} ]   ← 진짜 저장소
 *
 *   App() 실행 (렌더할 때마다 새로 실행)
 *     const [count, setCount] = useState(0);   → hooks[0] 을 읽음
 *     const total = useMemo(…);                → hooks[1] 을 읽음
 *     useEffect(…);                            → hooks[2] 를 읽음
 *
 * Hook 은 "이름" 이 아니라 "몇 번째로 불렸는지(인덱스)" 로 자기 칸을 찾는다.
 * 그래서 렌더할 때마다 Hook 을 "같은 순서, 같은 개수" 로 불러야 한다.
 * (조건문 · 반복문 안에서 Hook 을 부르면 안 되는 이유. 아래 nextHook 이 이를 검사한다)
 *
 * 이 파일은 "지금 렌더 중인 컴포넌트" 와 "다음 Hook 인덱스" 를 모듈 변수로 들고 있다.
 * FunctionComponent(component.js) 가 렌더 직전에 prepareHooks, 직후에 finishHooks 를 부른다.
 * ─────────────────────────────────────────────────────────────────────
 */

// ── 렌더 중인 컴포넌트 정보 (모듈 내부 상태) ─────────────────────────

/** 지금 렌더 중인 FunctionComponent. 렌더 중이 아니면 null */
let current = null;
/** 이번 렌더에서 다음에 읽을 hooks 칸 번호 */
let hookIndex = 0;
/** 이번이 첫 렌더인가 (hooks 칸을 새로 만들어도 되는가) */
let firstRender = false;
/** 자식(stateless) 컴포넌트를 실행 중인 깊이. 0 보다 크면 Hook 호출 금지 */
let childDepth = 0;

/**
 * [component.js 전용] 렌더 시작: 이 컴포넌트의 hooks 를 처음부터 읽을 준비
 * @param {object} instance FunctionComponent
 */
export function prepareHooks(instance) {
  if (current) {
    // 렌더 도중에 다른 루트를 렌더하면 Hook 이 엉뚱한 컴포넌트에 붙는다
    throw new Error("[hooks] 다른 컴포넌트를 렌더하는 도중에는 렌더를 시작할 수 없습니다.");
  }
  current = instance;
  hookIndex = 0;
  firstRender = !instance.mounted; // 마운트 전이면 hooks 칸을 새로 만드는 렌더
  childDepth = 0;
}

/**
 * [component.js 전용] 렌더 끝: Hook 개수가 이전 렌더와 같은지 확인하고 정리
 * @param {boolean} completed 컴포넌트 함수가 끝까지 실행되었는가 (예외로 중간에 멈췄으면 false → 개수 검사 생략)
 */
export function finishHooks(completed = true) {
  const instance = current;
  const used = hookIndex;
  current = null;
  hookIndex = 0;
  childDepth = 0;
  if (completed && instance && instance.mounted && used !== instance.hooks.length) {
    throw new Error(
      `[hooks] 이번 렌더에서 Hook 을 ${used}개 불렀지만 이전 렌더에서는 ${instance.hooks.length}개였습니다. ` +
        "Hook 은 조건문 · 반복문 · 일찍 return 하는 코드 뒤가 아니라 컴포넌트 맨 위에서 항상 같은 순서로 불러야 합니다.",
    );
  }
}

/** [component.js 전용] 지금 렌더 중인가 (렌더 중 setState 를 막는 데 사용) */
export function isRendering() {
  return current !== null;
}

/**
 * [component.js 전용] 자식(stateless) 컴포넌트 실행 구간 표시
 * 자식 안에서 Hook 을 부르면 nextHook 이 오류를 던진다.
 */
export function enterChild() {
  childDepth += 1;
}
export function exitChild() {
  childDepth -= 1;
}

/**
 * 이번 Hook 의 칸을 꺼낸다. (모든 Hook 공통)
 * - 렌더 중이 아니거나, 자식 컴포넌트 안이면 오류
 * - 첫 렌더: create() 로 새 칸을 만든다
 * - 다시 렌더: 같은 자리의 칸이 같은 종류인지 확인한다
 *
 * @param {string} kind "state" | "effect" | "memo"
 * @param {() => object} create 첫 렌더에서 칸을 만드는 함수
 */
function nextHook(kind, create) {
  const name = `use${kind[0].toUpperCase()}${kind.slice(1)}`;
  if (!current) {
    throw new Error(`[hooks] ${name} 는 컴포넌트를 렌더하는 동안에만 부를 수 있습니다.`);
  }
  if (childDepth > 0) {
    throw new Error(
      `[hooks] ${name} 는 최상위(루트) 컴포넌트에서만 쓸 수 있습니다. ` +
        "자식 컴포넌트는 상태 없이 props 만 받아야 합니다 (Lifting State Up).",
    );
  }

  const hooks = current.hooks;
  const index = hookIndex;
  hookIndex += 1;

  if (index >= hooks.length) {
    if (!firstRender) {
      throw new Error(
        `[hooks] 이전 렌더보다 Hook 을 더 많이 불렀습니다 (${index + 1}번째 ${name}). ` +
          "Hook 은 조건문 · 반복문 안에서 부르면 안 됩니다.",
      );
    }
    const hook = { kind, ...create() };
    hooks.push(hook);
    return hook;
  }

  const hook = hooks[index];
  if (hook.kind !== kind) {
    throw new Error(
      `[hooks] ${index + 1}번째 Hook 이 이전 렌더에서는 use${hook.kind[0].toUpperCase()}${hook.kind.slice(1)} 였는데 ` +
        `이번에는 ${name} 입니다. Hook 호출 순서가 바뀌었습니다.`,
    );
  }
  return hook;
}

/** deps 배열 검사: 없음(undefined) 또는 배열만 허용 */
function checkDeps(deps, name) {
  if (deps !== undefined && !Array.isArray(deps)) {
    throw new TypeError(`[hooks] ${name} 의 의존성 목록은 배열이어야 합니다: ${String(deps)}`);
  }
}

/**
 * 의존성이 바뀌었는가
 * - deps 없음(undefined): 매번 바뀐 것으로 본다 → 렌더할 때마다 실행
 * - 길이가 다르거나, 같은 자리 값이 Object.is 로 다르면 바뀐 것
 *   (Object.is: NaN 은 NaN 과 같고, +0 과 -0 은 다르다. React 와 같은 비교)
 */
function depsChanged(prev, next) {
  if (prev === undefined || next === undefined) return true;
  if (prev.length !== next.length) return true;
  return next.some((value, i) => !Object.is(value, prev[i]));
}

// ── 공개 Hooks ──────────────────────────────────────────────────────

/**
 * 상태 저장 + 변경 시 재렌더링
 *
 * @param {*} initial 처음 값. 함수면 첫 렌더에서 한 번만 실행해 그 결과를 쓴다 (지연 초기화)
 * @returns {[any, (next: any) => void]} [현재 값, 값을 바꾸는 함수]
 *
 * setState(next)
 *   - next 가 함수면 next(이전 값) 의 결과로, 아니면 next 로 바꾼다.
 *   - 새 값이 이전 값과 Object.is 로 같으면 아무것도 하지 않는다 (불필요한 렌더 생략).
 *   - 다르면 값을 바꾸고 컴포넌트에 다시 렌더링을 "예약" 한다. (바로 렌더하지 않음 → 배칭)
 *   - setState 함수는 렌더가 바뀌어도 같은 함수다 (useEffect deps 에 넣어도 안전).
 */
export function useState(initial) {
  const instance = current;
  const hook = nextHook("state", () => ({
    value: typeof initial === "function" ? initial() : initial,
    setState: null,
  }));

  if (!hook.setState) {
    // 첫 렌더에서 한 번만 만든다. instance 를 클로저로 기억하므로 나중에 이벤트에서 불러도 된다.
    hook.setState = (next) => {
      if (instance.unmounted) return; // 언마운트된 컴포넌트는 무시
      if (isRendering()) {
        throw new Error("[hooks] 렌더링 도중에는 setState 를 부를 수 없습니다. 이벤트 핸들러나 useEffect 안에서 부르세요.");
      }
      const value = typeof next === "function" ? next(hook.value) : next;
      if (Object.is(value, hook.value)) return; // 같은 값 → 렌더 생략 (bail out)
      hook.value = value;
      instance.scheduleUpdate();
    };
  }
  return [hook.value, hook.setState];
}

/**
 * 렌더링 후 부수효과 실행 (의존성이 바뀔 때만)
 *
 * @param {() => (void | (() => void))} callback 화면 반영 뒤 실행할 함수. 함수를 돌려주면 정리(cleanup) 함수로 기억
 * @param {any[]} [deps] 의존성 목록. 없으면 매 렌더, [] 면 처음 한 번, [a, b] 면 a · b 가 바뀔 때
 *
 * 렌더 중에는 실행하지 않고 "실행 예정(pending)" 표시만 한다.
 * 실제 실행은 FunctionComponent 가 DOM 에 반영(commit)한 뒤 runEffects 로 한다.
 * → effect 안에서 DOM 을 읽으면 이미 새 화면이 반영되어 있다.
 */
export function useEffect(callback, deps) {
  checkDeps(deps, "useEffect");
  if (typeof callback !== "function") throw new TypeError("[hooks] useEffect 에는 함수를 넘겨야 합니다.");
  const hook = nextHook("effect", () => ({ deps: undefined, cleanup: null, pending: false, callback: null, ran: false }));
  if (!hook.ran || depsChanged(hook.deps, deps)) {
    hook.pending = true;
    hook.callback = callback;
    hook.nextDeps = deps;
  }
}

/**
 * 계산 결과 저장, 의존성이 그대로면 재사용
 *
 * @param {() => any} factory 값을 계산하는 함수
 * @param {any[]} [deps] 의존성 목록. 없으면 매번 다시 계산
 * @returns {any} 저장된(또는 새로 계산한) 값
 */
export function useMemo(factory, deps) {
  checkDeps(deps, "useMemo");
  if (typeof factory !== "function") throw new TypeError("[hooks] useMemo 에는 함수를 넘겨야 합니다.");
  const hook = nextHook("memo", () => ({ deps: undefined, value: undefined, computed: false }));
  if (!hook.computed || depsChanged(hook.deps, deps)) {
    hook.value = factory();
    hook.deps = deps;
    hook.computed = true;
  }
  return hook.value;
}

// ── effect 실행 (component.js 전용) ─────────────────────────────────

/**
 * commit 뒤에 "실행 예정" effect 들을 순서대로 실행한다.
 * 각 effect 는 이전 cleanup → callback 순서. callback 이 함수를 돌려주면 다음 cleanup 으로 기억.
 * effect 하나가 오류를 내도 나머지 effect 는 실행하고, 오류는 콘솔에 알린다.
 *
 * @param {object[]} hooks FunctionComponent.hooks
 * @returns {number} 실행한 effect 개수
 */
export function runEffects(hooks) {
  let count = 0;
  for (const hook of hooks) {
    if (hook.kind !== "effect" || !hook.pending) continue;
    hook.pending = false;
    runCleanup(hook);
    try {
      const result = hook.callback();
      hook.cleanup = typeof result === "function" ? result : null;
    } catch (err) {
      console.error("[hooks] useEffect 실행 중 오류", err);
    }
    hook.deps = hook.nextDeps;
    hook.ran = true;
    hook.callback = null;
    count += 1;
  }
  return count;
}

/** 모든 effect 의 cleanup 실행 (언마운트할 때) */
export function runAllCleanups(hooks) {
  for (const hook of hooks) {
    if (hook.kind === "effect") runCleanup(hook);
  }
}

function runCleanup(hook) {
  if (!hook.cleanup) return;
  const cleanup = hook.cleanup;
  hook.cleanup = null;
  try {
    cleanup();
  } catch (err) {
    console.error("[hooks] useEffect 정리(cleanup) 중 오류", err);
  }
}
