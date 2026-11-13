// [App.js] 루트 컴포넌트 — 앱의 모든 상태(State)를 가지고 자식에게 props로 전달

/**
 * 할 일 보드
 *
 * 상태(State)는 전부 여기, 루트에만 있다 (Lifting State Up).
 *   todos    : 할 일 목록 [{ id, text, done, priority }]
 *   draft    : 입력창에 쓰고 있는 글자
 *   priority : 새 할 일의 중요도
 *   filter   : "all" | "active" | "done"
 *   query    : 검색어
 *   sorted   : 중요도순 정렬을 켰는가 (보이는 순서만 바꾼다)
 *   editingId: 수정 중인 할 일의 id (없으면 null)
 *   editText : 수정 입력창의 글자
 *   past     : 되돌리기용 — 목록을 바꾸기 직전의 todos 들 (최근 MAX_UNDO 개)
 *   testValues: 테스트 패널(TestPanel)의 모든 입력값을 담은 객체 하나
 *
 * 자식(Header, TodoForm, Toolbar, TodoList, TodoItem)은 상태가 없는 순수 함수다.
 * 값과 "상태를 바꾸는 콜백" 을 props 로 받고, 사용자가 무언가 하면 그 콜백을 부른다.
 *   TodoItem 체크 → onToggle(id) → App 의 setTodos → App 다시 렌더 → Diff → 바뀐 노드만 Patch
 * 상태가 한 곳에만 있어서, 통계 · 필터 개수 · 목록이 서로 어긋날 수 없다.
 *
 * Hook 사용 (매 렌더 같은 순서로 16개)
 *   useState  × 10 — 위 상태
 *   useMemo   × 2 — 통계(stats), 화면에 보일 목록(visible): 관련 상태가 바뀔 때만 다시 계산
 *   useEffect × 4 — localStorage 저장, 문서 제목, "/" 단축키(정리 함수로 리스너 제거), 수정 입력창에 포커스
 */

import { h } from "../core/vdom.js";
import { useState, useEffect, useMemo } from "../core/hooks.js";
import { stateless } from "../core/component.js";
import { Header } from "./components/Header.js";
import { TodoForm } from "./components/TodoForm.js";
import { Toolbar } from "./components/Toolbar.js";
import { TodoList } from "./components/TodoList.js";

/** localStorage 에 저장할 때 쓰는 이름 */
export const STORAGE_KEY = "mini-react:todos";

/** 중요도 (값 → 화면 표시 이름) */
export const PRIORITIES = Object.freeze({ high: "높음", normal: "보통", low: "낮음" });

/** 처음 열었을 때(저장된 목록이 없을 때) 보여 줄 예시 */
export const SAMPLE_TODOS = Object.freeze([
  { id: 1, text: "Virtual DOM 과 Diff 복습하기", done: true, priority: "normal" },
  { id: 2, text: "useState 가 상태를 기억하는 원리 설명하기", done: false, priority: "high" },
  { id: 3, text: "useEffect 정리(cleanup) 함수 테스트", done: false, priority: "normal" },
  { id: 4, text: "발표 자료 만들기", done: false, priority: "low" },
]);

/** 중요도 배지를 누를 때 다음 중요도 (높음 → 보통 → 낮음 → 높음 …) */
const NEXT_PRIORITY = Object.freeze({ high: "normal", normal: "low", low: "high" });

/** 중요도순 정렬 순위 (PRIORITIES 의 순서: 높음 0, 보통 1, 낮음 2) */
const RANK = Object.fromEntries(Object.keys(PRIORITIES).map((key, i) => [key, i]));

/** 테스트 패널의 처음 값 (입력 칸 값은 HTML 이 주는 그대로 문자열로 둔다) */
export const TEST_DEFAULT = Object.freeze({
  name: "홍길동", email: "mini@react.dev", pw: "1234", count: "3", level: "60", color: "#2563eb",
  date: "2026-11-09", time: "09:30", agree: true, size: "m", fruit: "apple", memo: "textarea 내용",
  locked: false, clicks: 0, dialog: false,
});

