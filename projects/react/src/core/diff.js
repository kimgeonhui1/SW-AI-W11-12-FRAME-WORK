// [diff.js] 이전/새 Virtual DOM을 비교해 변경된 부분을 찾는 Diff 알고리즘

import { validateVNode } from "./vdom.js";

/**
 * 패치(변경 사항) 종류
 *
 * 모든 패치는 path(경로)를 가진다.
 * path = 루트 VNode 에서 대상 노드까지 내려가는 "자식 인덱스" 배열
 *   []      → 루트 자신
 *   [2]     → 루트의 3번째 자식
 *   [2, 0]  → 루트의 3번째 자식의 1번째 자식
 * path 는 항상 "이전(old) 트리" 기준이다. patch 는 이 경로로 실제 DOM 노드를 찾는다.
 */
export const PATCH = Object.freeze({
  CREATE: "CREATE", //   { type, path: 부모 경로, index: 새 자식 위치, node: 추가할 VNode }
  REMOVE: "REMOVE", //   { type, path: 지울 노드 경로 }
  REPLACE: "REPLACE", // { type, path, node: 새 VNode }  — 태그가 다르거나 텍스트↔요소 전환
  TEXT: "TEXT", //       { type, path, value: 새 문자열 } — 텍스트 내용만 변경
  PROPS: "PROPS", //     { type, path, set: {이름: 값}, remove: [이름, ...] } — 속성만 변경
});

/**
 * 두 Virtual DOM 을 비교해 변경 목록(패치 배열)을 반환
 *
 * 알고리즘 (React 의 재조정(reconciliation) 휴리스틱을 단순화)
 * 1. 두 트리를 동시에 깊이 우선(DFS)으로 내려간다.
 * 2. 같은 위치에 있는 노드끼리만 비교한다. → O(n)
 *    (트리 전체를 최적으로 비교하는 알고리즘은 O(n³) 이라 쓰지 않는다)
 * 3. 태그(type)가 다르면 "완전히 다른 트리" 로 보고 통째로 교체(REPLACE)하며 더 내려가지 않는다.
 * 4. 태그가 같으면 노드를 재사용하고, 속성 차이(PROPS)만 기록한 뒤 자식으로 내려간다.
 * 5. 자식은 인덱스 순서대로 짝을 짓는다.
 *    - 새 쪽에만 있으면 CREATE, 옛 쪽에만 있으면 REMOVE
 *
 * 반환되는 패치 순서 = DFS 방문 순서 (부모가 자식보다 먼저, 형제는 앞에서부터)
 *
 * @param {object|string} oldVNode 이전 Virtual DOM
 * @param {object|string} newVNode 새 Virtual DOM
 * @param {{trustOld?: boolean}} [options]
 *   trustOld : 이전 VDOM 이 이미 검사를 통과한 트리면 true → 이전 VDOM 검사를 건너뛴다.
 *              (예: Phase 2 의 this.vdom 은 지난 렌더에서 "새 VDOM" 으로 검사를 마쳤다. 매 렌더 트리 순회 1번 절약)
 * @returns {Array<object>} 패치 목록. 바뀐 것이 없으면 빈 배열
 * @throws {TypeError} 두 트리 중 하나라도 올바른 VNode 가 아니면 (vdom.js 의 validateVNode 규칙)
 */
export function diff(oldVNode, newVNode, { trustOld = false } = {}) {
  // 입력 검사를 먼저 한다. 검사하지 않으면
  //   - null 은 브라우저마다 다른 문구의 오류("Cannot read properties of null" 등)로 멈추고
  //   - {} · 숫자 같은 값은 조용히 REPLACE 패치의 node 로 들어가 patch 단계에서야 오류가 나며
  //   - props: "x" 는 글자마다 속성으로, children: "abc" 는 글자마다 자식으로 비교된다.
  // REPLACE · CREATE 로 통째로 넘어가는 하위 트리까지 검사하므로, diff 가 내놓는 패치의 node 는 항상 올바르다.
  if (!trustOld) validateVNode(oldVNode, "diff 이전 VDOM");
  validateVNode(newVNode, "diff 새 VDOM");

  const patches = [];
  walk(oldVNode, newVNode, [], patches);
  return patches;
}

/**
 * 한 쌍의 노드를 비교해 패치를 기록하고, 같은 태그면 자식으로 내려간다. (깊이 우선)
 *
 * @param {object|string|undefined} oldNode
 * @param {object|string|undefined} newNode
 * @param {number[]} path   현재 노드 경로 (old 트리 기준)
 * @param {object[]} patches 결과를 쌓을 배열
 */
function walk(oldNode, newNode, path, patches) {
  // ① 새 트리에서 사라진 노드 → 삭제
  if (newNode === undefined) {
    patches.push({ type: PATCH.REMOVE, path });
    return;
  }

  const oldIsText = typeof oldNode === "string";
  const newIsText = typeof newNode === "string";

  // ② 둘 다 텍스트 → 내용이 다를 때만 TEXT
  if (oldIsText && newIsText) {
    if (oldNode !== newNode) {
      patches.push({ type: PATCH.TEXT, path, value: newNode });
    }
    return;
  }

  // ③ 텍스트 ↔ 요소 전환, 또는 태그가 다름 → 하위 트리 통째로 교체
  if (oldIsText || newIsText || oldNode.type !== newNode.type) {
    patches.push({ type: PATCH.REPLACE, path, node: newNode });
    return;
  }

  // ④ 같은 태그 → 속성 비교
  const propsPatch = diffProps(oldNode.props || {}, newNode.props || {});
  if (propsPatch) {
    patches.push({ type: PATCH.PROPS, path, ...propsPatch });
  }

  // ⑤ 자식 비교: 인덱스 순서대로 짝을 짓는다
  //    새 쪽에만 있으면 CREATE — 아직 DOM 에 노드가 없으므로 "부모 경로 + 넣을 위치" 로 표현한다.
  const oldChildren = oldNode.children || [];
  const newChildren = newNode.children || [];
  const max = Math.max(oldChildren.length, newChildren.length);
  for (let i = 0; i < max; i++) {
    if (i >= oldChildren.length) {
      patches.push({ type: PATCH.CREATE, path, index: i, node: newChildren[i] });
    } else {
      walk(oldChildren[i], newChildren[i], [...path, i], patches);
    }
  }
}

/**
 * 속성 객체 두 개를 비교한다.
 *
 * @returns {{set: object, remove: string[]} | null} 차이가 없으면 null
 *   set    : 새로 생기거나 값이 바뀐 속성
 *   remove : 사라진 속성 이름 목록
 */
function diffProps(oldProps, newProps) {
  const set = {};
  const remove = [];

  // 추가되었거나 값이 바뀐 속성
  // - Object.hasOwn: "constructor" · "toString" 처럼 Object.prototype 에 있는 이름을
  //   "원래 있던 속성" 으로 잘못 보지 않도록 자기 속성만 본다.
  // - defineProperty: set["__proto__"] = 값 은 프로토타입 설정이 되어 사라지므로 평범한 속성으로 만든다.
  for (const [name, value] of Object.entries(newProps)) {
    if (!Object.hasOwn(oldProps, name) || oldProps[name] !== value) {
      Object.defineProperty(set, name, { value, enumerable: true, writable: true, configurable: true });
    }
  }
  // 없어진 속성 (`name in newProps` 는 프로토타입까지 보므로 쓰지 않는다)
  for (const name of Object.keys(oldProps)) {
    if (!Object.hasOwn(newProps, name)) remove.push(name);
  }

  if (Object.keys(set).length === 0 && remove.length === 0) return null;
  return { set, remove };
}
