// [hooks.js] 상태와 생명주기를 다루는 Hooks (useState / useEffect / useMemo)

/**
 * 핵심 질문: "함수는 매번 새로 실행되는데, 상태는 어떻게 유지할까?"
 *
 * 함수 안의 지역 변수는 함수가 끝나면 사라지므로, 상태는 함수 "바깥" 인 FunctionComponent 의 hooks 배열에 둔다.
 *   hooks = [ {state: 3}, {memo: …}, {effect: …} ]
 *   App() 이 실행될 때 useState → hooks[0], useMemo → hooks[1], useEffect → hooks[2] 를 읽는다.
 * Hook 은 이름이 아니라 "몇 번째로 불렸는지" 로 자기 칸을 찾는다.
 * 그래서 매 렌더 같은 순서 · 같은 개수로 불러야 한다 (조건문 · 반복문 안에서 부르면 안 되는 이유 — nextHook 이 검사).
 *
 * 렌더 중인 컴포넌트와 다음 Hook 번호는 모듈 변수로 둔다. component.js 가 렌더 직전 prepareHooks, 직후 finishHooks 를 부른다.
 */

let current = null; //      지금 렌더 중인 FunctionComponent (아니면 null)
let hookIndex = 0; //       이번 렌더에서 다음에 읽을 칸
let firstRender = false; // 칸을 새로 만들어도 되는 렌더인가 (마운트 전)
let childDepth = 0; //      stateless 자식을 실행 중인 깊이 (0 보다 크면 Hook 금지)

/** [component.js 전용] 렌더 시작 */
export function prepareHooks(instance) {
  // 렌더 도중 다른 루트를 렌더하면 Hook 이 엉뚱한 컴포넌트에 붙는다
  if (current) throw new Error("[hooks] 다른 컴포넌트를 렌더하는 도중에는 렌더를 시작할 수 없습니다.");
  current = instance;
  hookIndex = 0;
  firstRender = !instance.mounted;
  childDepth = 0;
}

/** [component.js 전용] 렌더 끝. 끝까지 실행됐으면(completed) Hook 개수가 이전 렌더와 같은지 확인 */
export function finishHooks(completed = true) {
  const instance = current;
  const used = hookIndex;
  current = null;
  hookIndex = 0;
  childDepth = 0;
  if (completed && instance?.mounted && used !== instance.hooks.length) {
    throw new Error(
      `[hooks] 이번 렌더에서 Hook 을 ${used}개 불렀지만 이전 렌더에서는 ${instance.hooks.length}개였습니다. ` +
        "Hook 은 조건문 · 반복문 · 일찍 return 하는 코드 뒤가 아니라 컴포넌트 맨 위에서 항상 같은 순서로 불러야 합니다.",
    );
  }
}

/** [component.js 전용] 렌더 중인가 (렌더 중 setState 금지) */
export const isRendering = () => current !== null;
/** [component.js 전용] stateless 자식 실행 구간 표시 — 그 안에서 Hook 을 부르면 오류 */
export const enterChild = () => void (childDepth += 1);
export const exitChild = () => void (childDepth -= 1);

const hookName = (kind) => `use${kind[0].toUpperCase()}${kind.slice(1)}`;

/** 이번 Hook 의 칸을 꺼낸다. 첫 렌더면 create() 로 만들고, 다시 렌더면 같은 자리 · 같은 종류인지 확인 */
function nextHook(kind, create) {
  const name = hookName(kind);
  if (!current) throw new Error(`[hooks] ${name} 는 컴포넌트를 렌더하는 동안에만 부를 수 있습니다.`);
  if (childDepth > 0) {
    throw new Error(
      `[hooks] ${name} 는 최상위(루트) 컴포넌트에서만 쓸 수 있습니다. ` +
        "자식 컴포넌트는 상태 없이 props 만 받아야 합니다 (Lifting State Up).",
    );
  }
  const { hooks } = current;
  const index = hookIndex++;
  if (index >= hooks.length) {
    if (!firstRender) {
      throw new Error(
        `[hooks] 이전 렌더보다 Hook 을 더 많이 불렀습니다 (${index + 1}번째 ${name}). ` +
          "Hook 은 조건문 · 반복문 안에서 부르면 안 됩니다.",
      );
    }
    hooks.push({ kind, ...create() });
  }
  const hook = hooks[index];
  if (hook.kind !== kind) {
    throw new Error(
      `[hooks] ${index + 1}번째 Hook 이 이전 렌더에서는 ${hookName(hook.kind)} 였는데 ` +
        `이번에는 ${name} 입니다. Hook 호출 순서가 바뀌었습니다.`,
    );
  }
  return hook;
}

