// [FilterBar.js] 필터 버튼 + 남은 개수 — Stateless

import { h } from "../../core/vdom.js";

const FILTERS = [
  ["all", "전체"],
  ["active", "진행 중"],
  ["done", "완료"],
];

export function FilterBar({ filter, counts, onFilterChange, onClearDone }) {
  return h(
    "div",
    { className: "filter-bar" },
    h("span", { className: "stats" }, `남은 일 ${counts.active}개 / 전체 ${counts.all}개`),
    h(
      "div",
      { className: "filters" },
      FILTERS.map(([value, label]) =>
        h("button", { className: filter === value ? "selected" : "", onClick: () => onFilterChange(value) }, label)
      )
    ),
    h("button", { className: "clear", disabled: counts.done === 0, onClick: onClearDone }, "완료 항목 삭제")
  );
}
