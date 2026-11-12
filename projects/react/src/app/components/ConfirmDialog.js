// [ConfirmDialog.js] 확인 팝업 (예: 새 게임) — Stateless. 열고 닫는 State는 부모(App)가 가진다
//   - 바깥(어두운 배경)을 누르거나 Esc를 누르면 취소
//   - Tab은 팝업 안의 버튼 사이에서만 돈다 (뒤쪽 페이지로 포커스가 빠져나가지 않게)

import { h } from "../../core/vdom.js";

// Tab 키를 팝업 안의 버튼 사이에서만 돌게 한다 (승리 팝업도 같이 쓴다)
export function keepFocusInside(e) {
  if (e.key !== "Tab") return;
  const buttons = e.currentTarget.querySelectorAll("button");
  const first = buttons[0];
  const last = buttons[buttons.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

export function ConfirmDialog({ message, confirmLabel, cancelRef, onConfirm, onCancel }) {
  const onKeyDown = (e) => (e.key === "Escape" ? onCancel() : keepFocusInside(e));
  return h(
    "div",
    // 배경 자체를 눌렀을 때만 닫는다 (팝업 안을 누른 클릭이 배경까지 올라온 경우는 무시)
    { className: "modal-backdrop", onClick: (e) => e.target === e.currentTarget && onCancel() },
    h(
      "div",
      // 제목 없이 문장 하나만: 화면 낭독기는 그 문장을 팝업 이름으로 읽는다
      { className: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "modal-message", onKeyDown },
      h("p", { id: "modal-message" }, message),
      h(
        "div",
        { className: "modal-actions" },
        // 기본 포커스는 취소 (Enter를 실수로 눌러도 판이 지워지지 않게)
        h("button", { ref: cancelRef, onClick: onCancel }, "취소"),
        h("button", { className: "danger", onClick: onConfirm }, confirmLabel)
      )
    )
  );
}
