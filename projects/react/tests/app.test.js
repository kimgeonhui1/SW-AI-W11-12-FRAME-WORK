// [tests/app.test.js] Phase 2 기능 테스트 — 실제 app.html 을 iframe 으로 열어 사용자처럼 조작한다
//
// localStorage 는 iframe(srcdoc)과 이 테스트 페이지가 같은 출처라 공유된다 → 테스트마다 저장 값을 지우고 시작.

import { describe, test, assert, assertEqual } from "./runner.js";
import { loadFrame, waitFor } from "./helpers.js";

const STORAGE_KEY = "mini-react:todos";
/** 테스트 전에 저장돼 있던 값 (같은 주소에서 앱을 쓰던 목록을 지우지 않도록 마지막에 되돌린다) */
const ORIGINAL_STORAGE = localStorage.getItem(STORAGE_KEY);
function restoreStorage() {
  if (ORIGINAL_STORAGE === null) localStorage.removeItem(STORAGE_KEY);
  else localStorage.setItem(STORAGE_KEY, ORIGINAL_STORAGE);
}

/** 렌더 예약(마이크로태스크)과 강조 애니메이션 시작까지 기다림 */
const settle = () => new Promise((resolve) => setTimeout(resolve, 10));

/**
 * ../app.html 을 iframe 으로 연다.
 * @param {{storage?: string|null}} [options] storage: 시작 전에 localStorage 에 넣을 값 (null 이면 지움)
 */
async function openApp({ storage = null } = {}) {
  if (storage === null) localStorage.removeItem(STORAGE_KEY);
  else localStorage.setItem(STORAGE_KEY, storage);

  const pageUrl = new URL("../app.html", location.href);
  const html = await (await fetch(pageUrl, { cache: "no-store" })).text();
  const parsed = new DOMParser().parseFromString(html, "text/html");
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
  await waitFor(() => doc.getElementById("render-count"));
  return tools(frame, win, doc);
}

/** 페이지를 읽고 조작하는 도우미 */
function tools(frame, win, doc) {
  const $ = (sel) => doc.querySelector(sel);
  const $$ = (sel) => [...doc.querySelectorAll(sel)];
  return {
    frame, win, doc, $, $$,
    texts: () => $$(".todo-text").map((el) => el.textContent),
    renders: () => Number($("#render-count").textContent),
    patches: () => Number($("#patch-count").textContent),
    stat: (key) => $(`[data-stat="${key}"]`).textContent,
    /** 입력창에 글자를 넣고 input 이벤트 (사용자 타이핑) */
    async type(sel, text) {
      const input = $(sel);
      input.value = text;
      input.dispatchEvent(new win.Event("input", { bubbles: true }));
      await settle();
    },
    /** 새 할 일 추가 (타이핑 → 추가 버튼) */
    async add(text) {
      await this.type("#todo-input", text);
      $(".todo-form button[type=submit]").click();
      await settle();
    },
    async click(sel) {
      (typeof sel === "string" ? $(sel) : sel).click();
      await settle();
    },
    item: (text) => $$(".todo-item").find((li) => li.querySelector(".todo-text").textContent === text),
    errors: () => win.__errors,
    close: () => frame.remove(),
  };
}

