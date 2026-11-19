// [yut.js] 초능력 윷놀이 규칙 (화면과 상관없는 순수 함수만. 그래서 DOM 없이 테스트할 수 있다)
//
// 게임의 상태는 "일어난 일(action)의 목록" 하나뿐이다. 판 · 차례 · 승자는 전부 그 목록을 처음부터 다시 적용해서(reduce) 만든다.
//   - 윷 던지기처럼 무작위인 일은 App이 결과를 정해서 action에 담는다 (예: { type: "throw", name: "걸" })
//     → 같은 목록이면 언제 다시 계산해도 같은 판이 나온다 (테스트도 쉬움)
//
// 판 (29칸): 바깥 20칸 o0 ~ o19 (o0 = 출발 · 참먹이, 오른쪽 아래 모서리), 시계 반대 방향으로 돈다
//   모서리 o5(오른쪽 위) · o10(왼쪽 위) · o15(왼쪽 아래), 가운데 방 C
//   지름길: o5 → a1 → a2 → C → c1 → c2 → o15 / o10 → b1 → b2 → C → g1 → g2 → o0
//   모서리나 방에 "멈추면" 다음에는 지름길로 간다. 참먹이(o0)를 지나치면 난다(END)

export const TEAMS = ["홍", "청"];
export const PIECES = 4; // 팀마다 말 4개
export const HOME = "home"; // 아직 판에 오르지 않은 말
export const END = "end"; // 난 말
export const STEPS = { 빽도: -1, 도: 1, 개: 2, 걸: 3, 윷: 4, 모: 5 };
const BONUS = new Set(["윷", "모"]); // 한 번 더 던지는 결과

export const other = (team) => (team === "홍" ? "청" : "홍");

// ── 판 ──

const outer = (k) => `o${k}`;
// 바깥 길: k번 칸 다음부터 o19, 참먹이(o0)를 거쳐 나기까지
const outerFrom = (k) => [...Array.from({ length: 19 - k }, (_, i) => outer(k + 1 + i)), "o0", END];
const TO_O15 = [outer(15), ...outerFrom(15)]; // o15부터 바깥으로 나가는 길

/** pos에서 출발할 때 앞으로 가는 길 (첫 칸부터). 모서리 · 방에서 출발하면 지름길 */
export function routeFrom(pos) {
  switch (pos) {
    case HOME: return outerFrom(0);
    case "o0": return [END]; // 참먹이에 멈춰 있던 말은 무엇이 나와도 난다
    case "o5": return ["a1", "a2", "C", "c1", "c2", ...TO_O15];
    case "o10": return ["b1", "b2", "C", "g1", "g2", "o0", END];
    case "C": return ["g1", "g2", "o0", END]; // 방에 멈추면 가장 짧은 길(참먹이 쪽)
    case "a1": return ["a2", "C", "c1", "c2", ...TO_O15]; // 방을 "지나가면" 곧장 건너편(o15)으로
    case "a2": return ["C", "c1", "c2", ...TO_O15];
    case "c1": return ["c2", ...TO_O15];
    case "c2": return TO_O15;
    case "b1": return ["b2", "C", "g1", "g2", "o0", END];
    case "b2": return ["C", "g1", "g2", "o0", END];
    case "g1": return ["g2", "o0", END];
    case "g2": return ["o0", END];
    default: return outerFrom(Number(pos.slice(1)));
  }
}

// 빽도(뒤로 한 칸)
const BACK = { a1: "o5", a2: "a1", C: "a2", c1: "C", c2: "c1", b1: "o10", b2: "b1", g1: "C", g2: "g1", o0: "o19", o1: "o0" };
const backOf = (pos) => BACK[pos] ?? outer(Number(pos.slice(1)) - 1);

/** pos의 말이 name만큼 가면 도착하는 곳 (나면 END). 움직일 수 없으면 null (판에 없는 말의 빽도) */
export function destination(pos, name) {
  if (pos === END) return null;
  if (name === "빽도") return pos === HOME ? null : backOf(pos);
  const route = routeFrom(pos);
  return route[Math.min(STEPS[name], route.length) - 1];
}

