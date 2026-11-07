// [tests/helpers.js] 여러 테스트 파일이 같이 쓰는 도우미 함수 (테스트 자체는 없음)

import { assert, assertEqual } from "./runner.js";
import { h, createElement, containerToVdom } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";

/** 루트(가상 div) VNode. containerToVdom 결과와 같은 모양 */
export const root = (...children) => h("div", null, ...children);

/** 루트 VNode 를 실제 컨테이너(div)에 그린다 */
export function render(vroot) {
  const box = document.createElement("div");
  box.append(...vroot.children.map(createElement));
  return box;
}

/** HTML 문자열을 담은 컨테이너 */
export function fromHtml(html) {
  const box = document.createElement("div");
  box.innerHTML = html;
  return box;
}

/**
 * A 를 그린 뒤 patch(diff(A, B)) 를 적용하고, 결과가 B 와 같은지 확인한다.
 * @returns {{box: HTMLElement, patches: object[], touched: Node[]}}
 */
export function roundTrip(oldRoot, newRoot, message = "") {
  const box = render(oldRoot);
  const patches = diff(oldRoot, newRoot);
  const touched = patch(box, patches);
  assertEqual(containerToVdom(box), newRoot, message || "patch 결과 DOM 이 새 VDOM 과 달라요");
  return { box, patches, touched };
}

/** fn 이 예외를 던지는지 확인. 던진 예외를 돌려준다 */
export function assertThrows(fn, ErrorType, message = "예외가 나야 합니다") {
  try {
    fn();
  } catch (err) {
    if (ErrorType) assert(err instanceof ErrorType || err.name === ErrorType.name, `${ErrorType.name} 이어야 함: ${err}`);
    return err;
  }
  throw new Error(message);
}

/**
 * console.warn / console.error 를 잠깐 가로채 기록한다. (의도된 경고가 화면 콘솔을 어지럽히지 않게)
 * @returns {{result: any, warns: any[][], errors: any[][]}}
 */
export function captureConsole(fn) {
  const warns = [];
  const errors = [];
  const { warn, error } = console;
  console.warn = (...args) => warns.push(args);
  console.error = (...args) => errors.push(args);
  try {
    return { result: fn(), warns, errors };
  } finally {
    console.warn = warn;
    console.error = error;
  }
}

/** depth 단계로 중첩된 VNode: <div><div>…"leaf"…</div></div> */
export function deepTree(depth, leaf = "leaf") {
  let node = leaf;
  for (let i = 0; i < depth; i++) node = { type: "div", props: {}, children: [node] };
  return node;
}

