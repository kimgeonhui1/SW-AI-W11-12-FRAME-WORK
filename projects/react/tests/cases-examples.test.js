// [tests/cases-examples.test.js] 테스트 항목 #316 ~ #357 — Phase 1 "예시 변경" 버튼 · 테스트 카드
//
// 앞부분(#316~#336)은 EXAMPLES 의 edit 를 샘플 영역 사본에 직접 적용해, 나오는 패치 종류를 검사한다 (iframe 없음 · 빠름).
// 뒷부분(#337~#345)은 실제 ../index.html 을 iframe 으로 열어 버튼을 눌러 본다.

import { describe, test, assert, assertEqual } from "./runner.js";
import { containerToVdom, createElement } from "../src/core/vdom.js";
import { diff } from "../src/core/diff.js";
import { patch } from "../src/core/patch.js";
import { EXAMPLES } from "../src/phase1/main.js";
import { openIndex } from "./helpers.js";

/** index.html 의 실제 영역 샘플 HTML (한 번만 받아 온다) */
let sampleHtml = null;
async function sample() {
  if (sampleHtml === null) {
    const html = await (await fetch("../index.html", { cache: "no-store" })).text();
    sampleHtml = new DOMParser().parseFromString(html, "text/html").getElementById("real-area").innerHTML;
  }
  const area = document.createElement("div");
  area.innerHTML = sampleHtml;
  return area;
}

const byKey = (key) => EXAMPLES.find((example) => example.key === key);

/**
 * 샘플 영역에서 예시 하나를 실행하고 결과를 돌려준다.
 * 같은 패치를 "실제 영역" 역할의 다른 사본에 적용해, 결과가 고친 영역과 똑같은지(round trip)도 확인한다.
 * @param {string} key EXAMPLES 의 key
 * @param {HTMLElement} [area] 이미 준비한 영역 (없으면 새 샘플)
 */
async function apply(key, area) {
  area ??= await sample();
  const before = containerToVdom(area);
  const result = byKey(key).edit(area, before);
  const after = containerToVdom(area);
  const patches = diff(before, after);

  const real = document.createElement("div"); // 바뀌기 전 상태를 그린 "실제 영역"
  real.append(...before.children.map(createElement));
  patch(real, patches);
  assertEqual(JSON.stringify(containerToVdom(real)), JSON.stringify(after), "패치한 사본 = 고친 영역");

  return { result, area, before, after, types: patches.map((p) => p.type) };
}

