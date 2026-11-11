// [YutBoard.js] 윷판 (29칸) — Stateless. 칸 위에 팀별 말 묶음(업힌 수), 함정, 누를 수 있는 칸, 고른 말이 갈 수 있는 칸(결과 이름 표시)을 그린다

import { h } from "../../core/vdom.js";
import { NODES, CORNERS, END, nodeName } from "../yut.js";

// 칸 위치 (판 안쪽 영역 기준 %). 바깥은 o0(오른쪽 아래)에서 시계 반대 방향, 지름길은 모서리와 가운데를 잇는 대각선 위
const POS = {};
for (let k = 0; k < 20; k++) {
  const t = (k % 5) * 20;
  POS[`o${k}`] = k < 5 ? [100, 100 - t] : k < 10 ? [100 - t, 0] : k < 15 ? [0, t] : [t, 100];
}
const on = (from, to, f) => [from[0] + (to[0] - from[0]) * f, from[1] + (to[1] - from[1]) * f];
Object.assign(POS, {
  C: [50, 50],
  a1: on([100, 0], [50, 50], 1 / 3), a2: on([100, 0], [50, 50], 2 / 3),
  c1: on([50, 50], [0, 100], 1 / 3), c2: on([50, 50], [0, 100], 2 / 3),
  b1: on([0, 0], [50, 50], 1 / 3), b2: on([0, 0], [50, 50], 2 / 3),
  g1: on([50, 50], [100, 100], 1 / 3), g2: on([50, 50], [100, 100], 2 / 3),
});

// dests: 고른 말이 갈 수 있는 곳 → 그곳으로 가는 결과 이름들 (END = 나기)
export function YutBoard({ state, clickable, chosen, dests, targeting, onNode }) {
  const nodes = NODES.map((pos) => {
    const teams = ["홍", "청"].map((team) => [team, state.pieces[team].filter((p) => p === pos).length]).filter(([, n]) => n > 0);
    const goTo = dests.get(pos); // 고른 말이 이 칸으로 갈 수 있으면 그 결과 이름들
    const canPress = clickable.has(pos) || Boolean(goTo);
    const [x, y] = POS[pos];
    const label = `${nodeName(pos)} ${pos}${teams.map(([t, n]) => ` · ${t} ${n}개`).join("")}${state.traps[pos] ? ` · ${state.traps[pos]} 함정` : ""}`;
    return h(
      "button",
      {
        key: pos,
        className: `node${CORNERS.has(pos) ? " corner" : ""}${clickable.has(pos) ? " can" : ""}${chosen === pos ? " chosen" : ""}${goTo ? " dest" : ""}`,
        "data-node": pos,
        style: { left: `${x}%`, top: `${y}%` },
        disabled: !canPress,
        "aria-label": goTo ? `${label} · 여기로 가기 (${goTo.join(", ")})` : label,
        onClick: () => onNode(pos),
      },
      // 갈 수 있는 칸: 어떤 결과로 오는지 표시 (예: "걸 ▼")
      goTo ? h("span", { className: "dest-tag" }, `${goTo.join("·")} ▼`) : null,
      // 출발 · 도착 칸(o0): 비어 있으면 칸 안에 "출발" (말이 있으면 말이 덮는다)
      pos === "o0" && teams.length === 0 ? h("span", { className: "start-mark" }, "출발") : null,
      // 함정: 놓은 팀만 알아보게 색 표시 (상대도 보이게 둔다: 숨기면 화면 하나로 둘이 하는 게임에서 의미가 없음)
      state.traps[pos] ? h("span", { className: `trap ${state.traps[pos] === "홍" ? "red" : "blue"}`, title: "함정" }, "✕") : null,
      // 말 묶음: 업힌 수가 2개 이상이면 오른쪽 위에 숫자 배지. 방패를 든 팀의 말은 테두리
      teams.map(([team, n]) => h("span", { key: team, className: `token ${team} ${team === "홍" ? "red" : "blue"}${state.shield[team] ? " shielded" : ""}` }, n > 1 ? h("span", { className: "stack" }, `×${n}`) : null))
    );
  });
  return h(
    "div",
    { className: `yut-board${targeting ? " targeting" : ""}` },
    // inner: 칸 위치(%)의 기준 영역. 판 가장자리에 여백을 둬서 모서리 칸이 잘리지 않게
    h(
      "div",
      { className: "inner" },
      // 판의 선: 바깥 네모 + 대각선 두 줄 (SVG)
      h(
        "svg",
        { className: "lines", viewBox: "0 0 100 100", preserveAspectRatio: "none", "aria-hidden": "true" },
        h("rect", { x: "0", y: "0", width: "100", height: "100" }),
        h("line", { x1: "0", y1: "0", x2: "100", y2: "100" }),
        h("line", { x1: "100", y1: "0", x2: "0", y2: "100" })
      ),
      nodes,
      // 고른 말이 날 수 있으면 출발점(o0) 아래에 "나기" 버튼
      dests.has(END) ? h("button", { className: "goal", onClick: () => onNode(END) }, `나기 (${dests.get(END).join("·")})`) : null
    )
  );
}
