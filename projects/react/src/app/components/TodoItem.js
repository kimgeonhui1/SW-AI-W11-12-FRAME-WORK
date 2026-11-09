// [components/TodoItem.js] 할 일 한 줄 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

/**
 * 검색어와 맞는 부분을 <mark> 로 감싼 조각 목록을 만든다 (대소문자 무시, 여러 번 나와도 모두).
 *   예) ("useState 설명", "state") → ["use", <mark>State</mark>, " 설명"]
 * 조각 배열은 h() 가 자식으로 평탄화해 준다.
 *
 * @param {string} text 할 일 내용
 * @param {string} query 검색어 (비어 있으면 원래 글자 그대로)
 * @returns {Array<string|object>}
 */
function highlight(text, query) {
  if (!query) return [text];
  const lower = text.toLowerCase();
  const needle = query.toLowerCase();
  const parts = [];
  let from = 0; // 아직 조각으로 옮기지 않은 위치
  for (let at = lower.indexOf(needle); at !== -1; at = lower.indexOf(needle, from)) {
    if (at > from) parts.push(text.slice(from, at)); //                    맞는 부분 앞의 글자
    parts.push(h("mark", null, text.slice(at, at + needle.length))); //     맞는 부분 (원래 대소문자 그대로)
    from = at + needle.length;
  }
  if (from < text.length) parts.push(text.slice(from)); // 남은 뒷부분
  return parts;
}

/**
 * 할 일 한 줄: 체크박스 · 내용 · 중요도 · 삭제 버튼.
 * 체크나 삭제를 해도 스스로 바꾸지 않고, 부모(App)가 준 콜백에 id 만 넘긴다 (Lifting State Up).
 *
 * @param {{todo: {id: number, text: string, done: boolean, priority: string}, query: string,
 *          priorities: object, onToggle: (id: number) => void, onRemove: (id: number) => void}} props
 */
export const TodoItem = stateless(function TodoItem({ todo, query, priorities, onToggle, onRemove }) {
  return h(
    "li",
    { class: todo.done ? "todo-item done" : "todo-item", "data-id": String(todo.id), "data-priority": todo.priority },
    h("label", { class: "todo-check" },
      // checked 는 true/false 로 항상 넘긴다 → 체크 해제도 PROPS 패치(checked: false)로 반영된다
      h("input", { type: "checkbox", checked: todo.done, onChange: () => onToggle(todo.id) }),
      h("span", { class: "todo-text" }, highlight(todo.text, query))),
    h("span", { class: `prio prio-${todo.priority}` }, priorities[todo.priority]),
    h("button", { type: "button", class: "icon-btn", "aria-label": `"${todo.text}" 삭제`, onClick: () => onRemove(todo.id) }, "삭제"),
  );
});
