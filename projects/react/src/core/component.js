// [component.js] 함수형 컴포넌트를 감싸 상태 저장(hooks)과 렌더링(mount/update)을 담당

import { h, createElement, validateVNode } from "./vdom.js";
import { diff } from "./diff.js";
import { patch } from "./patch.js";
import { prepareHooks, finishHooks, enterChild, exitChild, runEffects, runAllCleanups } from "./hooks.js";

/**
 * 전체 흐름
 *   setState → scheduleUpdate()  바로 렌더하지 않고 마이크로태스크로 한 번만 예약 (배칭)
 *     → flush() → update()
 *        1. render()   컴포넌트 함수 실행 → hooks 에서 상태를 읽어 새 VDOM
 *        2. diff       Phase 1 의 Diff 그대로 (이전 VDOM 은 이미 검사했으므로 trustOld)
 *        3. patch      Phase 1 의 Patch 그대로 → 바뀐 노드만 실제 DOM 반영
 *        4. commit     VDOM · 이벤트 핸들러 표 교체, onCommit 알림
 *        5. runEffects useEffect 실행 (화면 반영 뒤)
 * mount() 는 1 → createElement 로 컨테이너 채움 → 4 → 5. 1~3 에서 오류가 나면 실제 DOM 은 그대로다.
 */

const EVENT_ATTR_PREFIX = "data-on-"; // 이벤트 핸들러 연결 속성: data-on-click="3"

/**
 * 무한 렌더 한도. effect 안에서 매번 다른 값으로 setState 하면 렌더 → effect → setState … 가 끝없이 반복된다.
 * 사용자 입력 없이 이만큼 연달아 렌더되면 멈추고 오류를 낸다 (React 도 비슷한 한도가 있다).
 */
export const MAX_NESTED_UPDATES = 50;

// 위임하려면 버블링되는 이벤트여야 한다 → focus · blur 는 버블링되는 focusin · focusout 으로
const EVENT_NAME_EXCEPTIONS = { focus: "focusin", blur: "focusout", doubleclick: "dblclick" };

/** onClick → "click", onFocus → "focusin" */
export function eventNameOf(propName) {
  const name = propName.slice(2).toLowerCase();
  return EVENT_NAME_EXCEPTIONS[name] ?? name;
}

export class FunctionComponent {
  /**
   * @param {(props: object) => any} component VNode · 문자열 · 배열 · null 을 돌려주는 함수형 컴포넌트
   * @param {Element} container 그려 넣을 실제 DOM 요소
   */
  constructor(component, container, props = {}) {
    if (typeof component !== "function") throw new TypeError("[FunctionComponent] component 는 함수여야 합니다.");
    if (container?.nodeType !== 1) throw new TypeError("[FunctionComponent] container 는 DOM 요소여야 합니다.");
    this.component = component;
    this.container = container;
    this.props = props ?? {};
    this.hooks = []; //                 hooks[i] = i번째로 불린 Hook 의 상태 (hooks.js)
    this.vdom = null; //                마지막으로 반영한 루트 VDOM
    this.mounted = false;
    this.unmounted = false;
    this.renderCount = 0; //            화면에 반영한 횟수 (mount 포함)
    this.handlers = new Map(); //       "3" → { type, fn } (렌더마다 새 표)
    this.listenedEvents = new Set(); // 컨테이너에 리스너를 단 이벤트 종류
    this.updateScheduled = false; //    배칭: update 예약 여부
    this.nestedUpdates = 0; //          연달아 일어난 렌더 수 (무한 반복 감지)
    this.commitListeners = new Set();
    this.handleEvent = this.handleEvent.bind(this);
  }

