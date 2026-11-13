// [tests/cases-page.test.js] 테스트 항목 #231 ~ #255 — 페이지 초기화 및 이벤트
//
// 실제 ../index.html 을 iframe 으로 열어(openIndex) 버튼을 누르며 검사한다.
// openIndex 는 페이지 스크립트보다 먼저 console.error · 잡히지 않은 오류를 win.__errors 에 모은다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { containerToVdom } from "../src/core/vdom.js";
import { REQUIRED_IDS } from "../src/phase1/main.js";
import { openIndex, waitFor } from "./helpers.js";

const MARK = "페이지 테스트 항목";

/** 페이지 상태를 읽고 조작하는 도우미 */
function pageTools({ win, doc, $ }) {
  const vdomOf = (id) => JSON.stringify(containerToVdom($(id)));
  return {
    /** 소스 편집기에 HTML 을 넣고 input 이벤트를 보낸다 (사용자가 입력한 것처럼) */
    typeSource(html) {
      $("test-source").value = html;
      $("test-source").dispatchEvent(new win.Event("input"));
    },
    /** 목록 끝에 항목 하나를 추가하는 편집 */
    addItem(text = MARK) {
      this.typeSource($("test-source").value.replace("</ul>", `<li>${text}</li></ul>`));
    },
    click: (id) => $(id).click(),
    historyCount: () => $("history-list").children.length,
    position: () => $("position-label").textContent,
    status: () => $("status").textContent,
    realHas: (text = MARK) => $("real-area").textContent.includes(text),
    testHas: (text = MARK) => $("test-area").textContent.includes(text),
    /** 상태 줄의 자가 점검: 실제 영역 = History 현재 VDOM */
    matches: () => $("status").textContent.includes("일치합니다"),
    realVdom: () => vdomOf("real-area"),
    testVdom: () => vdomOf("test-area"),
    errors: () => win.__errors.filter((e) => !e.includes("[phase1] Phase 1 화면을 시작할 수 없습니다")),
    notice: () => doc.querySelector(".startup-error")?.textContent ?? "",
  };
}

/** 필수 요소 하나를 지운 페이지: 시작하지 않고, 그 id 를 안내하며, 잡히지 않은 오류가 없어야 한다 */
async function checkMissing(id) {
  const page = await openIndex({ removeIds: [id] });
  const t = pageTools(page);
  assert(t.notice().includes(`#${id}`), `안내에 #${id} 가 있어야 함: ${t.notice()}`);
  assertEqual(t.errors(), [], "잡히지 않은 오류가 없어야 함");
  if (page.$("test-area")) assertEqual(page.$("test-area").childNodes.length, 0, "init() 이 실행되면 안 됨");
  page.frame.remove();
}

