// [component.js] 함수형 컴포넌트를 감싸 상태 저장(hooks)과 렌더링(mount/update)을 담당

import { h, createElement, validateVNode, clearRefs } from "./vdom.js";
import { diff } from "./diff.js";
import { patch } from "./patch.js";

/**
 * ■ 핵심 질문: "함수는 매번 새로 실행되는데, 상태는 어떻게 유지할까?"
 *
 * 함수 안의 지역 변수는 실행이 끝나면 사라진다. 그래서 상태를 함수 "밖"(FunctionComponent 객체의 hooks 배열)에 둔다.
 * 컴포넌트 함수를 실행하기 직전에 "지금 렌더링 중인 컴포넌트"를 currentComponent에 적어 두면,
 * 함수 안에서 호출된 useState가 그 객체를 찾아 hooks[0], hooks[1] ... 칸을 꺼내 쓸 수 있다.
 *
 * 몇 번째 칸인지는 "호출 순서"로 정한다 (hookIndex를 렌더링마다 0으로 되돌리고 Hook을 부를 때마다 1씩 증가).
 * 그래서 Hook을 if/for 안에서 부르면 렌더링마다 순서가 달라져 다른 칸을 읽게 된다 → 항상 같은 순서로 불러야 한다.
 */
let currentComponent = null;
// 자식 컴포넌트 함수를 실행 중인 깊이. 0보다 크면 지금 실행 중인 함수는 루트가 아니다 (Hook 금지 검사에 사용)
let childDepth = 0;
// Hook이 넘겨받은 함수(useMemo 계산 함수, useState 초기값 함수)를 실행 중인 깊이. 그 안에서 Hook을 부르면 안 된다
let hookLock = 0;
// 사용자 입력 없이 연달아 다시 렌더링할 수 있는 최대 횟수 (넘으면 무한 렌더링으로 보고 멈춘다. React도 50)
export const MAX_NESTED_UPDATES = 50;

// hooks.js가 "지금 Hook을 부른 컴포넌트"를 찾을 때 쓴다
export function getCurrentComponent() {
  if (currentComponent === null) throw new Error("Hook은 컴포넌트를 렌더링하는 중에만 호출할 수 있습니다.");
  // useMemo 계산 함수는 캐시가 있으면 실행되지 않는다 → 그 안의 Hook은 렌더링마다 불리다 말다 해서 칸 순서가 깨진다
  if (hookLock > 0) throw new Error("Hook 안(useMemo 계산 함수, useState 초기값 함수)에서 다른 Hook을 부를 수 없습니다.");
  // 과제 제약: State와 Hook은 루트 컴포넌트에서만. 자식은 props만 받는 순수 함수여야 한다
  if (childDepth > 0) throw new Error("Hook은 루트 컴포넌트에서만 사용할 수 있습니다. 자식 컴포넌트는 props만 받아야 합니다.");
  return currentComponent;
}

// hooks.js가 사용자 함수(useMemo 계산 함수, useState 초기값 함수)를 실행할 때 쓴다. 그 안에서 Hook을 부르면 에러가 나게 한다
export function runWithoutHooks(fn) {
  hookLock++;
  try {
    return fn();
  } finally {
    hookLock--;
  }
}

export class FunctionComponent {
  /**
   * @param component  루트 컴포넌트 함수 (props) => VNode
   * @param container  화면을 그릴 요소. 컴포넌트가 돌려준 노드들이 container의 자식으로 들어간다
   * @param props      루트 컴포넌트에 넘길 props
   */
  constructor(component, container, props = {}) {
    // 잘못 넘기면 mount 때 "is not a function" 같은 알기 어려운 에러가 나므로 만들 때 바로 알린다
    if (typeof component !== "function") throw new TypeError("FunctionComponent: component는 함수여야 합니다");
    if (container?.nodeType !== Node.ELEMENT_NODE) throw new TypeError("FunctionComponent: container는 DOM 요소여야 합니다");
    this.component = component;
    this.container = container;
    this.props = props;
    this.hooks = []; // Hook별 저장 칸. 렌더링이 끝나도 이 배열은 남아 있어서 상태가 유지된다
    this.hookKinds = []; // 칸마다 처음 쓴 Hook 종류 ("state" / "effect" / "ref" / "memo"). 순서가 바뀌었는지 검사용
    this.hookIndex = 0; // 이번 렌더링에서 다음 Hook이 쓸 칸 번호
    // 지금 화면에 그려진 VDOM. 다음 update의 diff 기준 (화면에서 다시 읽지 않는다 → onClick 같은 함수도 보존)
    // 루트는 container 자신을 뜻하는 속성 없는 div: { type: "div", props: {}, children: [컴포넌트가 돌려준 노드들] }
    this.vdom = null;
    // patch는 "parent.firstChild = 루트"로 다룬다. 루트가 container 자신이므로 container를 firstChild로 가진 객체를 넘긴다
    // (루트 div끼리는 props가 늘 {}라서 루트 패치는 UPDATE나 null뿐 → parent의 다른 기능은 쓰이지 않는다)
    this.patchParent = { firstChild: container };
    this.pendingEffects = []; // 이번 렌더링에서 실행해야 할 useEffect 목록 (화면 반영 "뒤"에 실행)
    this.updateScheduled = false;
    this.nestedUpdates = 0; // 사용자 입력 없이 연달아 일어난 렌더링 수 (무한 렌더링 감지)
  }

