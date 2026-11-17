// [room-logic.test.js] 멀티플레이 화면 로직 테스트 — 브라우저(room-logic.test.html)와 node(node tests/room-logic.test.js) 둘 다에서 실행
import * as L from "../src/poker/roomLogic.js";

const results = [];
const eq = (a, b, message) => { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(message + ": " + JSON.stringify(a) + " != " + JSON.stringify(b)); };
function test(name, fn) { try { fn(); results.push({ name, ok: true }); } catch (error) { results.push({ name, ok: false, message: error.message }); } }

const seat = (index, extra = {}) => ({ seat: index, name: index ? "Bravo" : "Alpha", stack: 980, committed: 20, isButton: index === 0, ...extra });
const state = (extra = {}) => ({ handNo: 1, board: ["Q♠", "J♠", "T♠"], pot: 40, seats: [seat(0), seat(1)], events: [], lastEventSeq: 5, ...extra });
const ev = (seq, extra = {}) => ({ seq, type: "action", handNo: 1, board: [], pot: 40, stacks: [980, 980], committed: [20, 20], seat: 0, action: "call", paid: 10, auto: false, ...extra });

test("본인 좌석이 아래, 나머지는 테이블 순서대로 왼쪽 → 위 → 오른쪽", () => {
  const spots = (you, cap) => L.seatLayout(you, cap).map((s) => s.seat + s.where[0]).join(" ");
  eq([spots(0, 2), spots(1, 2)], ["0b 1t", "1b 0t"], "2인: 상대가 위");
  eq([spots(0, 3), spots(2, 3)], ["0b 1l 2r", "2b 0l 1r"], "3인");
  eq([spots(0, 4), spots(1, 4), spots(3, 4)], ["0b 1l 2t 3r", "1b 2l 3t 0r", "3b 0l 1t 2r"], "4인");
  for (const cap of [2, 3, 4]) for (let you = 0; you < cap; you += 1) {
    eq(L.seatLayout(you, cap).map((s) => s.seat).sort(), Array.from({ length: cap }, (_, i) => i), "모든 좌석이 한 번씩 " + cap + "/" + you);
  }
});
test("칩 이동 경로는 좌석 화면 위치를 따른다", () => {
  const where = { 0: "bottom", 1: "left", 2: "top", 3: "right" };
  eq(L.flightPath({ from: 1, to: "pot" }, where), { "--fx": "22%", "--fy": "45%", "--tx": "72%", "--ty": "50%" }, "left → pot");
  eq(L.flightPath({ from: "pot", to: 3 }, where), { "--fx": "72%", "--fy": "50%", "--tx": "88%", "--ty": "36%" }, "pot → right");
});
test("서버 상태 그대로의 표시 상태", () => {
  const d = L.displayFromState(state());
  eq([d.board, d.pot, d.stacks, d.committed, d.synced], [["Q♠", "J♠", "T♠"], 40, [980, 980], [20, 20], true], "display");
});
test("이벤트는 그 순간의 칩·팟·보드를 그대로 보여 준다", () => {
  const start = L.displayFromState(state({ board: [], pot: 30, seats: [seat(0, { stack: 990, committed: 10 }), seat(1)] }));
  const d = L.applyEvent(start, ev(2));
  eq([d.pot, d.stacks, d.synced], [40, [980, 980], false], "after call");
  eq(d.flight, { id: "f2", from: 0, to: "pot", amount: 10 }, "chips fly from the actor to the pot");
  eq(d.last.action, "call", "last action");
  eq(start.pot, 30, "원본 표시 상태는 바뀌지 않는다");
  const checked = L.applyEvent(d, ev(3, { seat: 1, action: "check", paid: 0 }));
  eq(checked.flight, null, "no chips for a check");
  const street = L.applyEvent(checked, ev(4, { type: "street", board: ["Q♠", "J♠", "T♠"] }));
  eq([street.board.length, street.last.action], [3, "check"], "street keeps last action");
  const end = L.applyEvent(street, ev(5, { type: "hand_end", pot: 0, stacks: [980, 1020], committed: [0, 0], winnerSeat: 1, potWon: 40 }));
  eq([end.pot, end.stacks, end.flight.to], [0, [980, 1020], 1], "pot goes to the winner at hand_end");
  const tie = L.applyEvent(street, ev(5, { type: "hand_end", pot: 0, stacks: [1000, 1000], committed: [0, 0], winnerSeat: null, potWon: 40 }));
  eq(tie.flight, null, "tie has no single flight");
});
test("재생을 모두 적용하면 서버 상태와 같아진다", () => {
  const events = [ev(1, { type: "hand_start", pot: 30, stacks: [990, 980], committed: [10, 20] }), ev(2), ev(3, { seat: 1, action: "check", paid: 0 }),
    ev(4, { type: "street", board: ["Q♠", "J♠", "T♠"] })];
  const final = state({ events, lastEventSeq: 4 });
  let d = L.displayFromState(state({ board: [], pot: 0, handNo: 0, seats: [seat(0, { stack: 1000, committed: 0 }), seat(1, { stack: 1000, committed: 0 })] }));
  for (const event of L.planUpdate(0, final, true).events) d = L.applyEvent(d, event);
  const target = L.displayFromState(final);
  eq([d.board, d.pot, d.stacks, d.committed], [target.board, target.pot, target.stacks, target.committed], "converges");
});
test("이어지는 이벤트만 재생하고, 아니면 바로 맞춘다", () => {
  eq(L.planUpdate(1, state({ events: [ev(2), ev(3)], lastEventSeq: 3 }), true).mode, "replay", "contiguous");
  eq(L.planUpdate(1, state({ events: [ev(3), ev(2)], lastEventSeq: 3 }), true).events.map((e) => e.seq), [2, 3], "sorted");
  eq(L.planUpdate(1, state({ events: [ev(1), ev(2)], lastEventSeq: 2 }), true).events.map((e) => e.seq), [2], "already seen events are skipped");
  eq(L.planUpdate(1, state({ events: [ev(3)], lastEventSeq: 3 }), true).mode, "snap", "gap");
  eq(L.planUpdate(1, state({ events: [ev(2)], lastEventSeq: 3 }), true).mode, "snap", "does not reach the latest event");
  eq(L.planUpdate(0, state({ events: [ev(1)], lastEventSeq: 1 }), false).mode, "snap", "first load / refresh");
  eq(L.planUpdate(3, state({ events: [], lastEventSeq: 3 }), true).mode, "snap", "nothing new");
  const many = Array.from({ length: L.MAX_REPLAY_EVENTS + 1 }, (_, i) => ev(i + 1));
  eq(L.planUpdate(0, state({ events: many, lastEventSeq: many.length }), true).mode, "snap", "too far behind");
});
test("표시 문구와 입력 보정", () => {
  eq(L.actionText({ seat: 1, action: "raise", paid: 60, auto: false }, ["Alpha", "Bravo"]), "Bravo · 레이즈 60", "action text");
  eq(L.actionText({ seat: 0, action: "fold", paid: 0, auto: true }, ["Alpha", "Bravo"]), "Alpha · 폴드 (시간 초과 자동)", "auto text");
  eq(L.actionText(null, []), "", "no action");
  eq([L.positionLabel({ isButton: true, isSmallBlind: true }), L.positionLabel({ isBigBlind: true }), L.positionLabel({ isButton: true }), L.positionLabel({})],
    ["D · SB", "BB", "D", ""], "position");
  eq([L.potsText([{ amount: 40 }]), L.potsText([{ amount: 2800 }, { amount: 300 }, { amount: 200 }])], ["", "메인 2,800 · 사이드1 300 · 사이드2 200"], "pots");
  eq(L.normalizeCode(" ab-c2 3xyz"), "ABC23X", "code");
  eq([L.clampWager("55.4", 40, 980), L.clampWager(5, 40, 980), L.clampWager(5000, 40, 980), L.clampWager("x", 40, 980)], [55, 40, 980, 40], "wager");
  eq([L.validName(" 지원 "), L.validName(""), L.validName("x".repeat(25)), L.validName("a\nb")], [true, false, false, false], "name");
  eq([L.remainingSeconds(30000, 1000, 1000), L.remainingSeconds(30000, 1000, 12500), L.remainingSeconds(1000, 0, 9000), L.remainingSeconds(null, 0, 0)], [30, 19, 0, null], "timer");
  eq([L.eventDelay(ev(1)) > 0, L.eventDelay(ev(1, { type: "street" })) > 0], [true, true], "delays");
});
test("여러 팟의 결과와 돌려받은 칩", () => {
  const names = ["Alpha", "Bravo", "Carol", "Delta"];
  const showdown = { reason: "showdown", pot: 3300, winnerSeat: null, payouts: [2800, 0, 300, 200], hands: ["원 페어", "하이 카드", "원 페어", "원 페어"],
    pots: [{ amount: 2800, winners: [0] }, { amount: 300, winners: [2] }, { amount: 200, winners: [3] }] };
  eq(L.resultText(showdown, names, 2), "승리 +300 · 메인 2,800 → Alpha(원 페어) · 사이드1 300 → Carol(원 페어) · 사이드2 200 → Delta(원 페어)", "side pots");
  eq(L.resultText(showdown, names, 1).startsWith("패배 · 메인 2,800"), true, "loser");
  eq(L.resultText(showdown, names, 1, false).startsWith("메인 2,800"), true, "spectator gets no outcome word");
  const split = { reason: "showdown", pot: 135, winnerSeat: null, payouts: [0, 68, 67], hands: null, pots: [{ amount: 135, winners: [1, 2] }] };
  eq([L.resultText(split, names, 0), L.resultText(split, names, 2)], ["패배 · 팟 135 → Bravo, Carol 분배", "무승부 +67 · 팟 135 → Bravo, Carol 분배"], "split");
  const fold = { reason: "fold", pot: 30, winnerSeat: 0, payouts: [30, 0, 0], pots: [{ amount: 30, winners: [0] }] };
  eq([L.resultText(fold, names, 0), L.resultText(fold, names, 1)], ["승리 · Alpha +30 · 나머지 모두 폴드", "패배 · Alpha +30 · 나머지 모두 폴드"], "fold");
  const start = L.displayFromState(state({ pots: [{ amount: 40, eligible: [0, 1] }] }));
  eq(start.pots, [{ amount: 40, eligible: [0, 1] }], "pots from state");
  const back = L.applyEvent(start, ev(9, { type: "returned", seat: 3, amount: 700, pots: [{ amount: 2800, eligible: [0, 1] }] }));
  eq([back.flight.from, back.flight.to, back.flight.amount, back.pots.length], ["pot", 3, 700, 1], "unmatched chips fly back");
  const end = L.applyEvent(back, ev(10, { type: "hand_end", winnerSeat: null, potWon: 3300, pots: [{ amount: 2800, eligible: [0], winners: [0] }] }));
  eq([end.flight, end.pots], [null, []], "split payout has no single flight");
});
test("API 주소는 페이지를 연 호스트를 따른다", () => {
  eq(L.resolveApiBase({ search: "", protocol: "http:", hostname: "192.168.0.7" }, ""), "http://192.168.0.7:18784", "LAN host");
  eq(L.resolveApiBase({ search: "", protocol: "http:", hostname: "127.0.0.1" }, ""), "http://127.0.0.1:18784", "local");
  eq(L.resolveApiBase({ search: "?api=http://10.0.0.5:9000/", protocol: "http:", hostname: "x" }, "http://meta:1"), "http://10.0.0.5:9000", "query wins");
  eq(L.resolveApiBase({ search: "", protocol: "http:", hostname: "x" }, " http://meta:1/ "), "http://meta:1", "meta");
  eq([L.guestStorageKey(""), L.guestStorageKey("?guest=2"), L.guestStorageKey("?guest=<b>")], ["jungle-poker-lab.guest.v1", "jungle-poker-lab.guest.v1.2", "jungle-poker-lab.guest.v1.b"], "guest key");
});
test("보기 설정은 허용된 값만, 저장소가 막혀도 기본값", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  eq(L.readPref(storage, L.VIEW_PREF), "3d", "default");
  L.writePref(storage, L.VIEW_PREF, "2d");
  eq(L.readPref(storage, L.VIEW_PREF), "2d", "saved");
  L.writePref(storage, L.VIEW_PREF, "4d");
  eq(L.readPref(storage, L.VIEW_PREF), "2d", "invalid value ignored");
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  eq([L.readPref(broken, L.BLOOM_PREF), L.readPref(undefined, L.BLOOM_PREF)], ["off", "off"], "blocked storage");
  L.writePref(broken, L.BLOOM_PREF, "on");
});

const failed = results.filter((r) => !r.ok);
const summary = (results.length - failed.length) + "/" + results.length + " 통과";
if (typeof document !== "undefined") {
  document.body.insertAdjacentHTML("beforeend", "<h1>room-logic: " + summary + "</h1><ul>" + results.map((r) => "<li>" + (r.ok ? "✅ " : "❌ ") + r.name + (r.ok ? "" : " — " + r.message) + "</li>").join("") + "</ul>");
} else {
  for (const r of results) console.log((r.ok ? "ok   " : "FAIL ") + r.name + (r.ok ? "" : " — " + r.message));
  console.log(summary);
  if (failed.length) process.exitCode = 1;
}
