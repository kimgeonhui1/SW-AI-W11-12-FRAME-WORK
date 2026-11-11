// [yut.test.js] 초능력 윷놀이 규칙(yut.js) 단위 테스트 + 실제 App에서 클릭으로 두어 보는 기능 테스트

import { FunctionComponent } from "../src/core/component.js";
import { HOME, END, routeFrom, destination, throwSticks, resolveThrow, initialState, apply, movableFrom, makeOffers, POWERS } from "../src/app/yut.js";
import { App } from "../src/app/App.js";

const tests = [];
const test = (name, fn) => tests.push({ name, fn });
const tick = () => new Promise((resolve) => setTimeout(resolve));

function assertEqual(actual, expected, msg = "") {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${msg}\n  기대: ${e}\n  실제: ${a}`);
}
function assertThrows(fn, msg) {
  try {
    fn();
  } catch {
    return;
  }
  throw new Error(`에러가 나야 함: ${msg}`);
}

// 초능력을 고른 뒤 던지기 직전 상태. pieces로 말 위치를 직접 놓는다 (주사위 없이 규칙만 확인하려고)
const OFFERS = { 홍: { yut: ["three", "back"], mal: ["recall", "swap"] }, 청: { yut: ["small", "big"], mal: ["trap", "shield"] } };
// 고를 초능력이 후보에 들어 있게 후보를 만든다 (두 번째 후보는 아무거나)
const offersFor = (yut, mal) => ({ yut: [yut, yut === "back" ? "three" : "back"], mal: [mal, mal === "swap" ? "recall" : "swap"] });
function ready({ 홍 = {}, 청 = {}, pieces } = {}) {
  const pick = { 홍: [홍.yut ?? "three", 홍.mal ?? "recall"], 청: [청.yut ?? "small", 청.mal ?? "trap"] };
  let s = initialState({ 홍: offersFor(...pick.홍), 청: offersFor(...pick.청) });
  s = apply(s, { type: "pick", team: "홍", yut: pick.홍[0], mal: pick.홍[1] });
  s = apply(s, { type: "pick", team: "청", yut: pick.청[0], mal: pick.청[1] });
  if (pieces) s.pieces = { 홍: [...pieces.홍, ...Array(4 - pieces.홍.length).fill(HOME)], 청: [...pieces.청, ...Array(4 - pieces.청.length).fill(HOME)] };
  return s;
}
const run = (s, ...actions) => actions.reduce(apply, s);

// ── 판 · 길 ──

test("길: 출발 전 말은 o1부터, 바깥은 한 칸씩, 모서리를 지나가면 지름길로 가지 않음", () => {
  assertEqual([destination(HOME, "도"), destination("o4", "걸"), destination("o13", "개")], ["o1", "o7", "o15"]);
});
test("지름길: 모서리 · 방에 멈춘 뒤 출발하면 지름길, 방을 지나가면 곧장 건너편으로", () => {
  assertEqual(destination("o5", "도"), "a1", "o5에서 출발 → 지름길");
  assertEqual(destination("o5", "모"), "c2", "o5 → 방 → 건너편");
  assertEqual(destination("o10", "걸"), "C", "o10 → 방");
  assertEqual(destination("C", "도"), "g1", "방에서 출발 → 참먹이 쪽");
  assertEqual(destination("a2", "개"), "c1", "방을 지나가면 o15 쪽");
  assertEqual(destination("b2", "개"), "g1", "왼쪽 위 지름길은 방을 지나 참먹이 쪽");
});
test("나기: 참먹이(o0)에 멈추면 아직 판 위, 지나가거나 참먹이에서 출발하면 남", () => {
  assertEqual([destination("o19", "도"), destination("o19", "개"), destination("o0", "도"), destination("g2", "모")], ["o0", END, END, END]);
});
test("빽도: 뒤로 한 칸 (지름길 · 첫 칸 포함), 출발 전 말은 못 감", () => {
  assertEqual([destination("o1", "빽도"), destination("a1", "빽도"), destination("o7", "빽도"), destination(HOME, "빽도")], ["o0", "o5", "o6", null]);
});
test("길 목록은 언제나 END로 끝남 (모든 칸)", () => {
  for (const pos of [HOME, "o0", "o3", "o5", "o10", "o15", "o19", "a1", "a2", "C", "c1", "c2", "b1", "b2", "g1", "g2"]) {
    if (routeFrom(pos).at(-1) !== END) throw new Error(`${pos}의 길이 END로 끝나지 않음`);
  }
});

// ── 윷 ──

test("막대 던지기: 평평한 면 수로 결과, 1번 막대만 평평하면 빽도", () => {
  const seq = (...v) => {
    let i = 0;
    return () => v[i++];
  };
  assertEqual(
    [throwSticks(seq(0, 0, 0, 0)).name, throwSticks(seq(1, 1, 1, 1)).name, throwSticks(seq(0, 1, 1, 1)).name, throwSticks(seq(1, 0, 1, 1)).name, throwSticks(seq(0, 0, 1, 1)).name, throwSticks(seq(0, 0, 0, 1)).name],
    ["윷", "모", "빽도", "도", "개", "걸"]
  );
});
test("윷 · 모는 한 번 더 던지고, 결과가 쌓임 (모두 던진 뒤에 옮김)", () => {
  const s = run(ready(), { type: "throw", name: "윷" });
  assertEqual([s.phase, s.pending], ["throw", ["윷"]]);
  const s2 = run(s, { type: "throw", name: "걸" });
  assertEqual([s2.phase, s2.pending], ["move", ["윷", "걸"]]);
});
test("처음에 빽도: 판에 말이 없어 쓸 수 없으면 버리고 차례가 넘어감", () => {
  const s = run(ready(), { type: "throw", name: "빽도" });
  assertEqual([s.turn, s.phase, s.pending], ["청", "throw", []]);
});

// ── 옮기기 · 업기 · 잡기 · 승리 ──

test("업기: 내 말이 있는 칸에 멈추면 함께 다니고, 다음엔 같이 움직임", () => {
  let s = ready({ pieces: { 홍: ["o2"], 청: [] } });
  s = run(s, { type: "throw", name: "개" }, { type: "move", from: HOME, index: 0 });
  assertEqual(s.pieces.홍.filter((p) => p === "o2").length, 2, "o2에 두 말");
  s.turn = "홍";
  s = run({ ...s, phase: "throw", throwsLeft: 1 }, { type: "throw", name: "걸" }, { type: "move", from: "o2", index: 0 });
  assertEqual(s.pieces.홍.filter((p) => p === "o5").length, 2, "업힌 두 말이 함께 o5로");
});
test("잡기: 상대 말(업힌 것 전부)이 출발점으로, 한 번 더 던짐", () => {
  let s = ready({ pieces: { 홍: ["o1"], 청: ["o3", "o3"] } });
  s = run(s, { type: "throw", name: "개" }, { type: "move", from: "o1", index: 0 });
  assertEqual([s.pieces.청.filter((p) => p === HOME).length, s.phase, s.turn], [4, "throw", "홍"]);
});
test("말 4개를 모두 내면 승리", () => {
  let s = ready({ pieces: { 홍: [END, END, END, "o19"], 청: [] } });
  s = run(s, { type: "throw", name: "개" }, { type: "move", from: "o19", index: 0 });
  assertEqual([s.phase, s.winner], ["over", "홍"]);
});
test("규칙에 안 맞는 action은 에러 (남의 차례 고르기, 옮길 수 없는 말)", () => {
  assertThrows(() => apply(initialState(OFFERS), { type: "pick", team: "청", yut: "small", mal: "trap" }), "홍이 먼저 고름");
  const s = run(ready(), { type: "throw", name: "도" });
  assertThrows(() => apply(s, { type: "move", from: "o5", index: 0 }), "말이 없는 칸");
});

// ── 초능력 ──

test("초능력 후보: 팀마다 윷의 힘 2개 · 말의 힘 2개, 서로 다르고 종류가 맞음", () => {
  for (let k = 0; k < 50; k++) {
    const offers = makeOffers(Math.random);
    for (const t of ["홍", "청"]) {
      const { yut, mal } = offers[t];
      if (yut[0] === yut[1] || mal[0] === mal[1] || !yut.every((id) => POWERS[id].kind === "yut") || !mal.every((id) => POWERS[id].kind === "mal")) throw new Error(JSON.stringify(offers));
    }
  }
});
test("윷의 힘: 켜면 다음 던지기 결과가 정해지고, 한 번만 쓸 수 있음", () => {
  const s = run(ready({ 홍: { yut: "three" } }), { type: "arm" });
  assertEqual([s.armed, resolveThrow(s, Math.random).name], ["three", "걸"]);
  const s2 = run(s, { type: "throw", name: "걸" });
  assertEqual(s2.armed, null, "던지면 꺼짐");
  assertThrows(() => apply({ ...run(s2, { type: "move", from: HOME, index: 0 }), turn: "홍", phase: "throw" }, { type: "arm" }), "두 번째 사용");
});
test("윷의 힘: 소심한 손목은 도·개, 모 아니면 윷은 윷·모, 빽 투 더 퓨처는 빽도", () => {
  const names = (id) => new Set(Array.from({ length: 40 }, () => resolveThrow({ armed: id }, Math.random).name));
  assertEqual([[...names("small")].sort(), [...names("big")].sort(), [...names("back")]], [["개", "도"], ["모", "윷"], ["빽도"]]);
});
test("한 판만 더요(두 번 던지기): 두 결과 중 하나를 골라 그 결과로 진행", () => {
  let s = run(ready({ 홍: { yut: "twice" } }), { type: "arm" });
  s = run(s, { type: "throw2", choices: ["도", "걸"] });
  assertEqual([s.phase, s.choices], ["choose", ["도", "걸"]]);
  s = run(s, { type: "choose", index: 1 });
  assertEqual([s.phase, s.pending], ["move", ["걸"]]);
});
test("말의 힘 · 집으로: 상대 말(업힌 것 전부)을 출발점으로", () => {
  const s = run(ready({ 홍: { mal: "recall" }, pieces: { 홍: [], 청: ["o7", "o7"] } }), { type: "mal", targets: ["o7"] });
  assertEqual([s.pieces.청.every((p) => p === HOME), s.powers.홍.malUsed, s.phase], [true, true, "throw"]);
});
test("말의 힘 · 님 자리 제가 앉을게요(자리 맞바꾸기): 내 말과 상대 말의 자리가 바뀜", () => {
  const s = run(ready({ 홍: { mal: "swap" }, pieces: { 홍: ["o2"], 청: ["C"] } }), { type: "mal", targets: ["o2", "C"] });
  assertEqual([s.pieces.홍[0], s.pieces.청[0]], ["C", "o2"]);
});
test("말의 힘 · 함정: 그 칸에 멈춘 상대 말은 출발점으로, 함정은 한 번 쓰면 사라짐", () => {
  let s = ready({ pieces: { 홍: [], 청: [] } });
  s.turn = "청";
  s = run(s, { type: "mal", targets: ["o3"] });
  assertEqual(s.traps, { o3: "청" });
  s.turn = "홍";
  s = run(s, { type: "throw", name: "걸" }, { type: "move", from: HOME, index: 0 });
  assertEqual([s.pieces.홍[0], s.traps], [HOME, {}]);
});
test("말의 힘 · 택시 잡기(지름길): 바깥 길의 내 말을 바로 앞 모서리로 (모서리 위의 말은 안 됨)", () => {
  const s = ready({ 홍: { mal: "shortcut" }, pieces: { 홍: ["o7"], 청: [] } });
  assertEqual(run(s, { type: "mal", targets: ["o7"] }).pieces.홍[0], "o10");
  s.pieces.홍[0] = "o5";
  assertThrows(() => apply(s, { type: "mal", targets: ["o5"] }), "모서리 위의 말");
});
test("말의 힘 · 방패: 상대의 다음 차례 동안 그 말이 있는 칸에 멈출 수 없음, 내 차례가 오면 풀림", () => {
  let s = ready({ pieces: { 홍: ["o1"], 청: ["o3"] } });
  s.turn = "청";
  s.powers.청.mal = "shield";
  s = run(s, { type: "mal", targets: [] }, { type: "throw", name: "도" }, { type: "move", from: "o3", index: 0 }); // 청 o3 → o4
  assertEqual([s.turn, s.shield.청], ["홍", true]);
  s = run(s, { type: "throw", name: "걸" }); // 홍 o1 + 걸 = o4 (방패) → 그 말은 못 옮김
  assertEqual(movableFrom(s, "걸").includes("o1"), false);
  s = run(s, { type: "move", from: HOME, index: 0 }); // 새 말로 걸
  assertEqual([s.turn, s.shield.청], ["청", false], "청 차례가 오면 방패가 풀림");
});
test("말의 힘 · 다리에 쥐 났다(한 차례 쉬기): 상대가 다음 차례를 한 번 쉼", () => {
  let s = ready({ 홍: { mal: "freeze" } });
  s = run(s, { type: "mal", targets: [] }, { type: "throw", name: "도" }, { type: "move", from: HOME, index: 0 });
  assertEqual([s.turn, s.skip.청], ["홍", false], "청이 쉬고 다시 홍 차례");
});

// ── 앱 (실제 App을 마운트해서 클릭) ──

// 결과를 정해 둔 random: 값을 차례로 돌려줌. 0.5 미만이면 그 막대는 평평한 면 (예: [0,0,0,0.9] → 걸)
function scripted(values) {
  let i = 0;
  return () => values[i++ % values.length];
}
function mountApp(random) {
  const box = document.createElement("div");
  document.body.appendChild(box);
  const inst = new FunctionComponent(App, box, { random }).mount();
  const q = (sel) => box.querySelector(sel);
  const button = (text, root = box) => [...root.querySelectorAll("button")].find((b) => b.textContent.includes(text));
  const close = () => (inst.unmount(), box.remove());
  // 두 팀 모두 첫 번째 후보를 고른다
  const pickFirst = async () => {
    for (let k = 0; k < 2; k++) {
      for (const group of box.querySelectorAll(".power-pick .choices")) group.querySelector("button").click();
      await tick();
      button("이걸로 시작").click();
      await tick();
    }
  };
  return { box, q, button, close, pickFirst };
}

test("시작: 홍 → 청 순서로 윷의 힘 · 말의 힘을 후보 2개 중에서 고르고, 고르면 홍 차례", async () => {
  const app = mountApp(Math.random);
  assertEqual([app.q(".power-pick h2").textContent, app.box.querySelectorAll(".power-pick .choices button").length], ["홍팀 초능력 고르기", 4]);
  assertEqual(app.button("이걸로 시작").disabled, true, "둘 다 고르기 전에는 시작 못 함");
  await app.pickFirst();
  assertEqual([app.q(".power-pick"), app.q(".yut-status .message").textContent], [null, "홍 차례 · 윷을 던지세요"]);
  app.close();
});
test("던지기 → 말 고르기 → 표시된 칸 누르기: 갈 곳에 결과 이름이 뜨고, 누르면 옮겨져 기보에 남음", async () => {
  const app = mountApp(scripted([0, 0, 0, 0.9])); // 막대 3개 평평 → 걸 (random은 1 미만)
  await app.pickFirst();
  app.button("윷 던지기").click();
  await tick();
  assertEqual(app.q(".throw-result .name").textContent, "걸");
  const sticks = app.q(".sticks");
  assertEqual(sticks.classList.contains("toss"), true, "던진 막대는 애니메이션 클래스");
  // 출발 전 말을 고르면 갈 수 있는 칸(o3)만 표시되고, 다시 누르면 취소
  app.q(".team.홍 .home-pile").click();
  await tick();
  assertEqual([app.q(".team.홍 .home-pile").classList.contains("chosen"), [...app.box.querySelectorAll(".node.dest")].map((n) => n.dataset.node), app.q(".dest-tag").textContent], [true, ["o3"], "걸 ▼"]);
  app.q(".team.홍 .home-pile").click();
  await tick();
  assertEqual(app.box.querySelectorAll(".node.dest").length, 0, "다시 누르면 고르기 취소");
  app.q(".team.홍 .home-pile").click();
  await tick();
  app.q('.node[data-node="o3"]').click();
  await tick();
  assertEqual([app.q('.node[data-node="o3"] .token.홍')?.textContent, app.q(".yut-status .message").textContent], ["", "청 차례 · 윷을 던지세요"]);
  assertEqual(app.q(".yut-log li:last-child").textContent, "홍: 걸로 출발 전 → 바깥 3");
  // 다음 던지기: 막대 묶음의 key(던진 횟수)가 바뀌어 새 노드가 되므로 애니메이션이 처음부터 다시 돈다
  app.button("윷 던지기").click();
  await tick();
  assertEqual(app.q(".sticks") !== sticks, true, "던질 때마다 막대 묶음을 새로 만듦");
  app.close();
});

// ── 실행 ──
const results = [];
for (const { name, fn } of tests) {
  try {
    await fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, message: e.message });
  }
}
const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const passed = results.filter((r) => r.ok).length;
document.getElementById("results").innerHTML =
  `<h2>${passed} / ${results.length} passed</h2>` +
  results.map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`).join("");
console.table(results);