/** 되돌리기로 기억할 최대 횟수 (오래된 것부터 버린다) */
const MAX_UNDO = 20;

/** [예시] "3개 추가" 버튼이 넣는 할 일 (배칭 데모) */
const BATCH_SAMPLES = ["장보기", "운동 30분", "책 20쪽 읽기"];

/**
 * 저장된 목록을 읽는다. 없거나, JSON 이 망가졌거나, 모양이 틀리거나,
 * 저장소를 쓸 수 없으면(사생활 보호 모드 등) 예시 목록으로 시작한다.
 * (useState 에 이 함수를 그대로 넘기면 첫 렌더에서 한 번만 실행된다 — 지연 초기화)
 */
function loadTodos() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (Array.isArray(saved) && saved.every(isTodo)) return saved;
  } catch {
    // 예시로 시작
  }
  return freshSamples();
}

/** 할 일 하나의 모양이 맞는지 — 저장소에서 읽은 값은 믿지 않고 검사한다 */
const isTodo = (v) =>
  v !== null && typeof v === "object" && Number.isInteger(v.id) && typeof v.text === "string" &&
  typeof v.done === "boolean" && Object.hasOwn(PRIORITIES, v.priority);

/** 예시 목록의 새 복사본 (예시 원본은 얼려 두었으므로 복사해서 쓴다) */
const freshSamples = () => SAMPLE_TODOS.map((todo) => ({ ...todo }));

/** 목록에 새로 넣을 할 일 (id = 지금 목록의 가장 큰 id + 1, 지워진 id 와 겹치지 않게) */
const makeTodo = (list, text, priority) => ({ id: list.reduce((max, todo) => Math.max(max, todo.id), 0) + 1, text, done: false, priority });

/** 키 입력이 글자 입력창 안에서 일어났는가 ("/" 를 입력하려는데 단축키가 가로채지 않도록) */
const isTyping = (target) => target instanceof Element && target.closest("input, textarea, select, [contenteditable]") !== null;

