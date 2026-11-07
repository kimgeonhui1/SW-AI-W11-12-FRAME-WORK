// [diff.js] 이전/새 Virtual DOM을 비교해 변경된 부분을 찾는 Diff 알고리즘

import { validateVNode } from "./vdom.js";

/**
 * 패치 종류. 모든 패치는 path(루트에서 대상까지 내려가는 자식 인덱스 배열, 이전 트리 기준)를 가진다.
 *   [] = 루트 자신, [2, 0] = 루트의 3번째 자식의 1번째 자식
 */
export const PATCH = Object.freeze({
  CREATE: "CREATE", //   { path: 부모 경로, index: 새 자식 위치, node }
  REMOVE: "REMOVE", //   { path }
  REPLACE: "REPLACE", // { path, node } — 태그가 다르거나 텍스트 ↔ 요소
  TEXT: "TEXT", //       { path, value } — 텍스트 내용만 변경
  PROPS: "PROPS", //     { path, set: {이름: 값}, remove: [이름] } — 속성만 변경
});

/**
 * 두 VDOM 을 비교해 패치 목록을 돌려준다 (React 재조정 휴리스틱의 단순판, O(n)).
 * 두 트리를 같은 위치끼리 깊이 우선으로 내려가며, 태그가 다르면 통째로 교체하고 더 내려가지 않는다.
 * 같은 태그면 노드를 재사용하고 속성 차이만 기록한 뒤, 자식을 인덱스 순서대로 짝짓는다 (key 없음).
 * 패치 순서 = 방문 순서 (부모 먼저, 형제는 앞에서부터).
 *
 * @param {{trustOld?: boolean}} [options] trustOld: 이미 검사를 통과한 이전 VDOM 이면 그 검사를 건너뜀 (트리 순회 1번 절약)
 * @throws {TypeError} 잘못된 VNode 가 있으면 — 미리 검사하므로 diff 가 내놓는 패치의 node 는 항상 올바르다
 */
export function diff(oldVNode, newVNode, { trustOld = false } = {}) {
  if (!trustOld) validateVNode(oldVNode, "diff 이전 VDOM");
  validateVNode(newVNode, "diff 새 VDOM");
  const patches = [];
  walk(oldVNode, newVNode, [], patches);
  return patches;
}

/** 한 쌍의 노드를 비교해 패치를 기록하고, 같은 태그면 자식으로 내려간다 — 최소 변경을 찾는 5가지 경우 */
function walk(oldNode, newNode, path, patches) {
  // ① 새 트리에서 사라짐 → REMOVE
  if (newNode === undefined) return void patches.push({ type: PATCH.REMOVE, path });

  const oldIsText = typeof oldNode === "string";
  const newIsText = typeof newNode === "string";
  // ② 둘 다 텍스트 → 내용이 다를 때만 TEXT
  if (oldIsText && newIsText) {
    if (oldNode !== newNode) patches.push({ type: PATCH.TEXT, path, value: newNode });
    return;
  }
  // ③ 텍스트 ↔ 요소, 또는 태그가 다름 → 하위 트리 통째로 REPLACE
  if (oldIsText || newIsText || oldNode.type !== newNode.type) return void patches.push({ type: PATCH.REPLACE, path, node: newNode });

  // ④ 같은 태그 → 속성만 비교 (PROPS)
  const propsPatch = diffProps(oldNode.props || {}, newNode.props || {});
  if (propsPatch) patches.push({ type: PATCH.PROPS, path, ...propsPatch });

  // ⑤ 자식을 인덱스로 짝짓기. 새 쪽에만 있으면 CREATE (아직 DOM 이 없으므로 "부모 경로 + 위치")
  const oldChildren = oldNode.children || [];
  const newChildren = newNode.children || [];
  for (let i = 0; i < Math.max(oldChildren.length, newChildren.length); i++) {
    if (i >= oldChildren.length) patches.push({ type: PATCH.CREATE, path, index: i, node: newChildren[i] });
    else walk(oldChildren[i], newChildren[i], [...path, i], patches);
  }
}

/**
 * 속성 비교 → { set: 새로 생기거나 바뀐 속성, remove: 사라진 이름 } (차이 없으면 null)
 * Object.hasOwn: "toString" 처럼 Object.prototype 에 있는 이름을 원래 있던 속성으로 잘못 보지 않게.
 * Object.fromEntries: "__proto__" 도 평범한 속성으로 담긴다.
 */
function diffProps(oldProps, newProps) {
  const set = Object.fromEntries(
    Object.entries(newProps).filter(([name, value]) => !Object.hasOwn(oldProps, name) || oldProps[name] !== value),
  );
  const remove = Object.keys(oldProps).filter((name) => !Object.hasOwn(newProps, name));
  return Object.keys(set).length === 0 && remove.length === 0 ? null : { set, remove };
}
