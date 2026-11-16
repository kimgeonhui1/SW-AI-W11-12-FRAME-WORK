// [RoomApp.js] JUNGLE POKER LAB 멀티플레이 화면 — 닉네임 → 방 생성/참가 → 준비 → 2인 대전
//
// 흐름: 내 행동 요청 → 서버가 판정 → 두 사람 모두 같은 번호의 이벤트를 받음 → 각자 화면에서 순서대로 재생
//   · 화면은 결과를 정하지 않는다. 버튼은 "요청"만 보내고, 칩·팟·보드·승패는 서버가 준 값만 그린다
//   · state  = 서버가 준 최신 정답 / display = 지금 그리는 값(재생 중에는 과거). 재생이 끝나면 둘은 같다
//   · 상대 카드는 서버가 쇼다운 때만 보내 준다. 그 전에는 화면에 뒷면만 있다(값 자체가 브라우저에 없다)
import { h } from "../core/vdom.js";
import { useEffect, useRef, useState } from "../core/hooks.js";
import {
  STREET_LABELS, actionText, applyEvent, clampWager, displayFromState, eventDelay, normalizeCode,
  planUpdate, positionLabel, remainingSeconds, seatOrder, validName,
} from "./roomLogic.js";

function newId() {
  return globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2) + "-request";
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ── 자식 컴포넌트 (상태 없이 props만 받는다) ──

// 금색 칩 탑: 높이는 금액의 크기만 어림해 보여 준다. 정확한 값은 옆의 숫자다
function ChipStack({ value }) {
  const levels = value > 0 ? Math.min(10, Math.max(1, Math.ceil(Math.log2(value + 1)))) : 0;
  return h("div", { className: "chips", "aria-hidden": "true" },
    ...[0, 1, 2].map((column) => h("span", { className: "chip-tower", key: column },
      ...Array.from({ length: Math.max(0, levels - column * 2) }, (_, i) => h("i", { key: i, className: "chip", style: { bottom: i * 5 + "px" } })))));
}

function Card({ value, hidden = false }) {
  if (hidden) return h("div", { className: "card card-back", "aria-label": "비공개 카드" }, h("span", {}, "JP"));
  if (!value) return h("div", { className: "card card-empty", "aria-hidden": "true" });
  const suit = value.slice(-1);
  const rank = value.slice(0, -1).replace("T", "10");
  return h("div", { className: "card card-face" + (/[♥♦]/.test(suit) ? " red" : ""), "aria-label": rank + suit },
    h("b", {}, rank), h("span", {}, suit));
}

function Seat({ seat, where, you, stack, committed, cards, faceDown, turn, seconds, lastText, phase, handKey, winner }) {
  const empty = !seat.occupied;
  const status = empty ? "빈 자리" : !seat.connected ? "연결 끊김" : phase === "lobby" || phase === "hand_over" ? (seat.ready ? "준비 완료" : "대기 중") : "접속 중";
  const cardNodes = cards
    ? cards.map((value, index) => h(Card, { key: handKey + "-" + where + "-" + index + "-" + value, value }))
    : Array.from({ length: faceDown }, (_, index) => h(Card, { key: handKey + "-" + where + "-back-" + index, hidden: true }));
  return h("section", { className: "seat seat-" + where + (turn ? " is-turn" : "") + (empty ? " is-empty" : "") + (winner ? " is-winner" : ""), "aria-current": turn ? "step" : null },
    h("div", { className: "seat-cards" }, ...cardNodes),
    h("div", { className: "hud" },
      h("div", { className: "hud-row" },
        h("span", { className: "hud-name" }, empty ? "상대를 기다리는 중" : seat.name + (you ? " · 나" : "")),
        !empty && phase !== "lobby" ? h("span", { className: "hud-pos" }, positionLabel(seat)) : null),
      h("div", { className: "hud-row" },
        h("span", { className: "hud-label" }, "CHIPS"),
        h("strong", { className: "hud-stack" }, empty ? "—" : Number(stack).toLocaleString())),
      h("div", { className: "hud-row hud-meta" },
        h("span", { className: "presence " + (empty ? "off" : seat.connected ? "on" : "lost") }, status),
        turn ? h("span", { className: "turn-clock" }, "차례" + (seconds === null ? "" : " · " + seconds + "초")) : null),
      lastText ? h("div", { className: "hud-last" }, lastText) : null),
    h("div", { className: "seat-chips" }, h(ChipStack, { value: empty ? 0 : stack })),
    committed > 0 ? h("div", { className: "bet-chip" }, h("i", { className: "chip" }), h("span", {}, Number(committed).toLocaleString())) : null);
}

