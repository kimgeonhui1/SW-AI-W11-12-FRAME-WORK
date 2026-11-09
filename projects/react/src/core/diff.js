// [diff.js] 이전/새 Virtual DOM을 비교해 변경된 부분을 찾는 Diff 알고리즘

/**
 * ■ diff 반환 형식: "패치 트리" (VDOM과 같은 모양으로, 바뀐 곳만 표시한 트리)
 *
 *   null                                  → 바뀐 것 없음 (patch가 아무것도 안 한다)
 *   { type: "CREATE",  node }             → 이전엔 없던 노드. node(VNode)를 새로 만들어 넣는다
 *   { type: "REMOVE" }                    → 이번엔 없는 노드. 실제 DOM에서 지운다
 *   { type: "REPLACE", node }             → 태그가 다르거나 텍스트↔요소가 바뀜. 통째로 갈아 끼운다
 *   { type: "TEXT",    text }             → 같은 텍스트 노드인데 글자만 바뀜
 *   { type: "UPDATE",  props, children }  → 같은 태그. 속성 변경 목록 + 자식별 패치 배열
 *       props    : [{ name, value, oldValue }, ...]  (value가 undefined면 "속성 삭제")
 *       children : [자식0 패치, 자식1 패치, ...]     (인덱스 = 이전 VDOM의 자식 위치, 바뀐 게 없으면 null)
 *   { type: "UPDATE",  props, children, order, removed }  → 자식에 key가 있을 때 (아래 "key 모드")
 *       order    : [새 0번 자식이 이전 몇 번째였는지, ...]  (-1 = 새로 생긴 자식)
 *       children : [새 0번 자식의 패치, ...]               (인덱스 = "새" VDOM의 자식 위치. 새로 생긴 자식은 CREATE)
 *       removed  : [더 이상 없는 이전 자식의 인덱스, ...]
 *
 * 왜 트리 모양인가?
 *   patch가 실제 DOM을 "같은 인덱스로" 따라 내려가기만 하면 되어서, 노드 경로(예: [0, 2, 1])를 따로 계산할 필요가 없다.
 *
 * key가 없으면 "같은 위치(인덱스)끼리" 비교한다.
 *   리스트 맨 앞에 항목을 끼우면 뒤의 항목들이 전부 한 칸씩 밀려 UPDATE로 잡힌다. 결과 화면은 맞지만,
 *   DOM 노드는 자리를 지키고 "내용만" 바뀌므로 포커스·입력 중인 값처럼 노드에 붙은 상태가 다른 항목으로 넘어간다.
 * 자식에 key(h("li", { key: id }))가 있으면 "같은 key끼리" 비교하고, 노드를 지우지 않고 자리만 옮긴다. (실제 React와 같은 방식)
 */
