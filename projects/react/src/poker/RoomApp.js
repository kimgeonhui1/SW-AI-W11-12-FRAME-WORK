// [RoomApp.js] JUNGLE POKER LAB 멀티플레이 화면 — 닉네임 → 방 생성/참가 → 준비 → 2~4인 대전
//
// 흐름: 내 행동 요청 → 서버가 판정 → 두 사람 모두 같은 번호의 이벤트를 받음 → 각자 화면에서 순서대로 재생
//   · 화면은 결과를 정하지 않는다. 버튼은 "요청"만 보내고, 칩·팟·보드·승패는 서버가 준 값만 그린다
//   · state  = 서버가 준 최신 정답 / display = 지금 그리는 값(재생 중에는 과거). 재생이 끝나면 둘은 같다
//   · 다른 사람 카드는 서버가 쇼다운 때(끝까지 남은 사람만) 보내 준다. 그 전에는 뒷면만 있다(값 자체가 브라우저에 없다)
//   · 좌석: 본인이 아래, 나머지는 테이블 순서대로 왼쪽 → 위 → 오른쪽 (roomLogic.seatLayout)
//
// 3D 테이블 (외부 라이브러리 없이 CSS 3D): .table 이 하나의 3D 평면이고, 좌석·카드·칩·팟이 모두 그 안에 있다.
//   카메라 각도는 CSS 변수 --tilt 하나로 정한다 (3D 52°, 2D 0°). 이름표(HUD)·팟 글자는 평면 위에 세워
//   카메라를 바라보게 하므로(-tilt 만큼 되돌림) 각도가 바뀌어도 좌석을 따라간다. 모든 값은 room.css에 있다.
import { h } from "../core/vdom.js";
import { useEffect, useRef, useState } from "../core/hooks.js";
import {
  BLOOM_PREF, STREET_LABELS, VIEW_PREF, actTag, applyEvent, betLimits, chipChange, chipChangeText, clampWager, displayFromState,
  eventDelay, normalizeCode, flightPath, planUpdate, positionLabel, potsText, readPref, rebuyText, remainingSeconds, resultText,
  seatLayout, syncDisplay, validName, writePref,
} from "./roomLogic.js";

function newId() {
  return globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2) + "-request";
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ── 자식 컴포넌트 (상태 없이 props만 받는다) ──

// 금색 칩 탑: 높이는 금액의 크기만 어림해 보여 준다. 정확한 값은 옆의 숫자다
// 칩은 테이블 평면에 눕힌 원판이고, --i 번째 칩은 그만큼 위(translateZ)로 쌓인다
function ChipStack({ value }) {
  const levels = value > 0 ? Math.min(10, Math.max(1, Math.ceil(Math.log2(value + 1)))) : 0;
  return h("div", { className: "chips", "aria-hidden": "true" },
    ...[0, 1, 2].map((column) => h("span", { className: "chip-tower", key: column },
      ...Array.from({ length: Math.max(0, levels - column * 2) }, (_, i) => h("i", { key: i, className: "chip", style: { "--i": String(i) } })))));
}

// 카드: 앞면·뒷면 두 장을 겹친 3D 카드. 값이 없으면 뒷면이 위, 값이 오면 뒤집혀 앞면이 위 (CSS transition)
// 상대 카드는 쇼다운 전에 값이 없으므로 앞면 자리는 비어 있다
function Card({ value, hidden = false }) {
  if (!value && !hidden) return h("div", { className: "card card-empty", "aria-hidden": "true" });
  const suit = value ? value.slice(-1) : "";
  const rank = value ? value.slice(0, -1).replace("T", "10") : "";
  return h("div", { className: "card3d " + (value ? "is-up" : "is-down"), "aria-label": value ? rank + suit : "비공개 카드" },
    h("div", { className: "card card-back side-back", "aria-hidden": "true" }, h("span", {}, "JP")),
    value
      ? h("div", { className: "card card-face side-front" + (/[♥♦]/.test(suit) ? " red" : ""), "aria-hidden": "true" }, h("b", {}, rank), h("span", {}, suit))
      : h("div", { className: "card side-front card-blank", "aria-hidden": "true" }));
}

