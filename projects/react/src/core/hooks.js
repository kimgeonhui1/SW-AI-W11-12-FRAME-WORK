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
 * (조건문 · 반복문 안에서 Hook 을 부르면 안 되는 이유. 아래 nextHook · finishHooks 가 이를 검사한다)
 *
 * 이 파일은 "지금 렌더 중인 컴포넌트" 와 "다음 Hook 인덱스" 를 모듈 변수로 들고 있다.
 * FunctionComponent(component.js) 가 렌더 직전에 prepareHooks, 직후에 finishHooks 를 부른다.
 * ─────────────────────────────────────────────────────────────────────
 */

// ── 렌더 중인 컴포넌트 정보 (모듈 내부 상태) ─────────────────────────

let current = null; //      지금 렌더 중인 FunctionComponent (렌더 중이 아니면 null)
let hookIndex = 0; //       이번 렌더에서 다음에 읽을 hooks 칸 번호
let firstRender = false; // 이번이 첫 렌더인가 (= hooks 칸을 새로 만들어도 되는가)
let childDepth = 0; //      stateless 자식 컴포넌트를 실행 중인 깊이 (0 보다 크면 Hook 호출 금지)

/**
 * [component.js 전용] 렌더 시작: 이 컴포넌트의 hooks 를 처음부터(0번 칸부터) 읽을 준비를 한다.
 *
 * @param {object} instance 렌더할 FunctionComponent
 * @throws {Error} 다른 컴포넌트를 렌더하는 도중이면 (Hook 이 엉뚱한 컴포넌트에 붙기 때문)
 */
export function prepareHooks(instance) {
  if (current) throw new Error("[hooks] 다른 컴포넌트를 렌더하는 도중에는 렌더를 시작할 수 없습니다.");
  current = instance;
  hookIndex = 0;
  firstRender = !instance.mounted; // 마운트 전이면 칸을 새로 만드는 렌더
  childDepth = 0;
}

/**
 * [component.js 전용] 렌더 끝: 모듈 상태를 비우고, Hook 개수가 이전 렌더와 같은지 확인한다.
 *
 * 예) 이전 렌더에서 Hook 3개를 불렀는데 이번엔 2개만 불렀다면(조건문 안 Hook, 일찍 return 등)
 *     다음 렌더부터 칸이 어긋나므로 오류로 알린다.
 *
 * @param {boolean} [completed] 컴포넌트 함수가 끝까지 실행되었는가.
 *                              예외로 중간에 멈췄으면 false → 개수가 모자란 게 당연하므로 검사하지 않는다.
 * @throws {Error} Hook 개수가 달라졌을 때
 */
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

/** [component.js 전용] 지금 렌더 중인가 (렌더 도중 setState 를 막는 데 쓴다) */
export const isRendering = () => current !== null;

/**
 * [component.js 전용] stateless 자식 컴포넌트를 실행하는 구간을 표시한다.
 * 이 구간 안에서 Hook 을 부르면 nextHook 이 오류를 던진다 → "State 는 루트에서만" 규칙을 코드로 강제.
 * (자식 안에서 또 자식을 부를 수 있으므로 true/false 가 아니라 깊이를 센다)
 */
export const enterChild = () => void (childDepth += 1);
export const exitChild = () => void (childDepth -= 1);

/** "state" → "useState" (오류 메시지용 이름) */
const hookName = (kind) => `use${kind[0].toUpperCase()}${kind.slice(1)}`;

