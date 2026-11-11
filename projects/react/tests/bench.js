// [bench.js] 성능 측정 — "바뀐 곳만 고치기(diff + patch)"가 통째로 다시 그리기보다 얼마나 일을 덜 하는지 숫자로 본다
//
// 잰 것 두 가지
//   1) 시간: 같은 화면 변경을 세 방법으로 반영하고 레이아웃까지 끝난 시간 (중앙값)
//        diff + patch           : 이 프로젝트의 방식
//        createElement 통째로   : VDOM은 쓰지만 diff 없이 매번 새로 만들어 교체
//        innerHTML 통째로       : VDOM 없이 HTML 문자열로 교체
//   2) DOM 작업량: MutationObserver가 본 실제 DOM 변경을 셋으로 나눔
//        생성: 새로 만든 노드 수 (자손 포함) / 이동: 자리만 옮긴 노드 수 / 수정: 바뀐 속성 · 글자 수
//      → 시간은 기기마다 다르지만 작업량은 어디서 재도 같다

import { h, createElement } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import { FunctionComponent } from "../src/core/component.js";
import { useState } from "../src/core/hooks.js";
import { App } from "../src/app/App.js";

const N = 1000; // 목록 길이
const RUNS = 25; // 방법마다 반복 횟수 (중앙값 사용)
const tick = () => new Promise((r) => setTimeout(r));
const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];

// 목록 한 줄: <li key><span>이름</span><b>점수</b><button>삭제</button></li>
const rows = (n) => Array.from({ length: n }, (_, i) => ({ id: i, name: `항목 ${i}`, score: i % 100 }));
const view = (data, keyed = true) =>
  h("ul", { className: "list" }, data.map((r) => h("li", keyed ? { key: r.id, className: "row" } : { className: "row" }, h("span", null, r.name), h("b", null, String(r.score)), h("button", null, "삭제"))));
const html = (data) => `<ul class="list">${data.map((r) => `<li class="row"><span>${r.name}</span><b>${r.score}</b><button>삭제</button></li>`).join("")}</ul>`;

// MutationObserver 기록 → { 생성, 이동, 수정 }. 뺐다가 다시 넣은 노드는 "이동"(insertBefore로 옮기면 삭제 + 추가로 기록됨)
const subtreeSize = (node) => { let n = 0; const w = document.createTreeWalker(node); do n++; while (w.nextNode()); return n; };
function summarize(records) {
  const added = new Set(), removed = new Set();
  let edited = 0;
  for (const r of records) {
    if (r.type !== "childList") { edited++; continue; }
    r.addedNodes.forEach((n) => added.add(n));
    r.removedNodes.forEach((n) => removed.add(n));
  }
  const moved = [...added].filter((n) => removed.has(n)).length;
  const created = [...added].filter((n) => !removed.has(n)).reduce((sum, n) => sum + subtreeSize(n), 0);
  return { created, moved, edited };
}
function countMutations(root, fn) {
  const mo = new MutationObserver(() => {});
  mo.observe(root, { subtree: true, childList: true, attributes: true, characterData: true });
  fn();
  const records = mo.takeRecords();
  mo.disconnect();
  return summarize(records);
}

// 시나리오: before 화면에서 after 화면으로 바꾸기. 방법별 시간(ms, 중앙값)과 DOM 변경 수
function scenario(name, before, after, { keyed = true } = {}) {
  const box = document.createElement("div");
  document.body.appendChild(box);
  const oldV = view(before, keyed);
  const newV = view(after, keyed);
  const methods = {
    "diff + patch": () => patch(box, diff(oldV, newV)),
    "createElement 통째로": () => box.replaceChildren(createElement(newV)),
    "innerHTML 통째로": () => (box.innerHTML = html(after)),
  };
  const result = { name, ms: {}, mutations: {} };
  for (const [m, run] of Object.entries(methods)) {
    const times = [];
    for (let i = 0; i < RUNS; i++) {
      box.replaceChildren(createElement(oldV));
      void box.offsetHeight; // 시작 전 레이아웃을 끝내 둔다
      const t0 = performance.now();
      run();
      void box.offsetHeight; // 레이아웃까지 포함 (화면에 보이기까지 드는 일)
      times.push(performance.now() - t0);
    }
    box.replaceChildren(createElement(oldV));
    result.ms[m] = median(times);
    result.mutations[m] = countMutations(box, run);
  }
  box.remove();
  return result;
}

const base = rows(N);
const results = [
  scenario(`${N}줄 중 1줄 글자 바꾸기`, base, base.map((r, i) => (i === 500 ? { ...r, name: "바뀐 항목" } : r))),
  scenario(`${N}줄 끝에 1줄 추가`, base, [...base, { id: N, name: `항목 ${N}`, score: 0 }]),
  scenario(`${N}줄 중 2줄 자리 바꾸기 (key)`, base, base.map((r, i) => (i === 1 ? base[998] : i === 998 ? base[1] : r))),
  scenario(`${N}줄 맨 앞에 1줄 추가 (key 있음)`, base, [{ id: -1, name: "새 항목", score: 0 }, ...base]),
  scenario(`${N}줄 맨 앞에 1줄 추가 (key 없음)`, base, [{ id: -1, name: "새 항목", score: 0 }, ...base], { keyed: false }),
];

