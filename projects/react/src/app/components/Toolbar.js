// [components/Toolbar.js] 필터 · 검색 · 일괄 작업 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

const FILTERS = [["all", "전체", "total"], ["active", "진행 중", "active"], ["done", "완료", "done"]]; // [값, 이름, 개수 키]

export const Toolbar = stateless(function Toolbar({ filter, query, stats, onFilter, onQuery, onClearDone, onAddBatch }) {
  return h(
    "div",
    { class: "todo-toolbar" },
    h("div", { class: "todo-filters", role: "group", "aria-label": "보기" },
      FILTERS.map(([key, label, countKey]) =>
        h("button", { type: "button", class: key === filter ? "chip chip-on" : "chip", "aria-pressed": String(key === filter), "data-filter": key, onClick: () => onFilter(key) },
          label, h("span", { class: "chip-count" }, String(stats[countKey]))))),
    h("input", { id: "todo-search", type: "search", value: query, placeholder: "검색  ( / )", "aria-label": "할 일 검색", onInput: onQuery }),
    h("div", { class: "todo-actions" },
      h("button", { type: "button", class: "btn", id: "clear-done", disabled: stats.done === 0, onClick: onClearDone }, "완료 항목 지우기"),
      h("button", { type: "button", class: "btn", id: "add-batch", title: "setState 를 3번 부르지만 렌더는 1번", onClick: onAddBatch },
        "예시 3개 추가 ", h("span", { class: "muted-inline" }, "(setState ×3)"))),
  );
});
