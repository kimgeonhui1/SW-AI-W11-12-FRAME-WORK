// [patch.js] Diff 결과(변경 목록)를 실제 DOM에 반영
import { createElement } from "./vdom.js";

// Match domToVdom: comments and other unsupported nodes do not occupy VDOM slots.
function children(node) {
  return Array.from(node.childNodes).filter(child => child.nodeType === 1 || child.nodeType === 3);
}

export function patch(container, patches) {
  const root = children(container)[0] ?? null;
  // Resolve every old-tree address before any mutation shifts child indexes.
  const operations = patches.map(change => {
    let parent = container;
    let index = 0;
    if (change.path.length) {
      parent = root;
      for (const part of change.path.slice(0, -1)) {
        parent = parent && children(parent)[part];
      }
      index = change.path.at(-1);
    }
    if (!parent || !Number.isInteger(index) || index < 0) throw new Error("Invalid patch path");
    const siblings = children(parent);
    const target = siblings[index] ?? null;
    if (!target && (change.type !== "insert" || index !== siblings.length)) {
      throw new Error("Patch path does not match DOM");
    }
    if (!["insert", "remove", "replace", "text", "props"].includes(change.type) ||
        (change.type === "text" && target.nodeType !== 3) ||
        (change.type === "props" && target.nodeType !== 1)) {
      throw new Error("Patch type does not match DOM");
    }
    const created = change.type === "insert" || change.type === "replace"
      ? createElement(change.vnode) : null;
    return { change, parent, target, created };
  });

  for (const { change, parent, target, created } of operations) {
    switch (change.type) {
      case "insert": parent.insertBefore(created, target); break;
      case "remove": parent.removeChild(target); break;
      case "replace": parent.replaceChild(created, target); break;
      case "text": target.data = change.value; break;
      case "props":
        for (const name of change.remove) target.removeAttribute(name);
        for (const [name, value] of Object.entries(change.set)) target.setAttribute(name, value);
        break;
    }
  }
  return children(container)[0] ?? null;
}
