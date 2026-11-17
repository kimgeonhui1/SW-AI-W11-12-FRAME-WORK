// [roomLogic.js] 멀티플레이 화면의 순수 로직 — DOM·Hook 없이 "서버 상태 → 화면에 보여 줄 값"만 계산한다
//
// ■ 두 가지 상태를 구분한다
//   서버 상태(state)  : 서버가 보낸 정답. 버전·턴·칩·보드·결과가 들어 있다
//   표시 상태(display): 지금 화면에 그리는 칩·보드. 이벤트를 순서대로 재생하는 동안에만 서버 상태보다 "과거"다
//   재생이 끝나면 display는 반드시 서버 상태와 같아진다. 애니메이션은 게임 값을 바꾸지 못한다.

export const ACTION_LABELS = { fold: "폴드", check: "체크", call: "콜", bet: "베팅", raise: "레이즈", all_in: "올인" };
export const STREET_LABELS = { preflop: "프리플롭", flop: "플롭", turn: "턴", river: "리버", showdown: "쇼다운", complete: "종료" };
export const MAX_REPLAY_EVENTS = 16; // 이보다 많이 밀렸으면(오래 끊겼다 복귀) 재생하지 않고 최신 상태로 바로 맞춘다

// 화면 자리: 본인이 아래, 나머지는 테이블 순서(좌석 번호가 커지는 쪽 = 행동 순서)대로 시계 방향 왼쪽 → 위 → 오른쪽
//   2인: 아래·위 / 3인: 아래·왼쪽·오른쪽 / 4인: 아래·왼쪽·위·오른쪽
export const SPOTS = { 2: ["bottom", "top"], 3: ["bottom", "left", "right"], 4: ["bottom", "left", "top", "right"] };
export function seatLayout(youSeat, capacity) {
  const spots = SPOTS[capacity] || SPOTS[2];
  return spots.map((where, offset) => ({ seat: (youSeat + offset) % spots.length, where }));
}

// 칩이 날아가는 연출의 출발·도착점 (테이블 평면 %, room.css 좌석 위치와 같은 값). 값과 무관한 연출이다
export const FLIGHT_POINTS = {
  pot: [72, 50],
  bottom: { bet: [44, 57], hud: [26, 92] }, top: { bet: [44, 36], hud: [26, 10] },
  left: { bet: [22, 45], hud: [12, 36] }, right: { bet: [78, 45], hud: [88, 36] },
};
export function flightPath(flight, whereOf) {
  const point = (end, kind) => (end === "pot" ? FLIGHT_POINTS.pot : (FLIGHT_POINTS[whereOf[end]] || FLIGHT_POINTS.top)[kind]);
  const from = point(flight.from, "bet");
  const to = point(flight.to, "hud");
  return { "--fx": from[0] + "%", "--fy": from[1] + "%", "--tx": to[0] + "%", "--ty": to[1] + "%" };
}

// ■ 좌석별 행동 표시(acts)와 최근 행동 기록(log)
//   acts[좌석] = 그 좌석의 "이번 스트리트" 마지막 행동. 다른 사람 차례로 넘어가도 남아 있다
//   초기화 시점: 새 핸드(hand_start) → 모두 지움(블라인드만 표시) / 새 스트리트(street) → 폴드·올인만 남기고 지움
//                핸드가 끝나도(hand_end) 지우지 않는다 → 다음 핸드가 시작될 때 지운다. 이전 핸드 행동이 남지 않는다
//   log = 이번 핸드의 행동 기록(최근 MAX_LOG개). 새 핸드에서 비운다
export const MAX_LOG = 5;
const emptyActs = (count) => Array.from({ length: count }, () => null);

// 행동 표시 문구. 콜은 "이번에 더 낸 금액(+)", 베팅·레이즈·올인은 "이번 스트리트 총 베팅액(총)"
export function actTag(act) {
  if (!act) return "";
  const n = (value) => Number(value).toLocaleString();
  const auto = act.auto ? " (시간 초과)" : "";
  switch (act.kind) {
    case "sb": return "SB " + n(act.amount);
    case "bb": return "BB " + n(act.amount);
    case "check": return "체크" + auto;
    case "fold": return "폴드" + auto;
    case "call": return "콜 +" + n(act.paid);
    case "bet": return "베팅 총 " + n(act.to);
    case "raise": return "레이즈 총 " + n(act.to);
    case "all_in": return "올인 총 " + n(act.to);
    case "all_in_call": return "올인 콜 +" + n(act.paid);
    default: return ACTION_LABELS[act.kind] || act.kind;
  }
}

