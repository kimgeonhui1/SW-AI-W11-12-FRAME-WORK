// [component.js] 함수형 컴포넌트를 감싸 상태 저장(hooks)과 렌더링(mount/update)을 담당

import { h, createElement } from "./vdom.js";
import { diff } from "./diff.js";
import { patch } from "./patch.js";
import { prepareHooks, finishHooks, enterChild, exitChild, runEffects, runAllCleanups } from "./hooks.js";

/**
 * ── 전체 흐름 ─────────────────────────────────────────────────────────
 *
 *   setState(새 값)                        (hooks.js)
 *     └─ scheduleUpdate()                 바로 렌더하지 않고 마이크로태스크로 "한 번만" 예약 (배칭)
 *          └─ flush() → update()
 *               1. render()               컴포넌트 함수 실행 → hooks 배열에서 상태를 읽어 새 VDOM
 *               2. diff(이전 VDOM, 새 VDOM)   Phase 1 의 Diff 그대로
 *               3. patch(container, patches)  Phase 1 의 Patch 그대로 → 바뀐 노드만 실제 DOM 반영
 *               4. commit                 VDOM · 이벤트 핸들러 표 교체, onCommit 알림
 *               5. runEffects             useEffect 실행 (화면이 반영된 뒤)
 *
 * mount() 는 1 → (컨테이너를 createElement 결과로 채움) → 4 → 5.
 * 1~3 단계에서 오류가 나면 실제 DOM 은 그대로다. (patch 는 입력 오류 시 DOM 을 건드리지 않음 — Phase 1)
 * ─────────────────────────────────────────────────────────────────────
 */

/** 이벤트 핸들러를 연결하는 속성 이름 앞부분: data-on-click="3" */
const EVENT_ATTR_PREFIX = "data-on-";

/**
 * 렌더가 끝없이 이어지는 것을 막는 한도.
 * useEffect 안에서 매번 다른 값으로 setState 하면 렌더 → effect → setState → 렌더 … 가 무한히 반복된다.
 * 사용자 입력 없이(같은 작업 흐름 안에서) 이만큼 연달아 렌더되면 멈추고 오류를 낸다. (React 도 비슷한 한도가 있다)
 */
export const MAX_NESTED_UPDATES = 50;

/**
 * React 식 이벤트 prop 이름 → DOM 이벤트 이름
 * 위임(컨테이너 하나에서 받기)을 하려면 버블링되는 이벤트여야 한다.
 * focus / blur 는 버블링되지 않으므로 버블링되는 focusin / focusout 으로 바꾼다.
 */
const EVENT_NAME_EXCEPTIONS = { focus: "focusin", blur: "focusout", doubleclick: "dblclick" };

/** onClick 처럼 "on + 대문자" 로 시작하는 이름인가 */
function isEventPropName(name) {
  return /^on[A-Z]/.test(name);
}

/** onClick → "click", onKeyDown → "keydown", onFocus → "focusin" */
export function eventNameOf(propName) {
  const name = propName.slice(2).toLowerCase();
  return EVENT_NAME_EXCEPTIONS[name] ?? name;
}

export class FunctionComponent {
  /**
   * @param {(props: object) => any} component 함수형 컴포넌트 (VNode · 문자열 · 배열 · null 을 돌려줌)
   * @param {Element} container 그려 넣을 실제 DOM 요소
   * @param {object} [props] 루트 컴포넌트에 넘길 props
   */
  constructor(component, container, props = {}) {
    if (typeof component !== "function") {
      throw new TypeError("[FunctionComponent] component 는 함수여야 합니다.");
    }
    if (!container || container.nodeType !== 1) {
      throw new TypeError("[FunctionComponent] container 는 DOM 요소여야 합니다.");
    }
    this.component = component;
    this.container = container;
    this.props = props ?? {};

    /** Hook 상태 배열. hooks[i] = i번째로 호출된 Hook 의 상태 (hooks.js 참고) */
    this.hooks = [];
    /** 마지막으로 화면에 반영한 루트 VDOM ({ type: "div", props: {}, children }) */
    this.vdom = null;
    this.mounted = false;
    this.unmounted = false;
    /** 화면에 반영한 횟수 (mount 포함) */
    this.renderCount = 0;

    /** 이벤트 핸들러 표: "3" → 함수 (렌더할 때마다 새 표로 바뀜) */
    this.handlers = new Map();
    /** 컨테이너에 리스너를 단 이벤트 종류 */
    this.listenedEvents = new Set();
    /** update 예약 여부 (배칭) */
    this.updateScheduled = false;
    /** 연달아 일어난 렌더 수 (무한 반복 감지) */
    this.nestedUpdates = 0;
    /** onCommit 구독자 */
    this.commitListeners = new Set();

    this.handleEvent = this.handleEvent.bind(this);
  }

