// [TeamPanel.js] 팀 한 쪽: 출발 전 · 난 말 수, 출발 전 말 올리기, 초능력 2개(쓰기 버튼), 방패 · 발 묶임 표시 — Stateless

import { h } from "../../core/vdom.js";
import { POWERS, HOME, END } from "../yut.js";

export function TeamPanel({ team, state, canEnter, entering, targeting, onEnter, onArm, onMal }) {
  const pieces = state.pieces[team];
  const home = pieces.filter((p) => p === HOME).length;
  const done = pieces.filter((p) => p === END).length;
  const power = state.powers[team];
  const myTurn = state.turn === team && !state.winner;
  // 초능력은 내 차례 처음, 던지기 전에만
  const beforeThrow = myTurn && state.phase === "throw" && state.pending.length === 0;
  const color = team === "홍" ? "red" : "blue";
  const powerRow = (kind, id, used, onUse, label) =>
    h(
      "div",
      { className: `power${used ? " used" : ""}` },
      h("div", null, h("small", null, kind), h("strong", null, POWERS[id].name), h("p", null, POWERS[id].desc)),
      h("button", { disabled: used || !beforeThrow || (kind === "윷의 힘" && Boolean(state.armed)), onClick: onUse }, used ? "씀" : label)
    );
  return h(
    "section",
    // 차례가 아닌 팀은 흐리게 (끝난 판은 둘 다 그대로)
    { className: `team ${team} team-${color}${myTurn ? " active" : state.winner ? "" : " waiting"}` },
    h(
      "header",
      null,
      h("span", { className: `token ${color}` }),
      h("strong", null, `${team}팀`),
      myTurn ? h("span", { className: "turn-badge" }, "내 차례") : null,
      state.shield[team] ? h("span", { className: "badge" }, "방패") : null,
      state.skip[team] ? h("span", { className: "badge warn" }, "발 묶임") : null,
      h("span", { className: "count" }, `난 말 ${done} / 4`)
    ),
    // 출발 전 말: 누르면 고른 말이 되고, 판에 들어갈 수 있는 칸이 표시된다
    h(
      "button",
      {
        className: `home-pile${canEnter ? " can" : ""}${entering ? " chosen" : ""}`,
        disabled: !canEnter,
        "aria-pressed": String(Boolean(entering)),
        onClick: onEnter,
        "aria-label": `${team} 출발 전 말 ${home}개${canEnter ? " · 눌러서 고르기" : ""}`,
      },
      Array.from({ length: home }, (_, i) => h("span", { key: i, className: `token ${color}` })),
      h("span", null, home > 0 ? `출발 전 ${home}개` : "출발 전 말 없음")
    ),
    power
      ? [
          powerRow("윷의 힘", power.yut, power.yutUsed, onArm, "켜기"),
          powerRow("말의 힘", power.mal, power.malUsed, onMal, targeting ? "대상 고르는 중" : "쓰기"),
        ]
      : null
  );
}