describe("예시 변경 · 패치 종류 (#316~#336)", () => {
  test("#316 예시는 20개, key 가 서로 다르고 모두 edit 함수를 가짐", () => {
    assertEqual(EXAMPLES.length, 20);
    assertEqual(new Set(EXAMPLES.map((e) => e.key)).size, 20);
    assert(EXAMPLES.every((e) => typeof e.edit === "function" && e.label && e.hint));
  });
  test("#317 EXAMPLES 와 각 항목은 얼려 있음 (밖에서 못 바꿈)", () => {
    assert(Object.isFrozen(EXAMPLES) && EXAMPLES.every(Object.isFrozen));
  });
  test("#318 제목 글자 바꾸기 → TEXT 1개, 다시 누르면 원래 글자", async () => {
    const { types, area, before } = await apply("title");
    assertEqual(types, ["TEXT"]);
    byKey("title").edit(area);
    assertEqual(JSON.stringify(containerToVdom(area)), JSON.stringify(before));
  });
  test("#319 부제 색 바꾸기 → PROPS 1개, 세 번 누르면 처음 색으로", async () => {
    const { types, area } = await apply("color");
    assertEqual(types, ["PROPS"]);
    byKey("color").edit(area);
    byKey("color").edit(area);
    assert(area.querySelector("h2").getAttribute("style").includes("#7c3aed"));
  });
  test("#320 title 넣기 → PROPS(설정), 다시 → PROPS(삭제)", async () => {
    const first = await apply("tooltip");
    assertEqual(first.types, ["PROPS"]);
    const second = await apply("tooltip", first.area);
    assertEqual(second.types, ["PROPS"]);
    assert(!first.area.querySelector("h1").hasAttribute("title"));
  });
  test("#321 완료 표시 뒤집기 → 항목 수(3)만큼 PROPS", async () => {
    assertEqual((await apply("flipDone")).types, ["PROPS", "PROPS", "PROPS"]);
  });
  test("#322 목록 끝에 추가 → data-count PROPS + CREATE", async () => {
    const { types, area } = await apply("addItem");
    assertEqual(types, ["PROPS", "CREATE"]);
    assertEqual(area.querySelector("ul").getAttribute("data-count"), "4");
  });
  test("#323 마지막 항목 삭제 → data-count PROPS + REMOVE", async () => {
    assertEqual((await apply("removeLast")).types, ["PROPS", "REMOVE"]);
  });
  test("#324 맨 앞 항목 삭제 → key 가 없어 여러 패치 + 마지막 REMOVE 1개", async () => {
    const { types } = await apply("removeFirst");
    assert(types.length > 2, `패치 ${types.length}개`);
    assertEqual(types.filter((t) => t === "REMOVE").length, 1);
    assertEqual(types.at(-1), "REMOVE");
  });
  test("#325 순서 뒤집기 → CREATE · REMOVE 없이 TEXT · PROPS 만", async () => {
    const { types } = await apply("reverse");
    assert(types.length > 0 && types.every((t) => t === "TEXT" || t === "PROPS"), types.join(","));
  });
  test("#326 em ↔ i → REPLACE 1개, 글자는 그대로, 다시 누르면 em", async () => {
    const { types, area } = await apply("swapTag");
    assertEqual(types, ["REPLACE"]);
    assertEqual(area.querySelector("i").textContent, "기울임");
    byKey("swapTag").edit(area);
    assert(area.querySelector(".card em") && !area.querySelector(".card i"), "첫 카드는 다시 em");
  });
  test("#327 굵은 글씨 풀기 → REPLACE(요소 → 글자)", async () => {
    const { types, area } = await apply("unwrap");
    assertEqual(types, ["REPLACE"]);
    assert(!area.querySelector("strong") && area.textContent.includes("굵은 글씨"));
  });
  test("#328 HTML 같은 글자 → 요소가 아닌 글자로만 들어감 (img 없음)", async () => {
    const { types, area } = await apply("addUnsafe");
    assertEqual(types, ["PROPS", "CREATE"]);
    assert(!area.querySelector("img"), "img 요소가 생기면 안 됨");
    assert(area.querySelector("li:last-child").textContent.startsWith("<img"));
  });
  test("#329 카드 추가 → 하위 트리 통째로 CREATE 1개", async () => {
    const { types, area } = await apply("addCard");
    assertEqual(types, ["CREATE"]);
    assertEqual(area.querySelectorAll(".card").length, 2);
    assert(area.lastElementChild.classList.contains("card"), "영역 맨 끝에 붙음");
  });
  test("#330 추가한 카드 삭제 → REMOVE 1개 (끝에 카드가 없으면 false)", async () => {
    const area = await sample();
    assertEqual(byKey("removeCard").edit(area), false, "처음에는 끝에 카드가 없음");
    const added = await apply("addCard", area);
    assertEqual((await apply("removeCard", added.area)).types, ["REMOVE"]);
  });
  test("#331 여러 곳 한꺼번에 → TEXT · PROPS · CREATE 가 모두 나옴", async () => {
    const { types } = await apply("mixed");
    for (const type of ["TEXT", "PROPS", "CREATE"]) assert(types.includes(type), `${type} 없음: ${types}`);
  });
  test("#332 모두 비우기 → REMOVE 만, 영역이 빔", async () => {
    const { types, area } = await apply("clear");
    assert(types.length > 0 && types.every((t) => t === "REMOVE"));
    assertEqual(area.childNodes.length, 0);
  });
  test("#333 처음 상태로 → 비운 뒤면 CREATE, 결과 VDOM = 처음 VDOM", async () => {
    const area = await sample();
    const initial = containerToVdom(area);
    area.replaceChildren();
    byKey("reset").edit(area, initial);
    assertEqual(JSON.stringify(containerToVdom(area)), JSON.stringify(initial));
  });
  test("#334 처음 VDOM 이 없으면 처음 상태로는 false", async () => {
    assertEqual(byKey("reset").edit(await sample(), null), false);
  });
  test("#335 빈 영역: 카드 추가 · 처음 상태로를 뺀 예시는 모두 false 이고 영역을 건드리지 않음", () => {
    for (const example of EXAMPLES) {
      if (example.key === "addCard" || example.key === "reset") continue;
      const area = document.createElement("div");
      assertEqual(example.edit(area, null), false, example.key);
      assertEqual(area.childNodes.length, 0, example.key);
    }
  });
  test("#336 모든 예시를 차례로 20번 적용해도 매번 사본 patch 결과가 일치", async () => {
    const area = await sample();
    const initial = containerToVdom(area);
    for (const example of EXAMPLES) {
      const before = containerToVdom(area);
      if (example.edit(area, initial) === false) continue;
      const real = document.createElement("div");
      real.append(...before.children.map(createElement));
      patch(real, diff(before, containerToVdom(area)));
      assertEqual(JSON.stringify(containerToVdom(real)), JSON.stringify(containerToVdom(area)), example.key);
    }
  });
});

