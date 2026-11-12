// [PowerPick.js] 게임 시작 때 팀마다 초능력 고르기: 윷의 힘 후보 2개 중 1개, 말의 힘 후보 2개 중 1개 — Stateless

import { h } from "../../core/vdom.js";
import { POWERS } from "../yut.js";

export function PowerPick({ team, offers, selected, onSelect, onConfirm }) {
  const group = (kind, title, ids) =>
    h(
      "section",
      { className: "pick-group" },
      h("h3", null, title),
      h(
        "div",
        { className: "choices" },
        ids.map((id) =>
          h(
            "button",
            { key: id, className: `power-card${selected[kind] === id ? " picked" : ""}`, "aria-pressed": String(selected[kind] === id), onClick: () => onSelect(kind, id) },
            h("strong", null, POWERS[id].name),
            h("span", null, POWERS[id].desc)
          )
        )
      )
    );
  return h(
    "div",
    { className: `power-pick team-${team === "홍" ? "red" : "blue"}` },
    h("h2", null, `${team}팀 초능력 고르기`),
    h("p", { className: "hint" }, "내 차례에 윷을 던지기 전에 각각 한 번씩 쓸 수 있습니다. 상대에게는 고른 것이 보입니다."),
    group("yut", "윷의 힘 (윷 결과를 바꿈)", offers.yut),
    group("mal", "말의 힘 (판 위의 말을 움직임)", offers.mal),
    h("button", { className: "primary", disabled: !selected.yut || !selected.mal, onClick: onConfirm }, "이걸로 시작")
  );
}
