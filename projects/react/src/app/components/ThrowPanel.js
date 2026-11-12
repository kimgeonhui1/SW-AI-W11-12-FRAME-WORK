// [ThrowPanel.js] 윷 던지기: 막대 4개(던질 때마다 튀어 오르는 애니메이션) · 결과 · 아직 안 쓴 결과들 · 던지기 버튼 — Stateless

import { h } from "../../core/vdom.js";

export function ThrowPanel({ state, onThrow, onChoose }) {
  const { phase, pending, lastThrow, choices, throwSeq } = state;
  return h(
    "section",
    // 던지기 버튼을 지금 차례 팀 색으로 (누가 던질 차례인지 버튼만 봐도 알게)
    { className: `throw-panel team-${state.turn === "홍" ? "red" : "blue"}` },
    h(
      "div",
      { className: "throw-result" },
      // key = 던진 횟수: 던질 때마다 막대 묶음이 새로 만들어져서 CSS 애니메이션이 처음부터 다시 돈다
      // (key가 같으면 diff가 같은 노드를 재사용해서 애니메이션이 다시 시작되지 않는다)
      // 막대: 평평한 면(배)은 밝게, 둥근 면(등)은 어둡게. 1번 막대의 뒷표시(빽도 표시)는 점
      h(
        "div",
        { key: throwSeq, className: `sticks${lastThrow ? " toss" : ""}`, "aria-hidden": "true" },
        (lastThrow?.flats ?? [false, false, false, false]).map((flat, i) => h("span", { key: i, className: `stick${flat ? " flat" : ""}${i === 0 ? " marked" : ""}` }))
      ),
      h("strong", { key: `name-${throwSeq}`, className: `name${lastThrow ? " pop" : ""}` }, lastThrow ? lastThrow.name : "—")
    ),
    phase === "choose"
      ? h(
          "div",
          { className: "choose" },
          h("p", null, "두 번 던진 결과 중 하나를 고르세요"),
          choices.map((c, i) => h("button", { key: i, className: "primary", onClick: () => onChoose(i) }, c))
        )
      : null,
    // 아직 안 쓴 결과들 (말을 고르면 판에 결과마다 갈 곳이 표시된다)
    pending.length > 0
      ? h("div", { className: "pending" }, h("span", null, "남은 결과"), pending.map((name, i) => h("span", { key: i, className: "chip" }, name)))
      : null,
    h("button", { className: "primary throw", disabled: phase !== "throw", onClick: onThrow }, `${state.turn}팀 윷 던지기${state.throwsLeft > 1 ? ` (${state.throwsLeft}번)` : ""}`)
  );
}
