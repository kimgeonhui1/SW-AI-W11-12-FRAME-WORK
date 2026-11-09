// [components/Toolbar.js] 필터 · 검색 · 일괄 작업 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

/** 필터 버튼 목록: [필터 값, 버튼 이름, 옆에 보여 줄 개수의 stats 키] */
const FILTERS = [["all", "전체", "total"], ["active", "진행 중", "active"], ["done", "완료", "done"]];

/**
 * 필터 버튼 3개 · 검색창 · "완료 항목 지우기" · "예시 3개 추가" 버튼.
 * 지금 필터는 aria-pressed="true" 와 chip-on 클래스로 표시한다 (바뀌면 해당 버튼들만 PROPS 패치).
 *
 * @param {{filter: string, query: string, stats: object,
 *          onFilter: Function, onQuery: Function, onClearDone: Function, onAddBatch: Function}} props
 */
export const Toolbar = stateless(function Toolbar({ filter, query, stats, onFilter, onQuery, onClearDone, onAddBatch }) {
  return h(
    "div",
    { class: "todo-toolbar" },
    h("div", { class: "todo-filters", role: "group", "aria-label": "보기" },
      FILTERS.map(([key, label, countKey]) =>
        h("button", { type: "button", class: key === filter ? "chip chip-on" : "chip", "aria-pressed": String(key === filter), "data-filter": key, onClick: () => onFilter(key) },
          label, h("span", { class: "chip-count" }, String(stats[countKey]))))),
    // 검색창도 제어 컴포넌트: 값은 App 의 query 상태, 글자를 칠 때마다 onQuery
    h("input", { id: "todo-search", type: "search", value: query, placeholder: "검색  ( / )", "aria-label": "할 일 검색", onInput: onQuery }),
    h("div", { class: "todo-actions" },
      // 완료한 항목이 없으면 버튼을 끈다
      h("button", { type: "button", class: "btn", id: "clear-done", disabled: stats.done === 0, onClick: onClearDone }, "완료 항목 지우기"),
      // 배칭 데모 버튼: App 이 setState 를 3번 부르지만 렌더는 1번
      h("button", { type: "button", class: "btn", id: "add-batch", title: "setState 를 3번 부르지만 렌더는 1번", onClick: onAddBatch },
        "예시 3개 추가 ", h("span", { class: "muted-inline" }, "(setState ×3)"))),
  );
});
