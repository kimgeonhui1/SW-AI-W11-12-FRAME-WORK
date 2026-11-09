// [hooks.js] 상태와 생명주기를 다루는 Hooks (useState / useEffect / useMemo)
//
// 모든 Hook은 같은 방식으로 동작한다:
//   1) 지금 렌더링 중인 컴포넌트를 찾는다 (getCurrentComponent)
//   2) "호출 순서" 번호(hookIndex)로 그 컴포넌트의 hooks 배열에서 자기 칸을 꺼낸다
//   3) 처음이면 칸을 만들고, 아니면 지난 렌더링에 저장한 값을 다시 쓴다

import { getCurrentComponent, runWithoutHooks } from "./component.js";

// 이번 Hook의 컴포넌트와 칸 번호. 부를 때마다 번호가 1씩 늘어나서 Hook마다 다른 칸을 쓴다
function nextHook() {
  const component = getCurrentComponent();
  return [component, component.hookIndex++];
}

// 의존성 배열이 바뀌었는지. deps가 없으면(undefined) 매번 "바뀜"
function depsChanged(prevDeps, deps) {
  if (deps === undefined || prevDeps === undefined) return true;
  if (prevDeps.length !== deps.length) return true;
  // Object.is: ===와 거의 같지만 NaN과 NaN을 같다고 본다
  return deps.some((dep, i) => !Object.is(dep, prevDeps[i]));
}

// 상태 저장 + 변경 시 재렌더링
export function useState(initial) {
  const [component, i] = nextHook();
  // 첫 렌더링에만 초기값을 넣는다. 함수면 실행 결과를 쓴다 (무거운 초기 계산을 매번 하지 않게)
  if (!(i in component.hooks)) {
    const hook = { state: typeof initial === "function" ? runWithoutHooks(initial) : initial };
    // setState가 하는 일: ① 값 저장 ② 다시 렌더링 예약. 화면을 직접 고치지 않는다 (diff/patch가 한다)
    // 첫 렌더링에 한 번만 만들어 칸에 저장한다 → 렌더링마다 "같은 함수"라서 useEffect deps에 넣어도 매번 바뀌지 않는다 (React와 같음)
    hook.setState = (next) => {
      // 함수를 넘기면 "최신 상태"로 계산한다 → 한 번에 여러 번 불러도 누적된다 (setCount(c => c + 1) 두 번 = +2)
      const value = typeof next === "function" ? next(hook.state) : next;
      // 값이 같으면 다시 그릴 필요가 없다
      if (Object.is(value, hook.state)) return;
      hook.state = value;
      component.scheduleUpdate();
    };
    component.hooks[i] = hook;
  }
  const hook = component.hooks[i];
  return [hook.state, hook.setState];
}

// 렌더링 후 부수효과 실행 (의존성이 바뀔 때만)
export function useEffect(callback, deps) {
  const [component, i] = nextHook();
  const hook = component.hooks[i] ?? (component.hooks[i] = { deps: undefined, cleanup: undefined, ran: false });
  // 비교 기준은 "마지막으로 실제 실행된" deps. 실행 기록(ran, deps)은 runEffects가 실행할 때 남긴다
  if (hook.ran && !depsChanged(hook.deps, deps)) return;
  // 지금 바로 실행하지 않고 목록에 넣는다. FunctionComponent가 화면을 고친 "뒤"에
  // 이전 effect의 정리 함수(cleanup: 타이머 해제, 이벤트 해제 등)를 부르고 나서 실행한다
  component.pendingEffects.push({ hook, callback, deps });
}

// 렌더링마다 "같은 { current } 객체"를 돌려준다. current를 바꿔도 다시 그리지 않는다
// 쓰임: h("input", { ref }) 로 실제 DOM 요소 잡기, 타이머 id처럼 화면과 상관없는 값 보관
export function useRef(initial) {
  const [component, i] = nextHook();
  if (!(i in component.hooks)) component.hooks[i] = { current: initial };
  return component.hooks[i];
}

// 계산 결과 저장, 의존성이 그대로면 재사용
export function useMemo(factory, deps) {
  const [component, i] = nextHook();
  const hook = component.hooks[i];
  if (hook && !depsChanged(hook.deps, deps)) return hook.value;
  const value = runWithoutHooks(factory);
  component.hooks[i] = { value, deps };
  return value;
}