function checkArgs(fn, deps, name) {
  if (deps !== undefined && !Array.isArray(deps)) {
    throw new TypeError(`[hooks] ${name} 의 의존성 목록은 배열이어야 합니다: ${String(deps)}`);
  }
  if (typeof fn !== "function") throw new TypeError(`[hooks] ${name} 에는 함수를 넘겨야 합니다.`);
}

/** 의존성이 바뀌었는가: deps 없음이면 항상, 길이가 다르거나 Object.is 로 다른 값이 있으면 (NaN 끼리는 같음, React 와 같음) */
function depsChanged(prev, next) {
  if (prev === undefined || next === undefined || prev.length !== next.length) return true;
  return next.some((value, i) => !Object.is(value, prev[i]));
}

/**
 * 상태 저장 + 바뀌면 다시 렌더. initial 이 함수면 첫 렌더에서 한 번만 실행 (지연 초기화).
 * setState(next): next 가 함수면 next(이전 값). Object.is 로 같으면 아무것도 안 함(렌더 생략),
 * 다르면 값을 바꾸고 렌더를 "예약" 만 한다 (바로 렌더하지 않음 → 배칭). setState 는 렌더가 바뀌어도 같은 함수다.
 */
export function useState(initial) {
  const instance = current;
  const hook = nextHook("state", () => ({ value: typeof initial === "function" ? initial() : initial }));
  hook.setState ??= (next) => {
    if (instance.unmounted) return;
    if (isRendering()) throw new Error("[hooks] 렌더링 도중에는 setState 를 부를 수 없습니다. 이벤트 핸들러나 useEffect 안에서 부르세요.");
    const value = typeof next === "function" ? next(hook.value) : next;
    if (Object.is(value, hook.value)) return;
    hook.value = value;
    instance.scheduleUpdate();
  };
  return [hook.value, hook.setState];
}

/**
 * 렌더 후 부수효과. deps 없음 → 매 렌더, [] → 처음 한 번, [a, b] → a · b 가 바뀔 때.
 * 렌더 중에는 "실행 예정" 표시만 하고, 실제 실행은 DOM 반영(commit) 뒤 runEffects 가 한다 → effect 안에서는 새 화면이 보인다.
 * callback 이 함수를 돌려주면 다음 실행 전 · 언마운트 때 부를 정리(cleanup) 함수로 기억한다.
 */
export function useEffect(callback, deps) {
  checkArgs(callback, deps, "useEffect");
  const hook = nextHook("effect", () => ({ cleanup: null, pending: false, ran: false }));
  if (!hook.ran || depsChanged(hook.deps, deps)) Object.assign(hook, { pending: true, callback, nextDeps: deps });
}

/** 계산 결과를 저장해 두고, 의존성이 그대로면 재사용 (deps 없음 → 매번 계산) */
export function useMemo(factory, deps) {
  checkArgs(factory, deps, "useMemo");
  const hook = nextHook("memo", () => ({ computed: false }));
  if (!hook.computed || depsChanged(hook.deps, deps)) Object.assign(hook, { value: factory(), deps, computed: true });
  return hook.value;
}

/**
 * [component.js 전용] commit 뒤 실행 예정 effect 를 순서대로: 이전 cleanup → callback.
 * effect 하나가 오류를 내도 나머지는 실행하고 오류는 콘솔에 알린다.
 */
export function runEffects(hooks) {
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
    Object.assign(hook, { deps: hook.nextDeps, ran: true, callback: null });
  }
}

/** [component.js 전용] 언마운트할 때 모든 cleanup 실행 */
export function runAllCleanups(hooks) {
  for (const hook of hooks) if (hook.kind === "effect") runCleanup(hook);
}

function runCleanup(hook) {
  const { cleanup } = hook;
  if (!cleanup) return;
  hook.cleanup = null;
  try {
    cleanup();
  } catch (err) {
    console.error("[hooks] useEffect 정리(cleanup) 중 오류", err);
  }
}
