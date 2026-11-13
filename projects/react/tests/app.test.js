// [tests/app.test.js] Phase 2 기능 테스트 — 실제 app.html 을 iframe 으로 열어 사용자처럼 조작한다
//
// localStorage 는 iframe(srcdoc)과 이 테스트 페이지가 같은 출처라 공유된다 → 테스트마다 저장 값을 지우고 시작.

import { describe, test, assert, assertEqual } from "./runner.js";
import { loadPage, waitFor } from "./helpers.js";

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

  const frame = await loadPage("../app.html", (parsed) => {
    // 페이지 안에서 main.js 를 한 번 더 import 해 마운트된 app 을 window.__app 으로 꺼낸다.
    // 같은 문서 안의 import 는 페이지가 실행한 모듈과 같은 것(같은 app 객체)을 돌려준다.
    const grab = parsed.createElement("script");
    grab.type = "module";
    grab.textContent = 'import { app } from "./src/app/main.js"; window.__app = app;';
    parsed.body.append(grab);
  });
  return tools(frame);
}

/** iframe 안의 App(FunctionComponent)을 꺼내고, 렌더마다 패치 목록을 기록한다 */
async function attachApp(win) {
  await waitFor(() => win.__app && win.document.querySelector(".todo-app"));
  const app = win.__app;
  const commits = [];
  app.onCommit((info) => commits.push(info));
  return { app, commits };
}

/** 페이지를 읽고 조작하는 도우미 */
async function tools(frame) {
  const win = frame.contentWindow;
  const doc = frame.contentDocument;
  const { app, commits } = await attachApp(win);
  const $ = (sel) => doc.querySelector(sel);
  const $$ = (sel) => [...doc.querySelectorAll(sel)];
  return {
    frame, win, doc, $, $$, app,
    texts: () => $$(".todo-text").map((el) => el.textContent),
    renders: () => app.renderCount,
    /** 마지막 렌더의 패치 종류 목록 */
    lastPatchTypes: () => (commits.at(-1)?.patches ?? []).map((p) => p.type),
    stat: (key) => $(`[data-stat="${key}"]`).textContent,
    /** 테스트 패널 "지금 상태" 표의 값 하나 (화면에 보이는 글자 그대로) */
    state: (key) => $(`.test-state [data-key="${key}"]`).textContent,
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
    item: (text) => $$(".todo-item").find((li) => li.querySelector(".todo-text")?.textContent === text),
    /** 키보드 이벤트 (Enter · Escape 등). extra 로 isComposing 같은 값을 더 줄 수 있다 */
    async key(sel, key, extra = {}) {
      (typeof sel === "string" ? $(sel) : sel).dispatchEvent(new win.KeyboardEvent("keydown", { key, bubbles: true, ...extra }));
      await settle();
    },
    /** 할 일 글자를 더블클릭 (수정 시작) */
    async dblclick(text) {
      this.item(text).querySelector(".todo-text").dispatchEvent(new win.MouseEvent("dblclick", { bubbles: true }));
      await settle();
    },
    errors: () => win.__errors,
    close: () => frame.remove(),
  };
}

