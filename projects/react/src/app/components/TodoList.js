// [components/TodoList.js] 할 일 목록 · 빈 상태 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";
import { TodoItem } from "./TodoItem.js";

/**
 * 보일 항목(items)이 있으면 <ul> 목록, 없으면 상황에 맞는 안내 문구를 그린다.
 *   - 할 일이 하나도 없음(isEmpty)      → 첫 할 일을 추가하라는 안내
 *   - 검색어가 있는데 맞는 것이 없음    → 검색어를 넣어 안내
 *   - 필터(진행 중 · 완료)에 해당 없음  → 이 보기에 없다는 안내
 * 목록은 key 없이 순서(인덱스)로 비교되므로, 앞쪽 항목을 지우면 뒤 항목들이 한 칸씩 바뀐 것으로 나온다 (한계).
 *
 * @param {{items: object[], query: string, isEmpty: boolean, priorities: object,
 *          onToggle: Function, onRemove: Function}} props
 */
export const TodoList = stateless(function TodoList({ items, query, isEmpty, priorities, onToggle, onRemove }) {
  if (items.length === 0) {
    const message = isEmpty
      ? "할 일이 없습니다. 위 입력창에서 첫 할 일을 추가하세요."
      : query ? `"${query}" 와 맞는 할 일이 없습니다.` : "이 보기에 해당하는 할 일이 없습니다.";
    return h("p", { class: "todo-empty", role: "status" }, message);
  }
  // 자식 컴포넌트 안에서 또 자식 컴포넌트를 부를 수 있다 (둘 다 상태 없음)
  return h("ul", { class: "todo-list", "aria-label": "할 일 목록" }, items.map((todo) => TodoItem({ todo, query, priorities, onToggle, onRemove })));
});