// 모든 칸 (화면 배치와 테스트에서 쓴다)
export const NODES = [...Array.from({ length: 20 }, (_, k) => outer(k)), "a1", "a2", "C", "c1", "c2", "b1", "b2", "g1", "g2"];
export const CORNERS = new Set(["o0", "o5", "o10", "o15", "C"]);

// ── 윷 던지기 ──

/**
 * 막대 4개를 던진다. random() < 0.5면 평평한 면(배)이 위. 평평한 면 수로 결과가 정해진다
 *   0개 모, 1개 도, 2개 개, 3개 걸, 4개 윷. 1번 막대에 뒷표시가 있어서, 평평한 면이 그 막대 하나뿐이면 빽도
 */
export function throwSticks(random) {
  const flats = [0, 1, 2, 3].map(() => random() < 0.5);
  const n = flats.filter(Boolean).length;
  return { name: n === 0 ? "모" : n === 1 ? (flats[0] ? "빽도" : "도") : ["", "", "개", "걸", "윷"][n], flats };
}
// 초능력으로 정해진 결과도 막대 모양을 보여 주려고 만든다
export const sticksFor = (name) => ({ 빽도: [true, false, false, false], 도: [false, true, false, false], 개: [true, true, false, false], 걸: [true, true, true, false], 윷: [true, true, true, true], 모: [false, false, false, false] })[name];

// ── 초능력 ──

export const POWERS = {
  // 윷의 힘: 던지기 전에 켜 두면 다음 던지기 결과가 바뀐다
  small: { kind: "yut", name: "소심한 손목", desc: "다음 윷은 도나 개만 나옵니다. 바로 앞의 상대 말을 잡기 좋습니다." },
  three: { kind: "yut", name: "걸로 할게요", desc: "다음 윷은 무조건 걸이 나옵니다." },
  back: { kind: "yut", name: "빽 투 더 퓨처", desc: "다음 윷은 무조건 빽도가 나옵니다. 뒤따라오는 상대 말을 잡을 때 씁니다." },
  big: { kind: "yut", name: "모 아니면 윷", desc: "다음 윷은 윷이나 모만 나옵니다. 한 번 더 던지기도 그대로 받습니다." },
  twice: { kind: "yut", name: "한 판만 더요", desc: "이번 던지기에서 윷을 두 번 던지고, 마음에 드는 결과 하나를 고릅니다." },
  // 말의 힘: 던지기 전에 바로 쓴다 (대상을 고르는 것도 있다)
  recall: { kind: "mal", name: "엄마가 밥 먹으래", desc: "판 위의 상대 말 하나(업힌 말 포함)를 출발점으로 돌려보냅니다.", target: "opponent" },
  swap: { kind: "mal", name: "님 자리 제가 앉을게요", desc: "판 위의 내 말과 상대 말을 하나씩 골라 자리를 바꿉니다.", target: "swap" },
  trap: { kind: "mal", name: "바나나 껍질", desc: "빈 칸 하나에 함정을 놓습니다. 그 칸에 멈춘 상대 말은 출발점으로 돌아갑니다.", target: "empty" },
  shortcut: { kind: "mal", name: "택시 잡기", desc: "바깥 길 위의 내 말 하나를 바로 앞 모서리로 옮깁니다.", target: "mineOuter" },
  shield: { kind: "mal", name: "철벽 치기", desc: "상대의 다음 차례가 끝날 때까지 내 말은 잡히지 않습니다." },
  freeze: { kind: "mal", name: "다리에 쥐 났다", desc: "상대가 다음 차례를 한 번 쉽니다." },
};
export const YUT_POWERS = Object.keys(POWERS).filter((id) => POWERS[id].kind === "yut");
export const MAL_POWERS = Object.keys(POWERS).filter((id) => POWERS[id].kind === "mal");

// 팀마다 윷의 힘 · 말의 힘 후보를 2개씩 무작위로 (게임 시작 action에 담는다)
export function makeOffers(random) {
  const two = (pool) => {
    const a = pool[Math.floor(random() * pool.length)];
    const rest = pool.filter((id) => id !== a);
    return [a, rest[Math.floor(random() * rest.length)]];
  };
  return Object.fromEntries(TEAMS.map((t) => [t, { yut: two(YUT_POWERS), mal: two(MAL_POWERS) }]));
}

