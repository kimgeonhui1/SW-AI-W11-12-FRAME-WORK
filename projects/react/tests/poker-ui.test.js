import { FunctionComponent } from "../src/core/component.js";
import { PokerApp } from "../src/poker/PokerApp.js";

const root = document.getElementById("root");
const profile = { displayName: "네온 플레이어", practice: { hands: 0, wins: 0, losses: 0, draws: 0 }, recentGames: [] };
const base = { matchKey: "ui-fixture", handNo: 1, button: "human", phase: "flop", turn: "human", humanStack: 960, botStack: 960, pot: 80, humanCards: ["A♠", "K♥"], botCards: [], botCardsRevealed: false, board: ["2♠", "3♥", "4♦"], legalActions: ["fold", "check", "bet", "all_in"], minRaiseTo: 20, maxRaiseTo: 960, toCall: 0, actions: [], handOver: false, matchOver: false, recordStatus: "not_saved", message: "테스트 상태" };
const tick = () => new Promise(resolve => setTimeout(resolve, 20));
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const button = text => [...root.querySelectorAll(".controls button")].find(node => node.textContent.includes(text));
let instance;
const mount = (game = base, request = async () => ({}), traces = []) => {
  instance?.unmount();
  instance = new FunctionComponent(PokerApp, root, { profile, initialGame: structuredClone(game), request, initialTraces: traces }).mount();
};
const results = [];
async function test(name, fn) { try { await fn(); results.push({ name, ok: true }); } catch (error) { results.push({ name, ok: false, message: error.message }); } }

await test("프로필·서버 잔액·포지션과 사용자 하단 배치", async () => {
  mount();
  assert(root.querySelector(".seat-human .seat-name").textContent === "네온 플레이어 · YOU", "profile name");
  assert(root.querySelector(".pot-value").textContent === "80", "pot");
  assert(root.querySelector(".seat-human .stack-line strong").textContent === "960", "stack");
  assert(root.querySelector(".seat-human .position-badge").textContent === "D · SB", "position");
  assert(root.querySelector(".seat-human").getBoundingClientRect().top > root.querySelector(".seat-bot").getBoundingClientRect().bottom, "seat order");
});
await test("칩이 0일 때 금색 칩 스택을 표시하지 않음", async () => {
  mount({ ...base, pot: 0, humanStack: 0 });
  assert(!root.querySelector(".center-felt .gold-chip"), "zero pot chips");
  assert(!root.querySelector(".seat-human .gold-chip"), "zero stack chips");
});
await test("동일 이벤트 루프의 빠른 클릭은 한 요청만 전송", async () => {
  let calls = 0, resolve;
  mount(base, () => { calls++; return new Promise(r => { resolve = r; }); });
  const check = button("체크"); check.click(); check.click();
  assert(calls === 1, "duplicate request");
  resolve({ game: { ...base, phase: "turn", board: [...base.board, "5♣"] } }); await tick();
  assert(!button("체크").disabled, "busy not released");
});
await test("스트리트 진행 시 기존 카드 DOM과 애니메이션 ID 유지", async () => {
  mount(base, async () => ({ game: { ...base, phase: "turn", board: [...base.board, "5♣"] } }));
  const first = root.querySelector(".community-cards .playing-card");
  button("체크").click(); await tick();
  assert(first === root.querySelector(".community-cards .playing-card"), "existing board remounted");
  assert(root.querySelectorAll(".community-cards .card-reveal").length === 4, "turn card missing");
});
await test("새 핸드에서는 같은 카드라도 새 DOM과 새 액션 애니메이션", async () => {
  const done = { ...base, handOver: true, actions: [{ player: "human", paid: 40 }, { player: "bot", paid: 40 }] };
  mount(done, async () => ({ game: { ...base, handNo: 2, board: [], button: "bot", actions: [{ player: "bot", paid: 10 }] } }));
  const first = root.querySelector(".seat-human .playing-card");
  button("다음 핸드").click(); await tick();
  assert(first !== root.querySelector(".seat-human .playing-card"), "new hand reused cards");
  assert(root.querySelectorAll(".chip-flight").length === 1, "new hand action incorrectly sliced");
  assert(root.querySelector(".seat-human .position-badge").textContent === "BB", "button not updated");
});
await test("UNKNOWN 오류는 서버 상태와 같은 요청 재시도 ID 유지", async () => {
  const calls = [];
  mount(base, async (path, body) => { calls.push(body); if (calls.length === 1) throw Object.assign(new Error("저장 확인 필요"), { status: 503, payload: { game: { ...base, pot: 0, handOver: true, recordStatus: "unknown", humanStack: 1000, botStack: 1000 } } }); return { game: { ...base, handOver: true, recordStatus: "unknown" } }; });
  button("올인").click(); await tick();
  assert(button("같은 요청 재시도"), "retry missing");
  assert(root.querySelector(".pot-value").textContent === "0", "server error state lost");
  assert(button("다음 핸드").disabled, "advanced unknown result");
  button("같은 요청 재시도").click(); await tick();
  assert(calls[0].action_id === calls[1].action_id, "retry ID changed");
});
await test("4xx 거부 이후 입력 잠금 해제 및 서버 상태 유지", async () => {
  mount(base, async () => { throw Object.assign(new Error("invalid wager"), { status: 400 }); });
  button("베팅").click(); await tick();
  assert(!button("베팅").disabled && !button("같은 요청 재시도"), "error stuck controls");
  assert(root.querySelector(".pot-value").textContent === "80", "optimistic pot mutation");
});
await test("200개 trace가 페이지나 Inspector 높이를 늘리지 않음", async () => {
  mount(); const height = root.querySelector(".inspector").getBoundingClientRect().height; const page = document.documentElement.scrollHeight;
  const traces = Array.from({ length: 200 }, (_, i) => ({ traceId: "trace-" + i, service: "Mini DBMS", method: "POST", path: "/sql", outcome: "ok", status: 200 }));
  mount(base, undefined, traces);
  assert(Math.abs(root.querySelector(".inspector").getBoundingClientRect().height - height) < 1, "inspector grew");
  assert(Math.abs(document.documentElement.scrollHeight - page) < 2, "page grew");
  const list = root.querySelector(".trace-list"); assert(list.scrollHeight > list.clientHeight, "missing inner scroll");
});
await test("가로 넘침 없이 모바일 조작부와 HUD 배치", async () => {
  mount();
  assert(document.documentElement.scrollWidth <= innerWidth, "horizontal overflow");
  const board=root.querySelector(".community-cards").getBoundingClientRect(), human=root.querySelector(".seat-human").getBoundingClientRect(), bot=root.querySelector(".seat-bot").getBoundingClientRect();
  assert(board.top > bot.bottom && board.bottom < human.top, "HUD overlaps board");
  const controls=root.querySelector(".controls").getBoundingClientRect();
  assert(controls.left >= 0 && controls.right <= innerWidth, "controls clipped");
});
instance?.unmount();
window.pokerUIResults = results;
document.getElementById("results").textContent = JSON.stringify(results, null, 2);
