// [TodoForm.js] 할 일 입력 폼 — Stateless. 입력값과 동작은 모두 부모(App)가 props로 준다

import { h } from "../../core/vdom.js";

export function TodoForm({ text, onTextChange, onAdd }) {
  return h(
    "form",
    {
      className: "todo-form",
      onSubmit: (e) => {
        // form 기본 동작(페이지 새로고침)을 막고 App의 추가 함수만 실행한다
        e.preventDefault();
        onAdd();
      },
    },
    // 제어 컴포넌트: 화면 값은 항상 App의 text State. 입력할 때마다 State를 바꿔 다시 그린다
    h("input", { value: text, placeholder: "할 일을 입력하세요", onInput: (e) => onTextChange(e.target.value) }),
    h("button", { type: "submit", disabled: text.trim() === "" }, "추가")
  );
}