describe("예시 변경 · 페이지 (#337~#345)", () => {
  /** 예시 버튼 하나를 누른다 */
  const press = (page, key) => page.doc.querySelector(`[data-example="${key}"]`).click();

  test("#337 #examples 에 버튼 20개, 각 버튼은 이름 + 나올 패치 작은 글씨", async () => {
    const page = await openIndex();
    const buttons = [...page.doc.querySelectorAll("#examples [data-example]")];
    assertEqual(buttons.length, 20);
    assertEqual(buttons[0].querySelector("small").textContent, "TEXT");
    page.frame.remove();
  });
  test("#338 버튼 하나 → 바로 Patch: History 2개, 자가 점검 일치, 로그에 TEXT", async () => {
    const page = await openIndex();
    press(page, "title");
    assertEqual(page.$("history-list").children.length, 2);
    assert(page.$("status").textContent.includes("일치합니다"));
    assertEqual(page.$("patch-log").querySelector(".badge").textContent, "TEXT");
    page.frame.remove();
  });
  test("#339 History 라벨에 예시 이름이 붙음", async () => {
    const page = await openIndex();
    press(page, "addItem");
    assert(page.$("history-list").textContent.includes("Patch #1 · 목록 끝에 추가"));
    page.frame.remove();
  });
  test("#340 소스 편집기도 예시 결과로 바뀜", async () => {
    const page = await openIndex();
    press(page, "addCard");
    assert(page.$("test-source").value.includes("새 카드 2"));
    page.frame.remove();
  });
  test("#341 20개를 모두 눌러도 매번 실제 영역 = 테스트 영역, 콘솔 오류 없음", async () => {
    const page = await openIndex();
    for (const { key } of EXAMPLES) {
      press(page, key);
      assertEqual(JSON.stringify(containerToVdom(page.$("real-area"))), JSON.stringify(containerToVdom(page.$("test-area"))), key);
    }
    assertEqual(page.win.__errors, []);
    page.frame.remove();
  });
  test("#342 바꿀 대상이 없으면 경고만, History 는 그대로", async () => {
    const page = await openIndex();
    press(page, "clear");
    const count = page.$("history-list").children.length;
    press(page, "removeLast");
    assertEqual(page.$("history-list").children.length, count);
    assertEqual(page.$("status").dataset.kind, "warn");
    assert(page.$("status").textContent.includes("마지막 항목 삭제"));
    page.frame.remove();
  });
  test("#343 예시 뒤 뒤로가기 → 실제 영역이 처음으로", async () => {
    const page = await openIndex();
    const initial = JSON.stringify(containerToVdom(page.$("real-area")));
    press(page, "mixed");
    page.$("undo-btn").click();
    assertEqual(JSON.stringify(containerToVdom(page.$("real-area"))), initial);
    page.frame.remove();
  });
  test("#344 모두 비우기 → 처음 상태로: 실제 영역이 처음과 같음", async () => {
    const page = await openIndex();
    const initial = JSON.stringify(containerToVdom(page.$("real-area")));
    press(page, "clear");
    press(page, "reset");
    assertEqual(JSON.stringify(containerToVdom(page.$("real-area"))), initial);
    page.frame.remove();
  });
  test("#345 #examples 가 없는 페이지도 정상 시작 (선택 요소)", async () => {
    const page = await openIndex({ removeIds: ["examples"] });
    assert(page.$("status").textContent.length > 0 && !page.doc.querySelector(".startup-error"));
    page.frame.remove();
  });
});