// 입력 중인 값 · 포커스 유지: 사용자가 입력창에 타이핑하는 중에 다른 곳이 바뀌면?
function keepsInput(method) {
  const box = document.createElement("div");
  document.body.appendChild(box);
  const v = (label) => h("div", null, h("p", null, label), h("input", { id: "bench-input" }));
  const oldV = v("이전");
  box.replaceChildren(createElement(oldV));
  const input = box.querySelector("input");
  input.focus();
  input.value = "입력 중";
  if (method === "diff + patch") patch(box, diff(oldV, v("다음")));
  else if (method === "createElement 통째로") box.replaceChildren(createElement(v("다음")));
  else box.innerHTML = `<div><p>다음</p><input id="bench-input"></div>`;
  const now = box.querySelector("input");
  const ok = document.activeElement === now && now.value === "입력 중";
  box.remove();
  return ok;
}
const inputKept = Object.fromEntries(["diff + patch", "createElement 통째로", "innerHTML 통째로"].map((m) => [m, keepsInput(m)]));

// Batching: 클릭 한 번에 setState 100번 → 렌더링은 몇 번?
let renders = 0;
let bump;
function Counter() {
  renders++;
  const [n, setN] = useState(0);
  bump = () => { for (let i = 0; i < 100; i++) setN((x) => x + 1); };
  return h("p", null, String(n));
}
const cBox = document.createElement("div");
document.body.appendChild(cBox);
const counter = new FunctionComponent(Counter, cBox).mount();
renders = 0;
bump();
await tick();
const batching = { setState: 100, renders, value: cBox.textContent };
counter.unmount();
cBox.remove();

// 실제 앱(윷놀이): 말 하나를 옮길 때 바뀌는 DOM 수 / 전체 요소 수
const random = (() => { const v = [0, 0, 0, 0.9]; let i = 0; return () => v[i++ % v.length]; })(); // 늘 걸
const aBox = document.createElement("div");
document.body.appendChild(aBox);
const app = new FunctionComponent(App, aBox, { random }).mount();
const button = (t) => [...aBox.querySelectorAll("button")].find((b) => b.textContent.includes(t));
for (let k = 0; k < 2; k++) {
  for (const g of aBox.querySelectorAll(".power-pick .choices")) g.querySelector("button").click();
  await tick();
  button("이걸로 시작").click();
  await tick();
}
button("윷 던지기").click();
await tick();
aBox.querySelector(".team.홍 .home-pile").click();
await tick();
// 렌더링 한 번(App 실행 + diff + patch)에 걸린 시간을 재려고 update를 감싼다
let appMs = 0;
const update = app.update.bind(app);
app.update = () => { const t0 = performance.now(); update(); appMs = performance.now() - t0; };
// 렌더링이 비동기라 기록이 콜백으로 먼저 넘어간다 → 콜백에서 모아 둔다
const appRecords = [];
const mo = new MutationObserver((rs) => appRecords.push(...rs));
mo.observe(aBox, { subtree: true, childList: true, attributes: true, characterData: true });
const elements = aBox.querySelectorAll("*").length;
aBox.querySelector(".node.dest").click(); // 고른 말이 갈 수 있는 칸
await tick();
const appResult = { elements, ...summarize([...appRecords, ...mo.takeRecords()]), ms: appMs, log: aBox.querySelector(".yut-log li:last-child").textContent };
mo.disconnect();
app.unmount();
aBox.remove();

// ── 출력 ──
const fmt = (x) => x.toFixed(2);
const methods = ["diff + patch", "createElement 통째로", "innerHTML 통째로"];
document.getElementById("results").innerHTML = `
  <p>${navigator.userAgent}</p>
  <table>
    <tr><th>시나리오</th>${methods.map((m) => `<th>${m}<br>ms · 생성 / 이동 / 수정</th>`).join("")}</tr>
    ${results.map((r) => `<tr><td>${r.name}</td>${methods.map((m) => { const c = r.mutations[m]; return `<td>${fmt(r.ms[m])} ms · ${c.created} / ${c.moved} / ${c.edited}</td>`; }).join("")}</tr>`).join("")}
    <tr><td>입력 중인 값 · 포커스 유지</td>${methods.map((m) => `<td>${inputKept[m] ? "유지" : "사라짐"}</td>`).join("")}</tr>
  </table>
  <p>Batching: setState ${batching.setState}번 → 렌더링 ${batching.renders}번 (값 ${batching.value})</p>
  <p>윷놀이 말 1개 옮기기 (${appResult.log}): 전체 요소 ${appResult.elements}개 · 생성 ${appResult.created} / 이동 ${appResult.moved} / 수정 ${appResult.edited}, 렌더링 ${fmt(appResult.ms)} ms (App 실행 + diff + patch)</p>`;
window.benchResult = { results, inputKept, batching, app: appResult };
console.log(JSON.stringify(window.benchResult, null, 2));