// 이벤트 하나를 acts·log에 반영 (applyEvent와 displayFromState가 같은 규칙을 쓴다)
export function reduceActs(acts, log, event, names) {
  const name = (seat) => names[seat] || "플레이어";
  let nextActs = acts;
  let nextLog = log;
  const add = (text) => { nextLog = [...nextLog, { seq: event.seq, text }].slice(-MAX_LOG); };
  if (event.type === "hand_start") {
    nextActs = emptyActs(event.stacks.length);
    nextLog = [];
    if (event.sb !== undefined && event.committed[event.sb] > 0) nextActs[event.sb] = { kind: "sb", amount: event.committed[event.sb] };
    if (event.bb !== undefined && event.committed[event.bb] > 0) nextActs[event.bb] = { kind: "bb", amount: event.committed[event.bb] };
    add(event.handNo + "번 핸드 시작");
  } else if (event.type === "action") {
    nextActs = [...acts];
    // 칩을 모두 냈지만 현재 베팅을 넘지 못한 경우(콜 금액 이하의 올인)는 "올인 콜"로 구분한다.
    // 베팅을 올린 올인에는 서버가 이번 스트리트 총액 to를 준다
    const allInCall = (event.action === "call" && event.allIn) || (event.action === "all_in" && event.to === undefined);
    const kind = allInCall ? "all_in_call" : event.action;
    nextActs[event.seat] = { kind, paid: event.paid, to: event.to, auto: Boolean(event.auto), seq: event.seq };
    add(name(event.seat) + " · " + actTag(nextActs[event.seat]));
  } else if (event.type === "street") {
    nextActs = acts.map((act) => (act && (act.kind === "fold" || act.kind === "all_in" || act.kind === "all_in_call") ? act : null));
    add("— " + (STREET_LABELS[event.street] || event.street) + " —");
  } else if (event.type === "returned") {
    add(name(event.seat) + " · 맞추지 못한 " + Number(event.amount).toLocaleString() + " 반환");
  } else if (event.type === "hand_end") {
    add("핸드 종료 · 팟 " + Number(event.potWon).toLocaleString());
  } else if (event.type === "recovered") {
    nextActs = emptyActs(event.stacks.length);
    nextLog = [];
  }
  return { acts: nextActs, log: nextLog };
}

// 서버 상태의 이벤트 중 "지금 핸드" 것만 다시 계산해 acts·log를 만든다 (새로고침·재접속 뒤에도 같은 표시)
export function actsFromState(state) {
  const names = state.seats.map((seat) => seat.name);
  let acc = { acts: emptyActs(state.seats.length), log: [], seq: 0 };
  for (const event of state.events || []) {
    if (event.handNo === state.handNo) acc = { ...reduceActs(acc.acts, acc.log, event, names), seq: event.seq };
  }
  return acc;
}

// 재생이 끝났거나 새 이벤트 없이 상태만 바뀌었을 때 화면을 서버 상태로 맞춘다.
// 대기 요청의 응답에는 "새" 이벤트만 들어 있으므로, 같은 핸드면 지금까지의 행동 표시를 이어 쓰고
// 아직 반영하지 않은 이벤트만 더한다. 새 핸드·복구·처음 접속이면 응답의 이벤트로 다시 만든다.
export function syncDisplay(current, state) {
  const full = displayFromState(state);
  const restarts = (state.events || []).some((e) => e.handNo === state.handNo && (e.type === "hand_start" || e.type === "recovered"));
  if (!current || !current.acts || current.handNo !== state.handNo || restarts) return full;
  const names = full.names;
  let acc = { acts: current.acts, log: current.log || [] };
  let seq = current.actsSeq || 0;
  for (const event of state.events || []) {
    if (event.handNo === state.handNo && event.seq > seq) {
      acc = reduceActs(acc.acts, acc.log, event, names);
      seq = event.seq;
    }
  }
  return { ...full, acts: acc.acts, log: acc.log, actsSeq: seq };
}

// 서버 상태 그대로의 표시 상태 (재생이 끝났을 때의 모습)
export function displayFromState(state) {
  const { acts, log, seq } = actsFromState(state);
  return {
    handNo: state.handNo,
    board: [...state.board],
    pot: state.pot,
    stacks: state.seats.map((seat) => seat.stack),
    committed: state.seats.map((seat) => seat.committed),
    pots: (state.pots || []).map((pot) => ({ amount: pot.amount, eligible: [...pot.eligible] })),
    names: state.seats.map((seat) => seat.name),
    acts,
    log,
    actsSeq: seq,
    last: null,
    flight: null,
    synced: true,
  };
}