/**
 * 이번 Hook 의 칸을 꺼낸다. (모든 Hook 이 공통으로 거치는 함수)
 *
 *   - 렌더 중이 아니면 오류 (이벤트 핸들러 같은 곳에서 Hook 을 부른 경우)
 *   - 자식(stateless) 컴포넌트 안이면 오류 (Lifting State Up 규칙)
 *   - 첫 렌더: create() 로 새 칸을 만들어 hooks 배열 끝에 넣는다
 *   - 다시 렌더: 같은 자리의 칸을 꺼내고, 이전과 같은 종류의 Hook 인지 확인한다
 *
 * @param {string} kind "state" | "effect" | "memo"
 * @param {() => object} create 첫 렌더에서 칸의 초기 내용을 만드는 함수
 * @returns {object} 이 Hook 의 칸 (렌더가 바뀌어도 같은 객체 — 여기에 값을 저장한다)
 */
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
  const index = hookIndex++; // 이번 Hook 의 칸 번호, 다음 Hook 을 위해 하나 증가

  if (index >= hooks.length) {
    // 칸이 아직 없다 → 첫 렌더라면 새로 만들고, 아니라면 이전보다 Hook 을 더 많이 부른 것
    if (!firstRender) {
      throw new Error(
        `[hooks] 이전 렌더보다 Hook 을 더 많이 불렀습니다 (${index + 1}번째 ${name}). ` +
          "Hook 은 조건문 · 반복문 안에서 부르면 안 됩니다.",
      );
    }
    hooks.push({ kind, ...create() });
  }

  const hook = hooks[index];
  // 같은 자리인데 종류가 다르면 Hook 호출 순서가 바뀐 것 (예: 조건에 따라 useState 를 건너뜀)
  if (hook.kind !== kind) {
    throw new Error(
      `[hooks] ${index + 1}번째 Hook 이 이전 렌더에서는 ${hookName(hook.kind)} 였는데 ` +
        `이번에는 ${name} 입니다. Hook 호출 순서가 바뀌었습니다.`,
    );
  }
  return hook;
}

/**
 * useEffect · useMemo 공통 인자 검사
 *   deps : 없음(undefined) 또는 배열만 허용
 *   fn   : 함수만 허용
 */
function checkArgs(fn, deps, name) {
  if (deps !== undefined && !Array.isArray(deps)) {
    throw new TypeError(`[hooks] ${name} 의 의존성 목록은 배열이어야 합니다: ${String(deps)}`);
  }
  if (typeof fn !== "function") throw new TypeError(`[hooks] ${name} 에는 함수를 넘겨야 합니다.`);
}

/**
 * 의존성(deps)이 바뀌었는가
 *   - deps 없음(undefined) → 항상 바뀐 것으로 본다 → 렌더할 때마다 실행 · 계산
 *   - 길이가 다르거나, 같은 자리 값이 Object.is 로 다르면 바뀐 것
 *     (Object.is: NaN 은 NaN 과 같고, +0 과 -0 은 다르다. React 와 같은 비교)
 */
function depsChanged(prev, next) {
  if (prev === undefined || next === undefined || prev.length !== next.length) return true;
  return next.some((value, i) => !Object.is(value, prev[i]));
}

// ── 공개 Hooks ──────────────────────────────────────────────────────

/**
 * 상태 저장 + 바뀌면 다시 렌더
 *
 * @param {*} initial 처음 값. 함수면 첫 렌더에서 한 번만 실행해 그 결과를 쓴다 (지연 초기화 —
 *                    localStorage 읽기처럼 비싼 계산을 매 렌더 하지 않도록)
 * @returns {[any, (next: any) => void]} [현재 값, 값을 바꾸는 함수 setState]
 *
 * setState(next) 가 하는 일 — "상태 변경 외에 무엇을 해야 할까?" 의 답
 *   1. next 가 함수면 next(이전 값) 의 결과로, 아니면 next 로 새 값을 정한다 (함수형 업데이트)
 *   2. 새 값이 이전 값과 Object.is 로 같으면 아무것도 하지 않는다 (불필요한 렌더 생략)
 *   3. 다르면 값을 바꾸고, 다시 렌더링을 "예약" 한다 — 바로 렌더하지 않는다 (Batching)
 *   ※ 렌더 도중에 부르면 오류, 언마운트된 컴포넌트면 무시한다.
 * setState 함수는 첫 렌더에서 한 번만 만들어서, 렌더가 바뀌어도 같은 함수다 (useEffect deps 에 넣어도 안전).
 */
