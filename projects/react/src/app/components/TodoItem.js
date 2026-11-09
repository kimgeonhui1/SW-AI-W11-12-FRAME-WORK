// [TodoItem.js] 할 일 한 줄 — Stateless. 체크/삭제는 부모가 준 함수를 부르기만 한다

import { h } from "../../core/vdom.js";

export function TodoItem({ todo, onToggle, onRemove }) {
  return h(
    "li",
    { className: todo.done ? "todo done" : "todo" },
    h("label", null, h("input", { type: "checkbox", checked: todo.done, onChange: () => onToggle(todo.id) }), " ", todo.text),
    h("button", { className: "remove", title: "삭제", onClick: () => onRemove(todo.id) }, "×")
  );
}