  // 처음 렌더링: 컴포넌트 실행 → VDOM 전체를 실제 DOM으로 만들어 넣기
  mount() {
    // 이미 그려져 있는데 또 mount하면 이전 DOM의 ref 정리 없이 화면을 새로 만든다 → 다시 그리려면 update, 처음부터 하려면 unmount 후 mount
    if (this.vdom !== null) throw new Error("이미 mount되었습니다. 다시 그리려면 update(), 처음부터 그리려면 unmount() 후 mount()를 쓰세요.");
    this.committing = true;
    try {
      const vdom = this.render();
      this.container.replaceChildren(...createElement(vdom).childNodes);
      // DOM을 다 만든 "뒤"에 기억한다. createElement가 실패했는데 vdom이 남으면 "이미 mount됨"으로 보여 다시 mount할 수 없다
      this.vdom = vdom;
      this.runEffects();
      return this; // new FunctionComponent(App, el).mount() 처럼 이어서 쓸 수 있게
    } catch (e) {
      // 첫 렌더링이 실패하면 그때 만든 Hook 칸을 버린다. 남겨 두면 다시 mount할 때 실패한 시도의 초기값을 그대로 쓴다 (React도 버린다)
      // (effect 실행 중 에러는 화면은 이미 그려진 것이라 해당하지 않는다)
      if (this.vdom === null) {
        this.hooks = [];
        this.hookKinds = [];
        this.hookCount = undefined;
      }
      throw e;
    } finally {
      this.committing = false;
    }
  }

  // 상태 변경 후 다시 렌더링: 새 VDOM → 이전 VDOM과 Diff → 바뀐 부분만 Patch (Phase 1 재사용)
  update() {
    if (this.vdom === null) return; // mount 전(또는 unmount 후)에는 그릴 곳이 없다
    // 렌더링 ~ effect 실행 동안 표시해 둔다 → 이 사이에 불린 setState는 "렌더링이 만든 렌더링"(연쇄)으로 센다 (scheduleUpdate)
    this.committing = true;
    try {
      this.commitUpdate();
    } finally {
      this.committing = false;
    }
  }

  commitUpdate() {
    const next = this.render();
    try {
      patch(this.patchParent, diff(this.vdom, next));
    } catch (e) {
      // validateVNode를 통과했으면 patch는 보통 실패하지 않지만, 브라우저가 값을 거부하는 경우가 남아 있다
      // (예: <input type="file">에 value를 넣으면 InvalidStateError). 그러면 DOM이 반쯤만 바뀌어 this.vdom과 어긋나고,
      // 다음 diff가 틀린 DOM을 기준으로 고치게 된다 → 마지막으로 성공한 VDOM으로 화면을 통째로 다시 만들어 둘을 맞춘다
      clearRefs(this.container);
      this.container.replaceChildren(...createElement(this.vdom).childNodes);
      throw e;
    }
    this.vdom = next;
    // 제어 컴포넌트: 사용자가 입력해서 화면 값만 바뀌고 State는 그대로면 diff는 "변경 없음"이라 화면 값이 남는다.
    // 화면 값을 항상 State(VDOM)와 같게 맞춘다 (React의 controlled input과 같은 동작)
    syncControlled(this.container, next);
    this.runEffects();
  }

