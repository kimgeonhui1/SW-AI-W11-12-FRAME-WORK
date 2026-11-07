// [App.js] 루트 컴포넌트 — 앱의 모든 상태(State)를 가지고 자식에게 props로 전달

/**
 * 할 일 보드. 상태는 전부 여기 루트에만 있다 (Lifting State Up).
 *   todos [{ id, text, done, priority }] · draft(입력 중인 글자) · priority(새 할 일 중요도) · filter("all" | "active" | "done") · query(검색어)
 * 자식(Header, TodoForm, Toolbar, TodoList, TodoItem)은 상태 없는 순수 함수로, 값과 "상태를 바꾸는 콜백" 을 props 로 받는다.
 *   TodoItem 체크 → onToggle(id) → setTodos → App 다시 렌더 → Diff → 바뀐 노드만 Patch
 * Hook: useState × 5, useMemo × 2(통계 · 보일 목록), useEffect × 3(저장 · 문서 제목 · "/" 단축키)
 */

import { h } from "../core/vdom.js";
import { useState, useEffect, useMemo } from "../core/hooks.js";
import { Header } from "./components/Header.js";
import { TodoForm } from "./components/TodoForm.js";
import { Toolbar } from "./components/Toolbar.js";
import { TodoList } from "./components/TodoList.js";

export const STORAGE_KEY = "mini-react:todos";
export const PRIORITIES = Object.freeze({ high: "높음", normal: "보통", low: "낮음" });

/** 저장된 목록이 없을 때 보여 줄 예시 */
export const SAMPLE_TODOS = Object.freeze([
  { id: 1, text: "Virtual DOM 과 Diff 복습하기", done: true, priority: "normal" },
  { id: 2, text: "useState 가 상태를 기억하는 원리 설명하기", done: false, priority: "high" },
  { id: 3, text: "useEffect 정리(cleanup) 함수 테스트", done: false, priority: "normal" },
  { id: 4, text: "발표 자료 만들기", done: false, priority: "low" },
]);

const BATCH_SAMPLES = ["장보기", "운동 30분", "책 20쪽 읽기"]; // "예시 3개 추가" 버튼

/** 저장된 목록 읽기. 없거나 망가졌거나 저장소를 못 쓰면(사생활 보호 모드 등) 예시 목록 */
function loadTodos() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (Array.isArray(saved) && saved.every(isTodo)) return saved;
  } catch {
    // 예시로 시작
  }
  return SAMPLE_TODOS.map((todo) => ({ ...todo }));
}

/** 저장소에서 읽은 값은 믿지 않고 모양을 검사 */
const isTodo = (v) =>
  v !== null && typeof v === "object" && Number.isInteger(v.id) && typeof v.text === "string" &&
  typeof v.done === "boolean" && Object.hasOwn(PRIORITIES, v.priority);

/** 새 할 일 (id = 가장 큰 id + 1) */
const makeTodo = (list, text, priority) => ({ id: list.reduce((max, todo) => Math.max(max, todo.id), 0) + 1, text, done: false, priority });

/** 입력창 안에서 친 키인가 (단축키가 가로채지 않게) */
const isTyping = (target) => target instanceof Element && target.closest("input, textarea, select, [contenteditable]") !== null;

export function App() {
  const [todos, setTodos] = useState(loadTodos); // 함수를 넘기면 첫 렌더에서 한 번만 실행 (지연 초기화)
  const [draft, setDraft] = useState("");
  const [priority, setPriority] = useState("normal");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");

  // todos 가 바뀔 때만 다시 센다 (입력창에 글자를 칠 때는 재사용)
  const stats = useMemo(() => {
    const done = todos.filter((todo) => todo.done).length;
    const total = todos.length;
    return { total, done, active: total - done, percent: total === 0 ? 0 : Math.round((done / total) * 100) };
  }, [todos]);

  // 목록 · 필터 · 검색어 중 하나가 바뀔 때만 다시 거른다
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return todos.filter((todo) => {
      if ((filter === "active" && todo.done) || (filter === "done" && !todo.done)) return false;
      return needle === "" || todo.text.toLowerCase().includes(needle);
    });
  }, [todos, filter, query]);

  // 부수효과 — 화면이 반영된 뒤 실행
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(todos));
    } catch {
      // 저장소를 쓸 수 없으면 저장만 건너뜀
    }
  }, [todos]);

  useEffect(() => {
    document.title = stats.active > 0 ? `할 일 ${stats.active}개 남음 · 미니 React` : "모두 완료 · 미니 React";
  }, [stats.active]);

  useEffect(() => {
    // "/" → 검색창. 정리 함수로 리스너를 지운다
    const onKeyDown = (event) => {
      if (event.key !== "/" || isTyping(event.target)) return;
      event.preventDefault();
      document.getElementById("todo-search")?.focus();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // 상태를 바꾸는 함수 (자식에게 콜백으로)
  const addTodo = (event) => {
    event.preventDefault(); // form 제출로 새로고침되지 않게
    const text = draft.trim();
    if (text === "") return;
    setTodos((list) => [...list, makeTodo(list, text, priority)]); // setState 두 번 → 배칭되어 렌더 한 번
    setDraft("");
  };
  // 배칭 데모: setState 를 3번 부르지만 렌더는 1번
  const addBatch = () => BATCH_SAMPLES.forEach((text) => setTodos((list) => [...list, makeTodo(list, text, "normal")]));

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
      onClearDone: () => setTodos((list) => list.filter((todo) => !todo.done)),
      onAddBatch: addBatch,
    }),
    TodoList({
      items: visible,
      query: query.trim(),
      isEmpty: todos.length === 0,
      priorities: PRIORITIES,
      onToggle: (id) => setTodos((list) => list.map((todo) => (todo.id === id ? { ...todo, done: !todo.done } : todo))),
      onRemove: (id) => setTodos((list) => list.filter((todo) => todo.id !== id)),
    }),
  );
}