export function App() {
  // ── 상태 ──────────────────────────────────────────────────────────
  const [todos, setTodos] = useState(loadTodos); // 함수를 넘기면 첫 렌더에서 한 번만 실행 (지연 초기화)
  const [draft, setDraft] = useState("");
  const [priority, setPriority] = useState("normal");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [sorted, setSorted] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editText, setEditText] = useState("");
  const [past, setPast] = useState([]);
  const [testValues, setTestValues] = useState(TEST_DEFAULT); // 얼린 객체지만 바꿀 때는 항상 새 객체를 만들므로 괜찮다

  // ── 계산 값 (useMemo) ─────────────────────────────────────────────
  // todos 가 바뀔 때만 다시 센다. 입력창에 글자를 칠 때(draft 변경)는 이전 결과를 재사용.
  const stats = useMemo(() => {
    const done = todos.filter((todo) => todo.done).length;
    const total = todos.length;
    return { total, done, active: total - done, percent: total === 0 ? 0 : Math.round((done / total) * 100) };
  }, [todos]);

  // 목록 · 필터 · 검색어 · 정렬 중 하나가 바뀔 때만 다시 거른다 (검색은 대소문자 무시)
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const shown = todos.filter((todo) => {
      if ((filter === "active" && todo.done) || (filter === "done" && !todo.done)) return false;
      return needle === "" || todo.text.toLowerCase().includes(needle);
    });
    // sort 는 같은 순위끼리 원래 순서를 지킨다(안정 정렬). filter 가 새 배열을 만들었으므로 todos 는 그대로
    return sorted ? shown.sort((a, b) => RANK[a.priority] - RANK[b.priority]) : shown;
  }, [todos, filter, query, sorted]);

  // ── 부수효과 (useEffect) — 화면이 반영된 뒤 실행 ──────────────────────
  // todos 가 바뀔 때마다 저장 → 새로고침해도 목록이 남는다
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(todos));
    } catch {
      // 저장소를 쓸 수 없으면 저장만 건너뛴다 (화면은 그대로 동작)
    }
  }, [todos]);

  // 남은 개수가 바뀔 때만 브라우저 탭 제목을 바꾼다
  useEffect(() => {
    document.title = stats.active > 0 ? `할 일 ${stats.active}개 남음 · 미니 React` : "모두 완료 · 미니 React";
  }, [stats.active]);

  // "/" 를 누르면 검색창으로. deps [] → 처음 한 번만 리스너를 달고,
  // 정리 함수를 돌려주므로 컴포넌트가 사라질 때 리스너도 지워진다.
  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key !== "/" || isTyping(event.target)) return;
      event.preventDefault(); // 검색창에 "/" 가 입력되지 않게
      document.getElementById("todo-search")?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // 수정을 시작하면 그 입력창에 포커스 (화면에 입력창이 생긴 "뒤" 라야 하므로 렌더가 아니라 effect 에서)
  useEffect(() => {
    if (editingId !== null) document.querySelector(".todo-edit")?.focus();
  }, [editingId]);

  // ── 상태를 바꾸는 함수 (자식에게 콜백으로 내려감) ────────────────────
  // 목록을 바꿀 때는 항상 함수형 업데이트 setTodos(list => …) 를 쓴다
  // → 같은 이벤트에서 여러 번 불러도 앞의 결과 위에 차례로 쌓인다.
  // 목록을 바꾸기 전에는 remember() 로 지금 목록을 past 에 쌓는다 → "되돌리기" 가 이 값으로 돌아간다.
  // (todos 는 이번 렌더 시점의 목록 = 사용자가 보고 있던 목록)
  const remember = () => setPast((list) => [...list, todos].slice(-MAX_UNDO));
  const changeTodos = (update) => {
    remember();
    setTodos(update);
  };
  const mapTodo = (id, change) => changeTodos((list) => list.map((todo) => (todo.id === id ? { ...todo, ...change(todo) } : todo)));

  const addTodo = (event) => {
    event.preventDefault(); // form 제출로 페이지가 새로고침되지 않게
    const text = draft.trim();
    if (text === "") return;
    changeTodos((list) => [...list, makeTodo(list, text, priority)]);
    setDraft(""); // setState 여러 번 → 배칭되어 렌더는 한 번
  };
  // 배칭 데모: 목록 setState 를 3번 부르지만 렌더는 1번 (페이지 테스트로 확인)
  const addBatch = () => {
    remember(); // 되돌리기 한 번에 3개가 함께 빠지도록 기억은 한 번만
    BATCH_SAMPLES.forEach((text) => setTodos((list) => [...list, makeTodo(list, text, "normal")]));
  };
  // 모두 완료 ↔ 모두 해제: 하나라도 안 끝났으면 전부 완료로
  const toggleAll = () => changeTodos((list) => {
    const allDone = list.every((todo) => todo.done);
    return list.map((todo) => ({ ...todo, done: !allDone }));
  });
  // 보이는 목록에서 바로 위/아래 이웃과 자리를 바꾼다 (필터 · 검색 중이어도 눈에 보이는 이웃과)
  const neighborOf = (id, dir) => visible[visible.findIndex((todo) => todo.id === id) + dir];
  const canMove = (id, dir) => !sorted && neighborOf(id, dir) !== undefined; // 정렬 중에는 순서가 의미 없으므로 끈다
  const move = (id, dir) => {
    const other = neighborOf(id, dir);
    if (sorted || !other) return;
    changeTodos((list) => {
      const [a, b] = [list.find((todo) => todo.id === id), list.find((todo) => todo.id === other.id)];
      return list.map((todo) => (todo === a ? b : todo === b ? a : todo));
    });
  };
  // 수정: 시작하면 지금 글자를 입력창에 넣고, 저장은 앞뒤 공백을 뺀 글자가 있고 바뀌었을 때만 목록에 반영
  const startEdit = (id) => {
    setEditingId(id);
    setEditText(todos.find((todo) => todo.id === id)?.text ?? "");
  };
  const saveEdit = () => {
    const text = editText.trim();
    const todo = todos.find((item) => item.id === editingId);
    if (todo && text !== "" && text !== todo.text) mapTodo(editingId, () => ({ text }));
    setEditingId(null);
  };
  const editKey = (event) => {
    if (event.isComposing) return; // 한글 조합 중의 Enter 는 글자 확정용이므로 무시
    if (event.key === "Enter") saveEdit();
    else if (event.key === "Escape") setEditingId(null);
  };
  // 되돌리기: past 의 마지막 목록으로. 수정 중이던 것은 취소
  const undo = () => {
    if (past.length === 0) return;
    setTodos(past.at(-1));
    setPast((list) => list.slice(0, -1));
    setEditingId(null);
  };

  // 테스트 패널: testValues 의 칸 하나만 바꾼 새 객체로 (value 가 함수면 이전 값으로 계산 — 클릭 +1)
  const setField = (key, value) => setTestValues((v) => ({ ...v, [key]: typeof value === "function" ? value(v[key]) : value }));

  // ── 화면 ──────────────────────────────────────────────────────────
  // 자식 컴포넌트는 그냥 함수 호출이다. 돌려준 VNode 가 이 트리에 그대로 들어간다.
  // 카드 두 장을 위아래로: 할 일 보드(.todo-app) · 테스트 패널(.test-panel)
  return h(
    "div",
    { class: "app-stack" },
    h("div", { class: "todo-app" },
      Header({ stats }),
      TodoForm({
        draft,
        priority,
        priorities: PRIORITIES,
        onDraft: (event) => setDraft(event.target.value),
        onPriority: (event) => setPriority(event.target.value),
        onSubmit: addTodo,
      }),
      Toolbar({
        filter,
        query,
        stats,
        sorted,
        undoCount: past.length,
        onFilter: setFilter,
        onQuery: (event) => setQuery(event.target.value),
        onQueryKey: (event) => event.key === "Escape" && setQuery(""),
        onToggleAll: toggleAll,
        onSort: () => setSorted((on) => !on),
        onClearDone: () => changeTodos((list) => list.filter((todo) => !todo.done)),
        onUndo: undo,
        onAddBatch: addBatch,
        onReset: () => {
          changeTodos(freshSamples);
          setEditingId(null);
        },
      }),
      TodoList({
        items: visible,
        query: query.trim(),
        isEmpty: todos.length === 0,
        priorities: PRIORITIES,
        editingId,
        editText,
        canMove,
        onToggle: (id) => mapTodo(id, (todo) => ({ done: !todo.done })),
        onRemove: (id) => changeTodos((list) => list.filter((todo) => todo.id !== id)),
        onCycle: (id) => mapTodo(id, (todo) => ({ priority: NEXT_PRIORITY[todo.priority] })),
        onMove: move,
        onEditStart: startEdit,
        onEditText: (event) => setEditText(event.target.value),
        onEditKey: editKey,
        onEditSave: saveEdit,
        onEditCancel: () => setEditingId(null),
      })),
    TestPanel({
      values: testValues,
      onText: (key) => (event) => setField(key, event.target.value),
      onCheck: (key) => (event) => setField(key, event.target.checked),
      onSet: (key, value) => () => setField(key, value),
      onReset: () => setTestValues(TEST_DEFAULT),
    }),
  );
}

