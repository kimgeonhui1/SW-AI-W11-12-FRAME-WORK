// [components/Toolbar.js] 필터 · 검색 · 일괄 작업 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

/** 필터 버튼 목록: [필터 값, 버튼 이름, 옆에 보여 줄 개수의 stats 키] */
const FILTERS = [["all", "전체", "total"], ["active", "진행 중", "active"], ["done", "완료", "done"]];

/**
 * 필터 버튼 3개 · 검색창 · 일괄 작업 버튼들.
 * 지금 필터 · 정렬 켜짐은 aria-pressed="true" 와 chip-on 클래스로 표시한다 (바뀌면 해당 버튼들만 PROPS 패치).
 *
 * 일괄 작업
 *   모두 완료 / 모두 해제 : 하나라도 안 끝났으면 전부 완료, 모두 끝났으면 전부 해제 (글자도 상황에 맞게 바뀜)
 *   중요도순 정렬         : 켜면 높음 → 보통 → 낮음 순으로 보여 준다 (저장된 순서는 그대로, 보이는 순서만)
 *   완료 항목 지우기      : 완료한 것이 없으면 꺼짐
 *   되돌리기 (n)          : 목록을 바꾼 직전 상태로 (App 이 최근 20번까지 기억, 없으면 꺼짐)
 *   [예시] 3개 추가       : 배칭 데모 — setState 3번, 렌더 1번
 *   [예시] 처음 목록으로  : 처음 예시 4개로
 *
 * @param {{filter: string, query: string, stats: object, sorted: boolean, undoCount: number,
 *          onFilter: Function, onQuery: Function, onQueryKey: Function, onToggleAll: Function, onSort: Function,
 *          onClearDone: Function, onUndo: Function, onAddBatch: Function, onReset: Function}} props
 */
export const Toolbar = stateless(function Toolbar({ filter, query, stats, sorted, undoCount, onFilter, onQuery, onQueryKey, onToggleAll, onSort, onClearDone, onUndo, onAddBatch, onReset }) {
  const allDone = stats.total > 0 && stats.active === 0;
  return h(
    "div",
    { class: "todo-toolbar" },
    h("div", { class: "todo-filters", role: "group", "aria-label": "보기" },
      FILTERS.map(([key, label, countKey]) =>
        h("button", { type: "button", class: key === filter ? "chip chip-on" : "chip", "aria-pressed": String(key === filter), "data-filter": key, onClick: () => onFilter(key) },
          label, h("span", { class: "chip-count" }, String(stats[countKey]))))),
    // 검색창도 제어 컴포넌트: 값은 App 의 query 상태, 글자를 칠 때마다 onQuery, Esc 는 onQueryKey 가 검색어를 지운다
    h("input", { id: "todo-search", type: "search", value: query, placeholder: "검색  ( / ,  Esc 지우기)", "aria-label": "할 일 검색", onInput: onQuery, onKeyDown: onQueryKey }),
    // 일괄 작업: "편집" · "예시" 두 묶음으로 나눠 보여 준다 (작은 이름표 + 작은 버튼)
    h("div", { class: "todo-actions", role: "group", "aria-label": "편집" },
      h("span", { class: "todo-actions-label" }, "편집"),
      h("button", { type: "button", class: "btn", id: "toggle-all", disabled: stats.total === 0, onClick: onToggleAll }, allDone ? "모두 해제" : "모두 완료"),
      h("button", { type: "button", class: sorted ? "btn chip-on" : "btn", id: "sort-prio", "aria-pressed": String(sorted), onClick: onSort }, "중요도순"),
      // 완료한 항목이 없으면 버튼을 끈다
      h("button", { type: "button", class: "btn", id: "clear-done", disabled: stats.done === 0, onClick: onClearDone }, "완료 항목 지우기"),
      // 되돌릴 기록이 없으면 끈다. 괄호 안 숫자 = 되돌릴 수 있는 횟수
      h("button", { type: "button", class: "btn", id: "undo-todos", disabled: undoCount === 0, onClick: onUndo }, `되돌리기 (${undoCount})`)),
    h("div", { class: "todo-actions", role: "group", "aria-label": "예시" },
      h("span", { class: "todo-actions-label" }, "예시"),
      // 배칭 데모 버튼: App 이 setState 를 3번 부르지만 렌더는 1번
      h("button", { type: "button", class: "btn", id: "add-batch", title: "setState 를 3번 부르지만 렌더는 1번", onClick: onAddBatch },
        "3개 추가 ", h("span", { class: "muted-inline" }, "(setState ×3)")),
      h("button", { type: "button", class: "btn", id: "reset-todos", onClick: onReset }, "처음 목록으로")),
  );
});