describe("Phase 2 페이지 · 할 일 보드", () => {
  test("처음: 예시 4개, 렌더 1번, App 의 hooks 16개(state 10 · memo 2 · effect 4), 문서 제목", async () => {
    const t = await openApp();
    assertEqual(t.texts().length, 4);
    assertEqual(t.renders(), 1);
    assertEqual(t.app.hooks.length, 16);
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
    assert(t.lastPatchTypes().includes("CREATE"), "패치 목록에 CREATE");
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
    assert(t.lastPatchTypes().includes("PROPS"), "PROPS 패치");
    await t.click(li.querySelector("input"));
    assert(!li.classList.contains("done") && !li.querySelector("input").checked);
    assertEqual(t.stat("done"), "1");
    t.close();
  });

  test("삭제 → 그 항목만 사라짐", async () => {
    const t = await openApp();
    await t.click(t.item("발표 자료 만들기").querySelector(".todo-remove"));
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
    const t2 = await tools(t.frame);
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

  // ── 추가 상호작용 ─────────────────────────────────────────────────

  test("중요도 배지 클릭: 높음 → 보통 → 낮음 → 높음, 같은 li 에 PROPS 패치", async () => {
    const t = await openApp();
    const li = t.item("useState 가 상태를 기억하는 원리 설명하기");
    for (const expected of ["normal", "low", "high"]) {
      await t.click(li.querySelector(".prio"));
      assertEqual(li.dataset.priority, expected);
    }
    assert(li.isConnected, "같은 요소");
    assert(t.lastPatchTypes().includes("PROPS"));
    assertEqual(li.querySelector(".prio").textContent, "높음");
    t.close();
  });

  test("위/아래: 이웃과 자리를 바꾸고, 맨 위의 ↑ · 맨 아래의 ↓ 는 꺼짐", async () => {
    const t = await openApp();
    assert(t.$$(".todo-up")[0].disabled && t.$$(".todo-down").at(-1).disabled);
    assert(!t.$$(".todo-up")[1].disabled);
    await t.click(t.item("발표 자료 만들기").querySelector(".todo-up"));
    assertEqual(t.texts().slice(2), ["발표 자료 만들기", "useEffect 정리(cleanup) 함수 테스트"]);
    await t.click(t.item("발표 자료 만들기").querySelector(".todo-down"));
    assertEqual(t.texts().at(-1), "발표 자료 만들기");
    t.close();
  });

  test("위/아래는 key 없는 비교라 노드를 옮기지 않고 내용만 바꿈 (CREATE · REMOVE 없음)", async () => {
    const t = await openApp();
    const lis = t.$$(".todo-item");
    await t.click(lis[1].querySelector(".todo-up"));
    assert(t.$$(".todo-item").every((li, i) => li === lis[i]), "li 요소는 그대로");
    assert(t.lastPatchTypes().every((type) => type === "TEXT" || type === "PROPS"), t.lastPatchTypes().join(","));
    t.close();
  });

  test("위/아래는 필터 중이면 보이는 이웃과 바꿈", async () => {
    const t = await openApp();
    await t.click('[data-filter="active"]'); // 보임: useState · useEffect · 발표
    await t.click(t.item("useEffect 정리(cleanup) 함수 테스트").querySelector(".todo-up"));
    await t.click('[data-filter="all"]');
    assertEqual(t.texts(), ["Virtual DOM 과 Diff 복습하기", "useEffect 정리(cleanup) 함수 테스트", "useState 가 상태를 기억하는 원리 설명하기", "발표 자료 만들기"]);
    t.close();
  });

  test("중요도순: 높음 → 보통 → 낮음 (같은 순위는 원래 순서), 켜짐 표시, 위/아래 꺼짐, 끄면 원래 순서", async () => {
    const t = await openApp();
    const original = t.texts();
    await t.click("#sort-prio");
    assertEqual(t.texts(), ["useState 가 상태를 기억하는 원리 설명하기", "Virtual DOM 과 Diff 복습하기", "useEffect 정리(cleanup) 함수 테스트", "발표 자료 만들기"]);
    assertEqual(t.$("#sort-prio").getAttribute("aria-pressed"), "true");
    assert(t.$$(".todo-up, .todo-down").every((btn) => btn.disabled));
    await t.click("#sort-prio");
    assertEqual(t.texts(), original);
    t.close();
  });

  test("정렬은 보이는 순서만: 저장된 목록 순서는 그대로", async () => {
    const t = await openApp();
    await t.click("#sort-prio");
    assertEqual(JSON.parse(localStorage.getItem(STORAGE_KEY)).map((todo) => todo.id), [1, 2, 3, 4]);
    t.close();
  });

  test("모두 완료 → 전부 체크, 글자가 '모두 해제' 로 → 다시 누르면 전부 해제", async () => {
    const t = await openApp();
    await t.click("#toggle-all");
    assertEqual(t.stat("done"), "4");
    assertEqual(t.$("#toggle-all").textContent, "모두 해제");
    assertEqual(t.doc.title, "모두 완료 · 미니 React");
    await t.click("#toggle-all");
    assertEqual(t.stat("done"), "0");
    assertEqual(t.$("#toggle-all").textContent, "모두 완료");
    t.close();
  });

  test("목록이 비면 모두 완료 버튼이 꺼짐", async () => {
    const t = await openApp({ storage: "[]" });
    assert(t.$("#toggle-all").disabled);
    t.close();
  });

  test("되돌리기: 처음엔 꺼짐(0), 삭제 뒤 (1) → 누르면 그 항목이 같은 자리로", async () => {
    const t = await openApp();
    assert(t.$("#undo-todos").disabled);
    const before = t.texts();
    await t.click(t.item("useState 가 상태를 기억하는 원리 설명하기").querySelector(".todo-remove"));
    assertEqual(t.$("#undo-todos").textContent, "되돌리기 (1)");
    await t.click("#undo-todos");
    assertEqual(t.texts(), before);
    assert(t.$("#undo-todos").disabled);
    t.close();
  });

  test("되돌리기는 여러 번 차례로 (추가 → 체크 → 중요도 를 거꾸로)", async () => {
    const t = await openApp();
    const start = localStorage.getItem(STORAGE_KEY);
    await t.add("x");
    await t.click(t.item("x").querySelector("input"));
    await t.click(t.item("x").querySelector(".prio"));
    assertEqual(t.$("#undo-todos").textContent, "되돌리기 (3)");
    await t.click("#undo-todos");
    assertEqual(t.item("x").dataset.priority, "normal");
    await t.click("#undo-todos");
    assert(!t.item("x").querySelector("input").checked);
    await t.click("#undo-todos");
    assertEqual(t.item("x"), undefined);
    assertEqual(localStorage.getItem(STORAGE_KEY), start);
    t.close();
  });

  test("되돌리기: 예시 3개 추가(setState ×3)는 한 번에 3개가 빠짐", async () => {
    const t = await openApp();
    await t.click("#add-batch");
    assertEqual(t.texts().length, 7);
    await t.click("#undo-todos");
    assertEqual(t.texts().length, 4);
    t.close();
  });

  test("되돌리기는 최근 20번까지만 기억", async () => {
    const t = await openApp();
    const li = t.item("발표 자료 만들기");
    for (let i = 0; i < 25; i++) await t.click(li.querySelector("input"));
    assertEqual(t.$("#undo-todos").textContent, "되돌리기 (20)");
    t.close();
  });

  test("수정: 더블클릭 → 입력창(지금 글자, 포커스) → Enter 저장, 렌더 1번", async () => {
    const t = await openApp();
    await t.dblclick("발표 자료 만들기");
    const input = t.$(".todo-edit");
    assertEqual(input.value, "발표 자료 만들기");
    assert(t.doc.activeElement === input, "입력창에 포커스");
    await t.type(".todo-edit", "  발표 연습  ");
    const before = t.renders();
    await t.key(".todo-edit", "Enter");
    assertEqual(t.renders() - before, 1);
    assertEqual(t.texts().at(-1), "발표 연습"); // 앞뒤 공백은 뺌
    assertEqual(t.$(".todo-edit"), null);
    t.close();
  });

  test("수정: Esc 와 취소 버튼은 바꾸지 않음", async () => {
    const t = await openApp();
    await t.dblclick("발표 자료 만들기");
    await t.type(".todo-edit", "버릴 글자");
    await t.key(".todo-edit", "Escape");
    assertEqual(t.texts().at(-1), "발표 자료 만들기");
    await t.click(t.item("발표 자료 만들기").querySelector(".todo-edit-btn"));
    await t.type(".todo-edit", "또 버릴 글자");
    await t.click(".todo-cancel");
    assertEqual(t.texts().at(-1), "발표 자료 만들기");
    assert(t.$("#undo-todos").disabled, "되돌릴 기록도 생기지 않음");
    t.close();
  });

  test("수정: 저장 버튼, 빈 칸 · 같은 글자는 저장해도 그대로 (기록 안 남김)", async () => {
    const t = await openApp();
    await t.dblclick("발표 자료 만들기");
    await t.type(".todo-edit", "   ");
    await t.click(".todo-save");
    assertEqual(t.texts().at(-1), "발표 자료 만들기");
    await t.dblclick("발표 자료 만들기");
    await t.click(".todo-save");
    assert(t.$("#undo-todos").disabled);
    await t.dblclick("발표 자료 만들기");
    await t.type(".todo-edit", "새 이름");
    await t.click(".todo-save");
    assertEqual(t.texts().at(-1), "새 이름");
    t.close();
  });

  test("수정: 한글 조합 중(isComposing)의 Enter 는 저장하지 않음", async () => {
    const t = await openApp();
    await t.dblclick("발표 자료 만들기");
    await t.type(".todo-edit", "한글");
    await t.key(".todo-edit", "Enter", { isComposing: true });
    assert(t.$(".todo-edit"), "아직 수정 중");
    await t.key(".todo-edit", "Enter");
    assertEqual(t.texts().at(-1), "한글");
    t.close();
  });

  test("수정 중인 줄만 입력창으로 바뀌고(REPLACE 없이 다른 줄은 그대로), 글자 더블클릭은 체크를 바꾸지 않음", async () => {
    const t = await openApp();
    const others = t.$$(".todo-item").slice(0, 3);
    await t.dblclick("발표 자료 만들기");
    assert(t.$$(".todo-item").slice(0, 3).every((li, i) => li === others[i]), "다른 줄 요소 그대로");
    assertEqual(t.$$(".todo-edit").length, 1);
    assertEqual(t.stat("done"), "1");
    t.close();
  });

  test("수정 저장도 localStorage 에 남음", async () => {
    const t = await openApp();
    await t.dblclick("발표 자료 만들기");
    await t.type(".todo-edit", "저장 확인");
    await t.key(".todo-edit", "Enter");
    assert(localStorage.getItem(STORAGE_KEY).includes("저장 확인"));
    t.close();
  });

  test("검색창에서 Esc → 검색어가 지워지고 전체가 다시 보임", async () => {
    const t = await openApp();
    await t.type("#todo-search", "발표");
    assertEqual(t.texts().length, 1);
    await t.key("#todo-search", "Escape");
    assertEqual(t.$("#todo-search").value, "");
    assertEqual(t.texts().length, 4);
    t.close();
  });

  test("예시로 초기화: 처음 예시 4개로, 되돌리기로 직전 목록 복구 가능", async () => {
    const t = await openApp();
    await t.add("지워질 것");
    await t.click("#reset-todos");
    assertEqual(t.texts().length, 4);
    assertEqual(t.item("지워질 것"), undefined);
    await t.click("#undo-todos");
    assert(t.item("지워질 것"), "되돌리면 다시 있음");
    t.close();
  });

  test("추가 상호작용 전체 흐름 동안 콘솔 오류 없음, hooks 는 계속 16개", async () => {
    const t = await openApp();
    await t.click(t.$(".prio"));
    await t.click(t.$$(".todo-down")[0]);
    await t.click("#sort-prio");
    await t.click("#toggle-all");
    await t.dblclick("발표 자료 만들기");
    await t.key(".todo-edit", "Escape");
    await t.click("#undo-todos");
    await t.click("#reset-todos");
    assertEqual(t.app.hooks.length, 16);
    assertEqual(t.errors(), []);
    t.close();
  });

  // ── 테스트 패널 (TestPanel) ─────────────────────────────────

  test("테스트: 처음 값이 모든 입력에 그대로 (글자 · 숫자 · 범위 · 색 · 날짜 · 시각 · 체크 · 라디오 · 선택 · 여러 줄)", async () => {
    const t = await openApp();
    const p = (sel) => t.$(`.test-panel ${sel}`);
    const expected = { name: "홍길동", email: "mini@react.dev", pw: "1234", count: "3", level: "60", color: "#2563eb", date: "2026-11-09", time: "09:30" };
    for (const [name, value] of Object.entries(expected)) assertEqual(p(`input[name=${name}]`).value, value, name);
    assert(p("input[name=agree]").checked);
    assert(p("input[value=m]").checked && !p("input[value=s]").checked);
    assertEqual(p("select").value, "apple");
    assertEqual(p("textarea").value, "textarea 내용");
    assertEqual(t.state("clicks"), "0");
    t.close();
  });

  test("테스트: 입력 칸 9종에 글자를 넣으면 상태에 반영, 같은 요소 유지, 패치는 PROPS · TEXT 만, 렌더 1번씩", async () => {
    const t = await openApp();
    const inputs = { name: "김철수", email: "a@b.c", pw: "9999", count: "7", level: "25", color: "#ff0000", date: "2027-01-02", time: "18:45", memo: "새 메모" };
    for (const [name, value] of Object.entries(inputs)) {
      const sel = name === "memo" ? ".test-panel textarea" : `.test-panel input[name=${name}]`;
      const el = t.$(sel);
      const before = t.renders();
      await t.type(sel, value);
      assertEqual(t.renders() - before, 1, `${name} 렌더 1번`);
      assert(t.$(sel) === el, `${name} 같은 요소`);
      assertEqual(el.value, value, `${name} 화면 값`);
      assertEqual(t.state(name), name === "pw" ? "•".repeat(value.length) : value, `${name} 상태`);
      assert(t.lastPatchTypes().every((type) => type === "PROPS" || type === "TEXT"), `${name}: ${t.lastPatchTypes()}`);
    }
    t.close();
  });

  test("테스트: 범위 → progress · output, 숫자 → meter 가 따라 바뀜", async () => {
    const t = await openApp();
    await t.type(".test-panel input[name=level]", "80");
    await t.type(".test-panel input[name=count]", "5");
    assertEqual(t.$(".test-panel progress").value, 80);
    assertEqual(t.$(".test-panel meter").value, 5);
    assertEqual(t.$(".test-output").textContent, "80 × 5 = 400");
    t.close();
  });

  test("테스트: 선택 상자 · 라디오 · 체크박스", async () => {
    const t = await openApp();
    const select = t.$(".test-panel select");
    select.value = "lemon";
    select.dispatchEvent(new t.win.Event("change", { bubbles: true }));
    await settle();
    assertEqual(t.state("fruit"), "lemon");
    assert(t.$('.test-panel option[value="lemon"]').hasAttribute("selected"));
    await t.click(".test-panel input[value=l]");
    assert(t.$(".test-panel input[value=l]").checked && !t.$(".test-panel input[value=m]").checked);
    await t.click(".test-panel input[name=agree]");
    assertEqual(t.state("agree"), "false");
    assert(!t.$(".test-panel input[name=agree]").checked);
    t.close();
  });

  test("테스트: 버튼 · input 버튼은 클릭 +1, 꺼진 버튼은 눌러도 그대로", async () => {
    const t = await openApp();
    await t.click(".test-count");
    await t.click('.test-panel input[type=button]');
    assertEqual(t.$(".test-count").textContent, "클릭 +1 (2)");
    await t.click(".test-panel button[disabled]");
    assertEqual(t.state("clicks"), "2");
    t.close();
  });

  test("테스트: 대화상자 열기 → open, 닫기 → 닫힘 (같은 dialog 요소에 PROPS 패치)", async () => {
    const t = await openApp();
    const dialog = t.$(".test-panel dialog");
    assert(!dialog.open);
    await t.click(".test-open");
    assert(dialog.open && t.$(".test-panel dialog") === dialog);
    assert(t.lastPatchTypes().includes("PROPS"));
    await t.click(".test-close");
    assert(!dialog.open);
    t.close();
  });

  test("테스트: 잠그기 → fieldset disabled 로 안의 입력이 모두 꺼짐, 풀면 다시 켜짐", async () => {
    const t = await openApp();
    await t.click(".test-lock input");
    assert(t.$(".test-panel fieldset").disabled);
    assert(t.$(".test-panel input[name=name]").matches(":disabled"));
    await t.click(".test-lock input");
    assert(!t.$(".test-panel input[name=name]").matches(":disabled"));
    t.close();
  });

  test("테스트: details 는 상태 없이 브라우저가 여닫고, 다른 값이 바뀌어 다시 렌더돼도 열린 채 유지", async () => {
    const t = await openApp();
    const details = t.$(".test-panel details");
    details.open = true;
    await t.click(".test-count");
    assert(details.open && t.$(".test-panel details") === details);
    t.close();
  });

  test("테스트: 초기화 → 모든 값이 처음으로 (화면 값도)", async () => {
    const t = await openApp();
    await t.type(".test-panel input[name=name]", "바뀐 이름");
    await t.click(".test-count");
    await t.click(".test-reset");
    assertEqual(t.$(".test-panel input[name=name]").value, "홍길동");
    assertEqual(t.state("clicks"), "0");
    t.close();
  });

  test("테스트: 할 일 목록과 상태가 섞이지 않음 (테스트 값을 바꿔도 할 일 · 되돌리기 그대로), 콘솔 오류 없음", async () => {
    const t = await openApp();
    const texts = t.texts();
    await t.type(".test-panel input[name=name]", "x");
    await t.click(".test-open");
    assertEqual(t.texts(), texts);
    assert(t.$("#undo-todos").disabled);
    assertEqual(t.errors(), []);
    t.close();
  });

  test("(정리) 테스트 전에 저장돼 있던 목록으로 되돌림", () => {
    restoreStorage();
    assertEqual(localStorage.getItem(STORAGE_KEY), ORIGINAL_STORAGE);
  });
});
