// [components/TodoForm.js] 새 할 일 입력 (상태 없음 — 입력값도 부모의 상태를 props 로 받음: 제어 컴포넌트)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

/**
 * 입력창의 글자(draft)와 중요도(priority)는 App 의 상태다.
 * 글자를 칠 때마다 onDraft → App 의 setDraft → 다시 렌더 → input 의 value 가 그 값으로 맞춰진다.
 * 추가하면 App 이 draft 를 "" 로 바꾸므로 입력창이 비워진다 (setProp 의 value 프로퍼티 동기화 덕분).
 *
 * @param {{draft: string, priority: string, priorities: object,
 *          onDraft: Function, onPriority: Function, onSubmit: Function}} props
 */
export const TodoForm = stateless(function TodoForm({ draft, priority, priorities, onDraft, onPriority, onSubmit }) {
  return h(
    "form",
    { class: "todo-form", onSubmit, "aria-label": "할 일 추가" }, // Enter 를 눌러도 submit 이 일어난다
    h("input", { id: "todo-input", type: "text", value: draft, placeholder: "할 일을 입력하고 Enter", autocomplete: "off", maxlength: "80", "aria-label": "새 할 일", onInput: onDraft }),
    // 선택된 중요도는 option 의 selected 로 표시한다 (값이 바뀌면 selected 속성 PROPS 패치)
    h("select", { id: "todo-priority", "aria-label": "중요도", onChange: onPriority },
      Object.entries(priorities).map(([value, label]) => h("option", { value, selected: value === priority }, `중요도 ${label}`))),
    // 빈 칸 · 공백만 있으면 버튼을 끈다 (App 의 addTodo 도 한 번 더 막는다)
    h("button", { type: "submit", class: "btn btn--primary", disabled: draft.trim() === "" }, "추가"),
  );
});
