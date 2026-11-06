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
 * @returns {Array<object>} 패치 목록. 바뀐 것이 없으면 빈 배열
 * @throws {TypeError} 두 트리 중 하나라도 올바른 VNode 가 아니면 (vdom.js 의 validateVNode 규칙)
 */
export function diff(oldVNode, newVNode) {
  // 입력 검사를 먼저 한다. 검사하지 않으면
  //   - null 은 브라우저마다 다른 문구의 오류("Cannot read properties of null" 등)로 멈추고
  //   - {} · 숫자 같은 값은 조용히 REPLACE 패치의 node 로 들어가 patch 단계에서야 오류가 나며
  //   - props: "x" 는 글자마다 속성으로, children: "abc" 는 글자마다 자식으로 비교된다.
  // REPLACE · CREATE 로 통째로 넘어가는 하위 트리까지 검사하므로, diff 가 내놓는 패치의 node 는 항상 올바르다.
  validateVNode(oldVNode, "diff 이전 VDOM");
  validateVNode(newVNode, "diff 새 VDOM");

  const patches = [];

  // 재귀 대신 명시적 스택으로 두 트리를 함께 내려간다.
  // (재귀로 짜면 깊이 수천 단계의 트리에서 브라우저 호출 스택이 넘친다 — Chrome 기준 약 5,000 단계)
  //
  // 스택 항목 세 종류 (재귀 버전과 같은 순서로 패치가 나오도록 "할 일" 을 역순으로 쌓는다)
  //   { kind: "walk",   oldNode, newNode, depth, index } : 한 쌍의 노드 비교 (재귀 버전의 walk 호출)
  //   { kind: "create", node, depth, index }            : 부모(depth 단계)에 index 위치로 CREATE
  //   { kind: "leave",  oldNode, newNode }              : 자식 비교가 끝남 → 조상 목록에서 뺀다
  //
  // path 는 노드마다 새 배열을 만들지 않고 하나(currentPath)를 고쳐 쓴다.
  // 노드마다 [...path, i] 를 만들면 깊이 d 인 트리에서 O(d²) 개의 숫자가 생겨
  // 깊이 10,000 이면 수억 개가 된다. 패치를 기록할 때만 slice() 로 복사한다.
  //   depth = 루트에서의 깊이 (루트 0), index = 부모 안에서의 위치
  //   → 이 노드의 path = currentPath[0 .. depth-2] + [index]
  //   깊이 우선으로 돌기 때문에, 어떤 노드를 꺼냈을 때 currentPath 의 앞부분은 항상 그 노드의 조상 경로다.
  const currentPath = [];
  const oldAncestors = new Set(); // 지금 비교 중인 old 노드의 조상들 (순환 참조 검사용)
  const newAncestors = new Set(); // 지금 비교 중인 new 노드의 조상들 (순환 참조 검사용)
  const stack = [{ kind: "walk", oldNode: oldVNode, newNode: newVNode, depth: 0, index: 0 }];

  while (stack.length > 0) {
    const task = stack.pop();

    if (task.kind === "leave") {
      oldAncestors.delete(task.oldNode);
      newAncestors.delete(task.newNode);
      continue;
    }

    if (task.kind === "create") {
      // 옛 트리에 없던 자리 → 새로 추가.
      // 아직 DOM 에 노드가 없으므로 "부모 경로 + 넣을 위치" 로 표현한다.
      patches.push({ type: PATCH.CREATE, path: currentPath.slice(0, task.depth), index: task.index, node: task.node });
      continue;
    }

    // kind === "walk": 이 노드의 경로로 currentPath 를 맞춘다
    currentPath.length = Math.max(task.depth - 1, 0);
    if (task.depth > 0) currentPath.push(task.index);
    const children = compareNode(task.oldNode, task.newNode, currentPath, patches, oldAncestors, newAncestors);
    if (!children) continue; // 더 내려갈 필요 없음 (삭제 · 텍스트 · 교체)

    // 자식 비교 (인덱스 기준으로 짝짓기). 재귀 버전에서는 for 문으로 차례로 walk 를 불렀다.
    // 스택은 나중에 넣은 것이 먼저 나오므로 leave 를 먼저, 자식은 뒤에서부터 넣는다.
    oldAncestors.add(task.oldNode);
    newAncestors.add(task.newNode);
    stack.push({ kind: "leave", oldNode: task.oldNode, newNode: task.newNode });
    const { oldChildren, newChildren } = children;
    const max = Math.max(oldChildren.length, newChildren.length);
    const childDepth = task.depth + 1;
    for (let i = max - 1; i >= 0; i--) {
      if (i >= oldChildren.length) {
        stack.push({ kind: "create", node: newChildren[i], depth: task.depth, index: i });
      } else {
        stack.push({ kind: "walk", oldNode: oldChildren[i], newNode: newChildren[i], depth: childDepth, index: i });
      }
    }
  }
  return patches;
}

/**
 * 한 쌍의 노드를 비교해 이 노드 자신의 패치를 기록한다. (자식은 diff 의 스택이 처리)
 *
 * @param {object|string|undefined} oldNode
 * @param {object|string|undefined} newNode
 * @param {number[]} path   현재 노드 경로 (old 트리 기준). 고쳐 쓰는 배열이므로 기록할 때 복사한다
 * @param {object[]} patches 결과를 쌓을 배열
 * @param {Set<object>} oldAncestors 지금 비교 중인 old 노드의 조상들 (순환 참조 검사용)
 * @param {Set<object>} newAncestors 지금 비교 중인 new 노드의 조상들 (순환 참조 검사용)
 * @returns {{oldChildren: Array, newChildren: Array} | null} 자식까지 비교해야 하면 두 자식 배열, 아니면 null
 */
function compareNode(oldNode, newNode, path, patches, oldAncestors, newAncestors) {
  // ① 새 트리에서 사라진 노드 → 삭제
  if (newNode === undefined) {
    patches.push({ type: PATCH.REMOVE, path: path.slice() });
    return null;
  }

  const oldIsText = typeof oldNode === "string";
  const newIsText = typeof newNode === "string";

  // ② 둘 다 텍스트 → 내용이 다를 때만 TEXT
  if (oldIsText && newIsText) {
    if (oldNode !== newNode) {
      patches.push({ type: PATCH.TEXT, path: path.slice(), value: newNode });
    }
    return null;
  }

  // ③ 텍스트 ↔ 요소 전환, 또는 태그가 다름 → 하위 트리 통째로 교체
  if (oldIsText || newIsText || oldNode.type !== newNode.type) {
    patches.push({ type: PATCH.REPLACE, path: path.slice(), node: newNode });
    return null;
  }

  // 자기 조상을 자식으로 다시 가진 VNode 는 끝없이 내려가므로, 브라우저 스택 오류 대신 TypeError 로 알린다.
  // (같은 태그끼리 자식까지 내려가는 이 지점에서만 더 내려가므로 여기서 검사하면 충분하다)
  if (oldAncestors.has(oldNode) || newAncestors.has(newNode)) {
    throw new TypeError(`[diff] 순환 참조된 VNode 입니다 (경로 [${path.join(",")}])`);
  }

  // ④ 같은 태그 → 속성 비교
  const propsPatch = diffProps(oldNode.props || {}, newNode.props || {});
  if (propsPatch) {
    patches.push({ type: PATCH.PROPS, path: path.slice(), ...propsPatch });
  }

  // ⑤ 자식 비교는 호출한 쪽(diff)이 스택으로 이어서 한다
  return { oldChildren: oldNode.children || [], newChildren: newNode.children || [] };
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
