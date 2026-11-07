// [patch.js] Diff 결과(변경 목록)를 실제 DOM에 반영

import { createElement, setProp, vdomChildNodes } from "./vdom.js";
import { PATCH } from "./diff.js";

/**
 * 패치 목록을 실제 DOM 에 적용한다.
 *
 * container 는 diff 에 넘긴 "루트 VNode" 에 해당하는 실제 DOM 요소다.
 * (Phase 1 에서는 #real-area. 루트 VNode 는 containerToVdom 으로 만든 가상 div)
 *
 * ── 왜 여러 단계로 나누는가? ───────────────────────────────────────
 * 1) 패치의 path 는 "변경 전 트리" 기준 인덱스다.
 *    예) 자식 [0, 1, 2] 중 0번을 지운 뒤 2번을 찾으면, 인덱스가 당겨져서 존재하지 않는 노드를 찾게 된다.
 *    → DOM 을 건드리기 전에 모든 패치의 대상 노드를 미리 찾아 두고, 찾아 둔 "노드 참조" 에 적용한다.
 * 2) 대상을 못 찾으면 실제 DOM 을 전혀 바꾸지 않아야 한다. (전부 적용되거나, 전혀 안 되거나)
 *    중간에 멈추면 실제 영역이 반쯤만 바뀐 상태로 남고, History 의 VDOM 과도 어긋난다.
 *    → 실패할 수 있는 일(대상 찾기 · 새 DOM 만들기)을 먼저 끝내고, 마지막에 한꺼번에 적용한다.
 *
 *   1단계: 대상 찾기       — 경로가 실제로 있는지, 패치 종류가 올바른지,
 *                            REMOVE · REPLACE 가 컨테이너 자신(경로 [])을 가리키지 않는지
 *   2단계: 새 DOM 미리 만들기 — CREATE · REPLACE 의 node (잘못된 VNode 는 여기서 오류)
 *   3단계: 적용             — 여기부터는 DOM 을 바꾸는 일만 한다
 * 1~2단계에서 오류가 나면 TypeError 를 던지고, 실제 DOM 은 그대로다.
 * (패치 모양 자체는 검사하지 않는다. diff 가 만든 패치는 항상 올바르다 — diff 가 입력 VNode 를 검사함)
 * ───────────────────────────────────────────────────────────────────
 *
 * @param {Element} container 루트 VNode 에 대응하는 실제 DOM 요소
 * @param {object[]} patches  diff() 가 반환한 패치 목록
 * @returns {Node[]} 실제로 변경된(또는 새로 생긴) DOM 노드 목록 — 화면 강조 표시용
 * @throws {TypeError} 대상을 찾지 못했거나 새 노드를 만들 수 없을 때 (DOM 은 바뀌지 않음)
 */
export function patch(container, patches) {
  // 1단계: 대상 노드 찾기
  // 노드 → 자식 목록(vdomChildNodes) 을 기억해 두고 재사용한다.
  // 패치마다 루트부터 내려가며 형제 목록을 새로 만들면 "패치 수 × 깊이 × 형제 수" 만큼 일이 든다.
  // (1단계에서는 DOM 을 바꾸지 않으므로 기억해 둔 목록이 계속 맞다)
  const childCache = new Map();
  const jobs = patches.map((p, i) => {
    if (!Object.values(PATCH).includes(p.type)) {
      throw new TypeError(`[patch] ${i}번째 패치: 알 수 없는 종류 "${p.type}"`);
    }
    if ((p.type === PATCH.REMOVE || p.type === PATCH.REPLACE) && p.path.length === 0) {
      // 컨테이너 자신을 지우거나 바꾸면 실제 영역이 통째로 사라진다
      throw new TypeError(`[patch] ${i}번째 패치: 컨테이너 자신(경로 [])은 ${p.type} 할 수 없습니다.`);
    }
    const target = resolvePath(container, p.path, childCache);
    if (!target) {
      // DOM 과 VNode 가 어긋난 경우(예: 누군가 실제 영역을 직접 수정)
      throw new TypeError(`[patch] ${i}번째 패치: 경로 [${p.path.join(",")}] 에 노드가 없습니다.`);
    }
    return { patch: p, target };
  });

  // 2단계: CREATE · REPLACE 로 넣을 DOM 을 미리 만든다
  for (const job of jobs) {
    if (job.patch.type !== PATCH.CREATE && job.patch.type !== PATCH.REPLACE) continue;
    try {
      job.node = createElement(job.patch.node);
    } catch (err) {
      // 예: type 이 "a b" 처럼 태그 이름으로 쓸 수 없는 글자 → 브라우저가 InvalidCharacterError(DOMException)
      // 다른 입력 오류와 같이 TypeError 로 알린다. (아직 DOM 은 바뀌지 않았다)
      throw new TypeError(`[patch] ${job.patch.type}: 새 노드를 만들 수 없습니다 — ${err.message}`);
    }
  }

  // 3단계: 적용
  const touched = [];
  for (const job of jobs) {
    const node = applyOne(job);
    if (node) touched.push(node);
  }
  return touched;
}

/**
 * 패치 하나를 적용하고, 변경된 DOM 노드를 반환한다.
 * (대상 찾기 · 새 노드 만들기가 모두 끝난 뒤에만 불린다)
 */
function applyOne({ patch: p, target, node }) {
  switch (p.type) {
    case PATCH.CREATE:
      // target = 부모 요소. diff 는 새 자식을 인덱스 오름차순으로 내보내므로
      // 뒤에 차례로 붙이면 원하는 위치에 들어간다.
      target.appendChild(node);
      return node;
    case PATCH.REMOVE:
      target.remove();
      return null; // 지워진 노드는 강조할 수 없다
    case PATCH.REPLACE:
      target.replaceWith(node);
      return node;
    case PATCH.TEXT:
      // 텍스트 노드는 새로 만들지 않고 내용만 바꾼다 (노드 재사용)
      target.nodeValue = p.value;
      return target;
    case PATCH.PROPS:
      // 삭제를 먼저 한다. HTML 속성 이름은 대소문자를 구분하지 않아서
      // { set: {Title: "a"}, remove: ["title"] } 를 "설정 → 삭제" 순서로 하면 방금 설정한 속성이 지워진다.
      // 삭제도 setProp(…, null) 을 거친다 → 속성을 지우면서 checked · value 같은 폼 프로퍼티도 함께 끈다
      for (const name of p.remove) setProp(target, name, null);
      for (const [name, value] of Object.entries(p.set)) setProp(target, name, value);
      return target;
  }
}

/**
 * 경로(path)를 따라 container 에서 실제 DOM 노드를 찾는다.
 *
 * 자식 인덱스는 반드시 vdomChildNodes(= domToVdom 이 사용한 것과 같은 필터)로 센다.
 * 그래야 들여쓰기 공백·주석처럼 VNode 에 없는 DOM 노드 때문에 위치가 어긋나지 않는다.
 *
 * @param {Map<Node, Node[]>} cache 노드 → 자식 목록 (patch 한 번 동안 재사용)
 * @returns {Node|null} 찾지 못하면 null
 */
function resolvePath(container, path, cache) {
  let node = container;
  for (const index of path) {
    let children = cache.get(node);
    if (!children) {
      children = vdomChildNodes(node.tagName === "TEMPLATE" ? node.content : node);
      cache.set(node, children);
    }
    node = children[index];
    if (!node) return null;
  }
  return node;
}
