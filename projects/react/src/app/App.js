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
 *
 * 자식(Header, TodoForm, Toolbar, TodoList, TodoItem)은 상태가 없는 순수 함수다.
 * 값과 "상태를 바꾸는 콜백" 을 props 로 받고, 사용자가 무언가 하면 그 콜백을 부른다.
 *   TodoItem 체크 → onToggle(id) → App 의 setTodos → App 다시 렌더 → Diff → 바뀐 노드만 Patch
 *
 * Hook 사용
 *   useState × 5 — 위 상태
 *   useMemo  × 2 — 통계(stats), 화면에 보일 목록(visible): 관련 상태가 바뀔 때만 다시 계산
 *   useEffect × 3 — localStorage 저장, 문서 제목, "/" 단축키(정리 함수로 리스너 제거)
 */

import { h } from "../core/vdom.js";
import { useState, useEffect, useMemo } from "../core/hooks.js";
import { Header } from "./components/Header.js";
import { TodoForm } from "./components/TodoForm.js";
import { Toolbar } from "./components/Toolbar.js";
import { TodoList } from "./components/TodoList.js";

/** localStorage 에 저장할 때 쓰는 이름 */
export const STORAGE_KEY = "mini-react:todos";

/** 중요도 이름 (값 → 화면 표시) */
export const PRIORITIES = Object.freeze({ high: "높음", normal: "보통", low: "낮음" });

/** 처음 열었을 때 (저장된 목록이 없을 때) 보여 줄 예시 */
export const SAMPLE_TODOS = Object.freeze([
  { id: 1, text: "Virtual DOM 과 Diff 복습하기", done: true, priority: "normal" },
  { id: 2, text: "useState 가 상태를 기억하는 원리 설명하기", done: false, priority: "high" },
  { id: 3, text: "useEffect 정리(cleanup) 함수 테스트", done: false, priority: "normal" },
  { id: 4, text: "발표 자료 만들기", done: false, priority: "low" },
]);

/** "예시 3개 추가" 버튼이 넣는 할 일 */
const BATCH_SAMPLES = ["장보기", "운동 30분", "책 20쪽 읽기"];

/** 저장된 목록을 읽는다. 없거나 망가졌으면 예시 목록 */
function loadTodos() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (Array.isArray(saved) && saved.every(isTodo)) return saved;
  } catch {
    // 저장소를 쓸 수 없거나(사생활 보호 모드 등) JSON 이 망가짐 → 예시로 시작
  }
  return SAMPLE_TODOS.map((todo) => ({ ...todo }));
}

/** 할 일 하나의 모양이 맞는지 (저장소에서 읽은 값을 믿지 않고 검사) */
function isTodo(value) {
  return (
    value !== null && typeof value === "object" &&
    Number.isInteger(value.id) && typeof value.text === "string" &&
    typeof value.done === "boolean" && Object.hasOwn(PRIORITIES, value.priority)
  );
}

/** 목록에 새로 넣을 할 일 (id 는 지금 목록의 가장 큰 id + 1) */
function makeTodo(list, text, priority) {
  const id = list.reduce((max, todo) => Math.max(max, todo.id), 0) + 1;
  return { id, text, done: false, priority };
}

/** 키 입력이 글자 입력창 안에서 일어났는가 (단축키를 가로채지 않기 위해) */
function isTyping(target) {
  return target instanceof Element && target.closest("input, textarea, select, [contenteditable]") !== null;
}

export function App() {
  // ── 상태 ──────────────────────────────────────────────────────────
  const [todos, setTodos] = useState(loadTodos); // 함수를 넘기면 첫 렌더에서 한 번만 실행 (지연 초기화)
  const [draft, setDraft] = useState("");
  const [priority, setPriority] = useState("normal");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");

  // ── 계산 값 (useMemo) ─────────────────────────────────────────────
  // todos 가 바뀔 때만 다시 센다. 입력창에 글자를 칠 때(draft 변경)는 이전 결과를 재사용.
  const stats = useMemo(() => {
    const done = todos.filter((todo) => todo.done).length;
    const total = todos.length;
    return { total, done, active: total - done, percent: total === 0 ? 0 : Math.round((done / total) * 100) };
  }, [todos]);

  // 필터 · 검색어 · 목록 중 하나가 바뀔 때만 다시 거른다.
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return todos.filter((todo) => {
      if (filter === "active" && todo.done) return false;
      if (filter === "done" && !todo.done) return false;
      return needle === "" || todo.text.toLowerCase().includes(needle);
    });
  }, [todos, filter, query]);

  // ── 부수효과 (useEffect) — 화면이 반영된 뒤 실행 ──────────────────────
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(todos));
    } catch {
      // 저장소를 쓸 수 없으면 저장만 건너뛴다 (화면은 그대로 동작)
    }
  }, [todos]);

  useEffect(() => {
    document.title = stats.active > 0 ? `할 일 ${stats.active}개 남음 · 미니 React` : "모두 완료 · 미니 React";
  }, [stats.active]);

  useEffect(() => {
    // "/" 를 누르면 검색창으로. 컴포넌트가 사라질 때 리스너도 지우도록 정리 함수를 돌려준다.
    const onKeyDown = (event) => {
      if (event.key !== "/" || isTyping(event.target)) return;
      event.preventDefault();
      document.getElementById("todo-search")?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // ── 상태를 바꾸는 함수 (자식에게 콜백으로 내려감) ────────────────────
  const addTodo = (event) => {
    event.preventDefault(); // form 제출로 페이지가 새로고침되지 않게
    const text = draft.trim();
    if (text === "") return;
    // setState 두 번 → 배칭되어 렌더는 한 번
    setTodos((list) => [...list, makeTodo(list, text, priority)]);
    setDraft("");
  };
  const toggleTodo = (id) => setTodos((list) => list.map((todo) => (todo.id === id ? { ...todo, done: !todo.done } : todo)));
  const removeTodo = (id) => setTodos((list) => list.filter((todo) => todo.id !== id));
  const clearDone = () => setTodos((list) => list.filter((todo) => !todo.done));
  const addBatch = () => {
    // 배칭 데모: setState 를 3번 부르지만 렌더는 1번 (렌더 관찰 패널에서 확인)
    for (const text of BATCH_SAMPLES) setTodos((list) => [...list, makeTodo(list, text, "normal")]);
  };

  // ── 화면 ──────────────────────────────────────────────────────────
  return h(
    "div",
    { class: "todo-app" },
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
      onFilter: setFilter,
      onQuery: (event) => setQuery(event.target.value),
      onClearDone: clearDone,
      onAddBatch: addBatch,
    }),
    TodoList({
      items: visible,
      query: query.trim(),
      isEmpty: todos.length === 0,
      priorities: PRIORITIES,
      onToggle: toggleTodo,
      onRemove: removeTodo,
    }),
  );
}
