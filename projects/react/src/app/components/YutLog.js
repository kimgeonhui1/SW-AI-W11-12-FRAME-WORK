// [YutLog.js] 기보: 누가 무엇을 던지고 어디로 갔는지, 잡기 · 초능력 · 함정 — Stateless

import { h } from "../../core/vdom.js";

export function YutLog({ log, logRef }) {
  return h(
    "section",
    { className: "yut-log" },
    h("h2", null, "기보"),
    log.length === 0
      ? h("p", { className: "empty" }, "아직 기록이 없습니다.")
      : // key: 줄 번호. 새 줄이 붙어도 이전 줄들은 같은 DOM 노드를 그대로 쓴다
        h("ol", { ref: logRef }, log.map((line, i) => h("li", { key: i }, line)))
  );
}