/** 켜 둔 윷의 힘에 맞춰 이번 던지기 결과를 정한다 (App이 부르고, 결과를 action에 담는다) */
export function resolveThrow(state, random) {
  const pick = (names) => names[Math.floor(random() * names.length)];
  switch (state.armed) {
    case "small": return { name: pick(["도", "개"]) };
    case "three": return { name: "걸" };
    case "back": return { name: "빽도" };
    case "big": return { name: pick(["윷", "모"]) };
    case "twice": return { choices: [throwSticks(random).name, throwSticks(random).name] };
    default: return throwSticks(random);
  }
}

// ── 상태 ──

export function initialState(offers) {
  return {
    phase: "pick", // pick(초능력 고르기) → throw(던지기) → move(말 옮기기) / choose(두 번 던지기 고르기) → over
    picking: "홍",
    offers,
    turn: "홍",
    turnNo: 1,
    pieces: { 홍: Array(PIECES).fill(HOME), 청: Array(PIECES).fill(HOME) },
    pending: [], // 아직 쓰지 않은 윷 결과
    throwsLeft: 1,
    lastThrow: null, // 막대 모양 표시용
    throwSeq: 0, // 던진 횟수 (화면이 던질 때마다 막대 애니메이션을 다시 틀려고)
    choices: null, // 두 번 던지기에서 고를 결과 두 개
    powers: { 홍: null, 청: null }, // { yut, yutUsed, mal, malUsed }
    armed: null, // 지금 차례에 켜 둔 윷의 힘
    traps: {}, // 칸 → 함정을 놓은 팀
    shield: { 홍: false, 청: false },
    skip: { 홍: false, 청: false },
    winner: null,
    log: [],
  };
}

// 칸 이름 (기보용)
export function nodeName(pos) {
  if (pos === HOME) return "출발 전";
  if (pos === END) return "남";
  if (pos === "o0") return "출발점"; // 전통 이름은 참먹이. 화면에는 알아보기 쉬운 말로
  if (pos === "C") return "방";
  if (["o5", "o10", "o15"].includes(pos)) return "모서리";
  return pos.startsWith("o") ? `바깥 ${pos.slice(1)}` : "지름길";
}

const stackAt = (state, team, pos) => state.pieces[team].map((p, i) => (p === pos ? i : -1)).filter((i) => i >= 0);
export const piecesOn = (state, team) => state.pieces[team].filter((p) => p !== HOME && p !== END);

/** 지금 차례 팀이 결과 name으로 옮길 수 있는 출발 칸들 (HOME 포함, 업힌 말은 한 칸으로) */
export function movableFrom(state, name) {
  const team = state.turn;
  const starts = [...new Set(state.pieces[team].filter((p) => p !== END))];
  return starts.filter((pos) => {
    const dest = destination(pos, name);
    if (dest === null) return false;
    // 방패를 든 상대 말이 있는 칸에는 멈출 수 없다 (잡을 수 없으니까)
    return !(dest !== END && state.shield[other(team)] && stackAt(state, other(team), dest).length > 0);
  });
}

const usable = (state) => state.pending.some((name) => movableFrom(state, name).length > 0);

// 말들을 dest에 내려놓는다: 상대 말이 있으면 잡고, 상대 함정이면 내 말이 출발점으로
function land(s, team, indexes, dest, { bonus }) {
  const opp = other(team);
  for (const i of indexes) s.pieces[team][i] = dest;
  if (dest === END) {
    s.log.push(`${team} 말 ${indexes.length}개가 났습니다`);
    return;
  }
  const caught = stackAt(s, opp, dest);
  if (caught.length > 0) {
    for (const i of caught) s.pieces[opp][i] = HOME;
    s.log.push(`${team}이 ${opp} 말 ${caught.length}개를 잡았습니다${bonus ? " · 한 번 더" : ""}`);
    if (bonus) s.throwsLeft += 1;
  }
  if (s.traps[dest] === opp) {
    delete s.traps[dest];
    for (const i of indexes) s.pieces[team][i] = HOME;
    s.log.push(`${team} 말이 ${opp}의 함정에 걸려 출발점으로 돌아갔습니다`);
  }
}