/** 재현 가능한 의사 난수 (mulberry32) */
export function makeRandom(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * 무작위 VNode 생성기
 * @param {() => number} rand makeRandom 결과
 * @param {object} [opts]
 *   tags, texts, propNames, propValues: 고를 후보
 *   maxDepth, maxChildren: 크기 제한
 *   voidTags: 자식 없이 만들 태그 (br, img …)
 */
export function makeGenerator(rand, opts = {}) {
  const tags = opts.tags ?? ["div", "span", "section", "b", "i", "em", "ul"];
  const voidTags = opts.voidTags ?? [];
  const texts = opts.texts ?? ["가", "hello", "a b", "끝."];
  const propNames = opts.propNames ?? ["class", "id", "title", "data-x"];
  const propValues = opts.propValues ?? ["a", "b", "c d", ""];
  const maxDepth = opts.maxDepth ?? 4;
  const maxChildren = opts.maxChildren ?? 4;
  const pick = (arr) => arr[Math.floor(rand() * arr.length)];

  function props() {
    const result = {};
    const count = Math.floor(rand() * 3);
    for (let i = 0; i < count; i++) result[pick(propNames)] = pick(propValues);
    return result;
  }

  /** 자식 목록. 문자열이 연달아 나오지 않게 한다 (파싱하면 하나로 합쳐지므로) */
  function children(depth) {
    const list = [];
    const count = depth >= maxDepth ? 0 : Math.floor(rand() * (maxChildren + 1));
    for (let i = 0; i < count; i++) {
      const prevIsText = typeof list[list.length - 1] === "string";
      if (!prevIsText && rand() < 0.35) list.push(pick(texts));
      else list.push(element(depth + 1));
    }
    return list;
  }

  function element(depth = 0) {
    if (voidTags.length && rand() < 0.15) return { type: pick(voidTags), props: props(), children: [] };
    return { type: pick(tags), props: props(), children: children(depth) };
  }

  /** 기존 트리를 조금 바꾼 사본 (텍스트 · 속성 · 추가 · 삭제 · 교체 · 순서) */
  function mutate(node, depth = 0) {
    if (typeof node === "string") return rand() < 0.3 ? pick(texts) : node;
    const copy = { type: node.type, props: { ...node.props }, children: node.children.map((c) => mutate(c, depth + 1)) };
    if (depth > 0 && rand() < 0.1) copy.type = pick(tags);
    // 루트(depth 0)는 컨테이너라 containerToVdom 이 속성을 일부러 무시한다 → 루트 props 는 바꾸지 않는다
    if (depth > 0 && rand() < 0.2) copy.props = props();
    const roll = rand();
    if (voidTags.includes(copy.type)) copy.children = [];
    else if (roll < 0.15) copy.children.push(element(depth + 1));
    else if (roll < 0.3 && copy.children.length) copy.children.splice(Math.floor(rand() * copy.children.length), 1);
    else if (roll < 0.4 && copy.children.length > 1) copy.children.reverse();
    copy.children = mergeAdjacentTexts(copy.children);
    return copy;
  }

  return { element, children, mutate, props, pick, rootOf: (depth = 0) => ({ type: "div", props: {}, children: children(depth) }) };
}

/** 연달아 나온 문자열 자식을 하나로 합친다 (HTML 로 파싱한 결과와 맞추기 위함) */
export function mergeAdjacentTexts(children) {
  const out = [];
  for (const child of children) {
    if (typeof child === "string" && typeof out[out.length - 1] === "string") out[out.length - 1] += child;
    else out.push(child);
  }
  return out;
}

/**
 * iframe 을 화면 밖에 만들고 로드가 끝날 때까지 기다린다.
 * @param {{src?: string, srcdoc?: string}} attrs
 */
export function loadFrame(attrs) {
  return new Promise((resolve, reject) => {
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:absolute; left:-10000px; top:0; width:1100px; height:900px;";
    frame.addEventListener("load", () => resolve(frame), { once: true });
    frame.addEventListener("error", reject, { once: true });
    Object.assign(frame, attrs);
    document.body.append(frame);
  });
}

/** 조건이 참이 될 때까지 기다린다 */
export async function waitFor(check, timeoutMs = 3000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    if (check()) return;
    await new Promise((r) => setTimeout(r, 15));
  }
  throw new Error("시간 안에 조건이 만족되지 않음");
}

/**
 * ../index.html 을 고쳐서 iframe 으로 연다.
 * - removeIds: 지울 요소 id 목록 (필수 요소가 없는 상황 재현)
 * - 페이지 스크립트보다 먼저 console.error / window error 를 기록하는 스크립트를 넣는다
 *   → frame.contentWindow.__errors 로 콘솔 오류를 확인할 수 있다
 * @returns {Promise<{frame: HTMLIFrameElement, win: Window, doc: Document, $: (id: string) => HTMLElement}>}
 */
export async function openIndex({ removeIds = [] } = {}) {
  const pageUrl = new URL("../index.html", location.href);
  const html = await (await fetch(pageUrl, { cache: "no-store" })).text();
  const parsed = new DOMParser().parseFromString(html, "text/html");
  for (const id of removeIds) parsed.getElementById(id)?.remove();

  // srcdoc 페이지에서도 ./src/... 상대 경로가 원래 위치 기준으로 풀리도록 <base> 지정
  const base = parsed.createElement("base");
  base.href = pageUrl.href;
  const spy = parsed.createElement("script");
  spy.textContent = `
    window.__errors = [];
    const original = console.error.bind(console);
    console.error = (...args) => { window.__errors.push(args.map(String).join(" ")); original(...args); };
    window.addEventListener("error", (e) => window.__errors.push("uncaught: " + e.message));
  `;
  parsed.head.prepend(base, spy);

  const frame = await loadFrame({ srcdoc: "<!DOCTYPE html>" + parsed.documentElement.outerHTML });
  const win = frame.contentWindow;
  const doc = frame.contentDocument;
  const $ = (id) => doc.getElementById(id);
  // 모듈 스크립트 실행이 끝날 때까지 (정상 시작이면 #status, 실패면 안내 문단)
  await waitFor(() => ($("status") && $("status").textContent) || doc.querySelector(".startup-error"));
  await new Promise((r) => setTimeout(r, 30));
  return { frame, win, doc, $ };
}
