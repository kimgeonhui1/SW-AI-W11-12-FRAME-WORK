// [patch.js] Diff 결과(변경 목록)를 실제 DOM에 반영

import { createElement, setProp, removeProp, clearRefs, withDeferredRefs, childHost, validateVNode, SVG_NS } from "./vdom.js";

// 이 부모 아래에 새로 만들 요소가 SVG여야 하는지 (<foreignObject> 안쪽은 다시 HTML)
function inSvg(parent) {
  return parent.namespaceURI === SVG_NS && parent.localName !== "foreignObject";
}

/**
 * ■ patch : diff가 만든 패치 트리를 실제 DOM에 적용한다
 *
 * @param container 루트 노드를 담고 있는 부모 요소. 루트 = container.childNodes[0]
 * @param patches   diff(oldVNode, newVNode)의 결과 (null이면 아무것도 안 함)
 *
 * 사용 예)
 *   container.appendChild(createElement(oldVNode));   // 처음 한 번 그리기
 *   patch(container, diff(oldVNode, newVNode));        // 이후엔 바뀐 곳만 고치기
 *
 * ⚠️ "VDOM 자식 i번째 = 실제 DOM 자식 i번째"를 전제로 한다.
 *    실제 DOM을 domToVdom으로 읽었다면 createElement 결과로 한 번 교체해 둘의 모양을 맞춰야 한다 (vdom.js 참고).
 */
export function patch(container, patches) {
  // DOM을 건드리기 "전에" 패치가 가리키는 노드가 전부 있는지 먼저 확인한다 (전부 적용되거나, 전혀 안 되거나).
  // 바로 적용하다 중간에 대상이 없으면 앞쪽만 바뀐 채 멈춰서 화면이 반쯤 바뀐다
  verifyPatch(patches, container.firstChild);
  // ref 연결은 patch가 끝난 뒤 한꺼번에 한다 → 같은 ref가 형제 사이를 옮겨가도 "해제 → 연결" 순서가 지켜진다
  withDeferredRefs(() => applyPatch(container, patches, container.firstChild));
}

const PATCH_TYPES = new Set(["CREATE", "REMOVE", "REPLACE", "TEXT", "UPDATE"]);

// applyPatch와 같은 길을 따라가며 "적용할 수 있는지"만 확인한다 (DOM은 바꾸지 않음)
function verifyPatch(p, node) {
  if (p === null) return;
  if (!PATCH_TYPES.has(p?.type)) throw new TypeError(`[patch] 알 수 없는 패치 종류입니다: ${JSON.stringify(p?.type)}`);
  // 새로 만들 노드도 미리 검사한다. 적용 도중 createElement가 실패하면 앞쪽 변경만 반영된 채 멈춘다
  if (p.type === "CREATE" || p.type === "REPLACE") {
    if (p.node === undefined) throw new TypeError(`[patch] ${p.type} 패치에 새 노드(node)가 없습니다`);
    validateVNode(p.node, `[patch] ${p.type}의 새 노드`);
  }
  if (p.type === "CREATE") return;
  // CREATE 말고는 고칠 실제 노드가 있어야 한다. 없거나 종류가 다르면 DOM과 VDOM이 어긋난 것 (예: 누군가 실제 영역을 직접 고침)
  const ok = p.type === "TEXT" ? node?.nodeType === Node.TEXT_NODE : p.type === "UPDATE" ? node?.nodeType === Node.ELEMENT_NODE : !!node;
  if (!ok) throw new TypeError(`[patch] ${p.type} 패치를 적용할 DOM 노드가 없거나 종류가 다릅니다 (DOM과 VDOM이 어긋남)`);
  if (p.type !== "UPDATE") return;
  const childNodes = childHost(node).childNodes;
  if (p.order) {
    for (const i of p.removed) if (!childNodes[i]) throw new TypeError("[patch] 지울 자식 노드가 없습니다 (DOM과 VDOM이 어긋남)");
    p.order.forEach((oldIndex, i) => oldIndex !== -1 && verifyPatch(p.children[i], childNodes[oldIndex] ?? null));
  } else {
    p.children.forEach((childPatch, i) => verifyPatch(childPatch, childNodes[i] ?? null));
  }
}

