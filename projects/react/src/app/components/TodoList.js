// [TodoList.js] 할 일 목록 — Stateless. 보여 줄 목록은 App이 필터링해서 넘긴다

import { h } from "../../core/vdom.js";
import { TodoItem } from "./TodoItem.js";

export function TodoList({ todos, onToggle, onRemove }) {
  if (todos.length === 0) return h("p", { className: "empty" }, "표시할 할 일이 없습니다.");
  return h(
    "ul",
    { className: "todo-list" },
    todos.map((todo) => h(TodoItem, { todo, onToggle, onRemove }))
  );
}