  /**
   * setState가 부른다. 바로 그리지 않고 "현재 작업이 끝난 직후"(마이크로태스크)에 한 번만 그린다 = Batching.
   * 클릭 한 번에 setState를 여러 번 불러도 update는 1번 → 중간 상태가 화면에 보이지 않고, diff·patch도 1번만 한다.
   */
  scheduleUpdate() {
    // 무한 렌더링 감지: effect 안에서 deps 없이 setState를 부르면 렌더링 → effect → setState → 렌더링 ... 이 끝없이 반복된다.
    // 마이크로태스크는 큐가 빌 때까지 브라우저가 화면 그리기·클릭 처리를 하지 않으므로, 그대로 두면 탭이 에러도 없이 굳는다.
    // "렌더링·effect 도중(committing)"에 불린 setState만 연쇄로 센다. 이벤트 핸들러나 async 반복문처럼 밖에서 부르면 0으로 되돌린다.
    // (시간으로 세면 await를 끼운 정상적인 반복문 60번도 연쇄로 오해해서 막아 버린다)
    if (!this.committing) this.nestedUpdates = 0;
    if (this.updateScheduled) return;
    this.updateScheduled = true;
    if (this.committing) this.nestedUpdates++;
    queueMicrotask(() => {
      this.updateScheduled = false;
      if (this.nestedUpdates > MAX_NESTED_UPDATES) {
        this.nestedUpdates = 0;
        throw new Error(
          `렌더링이 ${MAX_NESTED_UPDATES}번 넘게 연달아 일어나 멈췄습니다. useEffect 안에서 deps 없이 setState를 부르거나, 렌더링 중에 setState를 부르고 있지 않은지 확인하세요.`
        );
      }
      this.update();
    });
  }

  /**
   * 화면에서 내린다: 모든 effect의 cleanup 실행 → ref 해제 → DOM 비우기 → 상태 초기화
   * cleanup을 부르지 않으면 effect가 건 타이머·이벤트 리스너가 화면이 사라진 뒤에도 계속 돈다.
   * 이후 setState가 불려도 update가 vdom === null을 보고 아무것도 하지 않는다.
   */
  unmount() {
    if (this.vdom === null) return;
    const errors = [];
    this.hooks.forEach((hook, i) => {
      if (this.hookKinds[i] !== "effect" || typeof hook.cleanup !== "function") return;
      const cleanup = hook.cleanup;
      hook.cleanup = undefined;
      // 하나가 에러를 내도 나머지 cleanup은 모두 실행한다 (runEffects와 같은 규칙)
      try {
        cleanup();
      } catch (e) {
        errors.push(e);
      }
    });
    clearRefs(this.container);
    this.container.replaceChildren();
    this.vdom = null;
    // 다시 mount하면 처음부터 시작한다 (React도 unmount된 컴포넌트의 상태는 버린다)
    this.hooks = [];
    this.hookKinds = [];
    this.hookCount = undefined;
    if (errors.length > 0) throw errors[0];
  }

  // 컴포넌트 함수를 실행해 VDOM을 얻는다. Hook이 이 객체를 찾을 수 있게 앞뒤로 currentComponent를 설정/해제한다
  render() {
    this.hookIndex = 0;
    this.pendingEffects = [];
    // 렌더링 도중 다른 컴포넌트를 렌더링해도(중첩) 끝나면 바깥 컴포넌트로 돌아가게 이전 값을 기억한다
    const outer = currentComponent;
    currentComponent = this;
    try {
      const result = this.component(this.props);
      // Hook은 "호출 순서"로 칸을 찾으므로 렌더링마다 호출 개수가 같아야 한다.
      // if/for 안에서 Hook을 불러 개수가 달라지면 다른 Hook의 칸을 조용히 읽게 되므로 바로 에러로 알린다
      if (this.hookCount === undefined) this.hookCount = this.hookIndex;
      else if (this.hookIndex !== this.hookCount) {
        throw new Error(`Hook 호출 개수가 바뀌었습니다 (${this.hookCount} → ${this.hookIndex}). Hook을 조건문/반복문 안에서 부르지 마세요.`);
      }
      // 결과를 container를 뜻하는 루트 div로 감싼다. h의 자식 정리 규칙(배열 펼치기, null 제거, 텍스트 합치기)을 거쳐서
      // 컴포넌트가 노드 하나 · 여러 개(배열) · 문자열 · null 무엇을 돌려줘도 된다 (React의 Fragment / null과 같은 효과)
      const root = h("div", null, expand(result));
      // 화면을 건드리기 "전에" 결과를 검사한다 → 잘못된 VDOM이면 DOM은 그대로 두고 위치가 담긴 에러를 낸다
      validateVNode(root);
      return root;
    } finally {
      // 에러가 나도 되돌려야 렌더링 밖에서 Hook을 부르는 실수를 계속 잡아낼 수 있다
      currentComponent = outer;
    }
  }

