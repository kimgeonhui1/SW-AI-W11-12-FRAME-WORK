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

// 서버 상태 그대로의 표시 상태 (재생이 끝났을 때의 모습)
export function displayFromState(state) {
  return {
    handNo: state.handNo,
    board: [...state.board],
    pot: state.pot,
    stacks: state.seats.map((seat) => seat.stack),
    committed: state.seats.map((seat) => seat.committed),
    pots: (state.pots || []).map((pot) => ({ amount: pot.amount, eligible: [...pot.eligible] })),
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