// 이벤트 하나를 표시 상태에 반영 → 새 표시 상태. 이벤트에는 "그 순간"의 칩·팟·보드가 들어 있다
export function applyEvent(display, event) {
  const next = {
    ...display,
    handNo: event.handNo,
    board: [...event.board],
    pot: event.pot,
    stacks: [...event.stacks],
    committed: [...event.committed],
    pots: event.type === "hand_end" ? [] : (event.pots || []).map((pot) => ({ amount: pot.amount, eligible: [...pot.eligible] })),
    synced: false,
    flight: null,
  };
  const reduced = reduceActs(display.acts || emptyActs(event.stacks.length), display.log || [], event, display.names || []);
  next.acts = reduced.acts;
  next.log = reduced.log;
  next.actsSeq = event.seq;
  if (event.type === "action") {
    next.last = { seat: event.seat, action: event.action, paid: event.paid, auto: Boolean(event.auto), seq: event.seq };
    if (event.paid > 0) next.flight = { id: "f" + event.seq, from: event.seat, to: "pot", amount: event.paid };
  } else if (event.type === "hand_start") {
    next.last = null;
  } else if (event.type === "returned") {
    // 아무도 받지 못한 초과 베팅은 낸 사람에게 돌아간다
    next.flight = { id: "f" + event.seq, from: "pot", to: event.seat, amount: event.amount };
  } else if (event.type === "hand_end" && event.potWon > 0) {
    // 팟이 여러 명에게 나뉘면(무승부·사이드 팟) 한 사람에게 날아가는 칩을 그리지 않는다
    if (event.winnerSeat !== null && event.winnerSeat !== undefined) next.flight = { id: "f" + event.seq, from: "pot", to: event.winnerSeat, amount: event.potWon };
  }
  return next;
}

// 새 서버 상태를 받았을 때 무엇을 할지 결정한다
//   lastSeq : 지금까지 화면에 반영한(또는 재생 대기열에 넣은) 마지막 이벤트 번호
//   → { mode: "replay", events } : 이어지는 이벤트를 순서대로 재생
//     { mode: "snap" }           : 재생 없이 서버 상태로 바로 맞춤 (첫 접속·새로고침·이벤트 누락·너무 많이 밀림)
export function planUpdate(lastSeq, state, hasDisplay) {
  const fresh = (state.events || []).filter((event) => event.seq > lastSeq).sort((a, b) => a.seq - b.seq);
  if (!hasDisplay || !fresh.length) return { mode: "snap", events: [] };
  const contiguous = fresh[0].seq === lastSeq + 1 && fresh.every((event, index) => event.seq === fresh[0].seq + index);
  const reachesEnd = fresh[fresh.length - 1].seq === state.lastEventSeq;
  if (!contiguous || !reachesEnd || fresh.length > MAX_REPLAY_EVENTS) return { mode: "snap", events: [] };
  return { mode: "replay", events: fresh };
}

// 이벤트별 재생 시간(ms). 화면 연출용일 뿐이고 서버 판정과 무관하다
export function eventDelay(event) {
  if (event.type === "street") return 750;
  if (event.type === "hand_end") return 900;
  if (event.type === "hand_start") return 500;
  return event.paid > 0 ? 700 : 450;
}

// 핸드 결과의 내 칩 변화: 시작 칩 → 순증감 → 현재 칩, 팟에서 받은 칩(내 칩 포함)과 순이익을 구분
//   현재 칩은 서버의 지금 칩이라 그 사이 받은 1,000칩 지급(리바이)도 포함될 수 있다 → rebuy로 따로 알려 준다
export function chipChange(result, seatIndex, currentStack) {
  if (!result || !result.startStacks || result.startStacks[seatIndex] === null || result.startStacks[seatIndex] === undefined) return null;
  const start = result.startStacks[seatIndex];
  const end = result.endStacks[seatIndex];
  return { start, net: end - start, end, received: result.payouts ? result.payouts[seatIndex] || 0 : 0, now: currentStack, rebuy: currentStack - end };
}

