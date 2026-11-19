// [VictoryDialog.js] 승리 팝업 — Stateless. 트로피와 "○팀 승리!"가 커지며 나타나고, 뒤로 팀 색 색종이가 떨어진다
//   - 열고 닫는 State는 부모(App)가 가진다. 닫으면 끝난 판을 그대로 볼 수 있다
//   - Esc · 바깥 누르기 = 판 보기(닫기). Tab은 팝업 안에서만 돈다 (ConfirmDialog와 같은 규칙)

import { h } from "../../core/vdom.js";
import { keepFocusInside } from "./ConfirmDialog.js";

const PIECES = 36; // 색종이 수
// 색종이 위치 · 속도는 번호로 정한다 (Math.random을 쓰면 다시 렌더링될 때마다 위치가 바뀌어 diff가 매번 style을 고친다)
const confetti = Array.from({ length: PIECES }, (_, i) => ({
  left: `${(i * 37) % 100}%`,
  delay: `${((i * 7) % 12) * 0.12}s`,
  duration: `${2.4 + (i % 5) * 0.35}s`,
  kind: ["team", "gold", "white"][i % 3],
  shape: i % 2 ? "strip" : "square",
}));

export function VictoryDialog({ team, turnNo, focusRef, onRestart, onClose }) {
  const color = team === "홍" ? "red" : "blue";
  return h(
    "div",
    { className: `modal-backdrop victory team-${color}`, onClick: (e) => e.target === e.currentTarget && onClose() },
    h(
      "div",
      { className: "confetti", "aria-hidden": "true" },
      confetti.map((c, i) =>
        h("span", { key: i, className: `${c.kind} ${c.shape}`, style: { left: c.left, animationDelay: c.delay, animationDuration: c.duration } })
      )
    ),
    h(
      "div",
      {
        className: "modal victory-card",
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "victory-title",
        onKeyDown: (e) => (e.key === "Escape" ? onClose() : keepFocusInside(e)),
      },
      h("div", { className: "trophy", "aria-hidden": "true" }, "🏆"),
      h("h2", { id: "victory-title" }, `${team}팀 승리!`),
      h("p", null, `말 4개를 모두 먼저 냈습니다 · ${turnNo}턴`),
      h(
        "div",
        { className: "modal-actions" },
        h("button", { onClick: onClose }, "판 보기"),
        // 기본 포커스는 새 게임 (끝난 판에서 Enter를 누르면 바로 다음 판)
        h("button", { ref: focusRef, className: "primary", onClick: onRestart }, "새 게임")
      )
    )
  );
}