// ── 테스트 패널: HTML 입력 · 버튼 요소를 한곳에 (상태 없음 — props 만 사용, 값은 App 의 testValues) ──

/** 선택 상자의 항목: [묶음 이름, [[값, 이름], …]] → <optgroup> · <option> */
const FRUITS = [["빨강", [["apple", "사과"], ["cherry", "체리"]]], ["노랑", [["banana", "바나나"], ["lemon", "레몬"]]]];

/** 라디오 버튼 항목: [값, 이름] */
const SIZES = [["s", "작게"], ["m", "보통"], ["l", "크게"]];

/** "지금 상태" 표에 보여 줄 이름 (키 → 한글 이름). 순서도 이 순서대로 */
const LABELS = {
  name: "글자", email: "이메일", pw: "비밀번호", count: "숫자", level: "범위", color: "색", date: "날짜", time: "시각",
  memo: "여러 줄", fruit: "선택", agree: "체크박스", size: "라디오", locked: "잠금", clicks: "클릭 수", dialog: "대화상자",
};

/**
 * 이름표가 위, 입력 요소가 아래인 칸 하나. label 이 감싸므로 id 없이 연결된다.
 * @param {string} label 이름표
 * @param {object} control 입력 요소 VNode
 * @param {string} [extra] 추가 클래스 (예: "wide" = 한 줄 전체)
 */