describe("테스트 카드 · 폼 예시 (#346~#357)", () => {
  test("#346 샘플에 버튼 · 입력 · 선택 · 표 · 접기 · 대화상자 · 측정 요소가 모두 있음", async () => {
    const area = await sample();
    const selectors = [
      "form", "fieldset", "legend", "label", "button[type=button]", "button[type=submit]", "button[type=reset]", "button[disabled]",
      "input[type=text]", "input[type=email]", "input[type=password]", "input[type=number]", "input[type=range]", "input[type=color]",
      "input[type=date]", "input[type=checkbox]", "input[type=radio]", "input[type=button]", "select", "optgroup", "option", "textarea",
      "details", "summary", "dialog[open]", "progress", "meter", "output", "table", "caption", "thead", "tbody", "tfoot", "th", "td",
      "ol", "dl", "dt", "dd", "blockquote", "q", "cite", "abbr", "kbd", "sub", "sup", "mark", "del", "ins", "small", "s", "u", "b", "i",
      "time", "br", "wbr", "figure", "figcaption", "pre", "hr", "address",
    ];
    assertEqual(selectors.filter((sel) => !area.querySelector(sel)), [], "빠진 요소");
  });
  test("#347 테스트 카드도 toHtml → 파서 → VDOM 왕복이 같음", async () => {
    const area = await sample();
    const { toHtml } = await import("../src/phase1/main.js");
    const again = document.createElement("div");
    again.innerHTML = toHtml(containerToVdom(area).children);
    assertEqual(JSON.stringify(containerToVdom(again)), JSON.stringify(containerToVdom(area)));
  });
  test("#348 체크박스 checked 넣기/빼기 → PROPS 1개, 다시 누르면 원래대로", async () => {
    const first = await apply("checkbox");
    assertEqual(first.types, ["PROPS"]);
    assertEqual((await apply("checkbox", first.area)).types, ["PROPS"]);
    assert(first.area.querySelector("input[type=checkbox]").hasAttribute("checked"));
  });
  test("#349 details 열기/닫기 → PROPS(open) 1개", async () => {
    const { types, area } = await apply("details");
    assertEqual(types, ["PROPS"]);
    assert(area.querySelector("details").hasAttribute("open"));
  });
  test("#350 첫 버튼 끄기/켜기 → PROPS(disabled) 1개", async () => {
    const { types, area } = await apply("disable");
    assertEqual(types, ["PROPS"]);
    assert(area.querySelector("button").disabled);
  });
  test("#351 입력 칸 값 바꾸기 → PROPS(value) 1개, 다시 누르면 원래 값", async () => {
    const first = await apply("inputValue");
    assertEqual(first.types, ["PROPS"]);
    assertEqual(first.area.querySelector("input[type=text]").getAttribute("value"), "김철수");
    byKey("inputValue").edit(first.area);
    assertEqual(first.area.querySelector("input[type=text]").getAttribute("value"), "홍길동");
  });
  test("#352 페이지: 체크박스 예시 → 실제 영역 체크박스의 화면 상태(checked 프로퍼티)도 바뀜", async () => {
    const page = await openIndex();
    const box = page.$("real-area").querySelector("input[type=checkbox]");
    assert(box.checked);
    page.doc.querySelector('[data-example="checkbox"]').click();
    assert(!box.checked, "체크 해제");
    assert(page.$("status").textContent.includes("일치합니다"));
    page.frame.remove();
  });
  test("#353 페이지: 입력 칸 값 예시 → 실제 영역 input 의 화면 값(value 프로퍼티)도 바뀜", async () => {
    const page = await openIndex();
    page.doc.querySelector('[data-example="inputValue"]').click();
    assertEqual(page.$("real-area").querySelector("input[type=text]").value, "김철수");
    page.frame.remove();
  });
  test("#354 페이지: details 예시 → 실제 영역의 details 가 열림", async () => {
    const page = await openIndex();
    page.doc.querySelector('[data-example="details"]').click();
    assert(page.$("real-area").querySelector("details").open);
    page.frame.remove();
  });
  test("#355 페이지: 두 영역의 제출 버튼을 눌러도 submit 이 막혀 페이지가 그대로", async () => {
    const page = await openIndex();
    for (const id of ["real-area", "test-area"]) {
      const form = page.$(id).querySelector("form");
      const event = new page.win.SubmitEvent("submit", { bubbles: true, cancelable: true });
      form.dispatchEvent(event);
      assert(event.defaultPrevented, `${id} 의 submit 은 막혀야 함`);
    }
    assertEqual(page.$("history-list").children.length, 1);
    page.frame.remove();
  });
  test("#356 페이지: 처음에 실제 영역과 테스트 영역 모두 테스트 카드을 가짐 (VDOM 같음)", async () => {
    const page = await openIndex();
    assert(page.$("test-area").querySelector(".showcase form fieldset"));
    assertEqual(JSON.stringify(containerToVdom(page.$("real-area"))), JSON.stringify(containerToVdom(page.$("test-area"))));
    page.frame.remove();
  });
  test("#357 페이지: 두 영역의 라디오 묶음은 따로 (테스트 영역에서 골라도 실제 영역 선택은 그대로)", async () => {
    const page = await openIndex();
    const [realS, realM] = page.$("real-area").querySelectorAll("input[type=radio]");
    page.$("test-area").querySelector("input[type=radio]").click();
    assert(!realS.checked && realM.checked);
    page.frame.remove();
  });
});
