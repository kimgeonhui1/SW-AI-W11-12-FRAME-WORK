// [components/TodoItem.js] 할 일 한 줄 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

/**
 * 검색어와 맞는 부분을 <mark> 로 감싼 조각 목록 (대소문자 무시)
 * 예) ("useState 설명", "state") → ["use", <mark>State</mark>, " 설명"]
 */
function highlight(text, query) {
  if (!query) return [text];
  const lower = text.toLowerCase();
  const needle = query.toLowerCase();
  const parts = [];
  let from = 0;
  for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, from)) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(h("mark", null, text.slice(at, at + needle.length)));
    from = at + needle.length;
  }
  if (from < text.length) parts.push(text.slice(from));
  return parts;
}

/**
 * @param {{todo: {id: number, text: string, done: boolean, priority: string}, query: string,
 *          priorities: object, onToggle: (id: number) => void, onRemove: (id: number) => void}} props
 */
export const TodoItem = stateless(function TodoItem({ todo, query, priorities, onToggle, onRemove }) {
  return h(
    "li",
    { class: todo.done ? "todo-item done" : "todo-item", "data-id": String(todo.id), "data-priority": todo.priority },
    h(
      "label",
      { class: "todo-check" },
      // checked 는 true/false 로 항상 넘긴다 → 체크 해제도 PROPS 패치(set checked:false)로 반영
      h("input", { type: "checkbox", checked: todo.done, onChange: () => onToggle(todo.id) }),
      h("span", { class: "todo-text" }, highlight(todo.text, query)),
    ),
    h("span", { class: `prio prio-${todo.priority}` }, priorities[todo.priority]),
    h("button", { type: "button", class: "icon-btn", "aria-label": `"${todo.text}" 삭제`, onClick: () => onRemove(todo.id) }, "삭제"),
  );
});
