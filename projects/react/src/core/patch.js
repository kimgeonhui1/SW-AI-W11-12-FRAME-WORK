// [patch.js] Diff 결과(변경 목록)를 실제 DOM에 반영

import { createElement, setProp, vdomChildNodes, validateVNode, checkProps } from "./vdom.js";
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
 * 2) 입력이 하나라도 잘못되면 실제 DOM 을 전혀 바꾸지 않아야 한다. (전부 적용되거나, 전혀 안 되거나)
 *    중간에 멈추면 실제 영역이 반쯤만 바뀐 상태로 남고, History 의 VDOM 과도 어긋난다.
 *    → 실패할 수 있는 일(검사 · 대상 찾기 · 새 DOM 만들기)을 모두 먼저 끝내고, 마지막에 한꺼번에 적용한다.
 *
 *   0단계: 입력 검사       — 컨테이너, 패치 배열, 패치마다 모양 (validatePatch)
 *   1단계: 대상 찾기 · 검사 — 경로가 실제로 있는지, 대상 종류가 패치와 맞는지, CREATE 의 index 가 맞는지
 *   2단계: 새 DOM 미리 만들기 — CREATE · REPLACE 의 node (잘못된 태그 이름 등은 여기서 오류)
 *   3단계: 적용             — 여기부터는 DOM 을 바꾸는 일만 한다
 * 0~2단계에서 오류가 나면 TypeError 를 던지고, 실제 DOM 은 그대로다.
 * ───────────────────────────────────────────────────────────────────
 *
 * @param {Element|DocumentFragment} container 루트 VNode 에 대응하는 실제 DOM 요소
 * @param {object[]} patches  diff() 가 반환한 패치 목록
 * @returns {Node[]} 실제로 변경된(또는 새로 생긴) DOM 노드 목록 — 화면 강조 표시용
 * @throws {TypeError} 입력이 잘못되었을 때 (DOM 은 바뀌지 않음)
 */
