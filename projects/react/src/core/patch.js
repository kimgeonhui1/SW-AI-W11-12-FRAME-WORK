// [patch.js] Diff 결과(변경 목록)를 실제 DOM에 반영

import { createElement, setProp, removeProp, clearRefs, SVG_NS } from "./vdom.js";

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
  applyPatch(container, patches, container.firstChild);
}

// 실제 DOM 노드(node)에 패치 하나를 적용하고, UPDATE면 자식들로 재귀한다. (CREATE일 때 node는 없음)
function applyPatch(parent, p, node) {
  if (p === null) return;

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
      parent.replaceChild(createElement(p.node, inSvg(parent)), node);
      return;
    case "TEXT":
      // 텍스트 노드는 지우고 다시 만들 필요 없이 글자만 바꾸면 된다
      node.nodeValue = p.text;
      return;
    case "UPDATE":
      // 자식을 "먼저" 고치고 속성은 나중에 바꾼다. (createElement와 같은 순서)
      // <select>의 value는 그 값의 <option>이 이미 있어야 적용되고,
      // 자식 option의 selected 제거가 나중에 실행되면 방금 고른 값이 다시 풀리기 때문이다.
      {
        // 패치를 적용하기 "전에" 자식 노드 목록을 복사해 둔다.
        // childNodes는 살아 있는 목록이라 REMOVE로 하나 지우면 뒤 자식들의 인덱스가 당겨져 엉뚱한 노드를 고치게 된다.
        // 미리 잡아 둔 노드 참조로 작업하면 인덱스 변화와 상관없이 항상 원래 i번째 노드를 가리킨다.
        const childNodes = [...node.childNodes];
        if (p.order) applyKeyedChildren(node, p, childNodes);
        else p.children.forEach((childPatch, i) => applyPatch(node, childPatch, childNodes[i]));
      }
      for (const { name, value, oldValue } of p.props) {
        if (value === undefined) removeProp(node, name, oldValue);
        else setProp(node, name, value, oldValue);
      }
      return;
  }
}

/**
 * key 모드 자식 적용: 이전 DOM 노드를 지우지 않고 "새 순서"로 옮겨서 재사용한다
 *   1) 새 목록에 없는 이전 노드를 지운다
 *   2) 새 i번째 자리에 와야 할 노드(재사용 또는 새로 만든 것)가 이미 그 자리에 없을 때만 insertBefore로 옮긴다
 *      → 앞 항목 삭제·끝 추가·앞 삽입은 옮기는 노드가 없다 (지우거나 하나 끼우면 나머지는 저절로 제자리)
 *   3) 재사용한 노드에 그 노드의 패치(텍스트·속성 변경 등)를 적용한다
 * insertBefore는 이미 문서에 있는 노드를 넘기면 "복사"가 아니라 "이동"이라서, 노드에 붙은 상태(입력값, 리스너, ref)가 그대로 따라간다
 */
function applyKeyedChildren(node, p, oldNodes) {
  for (const oldIndex of p.removed) {
    clearRefs(oldNodes[oldIndex]);
    node.removeChild(oldNodes[oldIndex]);
  }
  p.order.forEach((oldIndex, i) => {
    const child = oldIndex === -1 ? createElement(p.children[i].node, inSvg(node)) : oldNodes[oldIndex];
    // childNodes[i]가 없으면(null) insertBefore는 맨 끝에 붙인다
    const current = node.childNodes[i] ?? null;
    if (child !== current) node.insertBefore(child, current);
    // 제자리에 놓은 뒤 패치 → REPLACE가 나와도 replaceChild가 같은 자리에 갈아 끼운다
    if (oldIndex !== -1) applyPatch(node, p.children[i], child);
  });
}