function Seat({ seat, where, you, stack, committed, cards, faceDown, turn, seconds, act, net, phase, handNo, handKey, winner }) {
  const empty = !seat.occupied;
  const status = empty ? "빈 자리" : !seat.connected ? "연결 끊김" : phase === "lobby" || phase === "hand_over" ? (seat.ready ? "준비 완료" : "대기 중") : "접속 중";
  // 좌석 상태 표시 한 곳: 파산 뒤 복귀 대기 · 다음 핸드부터 참가. 폴드·올인은 행동 표시(act)가 보여 주므로
  // 행동 기록이 없을 때(오래 끊겼다 돌아온 경우 등)만 배지로 대신 보여 준다
  const badge = empty || phase === "lobby" ? null
    : seat.busted ? ["out", rebuyText(seat, phase, handNo, true)]
      : !act && seat.folded ? ["fold", "폴드"] : !act && seat.allIn ? ["allin", "올인"]
        : phase === "playing" && !seat.inHand ? ["wait", "다음 핸드부터"] : null;
  const tag = actTag(act);
  // key에 카드 값을 넣지 않는다: 같은 카드 요소가 뒷면 → 앞면으로 바뀌어야 뒤집히는 애니메이션이 보인다 (새 핸드면 handKey가 바뀌어 새로 나눠 준다)
  const cardNodes = cards
    ? cards.map((value, index) => h(Card, { key: handKey + "-" + where + "-" + index, value }))
    : Array.from({ length: faceDown }, (_, index) => h(Card, { key: handKey + "-" + where + "-" + index, hidden: true }));
  return h("section", { className: "seat seat-" + where + (turn ? " is-turn" : "") + (empty ? " is-empty" : "") + (winner ? " is-winner" : "") + (seat.folded ? " is-folded" : ""),
    "aria-current": turn ? "step" : null, "data-seat": String(seat.seat) },
    h("div", { className: "seat-cards" }, ...cardNodes),
    h("div", { className: "hud" },
      h("div", { className: "hud-row" },
        h("span", { className: "hud-name" }, empty ? "빈 자리" : seat.name + (you ? " · 나" : "")),
        !empty && seat.isHost ? h("span", { className: "hud-host", title: "방장" }, "방장") : null,
        !empty && phase !== "lobby" && positionLabel(seat) ? h("span", { className: "hud-pos" }, positionLabel(seat)) : null),
      h("div", { className: "hud-row" },
        h("span", { className: "hud-label" }, "CHIPS"),
        h("strong", { className: "hud-stack" }, empty ? "—" : Number(stack).toLocaleString())),
      h("div", { className: "hud-row hud-meta" },
        h("span", { className: "presence " + (empty ? "off" : seat.connected ? "on" : "lost") }, status),
        badge ? h("span", { className: "seat-badge badge-" + badge[0] }, badge[1]) : null,
        turn ? h("span", { className: "turn-clock" }, "차례" + (seconds === null ? "" : " · " + seconds + "초")) : null),
      // 이번 스트리트 마지막 행동(크게). 콜은 "+더 낸 금액", 베팅·레이즈·올인은 "총 = 이번 스트리트 총 베팅액"
      tag ? h("div", { className: "hud-act act-" + act.kind + (act.auto ? " act-auto" : "") }, tag) : null,
      net !== null && net !== undefined ? h("div", { className: "hud-net " + (net > 0 ? "up" : net < 0 ? "down" : "even") },
        "이번 핸드 " + (net > 0 ? "+" : net < 0 ? "−" : "±") + Math.abs(net).toLocaleString()) : null),
    h("div", { className: "seat-chips" }, h(ChipStack, { value: empty ? 0 : stack })),
    !empty && phase !== "lobby" && seat.isButton ? h("i", { className: "dealer-btn", "aria-hidden": "true" }, "D") : null,
    committed > 0 ? h("div", { className: "bet-chip" }, h("i", { className: "chip" }), h("span", {}, Number(committed).toLocaleString())) : null);
}

