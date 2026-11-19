// [app/main.js] Phase 2 페이지 시작점 — App 컴포넌트를 #root에 마운트

import { FunctionComponent } from "../core/component.js";
import { App } from "./App.js";

new FunctionComponent(App, document.getElementById("root")).mount();
