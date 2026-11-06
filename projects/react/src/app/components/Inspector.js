// [components/Inspector.js] 렌더 관찰 패널 — App 이 화면에 반영될 때마다 무엇이 바뀌었는지 보여 준다

/**
 * 이 패널도 미니 React 로 만든 "또 하나의 루트 컴포넌트" 다. (App 의 자식이 아님)
 * 그래서 자기 상태(useState)를 가질 수 있다. App 과는 별도의 FunctionComponent 로 #inspector 에 마운트된다.
 *
 *   App 렌더 → App 의 onCommit 구독자 호출 → 이 패널의 setLog(…) → 패널 다시 렌더 (패널 자신의 Diff/Patch)
 *
 * props
 *   target   : 관찰할 FunctionComponent (App)
 *   settings : { highlight: boolean } — main.js 의 강조 효과가 읽는 설정 객체
 */

import { h } from "../../core/vdom.js";
import { useState, useEffect, useMemo } from "../../core/hooks.js";
import { stateless } from "../../core/component.js";

const MAX_LOG = 8; //     최근 렌더 기록 개수
const MAX_PATCHES = 30; // 패치 목록에 보여 줄 최대 개수
const TYPES = ["CREATE", "REMOVE", "REPLACE", "TEXT", "PROPS"];

/** 값을 한 줄로 짧게 */
function preview(value, max = 70) {
  let text;
  if (typeof value === "function") text = "ƒ()";
  else {
    try {
      text = JSON.stringify(value) ?? String(value);
    } catch {
      text = String(value);
    }
  }
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** 패치 하나를 사람이 읽을 수 있게 */
function describePatch(p) {
  const path = `[${p.path.join(",")}]`;
  switch (p.type) {
    case "CREATE":
      return `${path} 의 ${p.index}번째에 추가`;
    case "TEXT":
      return `${path} → ${preview(p.value, 40)}`;
    case "PROPS": {
      const set = Object.keys(p.set).join(", ");
      const remove = p.remove.join(", ");
      return `${path} ${set ? `설정 ${set}` : ""}${set && remove ? " · " : ""}${remove ? `삭제 ${remove}` : ""}`;
    }
    case "REPLACE":
      return `${path} → <${typeof p.node === "string" ? "텍스트" : p.node.type}>`;
    default:
      return path;
  }
}

/** commit 정보 → 패널에 필요한 것만 (DOM 노드 참조는 담지 않는다) */
function summarize(info) {
  const patches = info.patches ?? [];
  const counts = Object.fromEntries(TYPES.map((t) => [t, 0]));
  for (const p of patches) counts[p.type] += 1;
  return {
    renderCount: info.renderCount,
    reason: info.reason,
    ms: info.ms,
    created: info.reason === "mount" ? info.touched.length : 0,
    total: patches.length,
    counts,
    patches: patches.slice(0, MAX_PATCHES).map((p) => ({ type: p.type, text: describePatch(p) })),
    hooks: info.component.hooks.map((hook, i) => ({
      index: i,
      kind: hook.kind,
      value:
        hook.kind === "state" ? preview(hook.value)
        : hook.kind === "memo" ? preview(hook.value)
        : `deps ${preview(hook.deps)}`,
    })),
  };
}

const PatchList = stateless(function PatchList({ entry }) {
  if (entry.reason === "mount") {
    return h("p", { class: "insp-note" }, `처음 렌더링: 최상위 노드 ${entry.created}개를 createElement 로 만들었습니다.`);
  }
  if (entry.total === 0) return h("p", { class: "insp-note" }, "바뀐 것이 없습니다.");
  return h(
    "ol",
    { class: "insp-patches" },
    entry.patches.map((p) => h("li", null, h("span", { class: `ptag ptag-${p.type.toLowerCase()}` }, p.type), " ", p.text)),
    entry.total > entry.patches.length ? h("li", { class: "insp-note" }, `… 외 ${entry.total - entry.patches.length}개`) : null,
  );
});

const HookTable = stateless(function HookTable({ hooks }) {
  return h(
    "table",
    { class: "insp-hooks" },
    h("thead", null, h("tr", null, h("th", null, "#"), h("th", null, "Hook"), h("th", null, "저장된 값"))),
    h(
      "tbody",
      null,
      hooks.map((hook) =>
        h(
          "tr",
          null,
          h("td", null, String(hook.index)),
          h("td", null, h("code", null, `use${hook.kind[0].toUpperCase()}${hook.kind.slice(1)}`)),
          h("td", null, h("code", null, hook.value)),
        ),
      ),
    ),
  );
});

export function Inspector({ target, settings }) {
  const [log, setLog] = useState([]); //          최근 렌더 기록 (최신이 앞)
  const [highlightOn, setHighlightOn] = useState(settings.highlight);

  // App 의 commit 을 구독. 정리 함수(구독 해제)를 돌려주므로 패널이 사라지면 구독도 끝난다.
  useEffect(() => target.onCommit((info) => setLog((prev) => [summarize(info), ...prev].slice(0, MAX_LOG))), [target]);

  // 강조 설정을 main.js 와 공유하는 객체에 반영
  useEffect(() => {
    settings.highlight = highlightOn;
  }, [highlightOn]);

  const latest = log[0];
  const totals = useMemo(() => log.reduce((sum, entry) => sum + entry.total, 0), [log]);

  if (!latest) return h("p", { class: "insp-note" }, "App 이 렌더되기를 기다리는 중…");

  return h(
    "section",
    { class: "insp", "aria-label": "렌더 관찰" },
    h(
      "div",
      { class: "insp-head" },
      h("h2", null, "렌더 관찰"),
      h(
        "button",
        { type: "button", class: "btn btn--small", id: "toggle-highlight", "aria-pressed": String(highlightOn), onClick: () => setHighlightOn((on) => !on) },
        highlightOn ? "강조 켜짐" : "강조 꺼짐",
      ),
    ),
    h(
      "dl",
      { class: "insp-summary" },
      h("div", null, h("dt", null, "렌더 횟수"), h("dd", { id: "render-count" }, String(latest.renderCount))),
      h("div", null, h("dt", null, "이번 패치"), h("dd", { id: "patch-count" }, String(latest.total))),
      h("div", null, h("dt", null, "걸린 시간"), h("dd", null, `${latest.ms.toFixed(1)}ms`)),
    ),
    h(
      "div",
      { class: "insp-types" },
      TYPES.map((type) =>
        h("span", { class: latest.counts[type] ? `ptag ptag-${type.toLowerCase()}` : "ptag ptag-off" }, `${type} ${latest.counts[type]}`),
      ),
    ),
    h("h3", null, latest.reason === "mount" ? "처음 렌더링 (mount)" : `${latest.renderCount}번째 렌더의 패치`),
    PatchList({ entry: latest }),
    h("h3", null, "App 의 hooks 배열"),
    HookTable({ hooks: latest.hooks }),
    h("h3", null, "최근 렌더"),
    h(
      "ol",
      { class: "insp-log", reversed: true },
      log.map((entry) =>
        h("li", null, `#${entry.renderCount} · ${entry.reason === "mount" ? "mount" : `패치 ${entry.total}개`} · ${entry.ms.toFixed(1)}ms`),
      ),
    ),
    h("p", { class: "insp-note" }, `최근 ${log.length}번 렌더의 패치 합계 ${totals}개. 이 패널도 미니 React 루트 컴포넌트입니다.`),
  );
}