// 차례를 넘긴다. 발이 묶인 팀은 한 번 쉬고, 방패는 "자기 차례가 다시 올 때" 풀린다
function nextTurn(s) {
  let team = other(s.turn);
  s.turnNo += 1;
  if (s.skip[team]) {
    s.skip[team] = false;
    s.shield[team] = false;
    s.log.push(`${team}은 발이 묶여 이번 차례를 쉽니다`);
    team = other(team);
    s.turnNo += 1;
  }
  s.turn = team;
  s.shield[team] = false;
  Object.assign(s, { phase: "throw", pending: [], throwsLeft: 1, armed: null, choices: null });
}

// 던지기 · 옮기기가 끝난 뒤 다음 단계 정하기
function settle(s) {
  if (s.pieces[s.turn].every((p) => p === END)) {
    s.winner = s.turn;
    s.phase = "over";
    s.log.push(`${s.turn} 승리!`);
    return;
  }
  if (s.throwsLeft > 0) s.phase = "throw";
  else if (usable(s)) s.phase = "move";
  else {
    if (s.pending.length > 0) s.log.push(`쓸 수 없는 결과(${s.pending.join(", ")})는 버립니다`);
    nextTurn(s);
  }
}

function addThrow(s, name) {
  s.pending.push(name);
  s.throwsLeft -= 1;
  if (BONUS.has(name)) s.throwsLeft += 1;
  s.log.push(`${s.turnNo}턴 ${s.turn}: ${name}${BONUS.has(name) ? " · 한 번 더" : ""}`);
  settle(s);
}

/**
 * action 하나를 적용한 새 상태 (s를 직접 바꾸지 않는다). 규칙에 맞지 않는 action이면 이유를 담아 Error
 *   { type: "pick", team, yut, mal }   초능력 고르기
 *   { type: "arm" }                    윷의 힘 켜기
 *   { type: "throw", name, flats? }    윷 던지기 (결과는 App이 resolveThrow로 정함)
 *   { type: "throw2", choices }        두 번 던지기의 두 결과 / { type: "choose", index } 그중 하나 고르기
 *   { type: "move", from, index }      pending[index] 결과로 from 칸의 말(업힌 말 전부) 옮기기
 *   { type: "mal", targets }           말의 힘 쓰기 (대상 칸들)
 */
