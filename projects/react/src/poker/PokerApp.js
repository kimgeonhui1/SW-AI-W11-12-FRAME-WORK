import { h } from "../core/vdom.js";
import { useEffect, useRef, useState } from "../core/hooks.js";

function newId() {
  return globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
}

// Sculptural stacks indicate magnitude; the adjacent server value is authoritative.
function ChipStack({ value }) {
  const levels = value > 0 ? Math.min(9, Math.max(1, Math.ceil(Math.log2(value + 1)))) : 0;
  return h("div", { className: "chip-stack", "aria-hidden": "true" },
    ...[0, 1, 2].map((column) => h("span", { className: "chip-tower", key: column },
      ...Array.from({ length: Math.max(0, levels - column * 2) }, (_, i) =>
        h("i", { key: i, className: "gold-chip", style: { bottom: i * 4 + "px" } }))
    )));
}

function Card({ value, hidden = false, index = 0 }) {
  const red = value && /[♥♦]/.test(value);
  const suit = value ? value.slice(-1) : "";
  const rank = value ? value.slice(0, -1).replace("T", "10") : "";
  return h("div", { className: "playing-card deal-index-" + index + (red ? " red" : "") + (hidden ? " face-down" : value ? " card-reveal" : " card-slot"), "aria-label": hidden ? "상대 비공개 카드" : value || "미공개 보드" },
    hidden ? h("span", { className: "card-emblem" }, "◇") : value ? [
      h("span", { className: "card-corner" }, rank, h("small", {}, suit)),
      h("span", { className: "card-suit" }, suit),
      h("span", { className: "card-corner corner-bottom", "aria-hidden": "true" }, rank, h("small", {}, suit))
    ] : h("span", {}, "◇"));
}

function Trace({ event, index, selected, onSelect }) {
  const text = event.service === "Poker Server" && event.outcome === "ok"
    ? "서버 액션 검증 통과"
    : event.service === "Poker Server" && event.outcome === "rejected"
      ? "서버 액션 거부 · " + (event.result?.detail || "규칙 위반")
      : event.service === "Mini React"
        ? "DOM Patch 완료"
        : event.outcome === "miss"
    ? "HTTP 404 · 키 없음 (MISS)"
    : event.outcome === "hit"
      ? "HTTP " + event.status + " · 실제 캐시 HIT"
      : event.outcome === "ok"
        ? "HTTP " + event.status + " · 실제 응답"
        : event.outcome === "unavailable"
          ? "연결 실패 또는 결과 불명"
          : "HTTP " + event.status + " · " + (event.detail || "오류");
  const outcomeClass = event.outcome === "hit" ? " trace-hit"
    : event.outcome === "miss" ? " trace-miss"
      : event.outcome === "rejected" ? " trace-rejected"
        : ["ok"].includes(event.outcome) ? "" : " trace-error";
  return h("li", { className: "trace-row" + outcomeClass + (selected ? " selected" : "") },
    h("button", { type: "button", className: "trace-select", "aria-current": selected ? "step" : null, onClick: onSelect },
      h("span", { className: "trace-index" }, String(index + 1).padStart(2, "0")),
      h("span", { className: "trace-copy" },
        h("b", {}, event.service),
        h("code", {}, event.method + " " + event.path),
        h("small", {}, text),
        Number.isFinite(event.durationMs) ? h("small", { className: "trace-duration" }, event.durationMs.toFixed(2) + " ms") : null,
        event.traceId ? h("small", { className: "trace-id" }, "trace " + event.traceId.slice(0, 8)) : null
      )
    )
  );
}