export function useState(initial) {
  const instance = current; // setState 는 나중에(이벤트에서) 불리므로 지금 컴포넌트를 클로저로 기억해 둔다
  const hook = nextHook("state", () => ({ value: typeof initial === "function" ? initial() : initial }));
  hook.setState ??= (next) => {
    if (instance.unmounted) return;
    if (isRendering()) throw new Error("[hooks] 렌더링 도중에는 setState 를 부를 수 없습니다. 이벤트 핸들러나 useEffect 안에서 부르세요.");
    const value = typeof next === "function" ? next(hook.value) : next;
    if (Object.is(value, hook.value)) return; // 같은 값 → 렌더 생략 (bail out)
    hook.value = value;
    instance.scheduleUpdate(); // 렌더 예약 (component.js — 마이크로태스크로 한 번만)
  };
  return [hook.value, hook.setState];
}

/**
 * 렌더링 후 부수효과 실행 (의존성이 바뀔 때만)
 *
 * @param {() => (void | (() => void))} callback 화면 반영 뒤 실행할 함수.
 *        함수를 돌려주면 정리(cleanup) 함수로 기억해 두었다가, 다음 실행 직전과 언마운트 때 부른다.
 * @param {any[]} [deps] 의존성 목록. 없으면 매 렌더, [] 면 처음 한 번, [a, b] 면 a · b 가 바뀔 때
 *
 * 렌더 중에는 실행하지 않고 "실행 예정(pending)" 표시만 한다.
 * 실제 실행은 FunctionComponent 가 DOM 에 반영(commit)한 뒤 runEffects 로 한다.
 * → effect 안에서 DOM 을 읽으면 이미 새 화면이 반영되어 있다.
 */
export function useEffect(callback, deps) {
  checkArgs(callback, deps, "useEffect");
  const hook = nextHook("effect", () => ({ cleanup: null, pending: false, ran: false }));
  // 아직 한 번도 안 돌았거나 deps 가 바뀌었으면 실행 예정으로 표시 (deps 는 실행할 때 확정 — nextDeps)
  if (!hook.ran || depsChanged(hook.deps, deps)) Object.assign(hook, { pending: true, callback, nextDeps: deps });
}

/**
 * 계산 결과를 저장해 두고, 의존성이 그대로면 다시 계산하지 않고 재사용한다.
 * 예) App 의 통계(stats)는 todos 가 바뀔 때만 다시 세고, 입력창에 글자를 칠 때는 이전 결과를 쓴다.
 *
 * @param {() => any} factory 값을 계산하는 함수
 * @param {any[]} [deps] 의존성 목록. 없으면 매번 다시 계산
 * @returns {any} 저장된(또는 새로 계산한) 값
 */
export function useMemo(factory, deps) {
  checkArgs(factory, deps, "useMemo");
  const hook = nextHook("memo", () => ({ computed: false }));
  if (!hook.computed || depsChanged(hook.deps, deps)) Object.assign(hook, { value: factory(), deps, computed: true });
  return hook.value;
}

// ── effect 실행 (component.js 전용) ─────────────────────────────────

/**
 * commit 뒤에 "실행 예정" effect 들을 hooks 순서대로 실행한다.
 * 각 effect 는 "이전 cleanup → callback" 순서. callback 이 함수를 돌려주면 다음 cleanup 으로 기억한다.
 * effect 하나가 오류를 내도 나머지 effect 는 실행하고, 오류는 콘솔에 알린다.
 *
 * @param {object[]} hooks FunctionComponent.hooks
 */
export function runEffects(hooks) {
  for (const hook of hooks) {
    if (hook.kind !== "effect" || !hook.pending) continue;
    hook.pending = false;
    runCleanup(hook); // 이전 effect 의 정리 함수 먼저
    try {
      const result = hook.callback();
      hook.cleanup = typeof result === "function" ? result : null;
    } catch (err) {
      console.error("[hooks] useEffect 실행 중 오류", err);
    }
    // 이번에 실행한 deps 를 "이전 deps" 로 확정하고, 다 쓴 callback 은 놓아 준다
    Object.assign(hook, { deps: hook.nextDeps, ran: true, callback: null });
  }
}

/** [component.js 전용] 언마운트할 때 모든 effect 의 cleanup 실행 (구독 해제 · 리스너 제거 등) */
export function runAllCleanups(hooks) {
  for (const hook of hooks) if (hook.kind === "effect") runCleanup(hook);
}

/** cleanup 이 있으면 한 번만 실행하고 비운다 (오류는 콘솔에만 알리고 계속 진행) */
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
