// [TodoList.js] 할 일 목록 — Stateless. 보여 줄 목록은 App이 필터링해서 넘긴다

import { h } from "../../core/vdom.js";
import { TodoItem } from "./TodoItem.js";

export function TodoList({ todos, onToggle, onRemove }) {
  if (todos.length === 0) return h("p", { className: "empty" }, "표시할 할 일이 없습니다.");
  return h(
    "ul",
    { className: "todo-list" },
    // key: 항목을 지우거나 순서가 바뀌어도 같은 할 일은 같은 DOM 노드를 쓴다 (체크·포커스 상태가 다른 항목으로 넘어가지 않음)
    todos.map((todo) => h(TodoItem, { key: todo.id, todo, onToggle, onRemove }))
  );
}