function groupTraces(events) {
  const groups = [];
  const byKey = new Map();
  events.forEach((event, index) => {
    const key = event.actionId ? "action:" + event.actionId : event.traceId ? "trace:" + event.traceId : "event:" + index;
    let group = byKey.get(key);
    if (!group) {
      group = { key, actionId: event.actionId, traceId: event.traceId, events: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.events.push({ event, index });
  });
  return groups;
}

function dataText(value, fallback) {
  return value === undefined || value === null ? fallback : typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function Seat({ name, stack, cards, hidden, active, tag, handNo, position }) {
  const cardNodes = cards.map((value, index) => h(Card, { key: tag + "-" + handNo + "-" + index + "-" + (hidden ? "back" : value), value, hidden, index }));
  return h("section", { className: "seat seat-" + (tag === "P1" ? "human " : "bot ") + (active ? "active" : ""), "aria-current": active ? "step" : null },
    h("div", { className: "seat-top" },
      h("span", { className: "seat-avatar", "aria-hidden": "true" }, tag === "P1" ? Array.from(name)[0] : "♟"),
      h("span", { className: "seat-tag" }, tag),
      h("span", { className: "seat-name" }, name),
      position ? h("span", { className: "position-badge" }, position) : null,
      h("span", { className: "turn-dot" }, active ? "차례" : "")
    ),
    h("div", { className: "seat-cards" }, ...cardNodes),
    h("div", { className: "stack-line" },
      h("span", {}, "STACK"),
      h("strong", {}, Number(stack).toLocaleString()),
      h(ChipStack, { value: stack })
    )
  );
}

export function PokerApp({ request, profile: initialProfile, initialGame, initialTraces = [] }) {
  const [game, setGame] = useState(initialGame || null);
  const [profile, setProfile] = useState(initialProfile || null);
  const [traces, setTraces] = useState(initialTraces);
  const [busy, setBusy] = useState(false);
  const [wager, setWager] = useState(40);
  const [retryRequest, setRetryRequest] = useState(null);
  const [notice, setNotice] = useState("새 게임을 시작해 서버·Redis·DBMS 연결을 확인하세요.");
  const [selectedTraceIndex, setSelectedTraceIndex] = useState(Math.max(0, initialTraces.length - 1));
  const [playing, setPlaying] = useState(false);
  const [pendingCommit, setPendingCommit] = useState(null);
  const [chipFlights, setChipFlights] = useState([]);
  const inFlight = useRef(false);

  useEffect(() => {
    if (!pendingCommit) return;
    const event = {
      traceId: pendingCommit.traceId,
      actionId: pendingCommit.actionId,
      service: "Mini React",
      method: "RENDER → DIFF → PATCH",
      path: "#root",
      outcome: "ok",
      input: { update: "서버 응답 상태를 화면에 반영" },
      result: { domPatched: true },
      durationMs: Number((performance.now() - pendingCommit.startedAt).toFixed(3)),
    };
    const nextTraces = [...traces, event].slice(-200);
    setTraces(nextTraces);
    setSelectedTraceIndex(nextTraces.length - 1);
    setPendingCommit(null);
  }, [pendingCommit]);

  useEffect(() => {
    if (!playing || traces.length < 2) return;
    const timer = window.setInterval(() => {
      setSelectedTraceIndex((current) => (current + 1) % traces.length);
    }, 800);
    return () => window.clearInterval(timer);
  }, [playing, traces.length]);

  useEffect(() => {
    if (!chipFlights.length) return;
    const timer = window.setTimeout(() => setChipFlights([]), 850);
    return () => window.clearTimeout(timer);
  }, [chipFlights]);

  const execute = async (envelope) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setNotice("서버 요청 중…");
    try {
      const result = await request(envelope.path, envelope.body);
      if (result.game) {
        const sameHand = game?.matchKey === result.game.matchKey && game?.handNo === result.game.handNo;
        const beforeActions = sameHand && Array.isArray(game?.actions) ? game.actions.length : 0;
        const afterActions = Array.isArray(result.game.actions) ? result.game.actions : [];
        const newActions = afterActions.length >= beforeActions ? afterActions.slice(beforeActions) : afterActions;
        setChipFlights(newActions.filter((action) => action.paid > 0).map((action, index) => ({
          id: (result.traceId || newId()) + "-" + action.player + "-" + index,
          player: action.player,
          amount: action.paid,
        })));
        setPendingCommit({
          traceId: result.traceId,
          actionId: envelope.body.action_id || null,
          startedAt: performance.now(),
        });
        setGame(result.game);
        if (Number.isInteger(result.game.minRaiseTo)) setWager(result.game.minRaiseTo);
      }
      const nextTraces = result.traces || [];
      setTraces(nextTraces);
      if (nextTraces.length) setSelectedTraceIndex(nextTraces.length - 1);
      setNotice(result.game ? result.game.message : "요청 완료");
      setRetryRequest(null);
      if (result.game && result.game.handOver && result.game.recordStatus === "confirmed") {
        try {
          const updated = await request("/api/profile");
          setProfile(updated.profile);
          setTraces(updated.traces || result.traces || []);
        } catch {
          setNotice(result.game.message + " · 저장은 확인됐고 전적 새로고침은 실패했습니다.");
        }
      }
    } catch (error) {
      setChipFlights([]);
      if (error.payload && error.payload.game) {
        setPendingCommit({ traceId: error.payload.traceId, actionId: envelope.body.action_id || null, startedAt: performance.now() });
        setGame(error.payload.game);
      }
      if (error.payload && error.payload.traces) {
        setTraces(error.payload.traces);
        if (error.payload.traces.length) setSelectedTraceIndex(error.payload.traces.length - 1);
      }
      setNotice(error.message);
      if (error.status && error.status < 500) setRetryRequest(null);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const run = (path, body) => {
    if (inFlight.current || retryRequest) return;
    // An unresolved intent is retried only through retry(), with its original ID.
    const requestBody = {
      ...body,
      [path === "/api/game/action" ? "action_id" : "request_id"]: newId(),
    };
    const envelope = { path, body: requestBody };
    setRetryRequest(envelope);
    return execute(envelope);
  };

  const retry = () => retryRequest && execute(retryRequest);
  const start = () => run("/api/game/start", {});
  const nextHand = () => run("/api/game/next", {});
  const act = (action, to) => run("/api/game/action", to === undefined ? { action } : { action, to });
  const legal = new Set(game ? game.legalActions : []);
  const mayRaise = legal.has("bet") || legal.has("raise");
  const handDone = Boolean(game && game.handOver);
  const startLabel = !game ? "게임 시작" : game.matchOver ? "새 매치" : "매치 진행 중";
  const cards = game && game.botCardsRevealed ? game.botCards : [null, null];
  const humanIsButton = game?.button === "human";
  const botIsButton = game?.button === "bot";
  const handKey = (game?.matchKey || "waiting") + "-" + (game?.handNo || 0);
  const phaseLabel = game ? game.phase.toUpperCase() : "PRE-FLOP";
  const resultLabel = game && game.result
    ? game.result.winner === "tie" ? "무승부" : game.result.winner === "human" ? "승리" : "패배"
    : "";

  const table = h("section", { className: "game-column" },
    h("div", { className: "section-heading" },
      h("div", {},
        h("p", { className: "eyebrow" }, "SERVER-AUTHORITATIVE · 2 SEATS"),
        h("h1", {}, "Texas Hold’em", h("span", { className: "mode-tag" }, "PRACTICE")),
        profile ? h("p", { className: "profile-line" }, profile.displayName + " · 연습 " + profile.practice.hands + "H / " + profile.practice.wins + "W " + profile.practice.losses + "L " + profile.practice.draws + "D") : null
      ),
      h("span", { className: "connection-pill " + (game ? "connected" : "") }, game ? "LOCAL TABLE LIVE" : "WAITING")
    ),
    h("div", { className: "table-wrap", "aria-label": "2인 포커 테이블" },
      h("div", { className: "casino-room", "aria-hidden": "true" },
        h("div", { className: "portal" }, h("span", {}, "POKER LAB"), h("small", {}, "N E O N   D I S T R I C T   /   0 1")),
        h("div", { className: "wall-panel wall-left" }, h("span", {}, "◇"), h("i", {}), h("i", {}), h("i", {})),
        h("div", { className: "wall-panel wall-right" }, h("span", {}, "♠"), h("i", {}), h("i", {}), h("i", {})),
        h("div", { className: "floor-grid" })
      ),
      h("div", { className: "table-glow", "aria-hidden": "true" }),
      h("div", { className: "table-base", "aria-hidden": "true" }),
      h("div", { className: "poker-table", "aria-hidden": "true" },
        h("div", { className: "felt-mark" }, "PL", h("small", {}, "POKER LAB"))
      ),
      h("div", { className: "table-label" }, "HAND " + (game ? game.handNo : "—") + " / " + phaseLabel),
      h(Seat, { name: "Dealer Bot", tag: "P2", stack: game ? game.botStack : 0, cards, hidden: !(game && game.botCardsRevealed), active: game && game.turn === "bot", handNo: handKey, position: game ? (botIsButton ? "D · SB" : "BB") : null }),
      h("div", { className: "center-felt" },
        h("div", { className: "pot-readout" }, h("span", { className: "pot-label" }, "TOTAL POT"), h("strong", { className: "pot-value" }, Number(game?.pot || 0).toLocaleString()), h("small", {}, "CHIPS")),
        h("div", { className: "community-cards" }, ...Array.from({ length: 5 }, (_, index) => h(Card, { key: "board-" + handKey + "-" + index + "-" + (game?.board[index] || "empty"), value: game?.board[index], index }))),
        h(ChipStack, { value: game?.pot || 0 })
      ),
      ...chipFlights.map((flight) => h("span", { key: flight.id, className: "chip-flight from-" + flight.player, "aria-hidden": "true" }, String(flight.amount))),
      h(Seat, { name: (profile?.displayName || "Guest Player") + " · YOU", tag: "P1", stack: game ? game.humanStack : 0, cards: game ? game.humanCards : [], active: game && game.turn === "human", handNo: handKey, position: game ? (humanIsButton ? "D · SB" : "BB") : null })
    ),
    h("div", { className: "game-status" }, h("span", { className: "status-light" }), notice),
    h("div", { className: "controls" },
      !game || game.matchOver
        ? h("button", { className: "btn btn-primary", disabled: busy || Boolean(retryRequest), onClick: start }, startLabel)
        : null,
      handDone && !game.matchOver
        ? h("button", { className: "btn btn-primary", disabled: busy || Boolean(retryRequest), onClick: nextHand }, "다음 핸드")
        : null,
      !handDone && legal.has("fold") ? h("button", { className: "btn", disabled: busy || Boolean(retryRequest), onClick: () => act("fold") }, "폴드") : null,
      !handDone && legal.has("check") ? h("button", { className: "btn", disabled: busy || Boolean(retryRequest), onClick: () => act("check") }, "체크") : null,
      !handDone && legal.has("call") ? h("button", { className: "btn", disabled: busy || Boolean(retryRequest), onClick: () => act("call") }, "콜 · " + game.toCall) : null,
      !handDone && mayRaise
        ? h("span", { className: "wager-control" },
            h("label", { htmlFor: "wager-to" }, "총액"),
            h("input", { id: "wager-to", type: "number", min: game.minRaiseTo, max: game.maxRaiseTo, step: 1, value: wager,
              disabled: busy || Boolean(retryRequest), onInput: (event) => setWager(Number(event.target.value)) }),
            h("button", { className: "btn btn-raise", disabled: busy || Boolean(retryRequest) || !Number.isInteger(wager) || wager < game.minRaiseTo || wager > game.maxRaiseTo,
              onClick: () => act(legal.has("bet") ? "bet" : "raise", wager) }, legal.has("bet") ? "베팅" : "레이즈")
          )
        : null,
      !handDone && legal.has("all_in") ? h("button", { className: "btn btn-all-in", disabled: busy || Boolean(retryRequest), onClick: () => act("all_in") }, "올인") : null,
      retryRequest ? h("button", { className: "btn btn-retry", disabled: busy, onClick: retry }, "같은 요청 재시도") : null,
      game && !handDone ? h("span", { className: "to-call" }, "CALL " + game.toCall) : null,
      resultLabel ? h("span", { className: "result-pill" }, resultLabel + " · " + game.result.pot + " 칩") : null
    ),
    h("p", { className: "scope-note" }, "연습 모드 · 가상 칩만 사용 · 다음 핸드까지 서버가 상태와 정산을 결정합니다. 랭크·현금 기능은 없습니다."),
    profile ? h("section", { className: "practice-record" },
      h("h3", {}, "최근 연습 기록"),
      profile.recentGames.length
        ? h("ol", {}, ...profile.recentGames.slice(0, 5).map((row) => h("li", { key: row.matchKey + "-" + row.handNo },
            "Hand " + row.handNo + " · " + (row.winner === "human" ? "승리" : row.winner === "bot" ? "패배" : "무승부") + " · 잔액 " + Number(row.endStack).toLocaleString()
          )))
        : h("p", {}, "완료된 Hand가 아직 없습니다.")
    ) : null
  );

  const inspector = h("aside", { className: "inspector" },
    h("div", { className: "inspector-head" },
      h("div", {},
        h("p", { className: "eyebrow" }, "LIVE SYSTEM TRACE"),
        h("h2", {}, "Inspector")
      ),
      h("span", { className: "live-indicator" }, "● LIVE")
    ),
    h("p", { className: "inspector-desc" }, "Trace ID와 Action ID 기준으로 실제 계측 이벤트를 묶습니다. 홀카드·토큰은 제외하며 계측되지 않은 값은 미계측으로 표시합니다."),
    h("div", { className: "timeline-controls", "aria-label": "trace timeline playback controls" },
      h("button", { type: "button", className: "timeline-button", disabled: traces.length < 2, onClick: () => { setPlaying(false); setSelectedTraceIndex((selectedTraceIndex - 1 + traces.length) % traces.length); } }, "이전"),
      h("button", { type: "button", className: "timeline-button timeline-play", disabled: traces.length < 2, onClick: () => setPlaying(!playing) }, playing ? "PAUSE" : "PLAY"),
      h("button", { type: "button", className: "timeline-button", disabled: traces.length < 2, onClick: () => { setPlaying(false); setSelectedTraceIndex((selectedTraceIndex + 1) % traces.length); } }, "다음"),
      h("span", { className: "timeline-position" }, traces.length ? (selectedTraceIndex + 1) + " / " + traces.length : "0 / 0")
    ),
    traces.length
      ? h("ol", { className: "trace-list" }, ...groupTraces(traces).map((group) => h("li", { className: "trace-group", key: group.key },
          h("div", { className: "trace-group-title" },
            h("b", {}, group.actionId ? "ACTION " + group.actionId.slice(0, 8) : "TRACE GROUP"),
            group.traceId ? h("small", {}, "trace " + group.traceId.slice(0, 8)) : h("small", {}, "미계측 ID")
          ),
          h("ol", { className: "trace-events" }, ...group.events.map(({ event, index }) => h(Trace, {
            key: group.key + "-" + index,
            event,
            index,
            selected: selectedTraceIndex === index,
            onSelect: () => { setPlaying(false); setSelectedTraceIndex(index); },
          })))
        )))
      : h("div", { className: "empty-trace" },
          h("span", {}, "⌁"),
          h("b", {}, "아직 연결된 Trace가 없습니다"),
          h("small", {}, "게임 요청이 실제 발생한 뒤 Redis / Mini DBMS 응답을 표시합니다.")
        ),
    traces.length
      ? (() => {
          const event = traces[selectedTraceIndex] || traces[traces.length - 1];
          const input = event.input || { method: event.method, path: event.path };
          const result = event.result || { status: event.status, outcome: event.outcome, detail: event.detail };
          return h("section", { className: "trace-detail", "aria-live": "polite" },
            h("div", { className: "trace-detail-title" }, h("b", {}, "선택 이벤트"), h("span", {}, event.durationMs === undefined ? "미계측" : event.durationMs.toFixed(2) + " ms")),
            h("dl", {},
              h("dt", {}, "입력"), h("dd", {}, h("pre", {}, dataText(input, "미계측"))),
              h("dt", {}, "결과"), h("dd", {}, h("pre", {}, dataText(result, "미계측")))
            )
          );
        })()
      : null,
    h("div", { className: "inspector-foot" },
      h("span", {}, "EVENTS"),
      h("strong", {}, String(traces.length).padStart(2, "0")),
      h("span", {}, "· 실제 계측 이벤트")
    )
  );

  return h("div", { className: "layout" }, table, inspector);
}
