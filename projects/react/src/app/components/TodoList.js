// [components/TodoList.js] 할 일 목록 · 빈 상태 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";
import { TodoItem } from "./TodoItem.js";

/**
 * @param {{items: object[], query: string, isEmpty: boolean, priorities: object,
 *          onToggle: Function, onRemove: Function}} props
 */
export const TodoList = stateless(function TodoList({ items, query, isEmpty, priorities, onToggle, onRemove }) {
  if (items.length === 0) {
    const message = isEmpty
      ? "할 일이 없습니다. 위 입력창에서 첫 할 일을 추가하세요."
      : query
        ? `"${query}" 와 맞는 할 일이 없습니다.`
        : "이 보기에 해당하는 할 일이 없습니다.";
    return h("p", { class: "todo-empty", role: "status" }, message);
  }
  return h(
    "ul",
    { class: "todo-list", "aria-label": "할 일 목록" },
    items.map((todo) => TodoItem({ todo, query, priorities, onToggle, onRemove })),
  );
});