  // useEffect는 DOM이 바뀐 "뒤"에 실행해야 effect 안에서 최신 화면을 읽을 수 있다
  // React와 같은 순서: 이번에 다시 실행할 effect들의 cleanup을 "모두" 먼저 부르고, 그다음 새 effect들을 실행한다
  // (effect A의 새 실행이 effect B의 아직 안 지운 이전 상태와 겹치지 않게)
  runEffects() {
    const effects = this.pendingEffects;
    this.pendingEffects = [];
    // effect 하나가 에러를 내도 나머지 cleanup/effect는 모두 실행한다.
    // 중간에 멈추면 일부는 이전 정리 함수만 지워진 채 새 effect가 안 돌아 상태가 어긋난다. 첫 에러는 끝에서 다시 던져 알린다
    const errors = [];
    const attempt = (fn) => {
      try {
        fn();
      } catch (e) {
        errors.push(e);
      }
    };
    for (const { hook } of effects) {
      // 먼저 비워 두고 부른다 → cleanup이 에러를 내도 같은 cleanup을 다음에 또 부르지 않는다
      const cleanup = hook.cleanup;
      hook.cleanup = undefined;
      if (typeof cleanup === "function") attempt(cleanup);
    }
    for (const { hook, callback, deps } of effects) {
      // "실행했다"는 기록은 실제로 실행할 때 남긴다 (렌더링 도중에 남기면, 렌더링이 실패했을 때 영영 건너뛰게 된다)
      hook.ran = true;
      hook.deps = deps;
      attempt(() => {
        const cleanup = callback();
        hook.cleanup = typeof cleanup === "function" ? cleanup : undefined;
      });
    }
    if (errors.length > 0) throw errors[0];
  }
}

/**
 * VDOM 안의 자식 컴포넌트 h(Child, props)를 실행해서 일반 요소/텍스트만 남긴다.
 * diff/patch는 태그 이름(문자열)만 다루므로, 함수 타입은 diff 전에 모두 풀어 둬야 한다.
 * 자식은 상태가 없는 순수 함수라 매번 다시 실행해도 결과가 props로만 정해진다.
 *
 * 자식 컴포넌트는 요소뿐 아니라 문자열, 숫자, 배열, null, "" 를 반환할 수 있다.
 * 그 결과가 부모의 자식 목록에 그대로 끼면 "텍스트는 이웃끼리 합쳐져 있다" 같은 VDOM 정리 규칙이 깨진다.
 * 그래서 요소마다 h()로 다시 만들어 normalizeChildren(배열 펼치기, null/boolean 제거, 숫자→문자열, 텍스트 합치기)을 거치게 한다.
 */
function expand(node) {
  // 배열·문자열·숫자·null·boolean은 여기서 건드리지 않고 그대로 돌려준다. 부모의 h()가 한꺼번에 정리한다
  if (Array.isArray(node)) return node.map(expand);
  if (node === null || typeof node !== "object") return node;
  if (typeof node.type === "function") {
    // key는 컴포넌트에게 주는 값이 아니라 diff가 짝짓는 표시다 (React도 props.key로 넘기지 않는다)
    const { key, ...props } = node.props;
    childDepth++;
    let out;
    try {
      // children도 props.children으로 넘긴다 (React와 같은 방식)
      out = expand(node.type({ ...props, children: node.children }));
    } finally {
      childDepth--;
    }
    // h(TodoItem, { key }) 의 key를 컴포넌트가 돌려준 요소에 옮겨 붙인다. diff는 요소만 보므로 여기 있어야 짝지어진다
    const isElement = out !== null && typeof out === "object" && !Array.isArray(out);
    if (key != null && isElement && out.props.key == null) out = { ...out, props: { ...out.props, key } };
    return out;
  }
  // 모양이 잘못된 노드({}, children이 배열이 아님 등)는 손대지 않고 넘긴다 → render 끝의 validateVNode가 위치와 함께 알려 준다
  if (typeof node.type !== "string" || !Array.isArray(node.children)) return node;
  return h(node.type, node.props, ...node.children.map(expand));
}

// VDOM의 value/checked를 실제 DOM의 현재 값(property)에 다시 맞춘다. 다를 때만 대입 (같은 값을 넣으면 커서 위치가 튈 수 있음)
function syncControlled(node, vnode) {
  if (!node || typeof vnode === "string") return;
  const props = vnode.props ?? {};
  if ("value" in props && props.value != null && node.value !== String(props.value)) node.value = String(props.value);
  if ("checked" in props && node.checked !== Boolean(props.checked)) node.checked = Boolean(props.checked);
  (vnode.children ?? []).forEach((child, i) => syncControlled(node.childNodes[i], child));
}
