// [tests/page.test.js] main.js 시작 조건 + 실제 index.html 화면 동작 자동 검사

/**
 * 무엇을 검사하나
 * 1. checkRequiredElements(): 필수 요소가 전부 / 일부 / 하나도 없을 때의 판단
 * 2. 이 테스트 페이지(tests/index.html)에서 main.js 를 import 해도 화면 코드가 실행되지 않는지
 * 3. 필수 요소가 일부만 있는 페이지에서는 init() 을 하지 않고 빠진 id 를 알리는지
 * 4. 실제 ../index.html 을 iframe 으로 열어 버튼을 눌러 보는 통합 테스트
 *    (로드 → 소스 편집 → Patch → 변경 없음 → 뒤로가기 → 앞으로가기 → 목록 클릭)
 *
 * 자동 검사로 확인하지 못하는 것: 사람이 키보드로 contenteditable 에 직접 입력하는 동작,
 * 강조 애니메이션이 눈에 보이는지, 레이아웃. 이것들은 보고서의 수동 확인 표로 검사한다.
 */

import { describe, test, assert, assertEqual } from "./runner.js";
import { REQUIRED_IDS, checkRequiredElements } from "../src/phase1/main.js";
import { containerToVdom } from "../src/core/vdom.js";

/** 주어진 id 들을 가진 요소를 담은 임시 div */
function boxWithIds(ids) {
  const box = document.createElement("div");
  for (const id of ids) {
    const el = document.createElement("div");
    el.id = id;
    box.append(el);
  }
  return box;
}

/**
 * iframe 을 화면 밖에 만들고 로드가 끝날 때까지 기다린다.
 * @param {{src?: string, srcdoc?: string}} attrs
 * @returns {Promise<HTMLIFrameElement>}
 */
function loadFrame(attrs) {
  return new Promise((resolve, reject) => {
    const frame = document.createElement("iframe");
    frame.style.cssText = "position:absolute; left:-10000px; top:0; width:1100px; height:900px;";
    frame.addEventListener("load", () => resolve(frame), { once: true });
    frame.addEventListener("error", reject, { once: true });
    Object.assign(frame, attrs);
    document.body.append(frame);
  });
}

/** 조건이 참이 될 때까지 기다린다 (모듈 스크립트 실행 대기용) */
async function waitFor(check, timeoutMs = 3000) {
  const started = performance.now();
  while (performance.now() - started < timeoutMs) {
    if (check()) return;
    await new Promise((r) => setTimeout(r, 20));
  }
  throw new Error("시간 안에 조건이 만족되지 않음");
}

describe("main.js 시작 조건 (checkRequiredElements)", () => {
  test("필수 요소가 모두 있으면 ready", () => {
    assertEqual(checkRequiredElements(boxWithIds(REQUIRED_IDS)), { state: "ready", missing: [] });
  });

  test("하나도 없으면 none (테스트 페이지처럼 import 만 한 경우)", () => {
    const result = checkRequiredElements(boxWithIds([]));
    assertEqual(result.state, "none");
    assertEqual(result.missing, [...REQUIRED_IDS]);
  });

  test("#real-area 만 있으면 partial, 나머지 id 를 모두 알려 준다", () => {
    const result = checkRequiredElements(boxWithIds(["real-area"]));
    assertEqual(result.state, "partial");
    assertEqual(result.missing, REQUIRED_IDS.filter((id) => id !== "real-area"));
  });

  test("하나만 빠져도 partial", () => {
    const result = checkRequiredElements(boxWithIds(REQUIRED_IDS.filter((id) => id !== "redo-btn")));
    assertEqual(result, { state: "partial", missing: ["redo-btn"] });
  });

  test("이 테스트 페이지에서 import 해도 화면 코드가 실행되지 않았다", () => {
    assertEqual(checkRequiredElements(document).state, "none");
    assert(!document.querySelector(".startup-error"), "안내 문단이 생기면 안 됨");
  });
});