export function patch(container, patches) {
  // 0단계: 입력 검사
  if (!container || (container.nodeType !== ELEMENT_NODE && container.nodeType !== FRAGMENT_NODE)) {
    throw new TypeError("[patch] container 는 DOM 요소여야 합니다.");
  }
  if (!Array.isArray(patches)) throw new TypeError("[patch] patches 는 배열이어야 합니다.");
  // forEach · map 은 배열의 빈 칸(hole, 예: [p1, , p2])을 건너뛰어 검사가 빠지므로 인덱스로 돈다
  for (let i = 0; i < patches.length; i++) validatePatch(patches[i], i);

  // 1단계: 대상 노드 찾기 + 대상이 패치 종류와 맞는지 검사
  const createCount = new Map(); // 부모 노드 → 이 목록에서 지금까지 나온 CREATE 수 (index 검사용)
  const jobs = Array.from(patches, (p, i) => {
    const target = resolvePath(container, p.path);
    if (!target) {
      // DOM 과 VNode 가 어긋난 경우(예: 누군가 실제 영역을 직접 수정)
      throw new TypeError(`[patch] ${i}번째 패치: 경로 [${p.path.join(",")}] 에 노드가 없습니다.`);
    }
    checkTarget(p, i, target, createCount);
    return { patch: p, target };
  });

  // 2단계: CREATE · REPLACE 로 넣을 DOM 을 미리 만든다
  jobs.forEach((job, i) => {
    if (job.patch.type !== PATCH.CREATE && job.patch.type !== PATCH.REPLACE) return;
    try {
      job.node = createElement(job.patch.node);
    } catch (err) {
      // 예: type 이 "a b" 처럼 태그 이름으로 쓸 수 없는 글자 → 브라우저가 InvalidCharacterError(DOMException)
      // 다른 입력 오류와 같이 TypeError 로 알린다. (아직 DOM 은 바뀌지 않았다)
      throw new TypeError(`[patch] ${i}번째 패치(${job.patch.type}): 새 노드를 만들 수 없습니다 — ${err.message}`);
    }
  });

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
 * (모든 검사가 끝난 뒤에만 불린다)
 */
function applyOne({ patch: p, target, node }) {
  switch (p.type) {
    case PATCH.CREATE: {
      // target = 부모 요소. diff 는 새 자식을 인덱스 오름차순으로 내보내므로
      // 뒤에 차례로 붙이면 원하는 위치에 들어간다. (1단계에서 index 가 그 위치인지 확인했다)
      target.appendChild(node);
      return node;
    }
    case PATCH.REMOVE: {
      target.remove();
      return null; // 지워진 노드는 강조할 수 없다
    }
    case PATCH.REPLACE: {
      target.replaceWith(node);
      return node;
    }
    case PATCH.TEXT: {
      // 텍스트 노드는 새로 만들지 않고 내용만 바꾼다 (노드 재사용)
      target.nodeValue = p.value;
      return target;
    }
    case PATCH.PROPS: {
      // 삭제를 먼저 한다. HTML 속성 이름은 대소문자를 구분하지 않아서
      // { set: {Title: "a"}, remove: ["title"] } 를 "설정 → 삭제" 순서로 하면 방금 설정한 속성이 지워진다.
      // 삭제도 setProp(…, null) 을 거친다 → 속성을 지우면서 checked · value 같은 폼 프로퍼티도 함께 끈다
      for (const name of p.remove) setProp(target, name, null);
      for (const [name, value] of Object.entries(p.set)) setProp(target, name, value);
      return target;
    }
    default:
      throw new Error(`[patch] 알 수 없는 패치 종류: ${p.type}`); // validatePatch 가 막으므로 오지 않음
  }
}

/**
 * 찾은 대상 노드가 패치 종류와 맞는지 검사한다. 잘못되면 TypeError.
 *
 * TEXT          : 대상이 텍스트 노드 (요소의 nodeValue 를 바꾸면 아무 일도 일어나지 않고 조용히 무시된다)
 * PROPS · CREATE: 대상이 요소 (텍스트 노드에는 속성도 자식도 없다)
 * REMOVE · REPLACE: 대상이 컨테이너 자신(path [])이면 안 됨 — validatePatch 에서 이미 막음
 * CREATE index  : 부모의 지금 자식 수 + 이 목록에서 앞서 같은 부모에 붙인 CREATE 수 와 같아야 한다
 *                 (CREATE 는 끝에 붙이므로, 다른 index 를 주면 엉뚱한 위치에 들어간 것처럼 된다)
 */
function checkTarget(p, i, target, createCount) {
  const where = `[patch] ${i}번째 패치(${p.type}, 경로 [${p.path.join(",")}])`;
  const isElement = target.nodeType === ELEMENT_NODE || target.nodeType === FRAGMENT_NODE;
  if (p.type === PATCH.TEXT && target.nodeType !== TEXT_NODE) {
    throw new TypeError(`${where}: 대상이 텍스트 노드가 아닙니다.`);
  }
  if ((p.type === PATCH.PROPS || p.type === PATCH.CREATE) && !isElement) {
    throw new TypeError(`${where}: 대상이 요소가 아닙니다.`);
  }
  if (p.type === PATCH.PROPS && target.nodeType === FRAGMENT_NODE) {
    throw new TypeError(`${where}: DocumentFragment 에는 속성을 줄 수 없습니다.`);
  }
  if (p.type === PATCH.CREATE) {
    const earlier = createCount.get(target) ?? 0;
    const expected = vdomChildNodes(target.tagName === "TEMPLATE" ? target.content : target).length + earlier;
    if (p.index !== expected) {
      throw new TypeError(`${where}: index 는 ${expected} 여야 합니다 (받은 값 ${p.index}).`);
    }
    createCount.set(target, earlier + 1);
  }
}

/**
 * 경로(path)를 따라 container 에서 실제 DOM 노드를 찾는다.
 *
 * 자식 인덱스는 반드시 vdomChildNodes(= domToVdom 이 사용한 것과 같은 필터)로 센다.
 * 그래야 들여쓰기 공백·주석처럼 VNode 에 없는 DOM 노드 때문에 위치가 어긋나지 않는다.
 *
 * @returns {Node|null} 찾지 못하면 null
 */
function resolvePath(container, path) {
  let node = container;
  for (const index of path) {
    const children = vdomChildNodes(node.tagName === "TEMPLATE" ? node.content : node);
    node = children[index];
    if (!node) return null;
  }
  return node;
}

/**
 * 패치 하나의 모양을 검사한다. 잘못되면 TypeError.
 *
 * 공통: type 이 PATCH 중 하나, path 는 0 이상 정수 배열
 * CREATE : index(0 이상 정수), node(올바른 VNode — 하위 트리 전체를 validateVNode 로 검사)
 * REPLACE: node(올바른 VNode), path 는 [] 이면 안 됨 (컨테이너 자신을 바꾸면 실제 영역이 사라진다)
 * TEXT   : value(문자열)
 * PROPS  : set(평범한 객체, 값은 문자열 · 숫자 · 불리언 · null), remove(문자열 배열)
 * REMOVE : path 는 [] 이면 안 됨 (컨테이너 자신을 지우면 실제 영역이 사라진다)
 */
function validatePatch(p, i) {
  const where = `[patch] ${i}번째 패치`;
  if (p === null || typeof p !== "object") throw new TypeError(`${where}가 객체가 아닙니다: ${String(p)}`);
  if (!Object.values(PATCH).includes(p.type)) throw new TypeError(`${where}: 알 수 없는 종류 "${p.type}"`);
  if (!Array.isArray(p.path) || !p.path.every(isIndex)) throw new TypeError(`${where}: path 는 0 이상 정수 배열이어야 합니다.`);

  switch (p.type) {
    case PATCH.CREATE:
      if (!isIndex(p.index)) throw new TypeError(`${where}: CREATE 에 index 가 없습니다.`);
      checkNode(p.node, `${where}: CREATE 의 node`);
      break;
    case PATCH.REPLACE:
      if (p.path.length === 0) throw new TypeError(`${where}: 컨테이너 자신(경로 [])은 REPLACE 할 수 없습니다.`);
      checkNode(p.node, `${where}: REPLACE 의 node`);
      break;
    case PATCH.TEXT:
      if (typeof p.value !== "string") throw new TypeError(`${where}: TEXT 의 value 가 문자열이 아닙니다.`);
      break;
    case PATCH.PROPS:
      if (p.set === null || typeof p.set !== "object") throw new TypeError(`${where}: PROPS 의 set 이 객체가 아닙니다.`);
      checkProps(p.set, `${where}: PROPS 의 set`);
      if (!Array.isArray(p.remove) || !p.remove.every((n) => typeof n === "string")) {
        throw new TypeError(`${where}: PROPS 의 remove 는 문자열 배열이어야 합니다.`);
      }
      break;
    case PATCH.REMOVE:
      if (p.path.length === 0) throw new TypeError(`${where}: 컨테이너 자신(경로 [])은 REMOVE 할 수 없습니다.`);
      break;
    default:
      break;
  }
}

/** CREATE · REPLACE 의 node 검사: 올바른 VNode 인가 (하위 트리 전체, 순환 참조 포함) */
function checkNode(node, where) {
  try {
    validateVNode(node, "patch");
  } catch (err) {
    throw new TypeError(`${where} 가 올바른 VNode 가 아닙니다 — ${err.message}`);
  }
}

// DOM 노드 종류 상수 (Node.ELEMENT_NODE 등과 같은 값. iframe 의 노드도 판별하려고 instanceof 대신 사용)
const ELEMENT_NODE = 1;
const TEXT_NODE = 3;
const FRAGMENT_NODE = 11;

/** 0 이상의 정수인가 */
function isIndex(n) {
  return Number.isInteger(n) && n >= 0;
}
