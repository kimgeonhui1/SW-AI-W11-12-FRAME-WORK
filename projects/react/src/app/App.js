// [App.js] 루트 컴포넌트 — 앱의 모든 상태(State)를 가지고 자식에게 props로 전달
import { h } from "../core/vdom.js";
import { useState, useEffect, useMemo } from "../core/hooks.js";

export function App() {
  const [count, setCount] = useState(0);
  const [label, setLabel] = useState("A");
  const doubled = useMemo(() => count * 2, [count]);

  // Keep HTML-only VDOM props unchanged; delegate events from the stable root.
  useEffect(() => {
    const root = document.querySelector("#root");
    const onClick = event => {
      const action = event.target.closest("button[data-action]")?.dataset.action;
      if (action === "increment") setCount(previous => previous + 1);
      if (action === "same") setCount(previous => previous);
      if (action === "label") setLabel(previous => previous === "A" ? "B" : "A");
    };
    root.addEventListener("click", onClick);
    return () => root.removeEventListener("click", onClick);
  }, []);

  useEffect(() => {
    // This output lives outside #root, so effects do not mutate managed VDOM.
    const status = document.querySelector("#effect-status");
    const log = document.querySelector("#effect-log");
    const record = message => {
      const item = document.createElement("li");
      item.textContent = message;
      log.appendChild(item);
    };
    status.textContent = `카운트 ${count} 반영 완료`;
    record(`Effect: ${count}`);
    return () => record(`Cleanup: ${count}`);
  }, [count]);

  return h("section", {},
    h("h1", {}, "Mini React — State / Effect / Memo"),
    h("p", {}, "카운트: ", h("span", { id: "count" }, String(count))),
    h("p", {}, "두 배 (Memo): ", h("span", { id: "doubled" }, String(doubled))),
    h("p", {}, "별도 표시 상태: ", h("span", { id: "label" }, label)),
    h("button", { type: "button", "data-action": "increment" }, "+1"),
    h("button", { type: "button", "data-action": "same" }, "같은 값 설정"),
    h("button", { type: "button", "data-action": "label" }, "표시 A/B 전환"),
    h("p", {}, "표시만 전환하면 카운트 의존 Memo는 캐시를 사용하고 Effect 기록은 늘지 않습니다.")
  );
}