// ── 루트 컴포넌트 (상태와 Hook은 여기에만 둔다) ──

export function RoomApp({ client, initialName = "", initialCode = "", startError = "" }) {
  const [signedIn, setSignedIn] = useState(Boolean(initialName));
  const [name, setName] = useState(initialName);
  const [codeInput, setCodeInput] = useState(normalizeCode(initialCode));
  const [code, setCode] = useState(null);
  const [state, setState] = useState(null);
  const [display, setDisplay] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(startError);
  const [link, setLink] = useState("ok");
  const [wager, setWager] = useState(40);
  const [retry, setRetry] = useState(null);
  const [preview, setPreview] = useState(null);
  const [now, setNow] = useState(() => performance.now());
  // 렌더링과 무관하게 유지하는 동기화 장부: 마지막으로 받은 버전·이벤트 번호, 재생 대기열
  const sync = useRef({ instance: null, version: null, gameVersion: null, lastSeq: 0, queue: [], target: null, playing: false, timer: null, receivedAt: 0, hasDisplay: false, alive: true, inFlight: false });

  // 재생 대기열에서 이벤트를 하나씩 꺼내 화면에 반영한다. 다 비면 서버 상태와 똑같이 맞춘다
  const pump = () => {
    const s = sync.current;
    if (!s.alive) return;
    const event = s.queue.shift();
    if (!event) {
      s.playing = false;
      s.timer = null;
      if (s.target) setDisplay(displayFromState(s.target));
      return;
    }
    s.playing = true;
    setDisplay((current) => applyEvent(current || displayFromState(s.target), event));
    s.timer = setTimeout(pump, eventDelay(event));
  };

  // 서버 상태를 받는 유일한 입구 (대기 요청의 응답, 내 행동의 응답, 거절 응답에 실린 최신 상태)
  const accept = (next) => {
    const s = sync.current;
    if (!next) return;
    if (s.instance && next.instance !== s.instance) {
      // 서버가 다시 시작돼 방이 복구됐다: 이전 번호표(버전·이벤트 번호)는 버리고 새 상태로 바로 맞춘다
      clearTimeout(s.timer);
      Object.assign(s, { version: null, gameVersion: null, lastSeq: 0, queue: [], playing: false, timer: null, hasDisplay: false });
    }
    s.instance = next.instance;
    if (s.version !== null && next.version < s.version) return; // 늦게 도착한 옛 응답은 버린다
    const previousSeq = s.lastSeq;
    const plan = planUpdate(s.lastSeq, next, s.hasDisplay);
    s.version = next.version;
    s.target = next;
    s.receivedAt = performance.now();
    s.lastSeq = Math.max(s.lastSeq, next.lastEventSeq);
    setState(next);
    setNow(s.receivedAt);
    if (next.gameVersion !== s.gameVersion) { // 게임이 실제로 진행됐을 때만 베팅 입력을 최소값으로 되돌린다 (접속 표시 변화로는 건드리지 않는다)
      s.gameVersion = next.gameVersion;
      if (Number.isInteger(next.minRaiseTo)) setWager(next.minRaiseTo);
    }
    if (plan.mode === "replay") {
      s.queue.push(...plan.events);
      if (!s.playing) pump();
      return;
    }
    if (s.playing && next.lastEventSeq === previousSeq) return; // 새 이벤트 없음: 재생이 끝나면 이 상태로 맞춰진다
    // 첫 접속·새로고침·이벤트 누락: 재생하지 않고 서버 상태로 바로 맞춘다
    clearTimeout(s.timer);
    s.queue = [];
    s.playing = false;
    s.timer = null;
    s.hasDisplay = true;
    setDisplay(displayFromState(next));
  };

  const leaveLocal = (message) => {
    const s = sync.current;
    clearTimeout(s.timer);
    Object.assign(s, { instance: null, version: null, gameVersion: null, lastSeq: 0, queue: [], target: null, playing: false, timer: null, hasDisplay: false });
    client.forgetRoom();
    setCode(null);
    setState(null);
    setDisplay(null);
    setRetry(null);
    setLink("ok");
    setNotice(message || "");
  };

  // 요청 하나를 보낸다. 서버가 답하지 못한 경우에만 "같은 요청"(같은 ID)을 다시 보낼 수 있게 남겨 둔다
  const send = async (envelope) => {
    const s = sync.current;
    if (s.inFlight) return null; // 빠른 연속 클릭은 한 번만 보낸다
    s.inFlight = true;
    setBusy(true);
    try {
      const result = await client.request(envelope.path, envelope.body);
      setRetry(null);
      setNotice("");
      if (result.state) accept(result.state);
      return result;
    } catch (error) {
      if (error.payload && error.payload.state) accept(error.payload.state);
      if (error.status) {
        setRetry(null); // 서버가 거절을 답했다: 다시 보내도 같은 결과이므로 재시도하지 않는다
        setNotice(error.message);
      } else {
        setRetry(envelope);
        setNotice("서버에 닿지 못했습니다. 연결을 확인한 뒤 같은 요청으로 다시 시도하세요.");
      }
      return null;
    } finally {
      s.inFlight = false;
      setBusy(false);
    }
  };

  const enter = (result) => {
    if (!result || !result.state) return;
    client.rememberRoom(result.state.code);
    setCode(result.state.code);
  };
  const createRoom = async () => enter(await send({ path: "/api/rooms", body: { request_id: newId() } }));
  const joinRoom = async (target) => {
    const wanted = normalizeCode(target);
    if (wanted.length !== 6) return setNotice("방 코드는 6자입니다.");
    enter(await send({ path: "/api/rooms/" + wanted + "/join", body: {} }));
  };
  const signIn = async () => {
    if (!validName(name)) return setNotice("닉네임은 1~24자로 입력하세요.");
    if (sync.current.inFlight) return;
    sync.current.inFlight = true;
    setBusy(true);
    try {
      const saved = await client.signIn(name.trim());
      setName(saved);
      setSignedIn(true);
      setNotice("");
    } catch (error) {
      setNotice(error.message);
    } finally {
      sync.current.inFlight = false;
      setBusy(false);
    }
  };
  const setReady = (value) => send({ path: "/api/rooms/" + code + "/ready", body: { ready: value, hand_no: state.handNo } });
  const act = (action, to) => send({
    path: "/api/rooms/" + code + "/action",
    body: { action_id: newId(), expected_version: state.gameVersion, action, ...(to === undefined ? {} : { to }) },
  });
  const exitRoom = async () => {
    if (state && state.phase === "lobby") await send({ path: "/api/rooms/" + code + "/leave", body: {} });
    leaveLocal("");
  };

  // 화면이 내려갈 때 재생 타이머 정리
  useEffect(() => {
    const s = sync.current;
    s.alive = true;
    return () => {
      s.alive = false;
      clearTimeout(s.timer);
    };
  }, []);

  // 새로고침 뒤 복귀: 주소에 남은 방 코드와 저장된 게스트 토큰으로 같은 좌석에 다시 들어간다
  useEffect(() => {
    if (signedIn && !code && normalizeCode(initialCode).length === 6) joinRoom(initialCode);
  }, [signedIn]);

  // 방에 있는 동안 서버 상태를 계속 받아 온다 (바뀔 때까지 서버가 응답을 잠시 붙잡는 방식 = long polling)
  useEffect(() => {
    if (!code) return undefined;
    const s = sync.current;
    const controller = new AbortController();
    let stopped = false;
    (async () => {
      let failures = 0;
      while (!stopped) {
        try {
          const query = s.version === null ? "?after=0" : "?since=" + s.version + "&after=" + s.lastSeq + "&wait=5";
          const result = await client.request("/api/rooms/" + code + "/state" + query, undefined, controller.signal);
          if (stopped) return;
          failures = 0;
          setLink("ok");
          accept(result.state);
        } catch (error) {
          if (stopped) return;
          if (error.status === 404 || error.status === 403) return leaveLocal(error.message);
          failures += 1;
          setLink("retrying"); // 끊겨도 좌석은 서버에 남아 있다. 다시 연결되면 최신 상태를 받아 복원한다
          await sleep(Math.min(5000, 700 * failures));
        }
      }
    })();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [code]);

  // 남은 시간 표시용 시계 (보여 주기만 한다. 시간 초과 판정은 서버가 한다)
  const ticking = Boolean(state && (state.phase === "playing" || state.phase === "hand_over"));
  useEffect(() => {
    if (!ticking) return undefined;
    const id = setInterval(() => setNow(performance.now()), 500);
    return () => clearInterval(id);
  }, [ticking]);

  // 참가 전 미리보기: 방 코드 6자를 입력하면 공개 정보(이름·인원)만 조회한다 (서버는 Mini Redis 캐시에서 먼저 읽는다)
  useEffect(() => {
    if (!signedIn || code || codeInput.length !== 6) {
      setPreview(null);
      return undefined;
    }
    let cancelled = false;
    client.request("/api/rooms/" + codeInput + "/public").then((result) => {
      if (!cancelled) setPreview(result.room);
    }).catch(() => {
      if (!cancelled) setPreview({ missing: true });
    });
    return () => { cancelled = true; };
  }, [signedIn, code, codeInput]);

  const header = h("header", { className: "room-top" },
    h("div", { className: "logo" }, h("span", {}, "JUNGLE"), h("b", {}, "POKER LAB")),
    h("div", { className: "room-meta" },
      code ? h("span", { className: "room-code" }, "방 코드 ", h("strong", {}, code)) : null,
      signedIn ? h("span", { className: "me" }, name) : null,
      code ? h("span", { className: "link link-" + link }, link === "ok" ? "서버 연결됨" : "재연결 중…") : null));
  const noticeBar = notice ? h("p", { className: "notice", role: "status" }, notice) : null;

  if (!signedIn) {
    return h("div", { className: "room-shell" }, header,
      h("section", { className: "panel" },
        h("h1", {}, "닉네임을 정하세요"),
        h("p", { className: "hint" }, "이 브라우저에 게스트로 저장됩니다. 가상 칩만 사용하며 실제 돈은 쓰지 않습니다."),
        h("div", { className: "form-row" },
          h("input", { className: "field", type: "text", maxLength: 24, placeholder: "닉네임 (1~24자)", value: name, "aria-label": "닉네임",
            onInput: (event) => setName(event.target.value), onKeyDown: (event) => { if (event.key === "Enter") signIn(); } }),
          h("button", { className: "btn btn-main", disabled: busy, onClick: signIn }, "입장")),
        noticeBar));
  }

  if (!code) {
    const seated = preview && !preview.missing ? preview.seats.filter((seat) => seat.occupied) : [];
    return h("div", { className: "room-shell" }, header,
      h("section", { className: "panel" },
        h("h1", {}, "방 만들기 또는 참가"),
        h("p", { className: "hint" }, "한 사람이 방을 만들고, 화면에 나온 방 코드를 상대에게 알려 주세요. 두 사람은 같은 서버 주소로 접속해야 합니다."),
        h("div", { className: "form-row" },
          h("button", { className: "btn btn-main", disabled: busy, onClick: createRoom }, "새 방 만들기")),
        h("div", { className: "form-row" },
          h("input", { className: "field field-code", type: "text", maxLength: 6, placeholder: "방 코드 6자", value: codeInput, "aria-label": "방 코드",
            onInput: (event) => setCodeInput(normalizeCode(event.target.value)), onKeyDown: (event) => { if (event.key === "Enter") joinRoom(codeInput); } }),
          h("button", { className: "btn", disabled: busy || codeInput.length !== 6, onClick: () => joinRoom(codeInput) }, "코드로 참가")),
        preview ? h("p", { className: "preview" }, preview.missing ? "이 코드의 방을 찾지 못했습니다."
          : seated.map((seat) => seat.name).join(", ") + " · " + seated.length + "/2명 · " + (preview.phase === "lobby" ? "대기 중" : "게임 진행 중")) : null,
        noticeBar));
  }

  if (!state || !display) {
    return h("div", { className: "room-shell" }, header, h("section", { className: "panel" }, h("p", {}, "방 상태를 불러오는 중…"), noticeBar));
  }

  const [topSeat, bottomSeat] = seatOrder(state.you.seat);
  const names = state.seats.map((seat) => seat.name);
  const synced = display.synced; // 재생이 끝나 화면이 서버 상태와 같은가
  const handKey = code + "-" + display.handNo;
  const myTurn = synced && state.phase === "playing" && state.turnSeat === state.you.seat;
  const legal = new Set(myTurn ? state.legalActions : []);
  const locked = busy || Boolean(retry);
  const mayRaise = legal.has("bet") || legal.has("raise");
  const seconds = synced ? remainingSeconds(state.turnRemainingMs, sync.current.receivedAt, now) : null;
  const nextIn = synced && state.phase === "hand_over" ? remainingSeconds(state.nextHandInMs, sync.current.receivedAt, now) : null;
  const me = state.seats[state.you.seat];
  const other = state.seats[topSeat];
  const showResult = synced && state.result && (state.phase === "hand_over" || state.phase === "match_over");
  const winnerSeat = showResult ? state.result.winnerSeat : undefined;
  const lastText = display.last ? actionText(display.last, names) : "";

  const seatNode = (index, where) => {
    const seat = state.seats[index];
    const mine = index === state.you.seat;
    // 상대 카드는 쇼다운 재생이 끝난 뒤에만 앞면으로 보인다
    const cards = seat.cards && (mine || synced) ? seat.cards : null;
    return h(Seat, {
      seat, where, you: mine, stack: display.stacks[index], committed: display.committed[index], cards,
      faceDown: seat.occupied && state.phase !== "lobby" && state.street ? seat.cardCount : 0,
      turn: synced && state.phase === "playing" && state.turnSeat === index,
      seconds, phase: state.phase, handKey, winner: winnerSeat === index,
      lastText: display.last && display.last.seat === index ? lastText : "",
    });
  };

  let resultText = "";
  if (showResult) {
    const result = state.result;
    resultText = result.winnerSeat === null ? "무승부 · 팟 " + result.pot.toLocaleString() + " 분배"
      : (result.winnerSeat === state.you.seat ? "승리" : "패배") + " · " + names[result.winnerSeat] + " +" + result.pot.toLocaleString()
        + (result.reason === "showdown" && result.hands ? " · " + result.hands[result.winnerSeat] : " · 상대 폴드");
  }
  const storageText = state.recordStatus === "unknown" ? "결과 저장을 확인하는 중입니다. 확인되면 다음 판을 시작할 수 있습니다."
    : state.recordStatus === "blocked" ? "결과 저장에 충돌이 있어 이 방은 더 진행할 수 없습니다." : "";

  const center = state.phase === "lobby"
    ? h("div", { className: "center center-lobby" },
        h("span", { className: "center-label" }, "방 코드"),
        h("strong", { className: "big-code" }, code),
        h("small", {}, other.occupied ? "두 사람 모두 준비를 누르면 시작합니다" : "상대에게 이 코드를 알려 주세요"))
    : h("div", { className: "center" },
        h("div", { className: "pot" }, h("span", { className: "center-label" }, "POT"), h("strong", { className: "pot-value" }, Number(display.pot).toLocaleString())),
        h("div", { className: "board" }, ...Array.from({ length: 5 }, (_, index) => h(Card, { key: handKey + "-board-" + index + "-" + (display.board[index] || "x"), value: display.board[index] }))),
        h(ChipStack, { value: display.pot }));

  const flight = display.flight
    ? h("span", { key: display.flight.id, className: "fly fly-" + (display.flight.from === "pot" ? "pot" : display.flight.from === bottomSeat ? "bottom" : "top")
        + "-to-" + (display.flight.to === "pot" ? "pot" : display.flight.to === bottomSeat ? "bottom" : "top"), "aria-hidden": "true" },
        h("i", { className: "chip" }), String(display.flight.amount))
    : null;

  const controls = [];
  if (state.phase === "lobby") {
    controls.push(h("button", { key: "ready", className: "btn btn-main", disabled: locked || !other.occupied, onClick: () => setReady(!me.ready) }, me.ready ? "준비 취소" : "준비"));
  } else if (state.phase === "hand_over" && synced) {
    controls.push(h("button", { key: "next", className: "btn btn-main", disabled: locked || me.ready || Boolean(storageText), onClick: () => setReady(true) },
      me.ready ? "상대를 기다리는 중" : "다음 판 준비"));
    if (nextIn !== null && !storageText) controls.push(h("span", { key: "auto", className: "auto-next" }, other.connected ? nextIn + "초 뒤 자동 시작" : "상대 재접속을 기다리는 중"));
  } else if (state.phase === "match_over" && synced) {
    controls.push(h("span", { key: "over", className: "auto-next" }, "매치 종료 · 한쪽 칩이 모두 소진됐습니다"));
  } else if (myTurn) {
    if (legal.has("fold")) controls.push(h("button", { key: "fold", className: "btn btn-fold", disabled: locked, onClick: () => act("fold") }, "폴드"));
    if (legal.has("check")) controls.push(h("button", { key: "check", className: "btn", disabled: locked, onClick: () => act("check") }, "체크"));
    if (legal.has("call")) controls.push(h("button", { key: "call", className: "btn", disabled: locked, onClick: () => act("call") }, "콜 " + state.toCall.toLocaleString()));
    if (mayRaise) {
      const min = state.minRaiseTo;
      const max = state.maxRaiseTo;
      const pick = (value) => setWager(clampWager(value, min, max));
      controls.push(h("span", { key: "wager", className: "wager" },
        h("input", { className: "wager-range", type: "range", min, max, step: 1, value: wager, disabled: locked, "aria-label": "베팅 총액 조절", onInput: (event) => pick(event.target.value) }),
        h("input", { className: "field wager-number", type: "number", min, max, step: 1, value: wager, disabled: locked, "aria-label": "베팅 총액", onInput: (event) => setWager(Number(event.target.value)) }),
        h("button", { className: "btn btn-quick", disabled: locked, onClick: () => pick(min) }, "최소"),
        h("button", { className: "btn btn-quick", disabled: locked, onClick: () => pick(state.pot + state.toCall * 2) }, "팟"),
        h("button", { className: "btn btn-main", disabled: locked || !Number.isInteger(wager) || wager < min || wager > max,
          onClick: () => act(legal.has("bet") ? "bet" : "raise", wager) }, (legal.has("bet") ? "베팅 " : "레이즈 ") + wager.toLocaleString())));
    }
    if (legal.has("all_in")) controls.push(h("button", { key: "allin", className: "btn btn-allin", disabled: locked, onClick: () => act("all_in") }, "올인"));
  } else if (state.phase === "playing") {
    controls.push(h("span", { key: "wait", className: "auto-next" }, synced ? names[state.turnSeat] + "의 차례입니다" : "진행 상황을 재생하는 중…"));
  }
  if (retry) controls.push(h("button", { key: "retry", className: "btn btn-retry", disabled: busy, onClick: () => send(retry) }, "같은 요청 다시 보내기"));
  controls.push(h("button", { key: "exit", className: "btn btn-ghost", disabled: busy, onClick: exitRoom }, state.phase === "lobby" ? "방 나가기" : "로비로"));

  return h("div", { className: "room-shell" }, header,
    h("main", { className: "arena" },
      h("div", { className: "backdrop", "aria-hidden": "true" }, h("i", { className: "wall wall-left" }), h("i", { className: "wall wall-right" }), h("i", { className: "wall wall-top" })),
      h("div", { className: "table", "aria-hidden": "true" }, h("div", { className: "felt" }, h("div", { className: "felt-line" }),
        h("div", { className: "felt-logo" }, h("span", {}, "JUNGLE"), h("b", {}, "POKER LAB")))),
      h("div", { className: "hand-label" }, state.phase === "lobby" ? "LOBBY" : "HAND " + display.handNo + (state.street && synced ? " · " + (STREET_LABELS[state.street] || state.street) : "")),
      seatNode(topSeat, "top"),
      center,
      flight,
      seatNode(bottomSeat, "bottom")),
    h("p", { className: "status", role: "status" },
      h("span", { className: "status-dot" }),
      showResult ? resultText : synced ? state.notice : lastText || "진행 상황을 재생하는 중…"),
    storageText ? h("p", { className: "notice" }, storageText) : null,
    state.recovered && state.phase !== "playing" ? h("p", { className: "notice" }, "서버가 다시 시작됐습니다. 진행 중이던 핸드는 무효이며 마지막으로 저장된 칩에서 이어갑니다.") : null,
    noticeBar,
    h("div", { className: "controls" }, ...controls),
    h("p", { className: "fine" }, "가상 칩 전용 · 카드·턴·칩·승패는 서버가 판정합니다 · 차례 제한 " + Math.round(state.turnSeconds) + "초(넘기면 체크, 베팅을 받은 상태면 폴드)"));
}