  /** 처음 렌더링: 새 노드를 모두 만든 뒤 한 번에 컨테이너를 채운다 (실패하면 컨테이너 그대로) */
  mount() {
    if (this.unmounted) throw new Error("[FunctionComponent] 언마운트된 컴포넌트는 다시 마운트할 수 없습니다.");
    if (this.mounted) throw new Error("[FunctionComponent] 이미 마운트되었습니다. 다시 그리려면 update() 를 쓰세요.");
    const started = performance.now();
    const { vdom, handlers } = this.render();
    const nodes = this.guard(() => {
      validateVNode(vdom, "mount"); // update 의 diff 가 이전 VDOM 검사를 건너뛸 수 있도록 첫 VDOM 도 검사
      return vdom.children.map(createElement);
    });
    this.container.replaceChildren(...nodes);
    this.mounted = true;
    this.commit(vdom, handlers, { reason: "mount", patches: null, touched: nodes, started });
    return this;
  }

  /** 다시 렌더링: 새 VDOM → Diff → Patch. 보통 setState → scheduleUpdate → flush 를 거쳐 불린다. @returns 적용한 패치 */
  update() {
    if (this.unmounted) return [];
    if (!this.mounted) throw new Error("[FunctionComponent] mount() 를 먼저 해야 합니다.");
    this.updateScheduled = false;
    const started = performance.now();
    const { vdom, handlers } = this.render();
    const { patches, touched } = this.guard(() => {
      const patches = diff(this.vdom, vdom, { trustOld: true }); // this.vdom 은 지난 렌더에서 검사를 마쳤다
      return { patches, touched: patch(this.container, patches) };
    });
    this.commit(vdom, handlers, { reason: "update", patches, touched, started });
    return patches;
  }

  /** 언마운트: cleanup 실행, 리스너 제거, 컨테이너 비우기. 이후 setState 는 무시된다 */
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
   * 다시 렌더링 예약 (setState 가 부름). Batching: 마이크로태스크로 한 번만 예약하므로
   * 핸들러 안에서 setState 를 여러 번 불러도 핸들러가 끝난 직후(화면을 그리기 전) 렌더 1번.
   */
  scheduleUpdate() {
    if (this.unmounted || !this.mounted || this.updateScheduled) return;
    this.updateScheduled = true;
    queueMicrotask(() => this.flush());
  }

  /** 예약된 update 를 지금 실행 (예약이 없으면 아무것도 안 함) */
  flush() {
    if (!this.updateScheduled || this.unmounted) return;
    this.updateScheduled = false;
    // 무한 렌더 감지: 첫 렌더 때 "다음 작업(setTimeout)에서 0 으로" 를 걸어 둔다. 마이크로태스크끼리는 그 사이에 끼지 않는다.
    if (this.nestedUpdates === 0) setTimeout(() => (this.nestedUpdates = 0), 0);
    if (++this.nestedUpdates > MAX_NESTED_UPDATES) {
      throw new Error(
        `[FunctionComponent] 렌더링이 ${MAX_NESTED_UPDATES}번 넘게 연달아 일어나 멈췄습니다. ` +
          "useEffect 안에서 의존성 없이 setState 를 계속 부르고 있지 않은지 확인하세요.",
      );
    }
    this.update();
  }

  /** 화면에 반영할 때마다 불릴 함수 등록 (강조 효과 · 테스트용). @returns 구독 해제 함수 */
  onCommit(listener) {
    this.commitListeners.add(listener);
    return () => this.commitListeners.delete(listener);
  }

  // ── 내부 ──

  /** 컴포넌트 함수를 실행해 루트 VDOM 과 핸들러 표를 만든다 (DOM 은 건드리지 않음) */
  render() {
    prepareHooks(this);
    return this.guard(() => {
      let output;
      try {
        output = this.component(this.props);
      } catch (err) {
        finishHooks(false); // 중간에 멈췄으므로 Hook 개수 검사는 안 함
        throw err;
      }
      finishHooks(true);
      // 결과(요소 · 문자열 · 배열 · null)를 containerToVdom 과 같은 모양의 루트로 감싼다 (h() 가 정규화)
      return extractHandlers(h("div", null, output));
    });
  }

  /** fn 이 실패하면 이번 렌더를 버리고(예정된 effect 취소, 첫 렌더였다면 hooks 비움) 오류를 다시 던진다 */
  guard(fn) {
    try {
      return fn();
    } catch (err) {
      for (const hook of this.hooks) if (hook.kind === "effect") hook.pending = false;
      if (!this.mounted) this.hooks = [];
      throw err;
    }
  }

