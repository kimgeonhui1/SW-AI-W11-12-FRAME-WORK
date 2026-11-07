// [patch.js] Diff 결과(변경 목록)를 실제 DOM에 반영

import { createElement, setProp, vdomChildNodes } from "./vdom.js";
import { PATCH } from "./diff.js";

/**
 * 패치 목록을 container(= diff 에 넘긴 루트 VNode 에 해당하는 실제 DOM, Phase 1 에서는 #real-area)에 적용한다.
 *
 * 왜 단계를 나누나
 * - path 는 "변경 전" 기준이다. 0번을 지운 뒤 2번을 찾으면 인덱스가 당겨지므로, 모든 대상을 먼저 찾아 둔다.
 * - 실패하면 DOM 을 전혀 바꾸지 않아야 한다 (반쯤 바뀌면 History 와 어긋남).
 *   그래서 실패할 수 있는 일(① 대상 찾기 ② 새 DOM 만들기)을 먼저 끝내고 ③ 마지막에 한꺼번에 적용한다.
 * 패치 모양 자체는 검사하지 않는다 (diff 가 입력을 검사하므로 diff 가 만든 패치는 항상 올바르다).
 *
 * @returns {Node[]} 바뀌거나 새로 생긴 노드 (화면 강조용)
 * @throws {TypeError} 대상이 없음 · 모르는 종류 · 컨테이너 자신을 REMOVE/REPLACE · 새 노드를 못 만듦 (DOM 은 그대로)
 */
export function patch(container, patches) {
  // ① 대상 찾기. 노드 → 자식 목록을 기억해 재사용한다 (패치마다 루트부터 형제 목록을 새로 만들지 않게).
  //    이 단계는 DOM 을 바꾸지 않으므로 기억한 목록이 계속 맞다.
  const childCache = new Map();
  const jobs = patches.map((p, i) => {
    if (!Object.values(PATCH).includes(p.type)) throw new TypeError(`[patch] ${i}번째 패치: 알 수 없는 종류 "${p.type}"`);
    if ((p.type === PATCH.REMOVE || p.type === PATCH.REPLACE) && p.path.length === 0) {
      throw new TypeError(`[patch] ${i}번째 패치: 컨테이너 자신(경로 [])은 ${p.type} 할 수 없습니다.`); // 실제 영역이 사라짐
    }
    const target = resolvePath(container, p.path, childCache);
    if (!target) throw new TypeError(`[patch] ${i}번째 패치: 경로 [${p.path.join(",")}] 에 노드가 없습니다.`); // DOM 이 VNode 와 어긋남
    return { patch: p, target };
  });

  // ② CREATE · REPLACE 로 넣을 DOM 을 미리 만든다 (태그 이름에 공백 등 → DOMException 도 TypeError 로)
  for (const job of jobs) {
    if (job.patch.type !== PATCH.CREATE && job.patch.type !== PATCH.REPLACE) continue;
    try {
      job.node = createElement(job.patch.node);
    } catch (err) {
      throw new TypeError(`[patch] ${job.patch.type}: 새 노드를 만들 수 없습니다 — ${err.message}`);
    }
  }

  // ③ 적용 — 여기부터는 DOM 을 바꾸는 일만 한다
  return jobs.map(applyOne).filter(Boolean);
}

/** 패치 하나 적용, 바뀐 노드 반환 (지운 노드는 강조할 수 없으므로 null) */
function applyOne({ patch: p, target, node }) {
  switch (p.type) {
    case PATCH.CREATE: // target = 부모. diff 는 새 자식을 인덱스 오름차순으로 내보내므로 끝에 붙이면 된다
      target.appendChild(node);
      return node;
    case PATCH.REMOVE:
      target.remove();
      return null;
    case PATCH.REPLACE:
      target.replaceWith(node);
      return node;
    case PATCH.TEXT: // 텍스트 노드는 새로 만들지 않고 내용만 바꾼다
      target.nodeValue = p.value;
      return target;
    case PATCH.PROPS:
      // 삭제 먼저: 속성 이름은 대소문자를 구분하지 않아 { set: {Title}, remove: [title] } 를 반대로 하면 방금 설정한 것이 지워진다.
      // 삭제도 setProp(…, null) 을 거쳐 checked · value 같은 폼 프로퍼티도 함께 끈다.
      for (const name of p.remove) setProp(target, name, null);
      for (const [name, value] of Object.entries(p.set)) setProp(target, name, value);
      return target;
  }
}

/** path 를 따라 실제 노드를 찾는다 (없으면 null). 자식은 domToVdom 과 같은 vdomChildNodes 로 센다 */
function resolvePath(container, path, cache) {
  let node = container;
  for (const index of path) {
    let children = cache.get(node);
    if (!children) cache.set(node, (children = vdomChildNodes(node.tagName === "TEMPLATE" ? node.content : node)));
    node = children[index];
    if (!node) return null;
  }
  return node;
}