const field = (label, control, extra = "") => h("label", { class: `tp-field ${extra}`.trim() }, h("span", { class: "tp-label" }, label), control);

/** 묶음 하나: 작은 제목 + 내용. fieldset 이면 disabled 로 안의 입력을 한꺼번에 끌 수 있다 */
const group = (tag, title, props, ...children) => h(tag, { class: "tp-group", ...props }, h(tag === "fieldset" ? "legend" : "h3", { class: "tp-title" }, title), ...children);

/**
 * 테스트 패널: 여러 종류의 input · select · textarea · 체크박스 · 라디오 · 버튼 · progress · meter · output ·
 * details · dialog 를 묶음별로 모았다.
 *
 * 모든 값은 App 의 values 상태 하나(객체)에 들어 있다 (제어 컴포넌트, Lifting State Up).
 *   글자를 치거나 고르면 → onText / onCheck / onSet → App 의 setTestValues → 다시 렌더 → Diff → 바뀐 곳만 Patch
 *   맨 아래 "지금 상태" 표가 values 를 그대로 보여 주므로, 무엇이 바뀌었는지 바로 보인다 (그 칸만 TEXT 패치).
 * 예외: <details> 는 일부러 상태에 묶지 않았다. 브라우저가 open 을 직접 여닫고, VDOM 에는 open 이 없으므로
 *       diff 가 건드리지 않는다 (상태 없이 동작하는 요소도 섞여 있을 수 있다는 예).
 *
 * @param {{values: object,
 *          onText: (key: string) => Function, onCheck: (key: string) => Function,
 *          onSet: (key: string, value: *) => Function, onReset: Function}} props
 *   onText(key)       → 입력값(event.target.value)을 values[key] 에 넣는 핸들러
 *   onCheck(key)      → 체크 여부(event.target.checked)를 values[key] 에 넣는 핸들러
 *   onSet(key, value) → 누르면 values[key] = value 로 만드는 핸들러 (value 가 함수면 이전 값으로 계산)
 */