  /** 렌더 결과 확정: VDOM · 핸들러 교체 → 구독자 알림 → effect 실행 */
  commit(vdom, handlers, { reason, patches, touched, started }) {
    this.vdom = vdom;
    this.handlers = handlers;
    for (const { type } of handlers.values()) {
      if (this.listenedEvents.has(type)) continue; // 이벤트 종류마다 컨테이너에 리스너 하나
      this.container.addEventListener(type, this.handleEvent);
      this.listenedEvents.add(type);
    }
    this.renderCount += 1;
    const info = { component: this, renderCount: this.renderCount, reason, patches, touched, ms: performance.now() - started };
    for (const listener of this.commitListeners) {
      try {
        listener(info);
      } catch (err) {
        console.error("[FunctionComponent] onCommit 구독자 오류", err);
      }
    }
    runEffects(this.hooks);
  }

  /**
   * 이벤트 위임: 이벤트가 일어난 요소부터 컨테이너까지 올라가며 data-on-<종류> 가 붙은 요소의 핸들러를 부른다 (버블링 흉내).
   * 핸들러는 항상 최근 렌더의 표에서 찾으므로 최신 상태를 본다. stopPropagation() 이 불리면 멈춘다.
   */
  handleEvent(event) {
    const attr = EVENT_ATTR_PREFIX + event.type;
    for (let node = event.target; node && node !== this.container; node = node.parentNode) {
      if (node.nodeType !== 1 || !node.hasAttribute(attr)) continue;
      const entry = this.handlers.get(node.getAttribute(attr));
      if (entry?.type === event.type) entry.fn(event);
      if (event.cancelBubble) break;
    }
  }
}

/**
 * 상태 없는 자식 컴포넌트 정의. 예) const TodoItem = stateless(({ todo, onToggle }) => h("li", …));
 * 실행하는 동안 "자식 렌더 중" 표시를 켜서, 그 안에서 Hook 을 부르면 오류가 나게 한다 (State 는 루트에서만).
 * 자식은 props 만 받아 VNode 를 돌려주는 순수 함수이고, 상태를 바꾸려면 부모가 준 콜백을 부른다 (Lifting State Up).
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
 * 트리에서 onClick 같은 이벤트 함수를 떼어 내고 data-on-* 문자열 속성으로 바꾼 새 트리를 만든다.
 * - diff · patch 에 넘어가는 VDOM 에는 함수가 없다 → Phase 1 형식 그대로. 원래 트리는 바꾸지 않는다 (useMemo 재사용 보호).
 * - 번호는 트리 순서대로 0, 1, 2 … → 구조가 같으면 같은 번호 → 핸들러가 매번 새 함수여도 패치 없음.
 * - null · undefined · false 핸들러는 지우고, 그 밖의 함수 아닌 값은 TypeError.
 */
export function extractHandlers(root) {
  const handlers = new Map();
  const convert = (node) => {
    if (node === null || typeof node !== "object" || Array.isArray(node)) return node; // 잘못된 값은 diff 가 알려 준다
    const entries = [];
    for (const [name, value] of Object.entries(node.props ?? {})) {
      if (!/^on[A-Z]/.test(name)) {
        entries.push([name, value]);
        continue;
      }
      if (value == null || value === false) continue;
      if (typeof value !== "function") throw new TypeError(`[FunctionComponent] <${node.type}> 의 ${name} 는 함수여야 합니다: ${String(value)}`);
      const id = String(handlers.size);
      handlers.set(id, { type: eventNameOf(name), fn: value });
      entries.push([EVENT_ATTR_PREFIX + eventNameOf(name), id]);
    }
    // Object.fromEntries: "__proto__" 도 평범한 속성으로. 자식은 props 다음에 변환 → 번호가 트리 순서대로
    const props = Object.fromEntries(entries);
    return { type: node.type, props, children: Array.isArray(node.children) ? Array.from(node.children, convert) : node.children };
  };
  return { vdom: convert(root), handlers };
}
