// [hooks.js] 상태와 생명주기를 다루는 Hooks (useState / useEffect / useMemo)
let activeComponent = null;

// Internal bridge used by FunctionComponent, not application hooks.
export function renderWithHooks(component, render) {
  const previous = activeComponent;
  activeComponent = component;
  component.hookCursor = 0;
  component.pendingEffects = [];
  try {
    const vnode = render();
    if (component.hookCursor !== component.hooks.length) throw new Error("Hook count changed");
    return vnode;
  } finally {
    activeComponent = previous;
  }
}

export function flushEffects(component) {
  const effects = component.pendingEffects;
  component.pendingEffects = [];
  for (const run of effects) run();
}

function slot(kind) {
  if (!activeComponent) throw new Error("Hooks require a component render");
  const owner = activeComponent;
  const index = owner.hookCursor++;
  let hook = owner.hooks[index];
  if (!hook) {
    if (owner.mounted) throw new Error("Hook count changed");
    hook = { kind };
    owner.hooks[index] = hook;
  } else if (hook.kind !== kind) {
    throw new Error("Hook order changed");
  }
  return [owner, hook];
}

function copyDeps(deps) {
  if (deps !== undefined && !Array.isArray(deps)) throw new Error("Dependencies must be an array or omitted");
  return deps?.slice();
}

function sameDeps(before, after) {
  return before !== undefined && after !== undefined && before.length === after.length &&
    before.every((value, index) => Object.is(value, after[index]));
}

// 상태 저장 + 변경 시 재렌더링
export function useState(initial) {
  const [owner, hook] = slot("state");
  if (!hook.initialized) {
    hook.value = typeof initial === "function" ? initial() : initial;
    hook.setter = next => {
      if (activeComponent) throw new Error("State cannot be set during render");
      const value = typeof next === "function" ? next(hook.value) : next;
      if (Object.is(value, hook.value)) return;
      hook.value = value;
      owner.update();
    };
    hook.initialized = true;
  }
  return [hook.value, hook.setter];
}
// 렌더링 후 부수효과 실행 (의존성이 바뀔 때만)
export function useEffect(callback, deps) {
  const [owner, hook] = slot("effect");
  const nextDeps = copyDeps(deps);
  if (!hook.initialized || !sameDeps(hook.deps, nextDeps)) {
    owner.pendingEffects.push(() => {
      const cleanup = hook.cleanup;
      hook.cleanup = undefined;
      if (cleanup) cleanup();
      const nextCleanup = callback();
      if (nextCleanup !== undefined && typeof nextCleanup !== "function") {
        throw new Error("Effect must return a cleanup function or undefined");
      }
      hook.cleanup = nextCleanup;
      hook.deps = nextDeps;
      hook.initialized = true;
    });
  }
}
// 계산 결과 저장, 의존성이 그대로면 재사용
export function useMemo(factory, deps) {
  const [, hook] = slot("memo");
  const nextDeps = copyDeps(deps);
  if (!hook.initialized || !sameDeps(hook.deps, nextDeps)) {
    hook.value = factory();
    hook.deps = nextDeps;
    hook.initialized = true;
  }
  return hook.value;
}