  /**
   * 처음 렌더링: 컴포넌트를 실행해 VDOM 을 만들고, 컨테이너 내용을 그 결과로 바꾼다.
   * @returns {this}
   */
  mount() {
    if (this.unmounted) throw new Error("[FunctionComponent] 언마운트된 컴포넌트는 다시 마운트할 수 없습니다.");
    if (this.mounted) throw new Error("[FunctionComponent] 이미 마운트되었습니다. 다시 그리려면 update() 를 쓰세요.");
    const started = performance.now();

    const { vdom, handlers } = this.render();
    let nodes;
    try {
      nodes = vdom.children.map(createElement); // DOM 을 바꾸기 전에 모두 만든다 (실패하면 컨테이너 그대로)
    } catch (err) {
      this.abandonRender();
      throw err;
    }
    this.container.replaceChildren(...nodes);
    this.mounted = true;

    this.commit(vdom, handlers, { reason: "mount", patches: null, touched: nodes, started });
    return this;
  }

  /**
   * 상태 변경 후 다시 렌더링: 새 VDOM → Diff → Patch (바뀐 부분만 실제 DOM 에 반영)
   * 보통 직접 부르지 않고 setState → scheduleUpdate → flush 를 거쳐 불린다.
   * @returns {object[]} 이번에 적용한 패치 목록
   */
  update() {
    if (this.unmounted) return [];
    if (!this.mounted) throw new Error("[FunctionComponent] mount() 를 먼저 해야 합니다.");
    this.updateScheduled = false;
    const started = performance.now();

    const { vdom, handlers } = this.render();
    let patches;
    let touched;
    try {
      patches = diff(this.vdom, vdom); //            잘못된 VNode 면 TypeError
      touched = patch(this.container, patches); //   입력 오류면 TypeError, DOM 그대로
    } catch (err) {
      this.abandonRender();
      throw err;
    }

    this.commit(vdom, handlers, { reason: "update", patches, touched, started });
    return patches;
  }

  /**
   * 언마운트: effect 정리 함수 실행, 이벤트 리스너 제거, 컨테이너 비우기.
   * 이후의 setState 는 무시된다.
   */
  unmount() {
    if (!this.mounted || this.unmounted) return;
    this.unmounted = true;
    this.mounted = false;
    this.updateScheduled = false;
    runAllCleanups(this.hooks);
    for (const type of this.listenedEvents) this.container.removeEventListener(type, this.handleEvent);
    this.listenedEvents.clear();
    this.handlers = new Map();
    this.container.replaceChildren();
    this.vdom = null;
  }

  /**
   * 다시 렌더링 예약 (setState 가 부름)
   *
   * Batching: 바로 렌더하지 않고 마이크로태스크로 한 번만 예약한다.
   * 이벤트 핸들러 안에서 setState 를 여러 번 불러도 예약은 한 번 → 핸들러가 끝난 직후 렌더 1번.
   * (마이크로태스크는 지금 실행 중인 코드가 끝나자마자, 브라우저가 화면을 그리기 전에 실행된다)
   */
  scheduleUpdate() {
    if (this.unmounted || !this.mounted || this.updateScheduled) return;
    this.updateScheduled = true;
    queueMicrotask(() => this.flush());
  }

  /** 예약된 update 를 지금 실행한다. 예약이 없으면 아무것도 하지 않는다. */
  flush() {
    if (!this.updateScheduled || this.unmounted) return;
    this.updateScheduled = false;

    // 무한 렌더 감지: 사용자 입력 같은 "새 작업" 없이 연달아 렌더되는 횟수를 센다.
    // 첫 렌더 때 setTimeout 으로 "다음 작업에서 0 으로" 를 걸어 둔다. 마이크로태스크끼리는 그 사이에 끼지 않는다.
    if (this.nestedUpdates === 0) setTimeout(() => (this.nestedUpdates = 0), 0);
    this.nestedUpdates += 1;
    if (this.nestedUpdates > MAX_NESTED_UPDATES) {
      throw new Error(
        `[FunctionComponent] 렌더링이 ${MAX_NESTED_UPDATES}번 넘게 연달아 일어나 멈췄습니다. ` +
          "useEffect 안에서 의존성 없이 setState 를 계속 부르고 있지 않은지 확인하세요.",
      );
    }
    this.update();
  }