export function diff(oldVNode, newVNode) {
  // 1) 이전엔 없고 이번엔 있음 → 새로 만들기
  if (oldVNode === undefined) return { type: "CREATE", node: newVNode };
  // 2) 이전엔 있고 이번엔 없음 → 지우기
  if (newVNode === undefined) return { type: "REMOVE" };

  const oldIsText = typeof oldVNode === "string";
  const newIsText = typeof newVNode === "string";

  // 3) 둘 다 텍스트 → 글자가 같으면 변화 없음, 다르면 글자만 바꾼다 (노드를 새로 만들 필요가 없다)
  if (oldIsText && newIsText) {
    return oldVNode === newVNode ? null : { type: "TEXT", text: newVNode };
  }

  // 4) 텍스트 ↔ 요소가 바뀌었거나 태그가 다름 → 고쳐 쓸 수 없으니 통째로 교체
  //    (<p>를 <div>로 바꾸는 DOM API는 없다. 태그가 다르면 새 요소를 만들 수밖에 없다)
  //    <input>의 type이 바뀌는 것도 교체한다. text ↔ checkbox ↔ radio는 브라우저 안에서 값을 다루는 방식이 달라서
  //    (checkbox의 기본 value "on"이 text로 바뀐 뒤에도 남는 등) 속성만 고치면 새로 그린 것과 화면이 달라진다.
  const inputTypeChanged = !oldIsText && !newIsText && oldVNode.type === "input" && oldVNode.props?.type !== newVNode.props?.type;
  if (oldIsText || newIsText || oldVNode.type !== newVNode.type || inputTypeChanged) {
    return { type: "REPLACE", node: newVNode };
  }

  // 5) 같은 태그 → 요소는 그대로 두고 속성과 자식만 비교한다
  const props = diffProps(oldVNode.props ?? {}, newVNode.props ?? {});
  const { children, order, removed } = diffChildren(oldVNode.children ?? [], newVNode.children ?? []);
  // key 모드에서 순서가 바뀌었거나 빠진 자식이 있으면, 자식별 패치가 전부 null이어도 "자식이 바뀐 것"이다
  const reordered = order !== undefined && (removed.length > 0 || order.some((oldIndex, i) => oldIndex !== i));

  // <select>/<textarea>는 자식이 바뀌면 value prop이 그대로여도 화면 값이 어긋난다.
  //   - select  : 선택돼 있던 option의 value가 바뀌면 select의 값도 따라 바뀐다
  //   - textarea: value를 한 번이라도 넣은 적이 있으면(dirty) 자식 텍스트를 바꿔도 화면 값이 그대로다
  // 그래서 자식 변경이 있으면 value를 다시 맞추라는 항목을 넣는다. (patch는 자식 → 속성 순서라 맞춘 값이 마지막에 남는다)
  // value가 없으면(undefined) removeProp이 "처음부터 그렸을 때의 값"으로 되돌린다 (vdom.js setProp 참고):
  //   - textarea: defaultValue(= 새 자식 텍스트)
  //   - select  : option의 selected 표시대로, 없으면 disabled가 아닌 첫 option
  // select는 multiple이 바뀔 때도 맞춘다. 단일 ↔ 다중 전환 시 브라우저가 남기는 선택이 새로 그린 것과 다르기 때문이다.
  // (이미 value가 바뀌어 diffProps가 넣었다면 새로 만들지 않는다 → 중복 없음)
  const newProps = newVNode.props ?? {};
  const childChanged = reordered || children.some((c) => c !== null);
  const multipleChanged = props.some((p) => p.name === "multiple");
  const resyncValue =
    (newVNode.type === "textarea" && childChanged) || (newVNode.type === "select" && (childChanged || multipleChanged));
  if (resyncValue && !props.some((p) => p.name === "value")) {
    props.push({ name: "value", value: newProps.value, oldValue: oldVNode.props?.value });
  }
  // value 항목은 모든 요소에서 항상 props 목록의 "맨 끝"으로 옮긴다. (createElement와 같은 순서)
  // patch는 props를 순서대로 적용하므로, multiple / min / max / step 이 먼저 바뀐 뒤에 값을 넣어야 잘리거나 풀리지 않는다.
  const valueIndex = props.findIndex((p) => p.name === "value");
  if (valueIndex !== -1) props.push(props.splice(valueIndex, 1)[0]);

  // 속성도 그대로고 자식도 전부 null이면 이 노드는 아무것도 안 바뀐 것 → null로 알려서 patch가 건너뛰게 한다
  if (props.length === 0 && !childChanged) return null;
  return order === undefined ? { type: "UPDATE", props, children } : { type: "UPDATE", props, children, order, removed };
}

/**
 * 속성 비교: 바뀐 것 / 새로 생긴 것 / 사라진 것을 [{ name, value, oldValue }] 목록으로 만든다
 * oldValue도 같이 넘기는 이유: style에서 "이전엔 있었는데 이번엔 없는 키"를 setProp이 지워야 하기 때문
 */
function diffProps(oldProps, newProps) {
  const changes = [];
  // 새 props 기준: 값이 달라졌거나 새로 생긴 속성
  for (const [name, value] of Object.entries(newProps)) {
    // key는 짝짓기용 표시일 뿐 DOM에 반영할 속성이 아니다
    if (name === "key") continue;
    if (!sameValue(oldProps[name], value)) changes.push({ name, value, oldValue: oldProps[name] });
  }
  // 이전 props 기준: 이번엔 없는 속성 → value: undefined (= 삭제)
  for (const name of Object.keys(oldProps)) {
    if (name !== "key" && !(name in newProps)) changes.push({ name, value: undefined, oldValue: oldProps[name] });
  }
  return changes;
}