const TestPanel = stateless(function TestPanel({ values, onText, onCheck, onSet, onReset }) {
  const level = Number(values.level);
  const count = Number(values.count) || 0;
  const locked = { disabled: values.locked }; // 잠그면 입력 · 선택 묶음이 통째로 꺼진다 (fieldset disabled)
  return h(
    "section",
    { class: "test-panel", "aria-labelledby": "test-panel-title" },

    // ── 머리: 제목 · 설명 · 잠금 스위치 ──
    h("div", { class: "tp-head" },
      h("div", null,
        h("h2", { id: "test-panel-title" }, "테스트"),
        h("p", { class: "todo-sub" }, "값을 바꿀 때마다 App 의 상태가 바뀌고, Diff → Patch 로 바뀐 곳만 다시 그립니다.")),
      h("label", { class: "test-lock" }, h("input", { type: "checkbox", checked: values.locked, onChange: onCheck("locked") }), " 입력 잠그기")),

    // ── 입력: 글자 · 숫자 · 범위 · 색 · 날짜 · 시각 · 여러 줄 ──
    group("fieldset", "입력", locked,
      h("div", { class: "tp-grid" },
        field("글자", h("input", { type: "text", name: "name", value: values.name, placeholder: "이름", onInput: onText("name") })),
        field("이메일", h("input", { type: "email", name: "email", value: values.email, onInput: onText("email") })),
        field("비밀번호", h("input", { type: "password", name: "pw", value: values.pw, onInput: onText("pw") })),
        field("숫자 (0~10)", h("input", { type: "number", name: "count", value: values.count, min: "0", max: "10", onInput: onText("count") })),
        field(`범위 (${level})`, h("input", { type: "range", name: "level", value: values.level, min: "0", max: "100", onInput: onText("level") })),
        field("색", h("input", { type: "color", name: "color", value: values.color, onInput: onText("color") })),
        field("날짜", h("input", { type: "date", name: "date", value: values.date, onInput: onText("date") })),
        field("시각", h("input", { type: "time", name: "time", value: values.time, onInput: onText("time") })),
        field("여러 줄", h("textarea", { name: "memo", rows: "2", value: values.memo, onInput: onText("memo") }), "wide"))),

    // ── 선택: 선택 상자 · 체크박스 · 라디오 ──
    group("fieldset", "선택", locked,
      h("div", { class: "tp-grid" },
        field("선택 상자", h("select", { name: "fruit", onChange: onText("fruit") },
          FRUITS.map(([label, items]) => h("optgroup", { label },
            items.map(([value, text]) => h("option", { value, selected: values.fruit === value }, text)))))),
        h("div", { class: "tp-field" },
          h("span", { class: "tp-label" }, "체크박스"),
          h("label", { class: "tp-check" }, h("input", { type: "checkbox", name: "agree", checked: values.agree, onChange: onCheck("agree") }), " 동의")),
        // 라디오: 같은 name 끼리 하나만 켜진다. 켜진 것은 checked 로 표시 (상태가 바뀌면 두 버튼의 checked 가 PROPS 패치)
        h("div", { class: "tp-field", role: "radiogroup", "aria-label": "라디오" },
          h("span", { class: "tp-label" }, "라디오"),
          h("div", { class: "tp-row" },
            SIZES.map(([value, text]) =>
              h("label", { class: "tp-check" }, h("input", { type: "radio", name: "size", value, checked: values.size === value, onChange: onSet("size", value) }), ` ${text}`)))))),

    // ── 버튼 ──
    group("div", "버튼", null,
      h("div", { class: "tp-row" },
        h("button", { type: "button", class: "btn test-count", onClick: onSet("clicks", (n) => n + 1) }, `클릭 +1 (${values.clicks})`),
        h("input", { type: "button", class: "btn", value: "input 버튼 (+1)", onClick: onSet("clicks", (n) => n + 1) }),
        h("button", { type: "button", class: "btn test-open", onClick: onSet("dialog", true) }, "대화상자 열기"),
        h("button", { type: "button", class: "btn", disabled: true }, "꺼진 버튼"),
        h("button", { type: "button", class: "btn test-reset", onClick: onReset }, "테스트 초기화"))),

    // ── 결과: 범위 → progress · output, 숫자 → meter ──
    group("div", "결과", null,
      h("div", { class: "tp-results" },
        h("span", { class: "tp-label" }, "진행률 (progress)"), h("progress", { value: String(level), max: "100" }, `${level}%`),
        h("span", { class: "tp-label" }, "측정값 (meter)"), h("meter", { value: String(count), min: "0", max: "10", low: "3", high: "7", optimum: "5" }, String(count)),
        h("span", { class: "tp-label" }, "계산 (output)"), h("output", { class: "test-output" }, `${level} × ${count} = ${level * count}`))),

    // ── 브라우저가 스스로 여닫는 요소 (상태 없음) ──
    h("details", { class: "tp-group" }, h("summary", null, "펼치기 (details · summary)"), h("p", null, "상태 없이 브라우저가 직접 여닫습니다.")),

    // ── 상태로 여닫는 요소: open 이 true/false 로 바뀌면 PROPS 패치 ──
    h("dialog", { open: values.dialog },
      h("p", null, "대화상자가 열렸습니다 (dialog open)"),
      h("button", { type: "button", class: "btn test-close", onClick: onSet("dialog", false) }, "닫기")),

    // ── 지금 상태: 이름 · 값 표. 값이 바뀌면 그 칸의 글자만 TEXT 패치 ──
    group("div", "지금 상태", null,
      h("dl", { class: "test-state" },
        Object.entries(LABELS).map(([key, label]) =>
          h("div", null, h("dt", null, label), h("dd", { "data-key": key }, key === "pw" ? "•".repeat(values.pw.length) : String(values[key])))))),
  );
});
