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
// 3인 한 핸드의 이벤트: 핸드 1 (버튼 0, SB 1, BB 2) → 핸드 2 시작
const names3 = ["Alpha", "Bravo", "Carol"];
const hev = (seq, type, extra = {}) => ({ seq, type, handNo: 1, board: [], pot: 30, stacks: [1000, 990, 980], committed: [0, 10, 20], pots: [], ...extra });
const hand1 = [
  hev(1, "hand_start", { sb: 1, bb: 2, button: 0 }),
  hev(2, "action", { seat: 0, action: "raise", paid: 60, to: 60, auto: false }),
  hev(3, "action", { seat: 1, action: "call", paid: 50, auto: false }),
  hev(4, "action", { seat: 2, action: "fold", paid: 0, auto: true }),
  hev(5, "street", { street: "flop", board: ["2♣", "7♦", "9♥"] }),
  hev(6, "action", { seat: 1, action: "all_in", paid: 930, to: 930, allIn: true, auto: false }),
  hev(7, "action", { seat: 0, action: "call", paid: 930, allIn: false, auto: false }),
];
test("좌석 행동 표시: 콜은 더 낸 금액, 레이즈는 스트리트 총액, 다음 차례에도 유지", () => {
  let d = L.displayFromState({ handNo: 0, board: [], pot: 0, seats: names3.map((n, i) => ({ seat: i, name: n, stack: 1000, committed: 0 })), events: [], lastEventSeq: 0 });
  d = L.applyEvent(d, hand1[0]);
  eq(d.acts.map(L.actTag), ["", "SB 10", "BB 20"], "blinds shown at hand start");
  d = L.applyEvent(d, hand1[1]);
  d = L.applyEvent(d, hand1[2]);
  eq(d.acts.map(L.actTag), ["레이즈 총 60", "콜 +50", "BB 20"], "raise total vs call added; earlier tags stay");
  d = L.applyEvent(d, hand1[3]);
  eq(L.actTag(d.acts[2]), "폴드 (시간 초과)", "auto fold");
  d = L.applyEvent(d, hand1[4]);
  eq(d.acts.map(L.actTag), ["", "", "폴드 (시간 초과)"], "new street: only fold / all-in remain");
  d = L.applyEvent(d, hand1[5]);
  d = L.applyEvent(d, hand1[6]);
  eq(d.acts.map(L.actTag), ["콜 +930", "올인 총 930", "폴드 (시간 초과)"], "all-in total");
  eq(d.log.map((e) => e.text).slice(-3), ["— 플롭 —", "Bravo · 올인 총 930", "Alpha · 콜 +930"], "log");
  eq(d.log.length <= L.MAX_LOG, true, "log is short");
  const next = L.applyEvent(d, hev(8, "hand_start", { handNo: 2, sb: 2, bb: 0, committed: [20, 0, 10] }));
  eq([next.acts.map(L.actTag), next.log.length], [["BB 20", "", "SB 10"], 1], "next hand clears the previous hand's actions");
  eq(L.actTag({ kind: "all_in_call", paid: 120 }), "올인 콜 +120", "all-in for less than the call");
  const shortAllIn = L.reduceActs([null, null], [], hev(9, "action", { seat: 0, action: "all_in", paid: 15, allIn: true, auto: false, stacks: [0, 0] }), names3);
  eq(L.actTag(shortAllIn.acts[0]), "올인 콜 +15", "all_in without a total is a call-size all-in");
});
test("새로고침 뒤 표시는 실시간 재생과 같고, 이전 핸드 행동은 섞이지 않는다", () => {
  const live = hand1.reduce((d, e) => L.applyEvent(d, e), L.displayFromState({ handNo: 0, board: [], pot: 0, seats: names3.map((n, i) => ({ seat: i, name: n, stack: 1000, committed: 0 })), events: [], lastEventSeq: 0 }));
  const old = hand1.map((e) => ({ ...e, handNo: 0, seq: e.seq - 100 }));
  const snap = L.displayFromState({ handNo: 1, board: ["2♣", "7♦", "9♥"], pot: 0, seats: names3.map((n, i) => ({ seat: i, name: n, stack: 0, committed: 0 })), events: [...old, ...hand1], lastEventSeq: 7 });
  eq([snap.acts, snap.log], [live.acts, live.log], "same tags and log");
});
test("대기 응답에 새 이벤트만 와도 이번 핸드 행동 표시가 유지된다", () => {
  const seats = names3.map((n, i) => ({ seat: i, name: n, stack: 900, committed: 0 }));
  let d = hand1.slice(0, 3).reduce((x, e) => L.applyEvent(x, e), L.displayFromState({ handNo: 0, board: [], pot: 0, seats, events: [], lastEventSeq: 0 }));
  const kept = L.syncDisplay(d, { handNo: 1, board: [], pot: 90, seats, events: [], lastEventSeq: 3 });
  eq(kept.acts.map(L.actTag), ["레이즈 총 60", "콜 +50", "BB 20"], "no new events: tags kept (this was the bug)");
  const more = L.syncDisplay(kept, { handNo: 1, board: [], pot: 90, seats, events: hand1.slice(2, 4), lastEventSeq: 4 });
  eq([more.acts.map(L.actTag), more.log.length], [["레이즈 총 60", "콜 +50", "폴드 (시간 초과)"], 4], "only unseen events applied, once");
  const next = L.syncDisplay(more, { handNo: 2, board: [], pot: 30, seats, events: [hev(9, "hand_start", { handNo: 2, sb: 2, bb: 0, committed: [20, 0, 10] })], lastEventSeq: 9 });
  eq(next.acts.map(L.actTag), ["BB 20", "", "SB 10"], "a new hand starts clean");
});
test("결과의 칩 변화와 지급(리바이)은 수익과 구분", () => {
  const result = { startStacks: [1000, 980, null], endStacks: [1216, 764, null], payouts: [236, 0, 0] };
  const mine = L.chipChange(result, 0, 1216);
  eq([mine.start, mine.net, mine.received, mine.rebuy], [1000, 216, 236, 0], "win");
  eq(L.chipChangeText(mine), "시작 1,000 → +216 → 현재 1,216 · 팟 수령 236 / 순이익 +216", "text");
  eq(L.chipChangeText(L.chipChange(result, 1, 764)), "시작 980 → −216 → 현재 764 · 팟 수령 0 / 순이익 −216", "loss");
  const bust = L.chipChange({ startStacks: [1000], endStacks: [0], payouts: [0] }, 0, 1000);
  eq(L.chipChangeText(bust), "시작 1,000 → −1,000 → 현재 1,000 · 팟 수령 0 / 순이익 −1,000 · 지급 +1,000(수익 아님)", "rebuy");
  eq(L.chipChange(result, 2, 500), null, "not in the hand");
});
test("베팅 한도 안내와 입력 검사", () => {
  const base = { toCall: 40, minRaiseTo: 120, maxRaiseTo: 600, allInTo: 600, allInKind: "raise" };
  const r = L.betLimits(base, new Set(["fold", "call", "raise", "all_in"]), 100);
  eq([r.text, r.allIn, r.error], ["콜 40 · 최소 레이즈 총 120 · 최대 총 600", "올인 총 600", "120 이상 입력하세요"], "raise");
  eq(L.betLimits(base, new Set(["raise"]), 700).error, "600 이하로 입력하세요 (가진 칩 한도)", "above");
  eq(L.betLimits(base, new Set(["raise"]), 12.5).error, "정수 칩만 입력할 수 있습니다", "fraction");
  eq(L.betLimits(base, new Set(["raise"]), NaN).error, "정수 칩만 입력할 수 있습니다", "empty");
  eq(L.betLimits(base, new Set(["raise"]), 300).error, "", "in range");
  const short = L.betLimits({ toCall: 40, minRaiseTo: 120, maxRaiseTo: 90, allInTo: 90, allInKind: "short" }, new Set(["fold", "call", "all_in"]), null);
  eq([short.text, short.allIn], ["콜 40", "올인 총 90 (최소 레이즈 120보다 적지만 올인은 허용)"], "short all-in");
  const under = L.betLimits({ toCall: 200, minRaiseTo: 400, maxRaiseTo: 150, allInTo: 150, allInKind: "call" }, new Set(["fold", "all_in"]), null);
  eq(under.allIn, "올인 총 150 (콜 금액 이하 — 올인 콜로 허용)", "all-in call");
  eq(L.betLimits({ toCall: 0, minRaiseTo: 20, maxRaiseTo: 500 }, new Set(["check", "bet"]), 20).text, "체크 가능 · 최소 베팅 총 20 · 최대 총 500", "bet");
});
test("파산 뒤 복귀 대기 문구", () => {
  const busted = { rebuyAfterHand: 4 };
  eq(L.rebuyText(busted, "hand_over", 3, true), "4번 핸드 관전 후 복귀", "right after the bust");
  eq(L.rebuyText(busted, "playing", 4, true), "관전 중 · 이 핸드 뒤 복귀", "watching");
  eq(L.rebuyText(busted, "hand_over", 4, true), "지급 확인 중", "waiting for the record");
  eq(L.rebuyText(busted, "round_over", 3, true), "다음 라운드 때 복귀", "round over");
  eq(L.rebuyText({ rebuyAfterHand: null }, "hand_over", 3, true), "칩 없음", "no rebuy pending");
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