export function chipChangeText(change) {
  if (!change) return "";
  const n = (value) => Number(value).toLocaleString();
  const sign = change.net > 0 ? "+" : change.net < 0 ? "−" : "±";
  return "시작 " + n(change.start) + " → " + sign + n(Math.abs(change.net)) + " → 현재 " + n(change.now)
    + " · 팟 수령 " + n(change.received) + " / 순이익 " + (change.net >= 0 ? "+" : "−") + n(Math.abs(change.net))
    + (change.rebuy > 0 ? " · 지급 +" + n(change.rebuy) + "(수익 아님)" : "");
}

// 파산 뒤 복귀 대기 문구. 서버가 준 rebuyAfterHand(관전할 핸드 번호)와 지금 단계로만 정한다
//   short: 좌석 배지용 / long: 내 조작 영역 안내용
export function rebuyText(seat, phase, handNo, short) {
  const after = seat.rebuyAfterHand;
  if (after === null || after === undefined) return short ? "칩 없음" : "칩이 없습니다";
  if (phase === "round_over") {
    return short ? "다음 라운드 때 복귀" : "칩이 없습니다. '다음 라운드 시작'을 누르면 1,000칩을 받고 바로 돌아옵니다.";
  }
  if (phase === "playing" && handNo === after) {
    return short ? "관전 중 · 이 핸드 뒤 복귀" : "이번 " + after + "번 핸드를 관전합니다. 끝나면 1,000칩을 받고 다음 핸드에 자동으로 돌아옵니다.";
  }
  if (handNo < after) {
    return short ? after + "번 핸드 관전 후 복귀" : "칩이 모두 떨어졌습니다. 다음 " + after + "번 핸드를 관전한 뒤 1,000칩을 받고 자동으로 돌아옵니다. (한 번 지급)";
  }
  return short ? "지급 확인 중" : "1,000칩 지급 기록을 확인하는 중입니다. 확인되면 자동으로 돌아옵니다.";
}

// 베팅 한도 안내 (서버가 준 값 그대로). 입력값이 범위 밖이면 무엇이 잘못됐는지 알려 준다
export function betLimits(state, legal, wager) {
  const n = (value) => Number(value).toLocaleString();
  const parts = [];
  parts.push(state.toCall > 0 ? "콜 " + n(state.toCall) : "체크 가능");
  const raising = legal.has("bet") || legal.has("raise");
  if (raising) parts.push("최소 " + (legal.has("bet") ? "베팅" : "레이즈") + " 총 " + n(state.minRaiseTo), "최대 총 " + n(state.maxRaiseTo));
  let allIn = "";
  if (legal.has("all_in") && state.allInTo !== null && state.allInTo !== undefined) {
    allIn = state.allInKind === "call" ? "올인 총 " + n(state.allInTo) + " (콜 금액 이하 — 올인 콜로 허용)"
      : state.allInKind === "short" ? "올인 총 " + n(state.allInTo) + " (최소 레이즈 " + n(state.minRaiseTo) + "보다 적지만 올인은 허용)"
        : "올인 총 " + n(state.allInTo);
  }
  let error = "";
  if (raising && wager !== null && wager !== undefined) {
    if (!Number.isInteger(wager)) error = "정수 칩만 입력할 수 있습니다";
    else if (wager < state.minRaiseTo) error = n(state.minRaiseTo) + " 이상 입력하세요";
    else if (wager > state.maxRaiseTo) error = n(state.maxRaiseTo) + " 이하로 입력하세요 (가진 칩 한도)";
  }
  return { text: parts.join(" · "), allIn, error };
}

export function actionText(last, names) {
  if (!last) return "";
  const who = names[last.seat] || "플레이어";
  const what = ACTION_LABELS[last.action] || last.action;
  return who + " · " + what + (last.paid > 0 ? " " + last.paid.toLocaleString() : "") + (last.auto ? " (시간 초과 자동)" : "");
}

// 포지션 표시: 버튼 D, 스몰 블라인드 SB, 빅 블라인드 BB (2인이면 버튼이 SB라 "D · SB")
export function positionLabel(seat) {
  return [seat.isButton && "D", seat.isSmallBlind && "SB", seat.isBigBlind && "BB"].filter(Boolean).join(" · ");
}

// 팟 구성: 한 개면 빈 문자열, 여러 개면 "메인 2,800 · 사이드1 300 · 사이드2 200"
export function potsText(pots) {
  if (!pots || pots.length < 2) return "";
  return pots.map((pot, index) => (index ? "사이드" + index + " " : "메인 ") + pot.amount.toLocaleString()).join(" · ");
}