  /**
   * 화면에 반영할 때마다 불릴 함수를 등록한다. (렌더 관찰 패널 · 강조 효과용)
   * @param {(info: {component, renderCount, reason, patches, touched, ms}) => void} listener
   * @returns {() => void} 구독 해제 함수
   */
  onCommit(listener) {
    this.commitListeners.add(listener);
    return () => this.commitListeners.delete(listener);
  }

  // ── 내부 ──────────────────────────────────────────────────────────

  /**
   * 컴포넌트 함수를 실행해 루트 VDOM 과 이벤트 핸들러 표를 만든다. (DOM 은 건드리지 않음)
   * @returns {{vdom: object, handlers: Map<string, Function>}}
   */
  render() {
    prepareHooks(this);
    try {
      let output;
      try {
        output = this.component(this.props);
      } catch (err) {
        finishHooks(false); // 중간에 멈췄으므로 Hook 개수 검사는 하지 않음
        throw err;
      }
      finishHooks(true); // Hook 개수가 이전 렌더와 다르면 여기서 오류

      // 컴포넌트가 돌려준 것(요소 · 문자열 · 배열 · null)을 컨테이너 모양의 루트로 감싼다.
      // h() 가 배열 평탄화, null · 불리언 제거, 숫자 → 문자열을 해 준다. (containerToVdom 결과와 같은 모양)
      return extractHandlers(h("div", null, output));
    } catch (err) {
      this.abandonRender();
      throw err;
    }
  }

  /** 렌더가 실패했을 때: 실행 예정으로 표시된 effect 를 취소, 첫 렌더였다면 hooks 를 비움 */
  abandonRender() {
    for (const hook of this.hooks) if (hook.kind === "effect") hook.pending = false;
    if (!this.mounted) this.hooks = [];
  }

  /** 렌더 결과를 확정: VDOM · 핸들러 교체 → 구독자 알림 → effect 실행 */
  commit(vdom, handlers, { reason, patches, touched, started }) {
    this.vdom = vdom;
    this.handlers = handlers;
    this.listenFor(handlers);
    this.renderCount += 1;

    const info = {
      component: this,
      renderCount: this.renderCount,
      reason,
      patches,
      touched,
      ms: performance.now() - started,
    };
    for (const listener of this.commitListeners) {
      try {
        listener(info);
      } catch (err) {
        console.error("[FunctionComponent] onCommit 구독자 오류", err);
      }
    }
    runEffects(this.hooks);
  }

  /** 핸들러 표에 나온 이벤트 종류마다 컨테이너에 리스너를 하나씩 단다 (이미 단 종류는 건너뜀) */
  listenFor(handlers) {
    for (const { type } of handlers.values()) {
      if (this.listenedEvents.has(type)) continue;
      this.container.addEventListener(type, this.handleEvent);
      this.listenedEvents.add(type);
    }
  }

  /**
   * 이벤트 위임: 컨테이너에서 받은 이벤트를, 실제로 일어난 요소부터 위로 올라가며
   * data-on-<종류> 가 붙은 요소의 핸들러를 차례로 부른다 (버블링 흉내).
   * 핸들러는 항상 "가장 최근 렌더" 의 표에서 찾으므로 최신 props · 상태를 본다.
   * 핸들러 안에서 event.stopPropagation() 을 부르면 더 위의 핸들러는 부르지 않는다.
   */
  handleEvent(event) {
    const attr = EVENT_ATTR_PREFIX + event.type;
    let node = event.target;
    while (node && node !== this.container) {
      if (node.nodeType === 1 && node.hasAttribute(attr)) {
        const entry = this.handlers.get(node.getAttribute(attr));
        if (entry && entry.type === event.type) entry.fn(event);
        if (event.cancelBubble) break; // stopPropagation() 이 불렸음
      }
      node = node.parentNode;
    }
  }
}

