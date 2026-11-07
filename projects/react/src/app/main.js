// [app/main.js] Phase 2 페이지 시작점 — App 컴포넌트를 #root에 마운트
// 다시 렌더될 때마다 바뀐 노드를 잠깐 강조한다. Element.animate() 는 속성 · 클래스를 남기지 않아 다음 Diff 에 영향이 없다.

import { FunctionComponent } from "../core/component.js";
import { App } from "./App.js";

const rootEl = document.getElementById("root");

/** 마운트된 App (테스트에서 렌더 횟수 · hooks 를 확인할 때 쓴다) */
export const app = rootEl ? new FunctionComponent(App, rootEl) : null;

if (app) {
  app.onCommit(({ reason, touched }) => {
    if (reason === "mount") return;
    for (const node of touched) {
      const el = node.nodeType === 3 ? node.parentElement : node; // 텍스트 노드면 감싸는 요소
      el?.animate?.(
        [{ boxShadow: "0 0 0 2px rgba(37, 99, 235, 0.75)", backgroundColor: "rgba(37, 99, 235, 0.14)" }, { boxShadow: "0 0 0 2px rgba(37, 99, 235, 0)", backgroundColor: "rgba(37, 99, 235, 0)" }],
        { duration: 700, easing: "ease-out" },
      );
    }
  });
  app.mount();
} else {
  console.error("[app] #root 요소가 없어 앱을 시작할 수 없습니다.");
}