// 핸드 결과 한 줄 (서버 result 그대로). 내 결과(승리·패배·무승부) + 팟마다 누가 가져갔는지
//   played: 내가 이 핸드에 참가했는가 (관전자에게는 승패를 붙이지 않는다)
//   무승부 = 내가 받은 모든 팟을 다른 사람과 나눴다 / 승리 = 하나라도 혼자 또는 일부를 가져갔다 / 패배 = 받은 칩이 없다
export function outcomeWord(result, youSeat, played = true) {
  if (!result || !played) return "";
  const pots = result.pots || [];
  const mine = pots.filter((pot) => pot.winners.includes(youSeat));
  if (!mine.length) return "패배";
  return mine.every((pot) => pot.winners.length > 1) ? "무승부" : "승리";
}

export function resultText(result, names, youSeat, played = true) {
  if (!result) return "";
  const word = outcomeWord(result, youSeat, played);
  const mine = result.payouts ? result.payouts[youSeat] || 0 : 0;
  if (result.reason === "fold") {
    const who = names[result.winnerSeat] || "플레이어";
    return [word, who + " +" + result.pot.toLocaleString() + " · 나머지 모두 폴드"].filter(Boolean).join(" · ");
  }
  const pots = (result.pots || []).map((pot, index) => {
    const label = result.pots.length > 1 ? (index ? "사이드" + index : "메인") + " " : "팟 ";
    const who = pot.winners.map((seat) => names[seat] + (result.hands && result.hands[seat] ? "(" + result.hands[seat] + ")" : "")).join(", ");
    return label + pot.amount.toLocaleString() + " → " + who + (pot.winners.length > 1 ? " 분배" : "");
  });
  return [word && (mine > 0 ? word + " +" + mine.toLocaleString() : word), ...pots].filter(Boolean).join(" · ");
}

// 방 코드 입력 정리: 대문자, 허용 문자만, 6자
export function normalizeCode(text) {
  return String(text || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
}

// API 주소 결정: ?api= > <meta> > "페이지를 연 호스트의 18784 포트"
// 다른 컴퓨터가 http://<서버 IP>:5500/room.html 로 열면 API도 같은 서버 IP로 간다 (localhost로 고정하지 않는다)
export function resolveApiBase(location, metaContent) {
  const fromQuery = new URLSearchParams(location.search || "").get("api");
  const chosen = (fromQuery || metaContent || "").trim().replace(/\/+$/, "");
  if (chosen) return chosen;
  return (location.protocol === "https:" ? "https:" : "http:") + "//" + location.hostname + ":18784";
}

// 같은 PC에서 두 사람을 시험할 때 ?guest=2 처럼 주면 브라우저 저장 키가 달라져 서로 다른 게스트가 된다
export function guestStorageKey(search) {
  const suffix = (new URLSearchParams(search || "").get("guest") || "").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 16);
  return "jungle-poker-lab.guest.v1" + (suffix ? "." + suffix : "");
}

export function validName(text) {
  const name = String(text || "").trim();
  return name.length >= 1 && name.length <= 24 && !/[\u0000-\u001f]/.test(name);
}

// 베팅 입력값 보정: 서버가 알려 준 최소·최대 안의 정수로
export function clampWager(value, min, max) {
  const number = Math.round(Number(value));
  if (!Number.isFinite(number)) return min;
  return Math.min(max, Math.max(min, number));
}

// 남은 턴 시간(초). 서버가 준 남은 ms와 그 응답을 받은 시각으로 화면에서만 줄여 보여 준다 (판정은 서버 시계)
export function remainingSeconds(remainingMs, receivedAt, now) {
  if (remainingMs === null || remainingMs === undefined) return null;
  return Math.max(0, Math.ceil((remainingMs - (now - receivedAt)) / 1000));
}

// 화면 보기 설정 (브라우저에만 기억한다. 게임과 무관)
export const VIEW_PREF = { key: "jungle-poker-lab.view", allowed: ["3d", "2d"], fallback: "3d" };
export const BLOOM_PREF = { key: "jungle-poker-lab.bloom", allowed: ["off", "on"], fallback: "off" };

// 저장소를 쓸 수 없거나(사생활 보호 창 등) 값이 이상하면 기본값
export function readPref(storage, pref) {
  try {
    const value = storage?.getItem(pref.key);
    return pref.allowed.includes(value) ? value : pref.fallback;
  } catch {
    return pref.fallback;
  }
}

export function writePref(storage, pref, value) {
  try {
    if (pref.allowed.includes(value)) storage?.setItem(pref.key, value);
  } catch { /* 저장이 막혀 있어도 화면은 그대로 동작 */ }
}
