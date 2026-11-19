// [App.js] 루트 컴포넌트 — 초능력 윷놀이. 모든 상태(State)를 가지고 자식에게 props로 전달

import { h } from "../core/vdom.js";
import { useState, useEffect, useMemo, useRef } from "../core/hooks.js";
import { HOME, POWERS, NODES, other, makeOffers, resolveThrow, replay, apply, movableFrom, destination, piecesOn } from "./yut.js";
import { PowerPick } from "./components/PowerPick.js";
import { YutBoard } from "./components/YutBoard.js";
import { ThrowPanel } from "./components/ThrowPanel.js";
import { TeamPanel } from "./components/TeamPanel.js";
import { YutLog } from "./components/YutLog.js";
import { ConfirmDialog } from "./components/ConfirmDialog.js";
import { VictoryDialog } from "./components/VictoryDialog.js";

// 말의 힘마다 누를 수 있는 칸 (swap은 내 말을 먼저(first 없음), 그다음 상대 말)
function targetsFor(state, power, first) {
  const opp = other(state.turn);
  const mine = new Set(piecesOn(state, state.turn));
  const theirs = new Set(piecesOn(state, opp));
  switch (power) {
    case "recall":
      return state.shield[opp] ? new Set() : theirs;
    case "swap":
      return first ? theirs : mine;
    case "trap":
      return new Set(NODES.filter((n) => !mine.has(n) && !theirs.has(n) && !state.traps[n]));
    case "shortcut":
      return new Set([...mine].filter((n) => n.startsWith("o") && n !== "o0" && Number(n.slice(1)) % 5 !== 0));
    default:
      return new Set();
  }
}
const TARGET_HINT = {
  recall: "출발점으로 돌려보낼 상대 말을 고르세요",
  swap: "자리를 바꿀 내 말을 고르세요",
  swap2: "자리를 바꿀 상대 말을 고르세요",
  trap: "함정을 놓을 빈 칸을 고르세요",
  shortcut: "앞 모서리로 옮길 내 말을 고르세요",
};

/**
 * Lifting State Up: State는 전부 여기(루트)에 두고, 자식은 props로 받은 값과 함수만 쓴다.
 *   actions   : 게임에서 일어난 일의 목록. 판 · 차례 · 승자는 전부 이 목록에서 계산한다 (yut.js의 replay)
 *   pickSel   : 초능력 고르기 화면에서 지금 고른 것
 *   chosen    : 옮기려고 고른 말(칸 이름, 출발 전 말은 HOME). 고르면 갈 수 있는 칸들을 판에 표시한다
 *   targeting : 말의 힘을 쓸 대상을 고르는 중인지 ({ power, first })
 *   victoryClosed : 승리 팝업을 닫았는지 (닫으면 끝난 판을 볼 수 있다)
 * props.random: 윷 · 초능력 후보의 무작위 함수 (테스트에서 결과를 정해 넣을 수 있게)
 */
