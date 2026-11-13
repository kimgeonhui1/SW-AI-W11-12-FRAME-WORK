// [components/Header.js] 제목 · 진행률 · 개수 (상태 없음 — props 만 사용)

import { h } from "../../core/vdom.js";
import { stateless } from "../../core/component.js";

/**
 * 개수 하나: <div><dt>이름</dt><dd data-stat="키">값</dd></div>
 * data-stat 은 페이지 테스트가 숫자를 찾을 때 쓴다.
 */
const stat = (label, value, key) => h("div", null, h("dt", null, label), h("dd", { "data-stat": key }, String(value)));

/**
 * 머리말. App 이 useMemo 로 계산한 통계(stats)를 받아 그리기만 한다.
 * @param {{stats: {total: number, done: number, active: number, percent: number}}} props
 */
export const Header = stateless(function Header({ stats }) {
  return h(
    "header",
    { class: "todo-header" },
    h("div", { class: "todo-heading" },
      h("h1", null, "오늘의 할 일"),
      h("p", { class: "todo-sub" }, "미니 React로 만든 할 일 보드 — 상태가 바뀌면 바뀐 노드만 다시 그립니다.")),
    // 진행 막대: 완료율이 바뀌면 aria-valuenow 와 style(width) 두 속성만 PROPS 패치로 바뀐다
    h("div", { class: "todo-progress", role: "progressbar", "aria-label": "완료율", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(stats.percent) },
      h("span", { class: "todo-progress-bar", style: `width: ${stats.percent}%` })),
    h("dl", { class: "todo-stats" },
      stat("전체", stats.total, "total"), stat("남음", stats.active, "active"),
      stat("완료", stats.done, "done"), stat("완료율", `${stats.percent}%`, "percent")),
  );
});
