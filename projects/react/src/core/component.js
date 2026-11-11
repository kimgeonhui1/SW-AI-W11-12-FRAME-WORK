// [component.js] 함수형 컴포넌트를 감싸 상태 저장(hooks)과 렌더링(mount/update)을 담당
import { diff } from "./diff.js";
import { patch } from "./patch.js";
import { renderWithHooks, flushEffects } from "./hooks.js";

export class FunctionComponent {
  constructor(component, container) {
    this.hooks = [];
    this.component = component;
    this.container = container;
    this.vdom = null;
    this.mounted = false;
    this.busy = false;
    this.pendingUpdate = false;
  }
  // 처음 렌더링
  mount() {
    if (this.mounted) throw new Error("Component is already mounted");
    if (this.container.childNodes.length) throw new Error("Mount requires an empty container");
    this.update();
  }
  // 상태 변경 후 다시 렌더링 (새 Virtual DOM → Diff → Patch)
  update() {
    if (this.busy) {
      this.pendingUpdate = true;
      return;
    }
    this.busy = true;
    try {
      let renders = 0;
      do {
        if (++renders > 25) throw new Error("Too many effect-driven updates");
        this.pendingUpdate = false;
        const next = renderWithHooks(this, this.component);
        patch(this.container, diff(this.vdom, next));
        this.vdom = next;
        this.mounted = true;
        flushEffects(this);
      } while (this.pendingUpdate);
    } finally {
      this.busy = false;
      this.pendingUpdate = false;
    }
  }
}