describe("main.js 시작 — 필수 요소가 일부만 있는 페이지", () => {
  test("init() 을 하지 않고 빠진 id 를 화면에 알린다", async () => {
    // srcdoc 페이지는 주소가 about:srcdoc 이라 상대 경로를 못 쓰므로 절대 주소로 불러온다
    const mainUrl = new URL("../src/phase1/main.js", location.href).href;
    const frame = await loadFrame({
      srcdoc: `<div id="real-area"><p>샘플</p></div><div id="test-area"></div><div id="status"></div>
               <script type="module" src="${mainUrl}"><\/script>`,
    });
    const doc = frame.contentDocument;
    await waitFor(() => doc.querySelector(".startup-error"));

    const notice = doc.querySelector(".startup-error").textContent;
    assert(notice.includes("#patch-btn") && notice.includes("#vdom-json"), `빠진 id 가 안내에 있어야 함: ${notice}`);
    assert(!notice.includes("#real-area"), "있는 요소는 안내에 없어야 함");
    assertEqual(doc.getElementById("test-area").childNodes.length, 0, "테스트 영역이 렌더링되면 안 됨 (init 미실행)");
    frame.remove();
  });
});

describe("index.html 통합 동작 (iframe)", () => {
  test("로드 → 편집 → Patch → 변경 없음 → 뒤로가기 → 앞으로가기 → 목록 이동", async () => {
    const frame = await loadFrame({ src: "../index.html" });
    const win = frame.contentWindow;
    const doc = frame.contentDocument;
    const $ = (id) => doc.getElementById(id);
    await waitFor(() => $("status").textContent.length > 0);

    const MARK = "통합 테스트 항목";
    const realHasMark = () => $("real-area").textContent.includes(MARK);
    const position = () => $("position-label").textContent;
    const matches = () => $("status").textContent.includes("일치합니다");

    // R1 · R2: 로드 직후 테스트 영역이 실제 영역과 같은 내용으로 그려지고 History 1개
    // textContent 로 비교하면 실제 영역 HTML 의 들여쓰기 공백까지 비교되므로, VDOM 끼리 비교한다
    assertEqual(containerToVdom($("test-area")), containerToVdom($("real-area")), "로드 직후 두 영역의 VDOM");
    assert($("test-source").value.includes("\n"), "소스 편집기가 들여쓴 HTML 이어야 함");
    assertEqual($("history-list").children.length, 1, "초기 History 개수");
    assert(!doc.querySelector(".startup-error"), "정상 페이지에서는 시작 오류가 없어야 함");

    // R3 · R4 ~ R7: 소스 편집기에서 목록 항목 추가 → Patch
    const source = $("test-source");
    source.value = source.value.replace("</ul>", `<li>${MARK}</li></ul>`);
    source.dispatchEvent(new win.Event("input"));
    assert($("test-area").textContent.includes(MARK), "소스 편집 → 미리보기 반영");
    assert(!realHasMark(), "Patch 전에는 실제 영역이 그대로");
    $("patch-btn").click();
    assert(realHasMark(), "Patch 후 실제 영역에 반영");
    assert(matches(), `실제 영역 = VDOM: ${$("status").textContent}`);
    assertEqual($("history-list").children.length, 2, "Patch 후 History 개수");

    // 아무것도 안 바꾸고 Patch → 변경 없음, History 그대로
    $("patch-btn").click();
    assert($("status").textContent.includes("변경 없음"), "변경 없음 안내");
    assertEqual($("history-list").children.length, 2, "변경 없음이면 저장하지 않음");

    // R8: 뒤로가기 → 실제 · 테스트 영역 모두 이전 상태
    $("undo-btn").click();
    assert(!realHasMark() && !$("test-area").textContent.includes(MARK), "뒤로가기 후 두 영역 모두 이전 상태");
    assert(matches(), "뒤로가기 후 일치");
    assert($("undo-btn").disabled, "처음 기록에서는 뒤로가기 꺼짐");

    // 앞으로가기 → 다시 반영
    $("redo-btn").click();
    assert(realHasMark() && $("test-area").textContent.includes(MARK), "앞으로가기 후 두 영역 모두 반영");
    assert($("redo-btn").disabled, "마지막 기록에서는 앞으로가기 꺼짐");

    // History 목록의 1번 기록 클릭 → 처음 상태로 이동
    $("history-list").querySelector("button").click();
    assert(!realHasMark(), "목록 클릭으로 처음 상태로 이동");
    assert(position().startsWith("현재 위치: 1 /"), `위치 표시: ${position()}`);
    assert(matches(), "목록 이동 후 일치");

    frame.remove();
  });
});
