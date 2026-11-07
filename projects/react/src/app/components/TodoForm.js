// [components/TodoForm.js] 새 할 일 입력 (상태 없음 — 입력값도 부모의 상태를 props 로 받음: 제어 컴포넌트)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

/**
 * 입력창 글자(draft) · 중요도(priority)는 App 의 상태다. 글자를 칠 때마다 onDraft → setDraft → 다시 렌더 → input 값이 맞춰진다.
 * 추가하면 App 이 draft 를 "" 로 바꿔 입력창이 비워진다 (setProp 의 value 프로퍼티 동기화 덕분).
 */
export const TodoForm = stateless(function TodoForm({ draft, priority, priorities, onDraft, onPriority, onSubmit }) {
  return h(
    "form",
    { class: "todo-form", onSubmit, "aria-label": "할 일 추가" },
    h("input", { id: "todo-input", type: "text", value: draft, placeholder: "할 일을 입력하고 Enter", autocomplete: "off", maxlength: "80", "aria-label": "새 할 일", onInput: onDraft }),
    h("select", { id: "todo-priority", "aria-label": "중요도", onChange: onPriority },
      Object.entries(priorities).map(([value, label]) => h("option", { value, selected: value === priority }, `중요도 ${label}`))),
    h("button", { type: "submit", class: "btn btn--primary", disabled: draft.trim() === "" }, "추가"),
  );
});