/**
 * 두 prop 값이 같은지 비교
 * style은 렌더링할 때마다 새 객체가 만들어지므로 === 로 비교하면 항상 "다름"이 된다.
 * 그래서 객체끼리는 키 하나하나를 비교한다(얕은 비교). 함수(onClick)는 === 로 비교한다.
 */
function sameValue(a, b) {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  const aKeys = Object.keys(a);
  if (aKeys.length !== Object.keys(b).length) return false;
  // key in b: b에 그 키가 아예 없으면 b[key]도 undefined라서, a[key]가 undefined일 때 같다고 잘못 판단하는 것을 막는다
  return aKeys.every((key) => key in b && a[key] === b[key]);
}

/**
 * 자식 비교: 같은 인덱스끼리 diff한다.
 * 길이가 다르면 짧은 쪽은 undefined로 비교되어 → 늘어난 자리는 CREATE, 줄어든 자리는 REMOVE가 된다.
 * (그래서 CREATE는 끝에만, REMOVE도 끝에만 생긴다. patch는 이 성질 덕분에 CREATE를 appendChild로 처리할 수 있다)
 */
function diffChildren(oldChildren, newChildren) {
  if (oldChildren.some(hasKey) || newChildren.some(hasKey)) return diffKeyedChildren(oldChildren, newChildren);
  const length = Math.max(oldChildren.length, newChildren.length);
  const patches = [];
  for (let i = 0; i < length; i++) {
    patches.push(diff(oldChildren[i], newChildren[i]));
  }
  return { children: patches };
}

// key가 있는 요소인지 (텍스트는 key를 가질 수 없다)
function hasKey(child) {
  return typeof child !== "string" && child.props?.key != null;
}
// 자식 목록의 짝짓기 이름들. key가 없는 자식(텍스트 등)은 "key 없는 자식들 중 몇 번째인지"를 이름으로 쓴다.
// 전체 위치가 아니라 key 없는 것끼리의 순번이라서, 앞에 key 항목이 끼어들어도 key 없는 자식은 계속 같은 이전 노드와 짝지어진다.
// (k:/u: 접두어로 key "0"과 순번 0이 섞이지 않게 한다)
function matchKeys(children) {
  let unkeyed = 0;
  return children.map((child) => (hasKey(child) ? `k:${child.props.key}` : `u:${unkeyed++}`));
}

/**
 * key 모드 자식 비교: 새 자식마다 "같은 이름의 이전 자식"을 찾아 그것과 diff한다.
 *   - 찾았으면: 이전 노드를 재사용 (order에 이전 위치, children에 그 노드에 대한 패치)
 *   - 없으면  : 새로 만든다 (order에 -1, children에 CREATE)
 *   - 이전 자식 중 아무도 안 가져간 것: removed (patch가 지운다)
 * 같은 key가 두 번 나오면 두 번째는 짝이 없는 것으로 보고 새로 만든다 (key는 형제 사이에서 유일해야 한다)
 */
function diffKeyedChildren(oldChildren, newChildren) {
  // 이름 → 이전 위치. 짝지어지면 지워서 같은 이전 노드를 두 번 쓰지 않게 한다
  const oldIndexByKey = new Map();
  matchKeys(oldChildren).forEach((key, i) => {
    if (!oldIndexByKey.has(key)) oldIndexByKey.set(key, i);
  });

  const order = [];
  const children = [];
  const newKeys = matchKeys(newChildren);
  newChildren.forEach((child, i) => {
    const key = newKeys[i];
    const oldIndex = oldIndexByKey.get(key);
    if (oldIndex === undefined) {
      order.push(-1);
      children.push({ type: "CREATE", node: child });
    } else {
      oldIndexByKey.delete(key);
      order.push(oldIndex);
      children.push(diff(oldChildren[oldIndex], child));
    }
  });
  // 아무도 안 가져간 이전 자식은 지운다. (Map에 남은 것만 보면 안 된다: 같은 key가 두 번 있던 이전 자식의 두 번째는 Map에 아예 없다)
  const used = new Set(order);
  const removed = oldChildren.map((_, i) => i).filter((i) => !used.has(i));
  return { children, order, removed };
}