// 실제 DOM 노드(node)에 패치 하나를 적용하고, UPDATE면 자식들로 재귀한다. (CREATE일 때 node는 없음)
// 적용 뒤 그 자리에 있는 노드를 돌려준다 (REPLACE면 새 노드). key 모드가 "바로 앞 노드"를 기억하는 데 쓴다
function applyPatch(parent, p, node) {
  if (p === null) return node; // (대상 노드가 있는지는 verifyPatch가 미리 확인했다)

  switch (p.type) {
    case "CREATE":
      // diff는 늘어난 자식을 "끝에만" CREATE로 만들고, 아래에서 앞→뒤 순서로 적용하므로 맨 끝에 붙이면 순서가 맞다
      parent.appendChild(createElement(p.node, inSvg(parent)));
      return;
    case "REMOVE":
      // 지우는 요소를 가리키던 ref는 null로 (화면에 없는 요소를 계속 붙잡고 있지 않게)
      clearRefs(node);
      parent.removeChild(node);
      return;
    case "REPLACE":
      // ref 정리를 "새 요소를 만들기 전에" 한다. 새 요소가 같은 ref를 받는 경우 정리가 나중이면 새 요소의 ref까지 지워진다
      clearRefs(node);
      {
        const el = createElement(p.node, inSvg(parent));
        parent.replaceChild(el, node);
        return el;
      }
    case "TEXT":
      // 텍스트 노드는 지우고 다시 만들 필요 없이 글자만 바꾸면 된다
      node.nodeValue = p.text;
      return node;
    case "UPDATE":
      // 자식을 "먼저" 고치고 속성은 나중에 바꾼다. (createElement와 같은 순서)
      // <select>의 value는 그 값의 <option>이 이미 있어야 적용되고,
      // 자식 option의 selected 제거가 나중에 실행되면 방금 고른 값이 다시 풀리기 때문이다.
      {
        // 패치를 적용하기 "전에" 자식 노드 목록을 복사해 둔다.
        // childNodes는 살아 있는 목록이라 REMOVE로 하나 지우면 뒤 자식들의 인덱스가 당겨져 엉뚱한 노드를 고치게 된다.
        // 미리 잡아 둔 노드 참조로 작업하면 인덱스 변화와 상관없이 항상 원래 i번째 노드를 가리킨다.
        // <template>의 자식은 childNodes가 아니라 content(DocumentFragment) 안에 있다 (childHost)
        const host = childHost(node);
        const childNodes = [...host.childNodes];
        if (p.order) applyKeyedChildren(host, p, childNodes);
        else p.children.forEach((childPatch, i) => applyPatch(host, childPatch, childNodes[i]));
      }
      // 삭제를 먼저 한다. HTML 속성 이름은 대소문자를 구분하지 않아서, { Title → title }을 "넣기 → 지우기" 순서로 하면
      // 방금 넣은 title까지 지워진다. 단 value는 삭제여도 맨 끝에 둔다 (multiple / max 등이 먼저 바뀌어야 값이 맞게 남는다. diff가 맨 끝에 둠)
      {
        const removeFirst = (c) => c.value === undefined && c.name !== "value";
        for (const c of p.props) if (removeFirst(c)) removeProp(node, c.name, c.oldValue);
        for (const c of p.props) {
          if (removeFirst(c)) continue;
          if (c.value === undefined) removeProp(node, c.name, c.oldValue);
          else setProp(node, c.name, c.value, c.oldValue);
        }
      }
      return node;
  }
}

/**
 * key 모드 자식 적용: 이전 DOM 노드를 지우지 않고 "새 순서"로 옮겨서 재사용한다
 *   1) 새 목록에 없는 이전 노드를 지운다
 *   2) 새 순서를 앞에서부터 보면서, "옮기지 않아도 되는 노드"는 그대로 두고 나머지만 바로 앞 노드 뒤로 옮긴다
 *   3) 재사용한 노드에 그 노드의 패치(텍스트·속성 변경 등)를 적용한다
 *
 * 어떤 노드를 그대로 두나? (실제 React와 같은 규칙: lastPlaced)
 *   지금까지 그대로 둔 노드의 "이전 위치" 중 가장 큰 값(lastPlaced)보다 이전 위치가 크면, 상대 순서가 이미 맞으므로 그대로 둔다.
 *   작으면 앞쪽에 있던 노드가 뒤로 가야 하는 것이므로 옮긴다.
 *   예) [A,B,C,D] → [B,C,D,A] : B(1) C(2) D(3)는 그대로, A(0 < 3)만 맨 뒤로 → 1번 이동
 *   왜 중요한가: 노드를 옮기면(insertBefore) 브라우저가 그 안의 포커스를 풀어 버린다.
 *   "i번째 자리에 없으면 옮기기"로 하면 위 예에서 B, C, D 3개를 옮겨서 입력 중이던 C의 포커스가 사라졌다.
 *   (한계: 맨 뒤 항목을 맨 앞으로 보내면 나머지를 옮긴다. React도 같은 한계를 가진다)
 *
 * insertBefore는 이미 문서에 있는 노드를 넘기면 "복사"가 아니라 "이동"이라서, 노드에 붙은 상태(입력값, 리스너, ref)가 그대로 따라간다
 */
function applyKeyedChildren(node, p, oldNodes) {
  for (const oldIndex of p.removed) {
    clearRefs(oldNodes[oldIndex]);
    node.removeChild(oldNodes[oldIndex]);
  }
  let lastPlaced = -1;
  let prev = null; // 새 순서에서 바로 앞에 놓인 노드
  p.order.forEach((oldIndex, i) => {
    const isNew = oldIndex === -1;
    const child = isNew ? createElement(p.children[i].node, inSvg(node)) : oldNodes[oldIndex];
    if (!isNew && oldIndex > lastPlaced) {
      lastPlaced = oldIndex; // 상대 순서가 맞다 → 옮기지 않는다
    } else {
      const ref = prev ? prev.nextSibling : node.firstChild;
      // 이미 그 자리면 건드리지 않는다 (같은 자리라도 insertBefore를 하면 떼었다 붙여서 포커스가 풀린다)
      if (ref !== child) node.insertBefore(child, ref);
    }
    // 재사용한 노드는 자리를 잡은 뒤 패치 → REPLACE가 나오면 같은 자리에 갈아 끼우고 새 노드를 돌려준다
    prev = isNew ? child : applyPatch(node, p.children[i], child);
  });
}