export function apply(state, action) {
  const s = structuredClone(state);
  const team = s.turn;
  const fail = (msg) => {
    throw new Error(msg);
  };
  switch (action.type) {
    case "pick": {
      if (s.phase !== "pick" || action.team !== s.picking) fail("지금은 그 팀이 고를 차례가 아닙니다");
      if (!s.offers[action.team].yut.includes(action.yut) || !s.offers[action.team].mal.includes(action.mal)) fail("후보에 없는 초능력입니다");
      s.powers[action.team] = { yut: action.yut, yutUsed: false, mal: action.mal, malUsed: false };
      s.log.push(`${action.team}: ${POWERS[action.yut].name} · ${POWERS[action.mal].name}을 골랐습니다`);
      if (action.team === "홍") s.picking = "청";
      else Object.assign(s, { picking: null, phase: "throw" });
      return s;
    }
    case "arm": {
      const p = s.powers[team];
      if (s.phase !== "throw" || s.pending.length > 0 || p.yutUsed) fail("윷의 힘은 차례 처음, 던지기 전에 한 번만 쓸 수 있습니다");
      p.yutUsed = true;
      s.armed = p.yut;
      s.log.push(`${team}: 윷의 힘 「${POWERS[p.yut].name}」`);
      return s;
    }
    case "throw": {
      if (s.phase !== "throw") fail("지금은 던질 수 없습니다");
      s.armed = null;
      s.lastThrow = { name: action.name, flats: action.flats ?? sticksFor(action.name) };
      s.throwSeq += 1;
      addThrow(s, action.name);
      return s;
    }
    case "throw2": {
      if (s.phase !== "throw" || s.armed !== "twice") fail("두 번 던지기를 켜지 않았습니다");
      s.armed = null;
      s.choices = action.choices;
      s.phase = "choose";
      s.log.push(`${team}: 두 번 던져 ${action.choices.join(" · ")}`);
      return s;
    }
    case "choose": {
      if (s.phase !== "choose") fail("고를 결과가 없습니다");
      const name = s.choices[action.index];
      s.choices = null;
      s.lastThrow = { name, flats: sticksFor(name) };
      s.throwSeq += 1;
      addThrow(s, name);
      return s;
    }
    case "move": {
      const name = s.pending[action.index];
      if (s.phase !== "move" || !name) fail("옮길 결과가 없습니다");
      if (!movableFrom(s, name).includes(action.from)) fail("그 말은 옮길 수 없습니다");
      const dest = destination(action.from, name);
      // 출발 전 말은 하나씩, 판 위의 말은 업힌 말까지 함께 간다
      const indexes = action.from === HOME ? [s.pieces[team].indexOf(HOME)] : stackAt(s, team, action.from);
      s.pending.splice(action.index, 1);
      s.log.push(`${team}: ${name === "윷" ? "윷으로" : `${name}로`} ${nodeName(action.from)} → ${nodeName(dest)}${indexes.length > 1 ? ` (${indexes.length}개 업고)` : ""}`);
      land(s, team, indexes, dest, { bonus: true });
      settle(s);
      return s;
    }
    case "mal": {
      const p = s.powers[team];
      if (s.phase !== "throw" || s.pending.length > 0 || p.malUsed) fail("말의 힘은 차례 처음, 던지기 전에 한 번만 쓸 수 있습니다");
      const opp = other(team);
      const [t1, t2] = action.targets ?? [];
      const mine = (pos) => stackAt(s, team, pos);
      const theirs = (pos) => stackAt(s, opp, pos);
      switch (p.mal) {
        case "recall":
          if (!t1 || theirs(t1).length === 0 || t1 === HOME) fail("판 위의 상대 말을 골라야 합니다");
          if (s.shield[opp]) fail("상대 말이 방패로 보호받고 있습니다");
          for (const i of theirs(t1)) s.pieces[opp][i] = HOME;
          break;
        case "swap": {
          const a = mine(t1);
          const b = theirs(t2);
          if (t1 === HOME || t2 === HOME || a.length === 0 || b.length === 0) fail("판 위의 내 말과 상대 말을 하나씩 골라야 합니다");
          for (const i of a) s.pieces[team][i] = t2;
          for (const i of b) s.pieces[opp][i] = t1;
          break;
        }
        case "trap":
          if (!NODES.includes(t1) || mine(t1).length > 0 || theirs(t1).length > 0 || s.traps[t1]) fail("빈 칸을 골라야 합니다");
          s.traps[t1] = team;
          break;
        case "shortcut": {
          const k = t1?.startsWith("o") ? Number(t1.slice(1)) : -1;
          if (mine(t1).length === 0 || k <= 0 || k % 5 === 0) fail("바깥 길 위(모서리 제외)의 내 말을 골라야 합니다");
          const corner = outer(((Math.ceil(k / 5) * 5) % 20)); // o1~o4 → o5, o6~o9 → o10, o11~o14 → o15, o16~o19 → 참먹이
          if (s.shield[opp] && theirs(corner).length > 0) fail("그 모서리의 상대 말이 방패로 보호받고 있습니다");
          land(s, team, mine(t1), corner, { bonus: false }); // 모서리에 상대 말이 있으면 잡지만 한 번 더는 없다
          break;
        }
        case "shield":
          s.shield[team] = true;
          break;
        case "freeze":
          s.skip[opp] = true;
          break;
      }
      p.malUsed = true;
      s.log.push(`${team}: 말의 힘 「${POWERS[p.mal].name}」${t1 ? ` (${[t1, t2].filter(Boolean).map(nodeName).join(" ↔ ")})` : ""}`);
      return s;
    }
    default:
      fail(`알 수 없는 action: ${action.type}`);
  }
}

/** action 목록 → 지금 상태 */
export const replay = (actions) => actions.slice(1).reduce(apply, initialState(actions[0].offers));