// 2D/3D·빛 번짐 토글 (선택은 이 브라우저에 기억한다)
function ViewToggles({ view, bloom, onView, onBloom }) {
  return h("div", { className: "view-toggles", role: "group", "aria-label": "테이블 보기 설정" },
    h("button", { type: "button", className: "view-btn", "aria-pressed": view === "2d" ? "true" : "false", onClick: onView }, view === "3d" ? "2D로 보기" : "3D로 보기"),
    h("button", { type: "button", className: "view-btn", "aria-pressed": bloom ? "true" : "false", onClick: onBloom }, "빛 번짐 " + (bloom ? "켬" : "끔")));
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
  const [capacity, setCapacity] = useState(4);
  const [now, setNow] = useState(() => performance.now());
  const [view, setView] = useState(() => readPref(globalThis.localStorage, VIEW_PREF));
  const [bloom, setBloom] = useState(() => readPref(globalThis.localStorage, BLOOM_PREF) === "on");
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
      if (s.target) setDisplay((current) => syncDisplay(current, s.target));
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
    // 첫 접속·새로고침(after=0)이면 응답에 이번 핸드 이벤트가 모두 있다. 그 밖에는 지금 표시를 이어 쓴다
    setDisplay((current) => (previousSeq === 0 ? displayFromState(next) : syncDisplay(current, next)));
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
  const createRoom = async () => enter(await send({ path: "/api/rooms", body: { request_id: newId(), max_seats: capacity } }));
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
  const startMatch = () => send({ path: "/api/rooms/" + code + "/start", body: { hand_no: 0 } });
  const nextRound = () => send({ path: "/api/rooms/" + code + "/next-round", body: { hand_no: state.handNo } });
  // 칩을 정산하고 자리에서 일어난다 (이번 매치에는 다시 앉을 수 없다). 핸드 사이에만 가능하다
  const cashOut = async () => {
    const result = await send({ path: "/api/rooms/" + code + "/leave", body: {} });
    if (result) leaveLocal(result.cashOut !== undefined ? "칩 " + Number(result.cashOut).toLocaleString() + "개를 정산하고 나왔습니다." : "");
  };
  const act = (action, to) => send({
    path: "/api/rooms/" + code + "/action",
    body: { action_id: newId(), expected_version: state.gameVersion, action, ...(to === undefined ? {} : { to }) },
  });
  const toggleView = () => {
    const next = view === "3d" ? "2d" : "3d";
    setView(next);
    writePref(globalThis.localStorage, VIEW_PREF, next);
  };
  const toggleBloom = () => {
    setBloom(!bloom);
    writePref(globalThis.localStorage, BLOOM_PREF, bloom ? "off" : "on");
  };
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
        h("p", { className: "hint" }, "한 사람이 방을 만들고, 화면에 나온 방 코드를 다른 사람들에게 알려 주세요. 모두 같은 서버 주소로 접속해야 합니다."),
        h("div", { className: "form-row" },
          h("div", { className: "seat-count", role: "group", "aria-label": "최대 인원" },
            ...[2, 3, 4].map((count) => h("button", { key: count, type: "button", className: "btn btn-quick", "aria-pressed": capacity === count ? "true" : "false",
              disabled: busy, onClick: () => setCapacity(count) }, count + "인"))),
          h("button", { className: "btn btn-main", disabled: busy, onClick: createRoom }, "새 방 만들기 (최대 " + capacity + "명)")),
        h("div", { className: "form-row" },
          h("input", { className: "field field-code", type: "text", maxLength: 6, placeholder: "방 코드 6자", value: codeInput, "aria-label": "방 코드",
            onInput: (event) => setCodeInput(normalizeCode(event.target.value)), onKeyDown: (event) => { if (event.key === "Enter") joinRoom(codeInput); } }),
          h("button", { className: "btn", disabled: busy || codeInput.length !== 6, onClick: () => joinRoom(codeInput) }, "코드로 참가")),
        preview ? h("p", { className: "preview" }, preview.missing ? "이 코드의 방을 찾지 못했습니다."
          : seated.map((seat) => seat.name).join(", ") + " · " + seated.length + "/" + preview.seats.length + "명 · " + (preview.phase === "lobby" ? "대기 중" : "게임 진행 중")) : null,
        noticeBar));
  }

  if (!state || !display) {
    return h("div", { className: "room-shell" }, header, h("section", { className: "panel" }, h("p", {}, "방 상태를 불러오는 중…"), noticeBar));
  }

  const layout = seatLayout(state.you.seat, state.seats.length);
  const whereOf = Object.fromEntries(layout.map((spot) => [spot.seat, spot.where]));
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
  const occupied = state.seats.filter((seat) => seat.occupied).length;
  const showResult = synced && state.result && (state.phase === "hand_over" || state.phase === "round_over");
  const winners = new Set(showResult ? state.result.winnerSeats || [] : []);
  const lastLog = display.log && display.log.length ? display.log[display.log.length - 1].text : "";

  const seatNode = (index, where) => {
    const seat = state.seats[index];
    const mine = index === state.you.seat;
    // 상대 카드는 쇼다운 재생이 끝난 뒤에만 앞면으로 보인다
    const cards = seat.cards && (mine || synced) ? seat.cards : null;
    return h(Seat, {
      key: "seat-" + where, seat, where, you: mine, stack: display.stacks[index], committed: display.committed[index], cards,
      faceDown: seat.occupied && state.phase !== "lobby" && state.street ? seat.cardCount : 0,
      turn: synced && state.phase === "playing" && state.turnSeat === index,
      seconds, phase: state.phase, handNo: state.handNo, handKey, winner: winners.has(index),
      act: seat.occupied && display.acts ? display.acts[index] : null,
      net: showResult && state.result.startStacks && state.result.startStacks[index] !== null
        ? state.result.endStacks[index] - state.result.startStacks[index] : null,
    });
  };

  // 이번 핸드 참가 여부: 쇼다운이면 hands에, 폴드로 끝났으면 서버가 남긴 inHand 표시로 안다
  const outcome = showResult ? resultText(state.result, names, state.you.seat, Boolean(me.inHand)) : "";
  const myChange = showResult ? chipChange(state.result, state.you.seat, me.stack) : null;
  const storageText = state.recordStatus === "unknown" ? "결과 저장을 확인하는 중입니다. 확인되면 다음 판을 시작할 수 있습니다."
    : state.recordStatus === "blocked" ? "결과 저장에 충돌이 있어 이 방은 더 진행할 수 없습니다." : "";

  const center = state.phase === "lobby"
    ? h("div", { className: "center center-lobby" },
        h("span", { className: "center-label" }, "방 코드"),
        h("strong", { className: "big-code" }, code),
        h("small", {}, occupied < 2 ? "다른 사람에게 이 코드를 알려 주세요 (최대 " + state.capacity + "명)"
          : "준비 " + state.readyCount + "/" + occupied + " · 모두 준비하면 바로 시작, 2명 이상 준비하면 방장이 시작할 수 있습니다"))
    : h("div", { className: "center" },
        h("div", { className: "pot" }, h("span", { className: "center-label" }, "POT"), h("strong", { className: "pot-value" }, Number(display.pot).toLocaleString()),
          potsText(display.pots) ? h("small", { className: "pot-split" }, potsText(display.pots)) : null),
        h("div", { className: "board" }, ...Array.from({ length: 5 }, (_, index) => h(Card, { key: handKey + "-board-" + index + "-" + (display.board[index] || "x"), value: display.board[index] }))),
        h(ChipStack, { value: display.pot }));

  // 최근 행동 기록 (이번 핸드만, 새 핸드가 시작되면 비운다). 넓은 화면은 테이블 중앙 위, 좁은 화면은 테이블 아래(좌석을 가리지 않게)
  const logList = (className) => (state.phase !== "lobby" && display.log && display.log.length
    ? h("ol", { className, "aria-label": "최근 행동" }, ...display.log.map((entry) => h("li", { key: className + "-" + entry.seq }, entry.text)))
    : null);

  const flight = display.flight
    ? h("span", { key: display.flight.id, className: "fly", style: flightPath(display.flight, whereOf), "aria-hidden": "true" },
        h("i", { className: "chip" }), String(display.flight.amount))
    : null;

  const controls = [];
  if (state.phase === "lobby") {
    controls.push(h("button", { key: "ready", className: "btn btn-main", disabled: locked || occupied < 2, onClick: () => setReady(!me.ready) }, me.ready ? "준비 취소" : "준비"));
    if (state.you.isHost) controls.push(h("button", { key: "start", className: "btn", disabled: locked || !state.canStart, onClick: startMatch }, "준비한 사람끼리 시작"));
  } else if (state.phase === "hand_over" && synced) {
    // 파산한 사람은 누를 버튼이 없다: 한 핸드를 관전한 뒤 서버가 1,000칩을 지급하고 자동으로 다시 넣어 준다
    if (me.busted) controls.push(h("span", { key: "busted", className: "auto-next wait-rebuy" }, rebuyText(me, state.phase, state.handNo, false)));
    else controls.push(h("button", { key: "next", className: "btn btn-main", disabled: locked || me.ready || Boolean(storageText), onClick: () => setReady(true) },
      me.ready ? "다른 사람을 기다리는 중" : "다음 판 준비"));
    if (nextIn !== null && !storageText) controls.push(h("span", { key: "auto", className: "auto-next" }, nextIn + "초 뒤 준비한 사람끼리 자동 시작"));
  } else if (state.phase === "round_over" && synced) {
    // 칩 가진 사람이 1명 이하라 관전할 핸드를 열 수 없다: 앉아 있는 누구나 "다음 라운드 시작"을 누를 수 있다(한 번만 반영)
    if (state.canNextRound) {
      controls.push(h("button", { key: "round", className: "btn btn-main", disabled: locked || Boolean(storageText), onClick: nextRound },
        "다음 라운드 시작 (칩 없는 사람에게 " + Number(state.rebuyAmount).toLocaleString() + "칩)"));
    }
    controls.push(h("span", { key: "round-note", className: "auto-next" }, state.canNextRound
      ? "칩 가진 사람이 1명이라 다음 핸드를 열 수 없습니다. 칩 보유자는 칩을 그대로 유지합니다."
      : "다른 사람이 들어오기를 기다리는 중입니다 (방 코드 " + code + ")"));
  } else if (state.phase === "playing" && synced && !me.inHand) {
    // 진행 중에 앉은 사람·이번 핸드를 쉬는 사람: 준비해 두면 다음 핸드에 카드를 받는다
    if (me.busted) controls.push(h("span", { key: "busted", className: "auto-next wait-rebuy" }, rebuyText(me, state.phase, state.handNo, false)));
    else controls.push(h("button", { key: "sit", className: "btn btn-main", disabled: locked || me.ready, onClick: () => setReady(true) },
      me.ready ? "다음 핸드 참가 예약됨" : "다음 핸드부터 참가"));
    controls.push(h("span", { key: "wait", className: "auto-next" }, names[state.turnSeat] + "의 차례입니다"));
  } else if (myTurn) {
    if (legal.has("fold")) controls.push(h("button", { key: "fold", className: "btn btn-fold", disabled: locked, onClick: () => act("fold") }, "폴드"));
    if (legal.has("check")) controls.push(h("button", { key: "check", className: "btn", disabled: locked, onClick: () => act("check") }, "체크"));
    if (legal.has("call")) controls.push(h("button", { key: "call", className: "btn", disabled: locked, onClick: () => act("call") }, "콜 " + state.toCall.toLocaleString()));
    const limits = betLimits(state, legal, mayRaise ? wager : null);
    if (mayRaise) {
      const min = state.minRaiseTo;
      const max = state.maxRaiseTo;
      const pick = (value) => setWager(clampWager(value, min, max));
      controls.push(h("span", { key: "wager", className: "wager" },
        h("span", { className: "wager-limits" }, limits.text),
        h("input", { className: "wager-range", type: "range", min, max, step: 1, value: wager, disabled: locked, "aria-label": "베팅 총액 조절", onInput: (event) => pick(event.target.value) }),
        h("input", { className: "field wager-number" + (limits.error ? " is-invalid" : ""), type: "number", min, max, step: 1, value: wager, disabled: locked, "aria-label": "베팅 총액 (이번 스트리트 총액)",
          onInput: (event) => setWager(event.target.value === "" ? NaN : Number(event.target.value)) }),
        limits.error ? h("span", { className: "wager-error", role: "alert" }, limits.error) : null,
        h("button", { className: "btn btn-quick", disabled: locked, onClick: () => pick(min) }, "최소"),
        h("button", { className: "btn btn-quick", disabled: locked, onClick: () => pick(state.pot + state.toCall * 2) }, "팟"),
        h("button", { className: "btn btn-main", disabled: locked || !Number.isInteger(wager) || wager < min || wager > max,
          onClick: () => act(legal.has("bet") ? "bet" : "raise", wager) }, (legal.has("bet") ? "베팅 총 " : "레이즈 총 ") + (Number.isFinite(wager) ? wager.toLocaleString() : "—"))));
    } else {
      controls.push(h("span", { key: "limits", className: "wager-limits" }, limits.text));
    }
    if (legal.has("all_in")) controls.push(h("button", { key: "allin", className: "btn btn-allin", disabled: locked, title: limits.allIn, onClick: () => act("all_in") }, "올인"));
    if (limits.allIn) controls.push(h("span", { key: "allin-note", className: "wager-limits" }, limits.allIn));
  } else if (state.phase === "playing") {
    controls.push(h("span", { key: "wait", className: "auto-next" }, synced ? names[state.turnSeat] + "의 차례입니다" : "진행 상황을 재생하는 중…"));
  }
  if (retry) controls.push(h("button", { key: "retry", className: "btn btn-retry", disabled: busy, onClick: () => send(retry) }, "같은 요청 다시 보내기"));
  if (state.phase !== "lobby" && synced && !(state.phase === "playing" && me.inHand)) {
    controls.push(h("button", { key: "cash", className: "btn btn-ghost", disabled: locked || Boolean(storageText), onClick: cashOut }, "칩 정산하고 나가기"));
  }
  controls.push(h("button", { key: "exit", className: "btn btn-ghost", disabled: busy, onClick: exitRoom }, state.phase === "lobby" ? "방 나가기" : "로비로 (자리 유지)"));

  return h("div", { className: "room-shell" }, header,
    // seats-N: 테이블 밖(행동 기록 등)도 인원수에 맞춰 배치할 수 있게 화면 상자에도 붙인다
    h("main", { className: "arena seats-" + state.seats.length + " view-" + view + (bloom ? " bloom-on" : "") },
      h("div", { className: "hand-label" }, state.phase === "lobby" ? "LOBBY" : "HAND " + display.handNo + (state.street && synced ? " · " + (STREET_LABELS[state.street] || state.street) : "")),
      h(ViewToggles, { view, bloom, onView: toggleView, onBloom: toggleBloom }),
      // 최근 행동 기록 (이번 핸드만, 새 핸드가 시작되면 비운다)
      logList("action-log"),
      // 3D 공간: 배경(바닥·벽)과 테이블 평면. 좌석·카드·칩·팟은 모두 테이블 평면 안에 있다
      h("div", { className: "scene" },
        // 배경: 연습 모드(poker.html)와 같은 구성 — 바닥 격자, 보라 바닥 빛, 네온 기둥 2개, 육각 간판, 양옆 벽 패널 — 을 3D 공간에 세움
        h("div", { className: "backdrop", "aria-hidden": "true" },
          h("i", { className: "floor" }), h("i", { className: "floor-glow" }),
          h("i", { className: "stand pillar pillar-left" }), h("i", { className: "stand pillar pillar-right" }),
          h("div", { className: "stand portal" }, h("span", {}, "POKER LAB"), h("small", {}, "N E O N   D I S T R I C T   /   0 1")),
          h("div", { className: "stand wall-panel panel-left" }, h("span", {}, "◇"), h("i", {}), h("i", {}), h("i", {})),
          h("div", { className: "stand wall-panel panel-right" }, h("span", {}, "♠"), h("i", {}), h("i", {}), h("i", {}))),
        h("div", { className: "table seats-" + state.seats.length },
          h("div", { className: "felt", "aria-hidden": "true" }, h("div", { className: "felt-line" }),
            h("div", { className: "felt-logo" }, h("span", {}, "JUNGLE"), h("b", {}, "POKER LAB"))),
          ...layout.filter((spot) => spot.where !== "bottom").map((spot) => seatNode(spot.seat, spot.where)),
          center,
          flight,
          seatNode(layout[0].seat, "bottom")))),
    h("p", { className: "status", role: "status" },
      h("span", { className: "status-dot" }),
      showResult ? outcome : synced ? state.notice : lastLog || "진행 상황을 재생하는 중…"),
    myChange ? h("p", { className: "chip-change", role: "status" }, "내 칩 · " + chipChangeText(myChange)) : null,
    logList("action-log action-log-below"),
    storageText ? h("p", { className: "notice" }, storageText) : null,
    state.recovered && state.phase !== "playing" ? h("p", { className: "notice" }, "서버가 다시 시작됐습니다. 진행 중이던 핸드는 무효이며 마지막으로 저장된 칩에서 이어갑니다.") : null,
    noticeBar,
    h("div", { className: "controls" }, ...controls),
    h("p", { className: "fine" }, "가상 칩 전용 · 카드·턴·칩·승패는 서버가 판정합니다 · 차례 제한 " + Math.round(state.turnSeconds) + "초(넘기면 체크, 베팅을 받은 상태면 폴드)"));
}