describe("Phase 2 페이지 · 할 일 보드", () => {
  test("처음: 예시 4개, 렌더 1번, App 의 hooks 10개(state 5 · memo 2 · effect 3), 문서 제목", async () => {
    const t = await openApp();
    assertEqual(t.texts().length, 4);
    assertEqual(t.renders(), 1);
    assertEqual(t.$$(".insp-hooks tbody tr").length, 10);
    assertEqual(t.stat("active"), "3");
    assertEqual(t.doc.title, "할 일 3개 남음 · 미니 React");
    t.close();
  });

  test("추가: 목록 끝에 생기고 입력창이 비워짐, 기존 항목 노드는 그대로 (CREATE)", async () => {
    const t = await openApp();
    const firstLi = t.$(".todo-item");
    await t.add("새 할 일");
    assertEqual(t.texts().at(-1), "새 할 일");
    assertEqual(t.$("#todo-input").value, "");
    assert(t.$(".todo-item") === firstLi, "첫 항목은 같은 요소여야 함");
    assert(t.$$(".insp-patches li").some((li) => li.textContent.includes("CREATE")), "패치 목록에 CREATE");
    assertEqual(t.stat("total"), "5");
    t.close();
  });

  test("추가는 setState 2번(목록 · 입력창)이지만 렌더는 1번", async () => {
    const t = await openApp();
    await t.type("#todo-input", "x");
    const before = t.renders();
    t.$(".todo-form button[type=submit]").click();
    await settle();
    assertEqual(t.renders() - before, 1);
    t.close();
  });

  test("빈 칸 · 공백만 입력하면 추가 버튼이 꺼지고, 제출해도 추가되지 않음", async () => {
    const t = await openApp();
    await t.type("#todo-input", "   ");
    assert(t.$(".todo-form button[type=submit]").disabled);
    t.$(".todo-form").dispatchEvent(new t.win.Event("submit", { bubbles: true, cancelable: true }));
    await settle();
    assertEqual(t.texts().length, 4);
    t.close();
  });

  test("중요도를 고르고 추가하면 그 중요도로 표시", async () => {
    const t = await openApp();
    const select = t.$("#todo-priority");
    select.value = "high";
    select.dispatchEvent(new t.win.Event("change", { bubbles: true }));
    await settle();
    await t.add("급한 일");
    assertEqual(t.item("급한 일").dataset.priority, "high");
    assertEqual(t.$("#todo-priority").value, "high", "선택이 유지되어야 함");
    t.close();
  });

  test("체크 → 완료 표시 · 통계 갱신, 같은 li 요소 재사용, 다시 체크 해제", async () => {
    const t = await openApp();
    const li = t.item("발표 자료 만들기");
    await t.click(li.querySelector("input"));
    assert(li.classList.contains("done") && li.isConnected, "같은 요소에 done");
    assert(li.querySelector("input").checked);
    assertEqual(t.stat("done"), "2");
    assert(t.$$(".insp-patches li").some((x) => x.textContent.includes("PROPS")), "PROPS 패치");
    await t.click(li.querySelector("input"));
    assert(!li.classList.contains("done") && !li.querySelector("input").checked);
    assertEqual(t.stat("done"), "1");
    t.close();
  });

  test("삭제 → 그 항목만 사라짐", async () => {
    const t = await openApp();
    await t.click(t.item("발표 자료 만들기").querySelector(".icon-btn"));
    assertEqual(t.texts(), ["Virtual DOM 과 Diff 복습하기", "useState 가 상태를 기억하는 원리 설명하기", "useEffect 정리(cleanup) 함수 테스트"]);
    t.close();
  });

  test("필터: 진행 중 · 완료 · 전체, 누른 버튼만 aria-pressed=true", async () => {
    const t = await openApp();
    await t.click('[data-filter="active"]');
    assertEqual(t.texts().length, 3);
    assertEqual(t.$('[data-filter="active"]').getAttribute("aria-pressed"), "true");
    await t.click('[data-filter="done"]');
    assertEqual(t.texts(), ["Virtual DOM 과 Diff 복습하기"]);
    assertEqual(t.$('[data-filter="active"]').getAttribute("aria-pressed"), "false");
    await t.click('[data-filter="all"]');
    assertEqual(t.texts().length, 4);
    t.close();
  });

  test("검색: 대소문자 무시, 맞는 부분을 <mark> 로, 없으면 안내 문구", async () => {
    const t = await openApp();
    await t.type("#todo-search", "USESTATE");
    assertEqual(t.texts(), ["useState 가 상태를 기억하는 원리 설명하기"]);
    assertEqual(t.$(".todo-text mark").textContent, "useState");
    await t.type("#todo-search", "없는 말");
    assert(t.$(".todo-empty").textContent.includes("없는 말"));
    await t.type("#todo-search", "");
    assertEqual(t.texts().length, 4);
    t.close();
  });

  test("검색과 필터를 함께", async () => {
    const t = await openApp();
    await t.click('[data-filter="done"]');
    await t.type("#todo-search", "use");
    assert(t.$(".todo-empty"), "완료 중에는 use 가 든 항목이 없음");
    t.close();
  });

  test("완료 항목 지우기: 완료만 사라지고, 완료가 없으면 버튼이 꺼짐", async () => {
    const t = await openApp();
    assert(!t.$("#clear-done").disabled);
    await t.click("#clear-done");
    assertEqual(t.texts().length, 3);
    assert(t.$("#clear-done").disabled);
    t.close();
  });

  test("배칭 버튼: setState 3번 → 항목 3개 추가, 렌더는 1번", async () => {
    const t = await openApp();
    const before = t.renders();
    await t.click("#add-batch");
    assertEqual(t.texts().slice(-3), ["장보기", "운동 30분", "책 20쪽 읽기"]);
    assertEqual(t.renders() - before, 1);
    t.close();
  });

  test("모두 지우면 빈 상태 안내", async () => {
    const t = await openApp({ storage: "[]" });
    assert(t.$(".todo-empty").textContent.includes("첫 할 일"));
    assertEqual(t.doc.title, "모두 완료 · 미니 React");
    t.close();
  });

  test("새로고침해도 목록 유지 (useEffect 로 localStorage 저장)", async () => {
    const t = await openApp();
    await t.add("저장될 일");
    const reloaded = new Promise((resolve) => t.frame.addEventListener("load", resolve, { once: true }));
    t.win.location.reload();
    await reloaded;
    const t2 = tools(t.frame, t.frame.contentWindow, t.frame.contentDocument);
    await waitFor(() => t2.doc.getElementById("render-count"));
    assert(t2.texts().includes("저장될 일"), `목록: ${t2.texts()}`);
    t.close();
  });

  test("저장 값이 망가졌으면 예시 목록으로 시작 (JSON 오류 · 모양 오류)", async () => {
    for (const bad of ["{망가짐", '[{"id":"x"}]', '{"a":1}']) {
      const t = await openApp({ storage: bad });
      assertEqual(t.texts().length, 4, bad);
      t.close();
    }
  });

  test('"/" 를 누르면 검색창으로, 입력창 안에서 친 "/" 는 그대로', async () => {
    const t = await openApp();
    t.win.dispatchEvent(new t.win.KeyboardEvent("keydown", { key: "/", bubbles: true, cancelable: true }));
    assert(t.doc.activeElement === t.$("#todo-search"), "검색창에 포커스");
    const input = t.$("#todo-input");
    input.focus();
    const event = new t.win.KeyboardEvent("keydown", { key: "/", bubbles: true, cancelable: true });
    input.dispatchEvent(event);
    assert(!event.defaultPrevented && t.doc.activeElement === input);
    t.close();
  });

  test("글자를 칠 때마다 렌더되지만 입력창 요소 · 값 · 포커스는 유지", async () => {
    const t = await openApp();
    const input = t.$("#todo-input");
    input.focus();
    for (const text of ["가", "가나", "가나다"]) await t.type("#todo-input", text);
    assert(t.$("#todo-input") === input && input.value === "가나다" && t.doc.activeElement === input);
    t.close();
  });

  test("렌더 관찰 패널: 강조 버튼 켜기 · 끄기, hooks 표에 최신 상태", async () => {
    const t = await openApp();
    assertEqual(t.$("#toggle-highlight").getAttribute("aria-pressed"), "true");
    await t.click("#toggle-highlight");
    assertEqual(t.$("#toggle-highlight").getAttribute("aria-pressed"), "false");
    await t.type("#todo-search", "검색어");
    assert(t.$$(".insp-hooks td").some((td) => td.textContent === '"검색어"'), "query 상태가 표에 보여야 함");
    t.close();
  });

  test("강조 효과는 실제 DOM 에 속성 · 클래스를 남기지 않음", async () => {
    const t = await openApp();
    const snapshot = () => t.$("#root").innerHTML;
    await t.click(t.item("발표 자료 만들기").querySelector("input"));
    const after = snapshot();
    await new Promise((resolve) => setTimeout(resolve, 800)); // 애니메이션(0.7초)이 끝난 뒤
    assertEqual(snapshot(), after);
    t.close();
  });

  test("이벤트는 위임: onclick 속성 없이 data-on-* 만, 전체 흐름 동안 콘솔 오류 없음", async () => {
    const t = await openApp();
    await t.add("하나");
    await t.click(t.item("하나").querySelector("input"));
    await t.click('[data-filter="done"]');
    await t.click("#clear-done");
    await t.click('[data-filter="all"]');
    await t.click("#add-batch");
    assertEqual(t.$$("#root [onclick], #root [oninput], #root [onchange]").length, 0);
    assert(t.$$("#root [data-on-click]").length > 0);
    assertEqual(t.errors(), []);
    t.close();
  });

  test("(정리) 테스트 전에 저장돼 있던 목록으로 되돌림", () => {
    restoreStorage();
    assertEqual(localStorage.getItem(STORAGE_KEY), ORIGINAL_STORAGE);
  });
});
