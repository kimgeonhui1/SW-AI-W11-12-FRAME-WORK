// [app/main.js] Phase 2 페이지 시작점 — App 컴포넌트를 #root에 마운트

/**
 * 1. App(루트 컴포넌트)을 감싼 FunctionComponent 를 만든다 (아직 그리지 않음)
 * 2. App 이 다시 렌더될 때마다(onCommit) 바뀐 노드를 잠깐 강조하도록 구독한다
 *    Element.animate() 는 속성 · 클래스를 남기지 않으므로 다음 Diff 에 영향이 없다 (Phase 1 과 같은 방식)
 * 3. App 을 #root 에 마운트한다 → 이후로는 setState 가 알아서 다시 렌더를 예약한다
 */

import { FunctionComponent } from "../core/component.js";
import { App } from "./App.js";

const rootEl = document.getElementById("root");

/** 마운트된 App (페이지 테스트가 렌더 횟수 · hooks 를 확인할 때 import 해서 쓴다) */
export const app = rootEl ? new FunctionComponent(App, rootEl) : null;

if (app) {
  app.onCommit(({ reason, touched }) => {
    if (reason === "mount") return; // 처음 그릴 때는 전부 새것이라 강조하지 않는다
    for (const node of touched) {
      const el = node.nodeType === 3 ? node.parentElement : node; // 텍스트 노드는 스타일을 줄 수 없으니 감싸는 요소를
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