/**
 * 자식(상태 없는) 컴포넌트를 정의한다.
 *
 *   const TodoItem = stateless(({ todo, onToggle }) => h("li", …));
 *   App 안에서:  TodoItem({ todo, onToggle })
 *
 * 돌려주는 함수는 원래 함수를 그대로 실행하는데, 실행하는 동안 "자식 렌더 중" 표시를 켠다.
 * 그 안에서 useState 등 Hook 을 부르면 오류가 난다 → "State 는 루트에서만" 규칙을 코드로 강제.
 * 자식은 props 만 받아 VNode 를 돌려주는 순수 함수이고, 상태를 바꾸려면 부모가 준 콜백을 부른다.
 *
 * @param {(props: object) => any} render
 * @returns {(props?: object) => any}
 */
export function stateless(render) {
  if (typeof render !== "function") throw new TypeError("[stateless] 함수를 넘겨야 합니다.");
  const child = (props = {}) => {
    enterChild();
    try {
      return render(props);
    } finally {
      exitChild();
    }
  };
  Object.defineProperty(child, "name", { value: render.name || "Stateless" });
  return child;
}

/**
 * 렌더 결과 트리에서 이벤트 함수(onClick 등)를 떼어 내고 data-on-* 문자열 속성으로 바꾼다.
 *
 * - diff · patch 로 넘어가는 VDOM 에는 함수가 없다 → Phase 1 의 VDOM 형식 · 검사(validateVNode) 그대로.
 * - 원래 트리는 바꾸지 않고 새 트리를 만든다. (useMemo 로 재사용하는 VNode 를 망가뜨리지 않도록)
 * - 번호는 트리 순서대로 0, 1, 2 … → 구조가 같으면 렌더마다 같은 번호 → 핸들러가 새 함수여도 패치 없음.
 * - onClick: null / undefined / false 는 "핸들러 없음" 으로 보고 지운다. 그 밖의 함수 아닌 값은 TypeError.
 * - 깊은 트리에서도 호출 스택이 넘치지 않도록 명시적 스택, 순환 참조는 TypeError.
 *
 * @param {object} root h("div", null, …) 로 감싼 루트
 * @returns {{vdom: object, handlers: Map<string, {type: string, fn: Function}>}}
 */
export function extractHandlers(root) {
  const handlers = new Map();
  const ancestors = new Set();
  const holder = [];
  // 스택 항목: { node, out: 결과를 넣을 배열 } 또는 { leave: node }
  const stack = [{ node: root, out: holder }];

  while (stack.length > 0) {
    const item = stack.pop();
    if (item.leave) {
      ancestors.delete(item.leave);
      continue;
    }
    const { node, out } = item;
    // 문자열 · 잘못된 값은 그대로 둔다 (잘못된 값은 diff 의 validateVNode 가 위치와 함께 알려 준다)
    if (node === null || typeof node !== "object" || Array.isArray(node)) {
      out.push(node);
      continue;
    }
    if (ancestors.has(node)) {
      throw new TypeError(`[FunctionComponent] 순환 참조된 VNode 입니다: <${node.type}>`);
    }

    const props = {};
    for (const [name, value] of Object.entries(node.props ?? {})) {
      if (isEventPropName(name)) {
        if (value == null || value === false) continue; // 핸들러 없음
        if (typeof value !== "function") {
          throw new TypeError(`[FunctionComponent] <${node.type}> 의 ${name} 는 함수여야 합니다: ${String(value)}`);
        }
        const type = eventNameOf(name);
        const id = String(handlers.size);
        handlers.set(id, { type, fn: value });
        setOwn(props, EVENT_ATTR_PREFIX + type, id);
      } else {
        setOwn(props, name, value);
      }
    }

    const copy = { type: node.type, props, children: node.children };
    out.push(copy);
    if (Array.isArray(node.children)) {
      copy.children = [];
      ancestors.add(node);
      stack.push({ leave: node });
      for (let i = node.children.length - 1; i >= 0; i--) {
        stack.push({ node: node.children[i], out: copy.children });
      }
    }
  }
  return { vdom: holder[0], handlers };
}

/** obj[name] = value 와 같지만 "__proto__" 같은 이름도 평범한 속성으로 만든다 */
function setOwn(obj, name, value) {
  Object.defineProperty(obj, name, { value, enumerable: true, writable: true, configurable: true });
}
