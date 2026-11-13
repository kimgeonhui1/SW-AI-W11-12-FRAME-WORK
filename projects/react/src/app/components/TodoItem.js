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
 * 수정 중인 줄: 입력창 + 저장 · 취소 버튼.
 * 입력값(editText)도 App 의 상태다 (제어 컴포넌트). Enter = 저장, Esc = 취소.
 * 입력창에 포커스를 주는 일은 App 의 useEffect 가 한다 (렌더 함수는 DOM 을 직접 만지지 않는다).
 */
function editingRow({ todo, editText, onEditText, onEditKey, onEditSave, onEditCancel }) {
  return h(
    "li",
    { class: "todo-item editing", "data-id": String(todo.id), "data-priority": todo.priority },
    h("input", { class: "todo-edit", type: "text", value: editText, maxlength: "80", "aria-label": "할 일 내용 수정", onInput: onEditText, onKeyDown: onEditKey }),
    h("button", { type: "button", class: "icon-btn todo-save", onClick: onEditSave }, "저장"),
    h("button", { type: "button", class: "icon-btn todo-cancel", onClick: onEditCancel }, "취소"),
  );
}

/**
 * 할 일 한 줄: 체크박스 · 내용 · 중요도 · 위/아래 · 수정 · 삭제.
 * 무엇을 눌러도 스스로 바꾸지 않고, 부모(App)가 준 콜백에 id 만 넘긴다 (Lifting State Up).
 *   - 내용을 더블클릭하거나 "수정" → onEditStart(id) → App 이 이 줄을 수정 모드(editingRow)로 그린다
 *   - 중요도 배지 클릭 → onCycle(id): 높음 → 보통 → 낮음 → 높음 … (PROPS 패치 + 글자 TEXT 패치)
 *   - ↑ / ↓ → onMove(id, -1 | +1): 이웃과 자리를 바꾼다. key 없이 순서로 비교하므로
 *     "두 줄의 내용이 바뀐 것" 으로 패치된다 (TEXT · PROPS). 맨 위/아래 · 정렬 중이면 버튼이 꺼진다
 *
 * @param {{todo: {id: number, text: string, done: boolean, priority: string}, query: string, priorities: object,
 *          editing: boolean, editText: string, canUp: boolean, canDown: boolean,
 *          onToggle: Function, onRemove: Function, onCycle: Function, onMove: Function, onEditStart: Function,
 *          onEditText: Function, onEditKey: Function, onEditSave: Function, onEditCancel: Function}} props
 */
export const TodoItem = stateless(function TodoItem(props) {
  const { todo, query, priorities, canUp, canDown, onToggle, onRemove, onCycle, onMove, onEditStart } = props;
  if (props.editing) return editingRow(props);
  return h(
    "li",
    { class: todo.done ? "todo-item done" : "todo-item", "data-id": String(todo.id), "data-priority": todo.priority },
    // label 은 체크박스만 감싼다 → 글자를 더블클릭(수정)해도 체크가 두 번 바뀌지 않는다
    h("label", { class: "todo-check" },
      // checked 는 true/false 로 항상 넘긴다 → 체크 해제도 PROPS 패치(checked: false)로 반영된다
      h("input", { type: "checkbox", checked: todo.done, "aria-label": `"${todo.text}" 완료`, onChange: () => onToggle(todo.id) })),
    h("span", { class: "todo-text", title: "더블클릭해서 수정", onDblClick: () => onEditStart(todo.id) }, highlight(todo.text, query)),
    h("button", { type: "button", class: `prio prio-${todo.priority}`, title: "눌러서 중요도 바꾸기", "aria-label": `중요도 ${priorities[todo.priority]}, 눌러서 바꾸기`, onClick: () => onCycle(todo.id) },
      priorities[todo.priority]),
    h("button", { type: "button", class: "icon-btn todo-up", "aria-label": "위로", disabled: !canUp, onClick: () => onMove(todo.id, -1) }, "↑"),
    h("button", { type: "button", class: "icon-btn todo-down", "aria-label": "아래로", disabled: !canDown, onClick: () => onMove(todo.id, 1) }, "↓"),
    h("button", { type: "button", class: "icon-btn todo-edit-btn", onClick: () => onEditStart(todo.id) }, "수정"),
    h("button", { type: "button", class: "icon-btn todo-remove", "aria-label": `"${todo.text}" 삭제`, onClick: () => onRemove(todo.id) }, "삭제"),
  );
});