export function App({ random = Math.random }) {
  const [actions, setActions] = useState(() => [{ type: "start", offers: makeOffers(random) }]);
  const [pickSel, setPickSel] = useState({ yut: null, mal: null });
  const [chosen, setChosen] = useState(null);
  const [targeting, setTargeting] = useState(null);
  const [notice, setNotice] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [victoryClosed, setVictoryClosed] = useState(false);
  const logRef = useRef(null);
  const dialogFocusRef = useRef(null); // 팝업이 열리면 먼저 포커스할 버튼 (확인 팝업: 취소, 승리 팝업: 새 게임)

  // 지금 상태는 action 목록이 바뀔 때만 다시 계산한다
  const state = useMemo(() => replay(actions), [actions]);
  const { phase, turn, pending } = state;
  const showVictory = Boolean(state.winner) && !victoryClosed;

  // 렌더링 뒤 부수효과: 탭 제목, 기보를 최신 줄로 스크롤, 팝업이 열리면 기본 버튼에 포커스
  useEffect(() => {
    document.title = state.winner ? `${state.winner} 승리 - 초능력 윷놀이` : phase === "pick" ? "초능력 고르기 - 초능력 윷놀이" : `${turn} 차례 - 초능력 윷놀이`;
  }, [state.winner, phase, turn]);
  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [state.log.length]);
  useEffect(() => {
    if (confirming || showVictory) dialogFocusRef.current?.focus();
  }, [confirming, showVictory]);

  // action이 규칙에 맞는지 먼저 확인하고(apply가 에러를 내면 안내만 보여 줌) 목록에 더한다
  const dispatch = (action) => {
    try {
      apply(state, action);
    } catch (e) {
      setNotice(e.message);
      return;
    }
    setActions((prev) => [...prev, action]);
    setChosen(null);
    setTargeting(null);
    setNotice(null);
  };

  // 윷 던지기: 무작위 결과는 여기서 정해서 action에 담는다 (규칙 쪽 reduce는 같은 목록이면 늘 같은 판)
  const throwYut = () => {
    const r = resolveThrow(state, random);
    dispatch(r.choices ? { type: "throw2", choices: r.choices } : { type: "throw", name: r.name, flats: r.flats });
  };

  // 옮길 수 있는 말: 나온 결과 중 하나라도 쓸 수 있는 말 (판 위 칸 이름, 출발 전 말은 HOME)
  const movable = new Set(phase === "move" ? pending.flatMap((n) => movableFrom(state, n)) : []);
  // 고른 말이 갈 수 있는 곳: 도착 칸 → [결과 번호들] (같은 칸으로 가는 결과가 여럿이면 첫 번째를 쓴다)
  const dests = new Map();
  if (chosen && movable.has(chosen)) {
    pending.forEach((n, i) => {
      if (!movableFrom(state, n).includes(chosen)) return;
      const to = destination(chosen, n);
      dests.set(to, [...(dests.get(to) ?? []), i]);
    });
  }
  const targets = targeting ? targetsFor(state, targeting.power, targeting.first) : new Set();
  // 칸을 눌렀을 때: 말의 힘 대상 고르기 → 도착 칸이면 옮기기 → 내 말이면 고르기(다시 누르면 취소)
  const pressNode = (pos) => {
    if (targeting) {
      if (!targets.has(pos)) return;
      if (targeting.power === "swap" && !targeting.first) return setTargeting({ power: "swap", first: pos });
      return dispatch({ type: "mal", targets: targeting.first ? [targeting.first, pos] : [pos] });
    }
    if (dests.has(pos)) return dispatch({ type: "move", from: chosen, index: dests.get(pos)[0] });
    setChosen(movable.has(pos) && pos !== chosen ? pos : null);
  };
  const pressMal = () => {
    const power = state.powers[turn].mal;
    setChosen(null);
    if (POWERS[power].target) setTargeting(targeting ? null : { power, first: null });
    else dispatch({ type: "mal", targets: [] });
  };

  const restart = () => {
    setActions([{ type: "start", offers: makeOffers(random) }]);
    setPickSel({ yut: null, mal: null });
    setConfirming(false);
    setVictoryClosed(false);
    setTargeting(null);
    setNotice(null);
  };
  // 진행 중인 판이면 확인 팝업 (지우면 되돌릴 수 없으므로). 시작 전 · 끝난 판은 바로
  const askRestart = () => (actions.length > 1 && phase !== "over" ? setConfirming(true) : restart());

  const armedName = state.armed ? ` (「${POWERS[state.armed].name}」 켜짐)` : "";
  const message = state.winner
    ? `${state.winner} 승리! 말 4개를 모두 냈습니다`
    : targeting
      ? TARGET_HINT[targeting.first ? "swap2" : targeting.power]
      : phase === "choose"
        ? `${turn} 차례 · 두 결과 중 하나를 고르세요`
        : phase === "move"
          ? chosen
            ? `${turn} 차례 · 표시된 칸 중 갈 곳을 고르세요`
            : `${turn} 차례 · 옮길 말을 고르세요 (${pending.join(", ")})`
          : `${turn} 차례 · 윷을 던지세요${armedName}`;
  // 도착 칸 표시: 칸 → 그 칸으로 가는 결과 이름들 (예: { o3: ["걸"], o5: ["모"] })
  const destNames = new Map([...dests].map(([to, idx]) => [to, idx.map((i) => pending[i])]));
  const team = (t) =>
    h(TeamPanel, {
      key: t,
      team: t,
      state,
      canEnter: t === turn && movable.has(HOME) && !targeting,
      entering: t === turn && chosen === HOME,
      targeting: t === turn && Boolean(targeting),
      onEnter: () => pressNode(HOME),
      onArm: () => dispatch({ type: "arm" }),
      onMal: pressMal,
    });

  return h(
    "main",
    { className: "yut-app" },
    h(
      "div",
      { className: "game-head" },
      h("div", null, h("h1", null, "초능력 윷놀이"), h("p", null, "둘이 번갈아 던지는 윷놀이. 차례마다 던지기 전에 초능력을 한 번씩 쓸 수 있습니다.")),
      phase === "pick" ? null : h("button", { onClick: askRestart }, "새 게임")
    ),
    phase === "pick"
      ? h(PowerPick, {
          team: state.picking,
          offers: state.offers[state.picking],
          selected: pickSel,
          onSelect: (kind, id) => setPickSel((prev) => ({ ...prev, [kind]: id })),
          onConfirm: () => {
            dispatch({ type: "pick", team: state.picking, yut: pickSel.yut, mal: pickSel.mal });
            setPickSel({ yut: null, mal: null });
          },
        })
      : [
          h(
            "div",
            { key: "status", className: `yut-status team-${turn === "홍" ? "red" : "blue"}${state.winner ? " won" : ""}` },
            h("strong", { className: "message", role: "status", "aria-live": "polite" }, message),
            targeting ? h("button", { onClick: () => setTargeting(null) }, "취소") : null,
            notice ? h("p", { className: "notice", role: "alert" }, notice) : null
          ),
          // 청팀(왼쪽) · 판과 던지기(가운데) · 홍팀(오른쪽)
          h(
            "div",
            { key: "layout", className: "yut-layout" },
            team("청"),
            h(
              "div",
              { className: "yut-center" },
              h(YutBoard, {
                state,
                clickable: targeting ? targets : movable,
                chosen: targeting ? null : chosen,
                dests: destNames,
                targeting: Boolean(targeting),
                onNode: pressNode,
              }),
              h(ThrowPanel, { state, onThrow: throwYut, onChoose: (index) => dispatch({ type: "choose", index }) }),
              h(YutLog, { log: state.log, logRef })
            ),
            team("홍")
          ),
        ],
    confirming
      ? h(ConfirmDialog, { message: "진행 중인 판이 지워지고, 되돌릴 수 없습니다.", confirmLabel: "새 게임", cancelRef: dialogFocusRef, onConfirm: restart, onCancel: () => setConfirming(false) })
      : null,
    showVictory
      ? h(VictoryDialog, { team: state.winner, turnNo: state.turnNo, focusRef: dialogFocusRef, onRestart: restart, onClose: () => setVictoryClosed(true) })
      : null
  );
}
