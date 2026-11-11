// [diff.js] 이전/새 Virtual DOM을 비교해 변경된 부분을 찾는 Diff 알고리즘

// 두 Virtual DOM을 비교해 변경 목록을 반환 (반환 형식은 자유)
export function diff(oldVNode, newVNode) {
  const patches = [];

  function walk(oldNode, newNode, path) {
    if (oldNode === newNode) return;
    if (oldNode === null) {
      patches.push({ type: "insert", path, vnode: newNode });
      return;
    }
    if (newNode === null) {
      patches.push({ type: "remove", path });
      return;
    }
    if (typeof oldNode === "string" && typeof newNode === "string") {
      patches.push({ type: "text", path, value: newNode });
      return;
    }
    if (typeof oldNode !== typeof newNode || oldNode.type !== newNode.type) {
      patches.push({ type: "replace", path, vnode: newNode });
      return;
    }

    const set = {};
    const remove = [];
    for (const name of Object.keys(oldNode.props)) {
      if (!Object.hasOwn(newNode.props, name)) remove.push(name);
    }
    for (const [name, value] of Object.entries(newNode.props)) {
      if (!Object.hasOwn(oldNode.props, name) || oldNode.props[name] !== value) {
        Object.defineProperty(set, name, { value, enumerable: true });
      }
    }
    if (Object.keys(set).length || remove.length) {
      patches.push({ type: "props", path, set, remove });
    }

    const before = oldNode.children;
    const after = newNode.children;
    let oldStart = 0;
    let newStart = 0;
    // Equal subtrees are stable anchors; compare only the gaps between them.
    const anchors = matchChildren(before, after);
    anchors.push([before.length, after.length]);
    for (const [oldEnd, newEnd] of anchors) {
      let oldIndex = oldStart;
      let newIndex = newStart;
      while (oldIndex < oldEnd && newIndex < newEnd) {
        // A surplus child must not displace a later update of the same type.
        const surplus = (oldEnd - oldIndex) - (newEnd - newIndex);
        if (!sameType(before[oldIndex], after[newIndex]) && surplus !== 0) {
          const candidates = surplus > 0 ? before : after;
          const start = surplus > 0 ? oldIndex : newIndex;
          const target = surplus > 0 ? after[newIndex] : before[oldIndex];
          let offset = 1;
          while (offset <= Math.abs(surplus) && !sameType(candidates[start + offset], target)) offset++;
          if (offset <= Math.abs(surplus)) {
            for (let i = 0; i < offset; i++) {
              if (surplus > 0) patches.push({ type: "remove", path: [...path, oldIndex++] });
              else patches.push({ type: "insert", path: [...path, oldIndex], vnode: after[newIndex++] });
            }
          }
        }
        walk(before[oldIndex], after[newIndex], [...path, oldIndex]);
        oldIndex++;
        newIndex++;
      }
      for (let i = oldIndex; i < oldEnd; i++) {
        patches.push({ type: "remove", path: [...path, i] });
      }
      for (let i = newIndex; i < newEnd; i++) {
        // Insert before the unchanged old anchor (or append at the end).
        patches.push({ type: "insert", path: [...path, oldEnd], vnode: after[i] });
      }
      oldStart = oldEnd + 1;
      newStart = newEnd + 1;
    }
  }

  walk(oldVNode, newVNode, []);
  return patches;
}

function sameType(a, b) {
  return typeof a === typeof b && (typeof a === "string" || a.type === b.type);
}

// Longest common subsequence of exact subtrees; no keys or DOM moves.
function matchChildren(before, after) {
  const lengths = Array.from({ length: before.length + 1 },
    () => Array(after.length + 1).fill(0));
  for (let i = before.length - 1; i >= 0; i--) {
    for (let j = after.length - 1; j >= 0; j--) {
      lengths[i][j] = equal(before[i], after[j])
        ? 1 + lengths[i + 1][j + 1]
        : Math.max(lengths[i + 1][j], lengths[i][j + 1]);
    }
  }
  const matches = [];
  let i = 0;
  let j = 0;
  while (i < before.length && j < after.length) {
    if (equal(before[i], after[j])) {
      matches.push([i++, j++]);
    } else if (lengths[i + 1][j] > lengths[i][j + 1]) {
      i++;
    } else {
      // On ties keep the earlier old candidate; equal duplicates match in order.
      j++;
    }
  }
  return matches;
}

function equal(a, b) {
  if (a === b) return true;
  if (typeof a === "string" || typeof b === "string" || a.type !== b.type) return false;
  const names = Object.keys(a.props);
  return names.length === Object.keys(b.props).length &&
    names.every(name => Object.hasOwn(b.props, name) && a.props[name] === b.props[name]) &&
    a.children.length === b.children.length && a.children.every((child, i) => equal(child, b.children[i]));
}