describe("페이지 초기화 및 이벤트 (#231~#255)", () => {
  test("#231 #real-area 가 없으면 시작하지 않고 안내", () => checkMissing("real-area"));
  test("#232 #test-area 가 없으면 시작하지 않고 안내", () => checkMissing("test-area"));
  test("#233 #test-source 가 없으면 시작하지 않고 안내", () => checkMissing("test-source"));
  test("#234 Patch 버튼이 없으면 시작하지 않고 안내", () => checkMissing("patch-btn"));
  test("#235 Undo 버튼이 없으면 시작하지 않고 안내", () => checkMissing("undo-btn"));
  test("#236 Redo 버튼이 없으면 시작하지 않고 안내", () => checkMissing("redo-btn"));
  test("#237 필수 요소가 하나만 있으면 나머지 11개를 모두 안내", async () => {
    const page = await openIndex({ removeIds: REQUIRED_IDS.filter((id) => id !== "real-area") });
    const notice = pageTools(page).notice();
    for (const id of REQUIRED_IDS.filter((id) => id !== "real-area")) assert(notice.includes(`#${id}`), `#${id} 누락`);
    page.frame.remove();
  });
  test("#238 모든 요소가 있으면 정상 시작 (History 1개, 두 영역 VDOM 같음, 오류 없음)", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    assertEqual(t.notice(), "");
    assertEqual(t.historyCount(), 1);
    assertEqual(t.testVdom(), t.realVdom());
    assertEqual(t.errors(), []);
    page.frame.remove();
  });
  test("#239 main.js 를 다시 import 해도 init() 이 두 번 실행되지 않음 (모듈은 한 번만 실행)", async () => {
    const page = await openIndex();
    const url = new URL("../src/phase1/main.js", location.href).href;
    await new page.win.Function("u", "return import(u)")(url);
    await new page.win.Function("u", "return import(u)")(url);
    assertEqual(pageTools(page).historyCount(), 1);
    page.frame.remove();
  });
  test("#240 이벤트 리스너가 한 번만 등록됨 (Undo 한 번에 한 칸만 이동)", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem("하나");
    t.click("patch-btn");
    t.addItem("둘");
    t.click("patch-btn");
    t.click("undo-btn");
    assertEqual(t.position(), "현재 위치: 2 / 3");
    page.frame.remove();
  });
  test("#241 Patch 버튼을 빠르게 10번 → 기록은 한 번만", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    for (let i = 0; i < 10; i++) t.click("patch-btn");
    assertEqual(t.historyCount(), 2);
    assert(t.status().includes("변경 없음"));
    page.frame.remove();
  });
  test("#242 Patch 직후 바로 Undo → 처음 상태, 일치", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    t.click("patch-btn");
    t.click("undo-btn");
    assert(!t.realHas() && !t.testHas());
    assert(t.matches(), t.status());
    assertEqual(t.position(), "현재 위치: 1 / 2");
    page.frame.remove();
  });
  test("#243 Undo 직후 바로 Redo → 다시 반영, 일치", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    t.click("patch-btn");
    t.click("undo-btn");
    t.click("redo-btn");
    assert(t.realHas() && t.testHas());
    assert(t.matches(), t.status());
    page.frame.remove();
  });
  test("#244 빈 HTML 소스로 Patch → 실제 영역도 비고, 일치", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.typeSource("");
    t.click("patch-btn");
    assertEqual(containerToVdom(page.$("real-area")).children, []);
    assert(t.matches(), t.status());
    page.frame.remove();
  });
  test("#245 잘못된 HTML 소스로 Patch → 파서가 고친 모양으로 반영, 오류 없음", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.typeSource("<div><p>닫히지 않은 <b>태그</div><span>");
    t.click("patch-btn");
    assertEqual(t.realVdom(), t.testVdom());
    assert(t.matches(), t.status());
    assertEqual(t.errors(), []);
    page.frame.remove();
  });
  test("#246 테스트 영역을 직접 고친 뒤 (Patch 없이) Undo → 편집 내용은 버려지고 이전 상태로", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    t.click("patch-btn");
    page.$("test-area").append(page.doc.createTextNode("저장 안 한 편집"));
    t.click("undo-btn");
    assert(!t.testHas("저장 안 한 편집") && !t.testHas());
    assertEqual(t.testVdom(), t.realVdom());
    page.frame.remove();
  });
  test("#247 테스트 영역을 직접 고친 뒤 Redo → 편집 내용은 버려지고 다음 상태로", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    t.click("patch-btn");
    t.click("undo-btn");
    page.$("test-area").append(page.doc.createTextNode("저장 안 한 편집"));
    t.click("redo-btn");
    assert(!t.testHas("저장 안 한 편집") && t.testHas());
    assertEqual(t.testVdom(), t.realVdom());
    page.frame.remove();
  });
  test("#248 소스 편집기 수정 → 미리보기 동기화", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.typeSource("<h1>소스에서 바꿈</h1>");
    assertEqual(page.$("test-area").innerHTML, "<h1>소스에서 바꿈</h1>");
    page.frame.remove();
  });
  test("#249 미리보기 수정 → 소스 동기화", async () => {
    const page = await openIndex();
    const heading = page.$("test-area").querySelector("h1, h2, p");
    heading.firstChild.nodeValue = "미리보기에서 바꿈";
    page.$("test-area").dispatchEvent(new page.win.Event("input"));
    assert(page.$("test-source").value.includes("미리보기에서 바꿈"));
    page.frame.remove();
  });
  test("#250 양방향 동기화를 10번 반복해도 내용이 변하지 않음", async () => {
    const page = await openIndex();
    const source = page.$("test-source");
    const first = source.value;
    for (let i = 0; i < 10; i++) {
      source.dispatchEvent(new page.win.Event("input")); //                 소스 → 미리보기
      page.$("test-area").dispatchEvent(new page.win.Event("input")); //    미리보기 → 소스
    }
    assertEqual(source.value, first);
    page.frame.remove();
  });
  test("#251 초기화 후 테스트 영역 요소를 새것으로 바꾸면, main.js 는 예전 요소를 계속 봄 (오류 없음)", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    const replacement = page.$("test-area").cloneNode(true);
    page.$("test-area").replaceWith(replacement);
    replacement.append(page.doc.createElement("hr"));
    t.click("patch-btn");
    assert(t.status().includes("변경 없음"), "떨어져 나간 예전 요소를 읽으므로 변경 없음");
    assertEqual(t.errors(), []);
    page.frame.remove();
  });
  test("#252 초기화 후 Patch 버튼을 지워도 나머지 버튼은 동작", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    t.click("patch-btn");
    page.$("patch-btn").remove();
    t.click("undo-btn");
    t.click("redo-btn");
    assert(t.matches(), t.status());
    assertEqual(t.errors(), []);
    page.frame.remove();
  });
  test("#253 새로고침하면 History 가 처음 상태(1개)로 돌아감", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    t.click("patch-btn");
    assertEqual(t.historyCount(), 2);
    const reloaded = new Promise((resolve) => page.frame.addEventListener("load", resolve, { once: true }));
    page.win.location.reload();
    await reloaded;
    const doc = page.frame.contentDocument;
    await waitFor(() => doc.getElementById("status")?.textContent);
    assertEqual(doc.getElementById("history-list").children.length, 1);
    assert(!doc.getElementById("real-area").textContent.includes(MARK));
    page.frame.remove();
  });
  test("#254 State History 는 브라우저 방문 기록(window.history)을 건드리지 않음", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    const before = { length: page.win.history.length, href: page.win.location.href };
    t.addItem();
    t.click("patch-btn");
    t.click("undo-btn");
    t.click("redo-btn");
    assertEqual({ length: page.win.history.length, href: page.win.location.href }, before);
    page.frame.remove();
  });
  test("#255 전체 동작 동안 콘솔 오류 없음", async () => {
    const page = await openIndex();
    const t = pageTools(page);
    t.addItem();
    t.click("patch-btn");
    t.click("patch-btn");
    t.click("undo-btn");
    t.click("redo-btn");
    page.$("history-list").querySelector("button").click();
    t.typeSource("<p>끝</p>");
    t.click("patch-btn");
    assert(t.matches(), t.status());
    assertEqual(page.win.__errors, []);
    page.frame.remove();
  });
});

