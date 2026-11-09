// [App.js] 루트 컴포넌트 — 앱의 모든 상태(State)를 가지고 자식에게 props로 전달

import { h } from "../core/vdom.js";
import { useState, useEffect, useMemo } from "../core/hooks.js";
import { TodoForm } from "./components/TodoForm.js";
import { TodoList } from "./components/TodoList.js";
import { FilterBar } from "./components/FilterBar.js";

const STORAGE_KEY = "mini-react-todos";

// 저장된 목록 읽기. 개인 정보 보호 모드 등에서 localStorage가 막혀 있거나 값이 깨져 있으면 빈 목록으로 시작
function loadTodos() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

/**
 * Lifting State Up: 상태는 전부 여기(루트)에 두고, 자식은 props로 받은 값과 함수만 쓴다.
 * 자식이 상태를 바꾸고 싶으면 App이 넘겨준 함수(onToggle 등)를 부른다 → App의 setState → 다시 렌더링.
 */
export function App() {
  const [todos, setTodos] = useState(loadTodos); // 함수를 넘겨서 localStorage는 첫 렌더링에만 읽는다
  const [text, setText] = useState("");
  const [filter, setFilter] = useState("all");

  // 개수와 필터링 결과는 todos/filter가 바뀔 때만 다시 계산한다 (입력창에 타이핑할 때는 재사용)
  const counts = useMemo(() => {
    const done = todos.filter((t) => t.done).length;
    return { all: todos.length, done, active: todos.length - done };
  }, [todos]);
  const visible = useMemo(
    () => (filter === "all" ? todos : todos.filter((t) => (filter === "done" ? t.done : !t.done))),
    [todos, filter]
  );

  // 렌더링 뒤 부수효과: 목록이 바뀔 때만 저장하고 탭 제목을 갱신한다
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(todos));
    } catch {
      // 저장이 막힌 환경에서는 저장만 건너뛴다 (앱 동작에는 영향 없음)
    }
  }, [todos]);
  useEffect(() => {
    document.title = `할 일 ${counts.active}개 - Mini React`;
  }, [counts.active]);

  // 상태는 항상 "새 배열/객체"로 바꾼다. 기존 배열을 직접 고치면 Object.is 비교에서 같은 값으로 보여 다시 그려지지 않는다
  const addTodo = () => {
    const value = text.trim();
    if (value === "") return;
    setTodos((prev) => [...prev, { id: Date.now(), text: value, done: false }]);
    setText(""); // 두 setState가 Batching되어 렌더링은 1번
  };
  const toggleTodo = (id) => setTodos((prev) => prev.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));
  const removeTodo = (id) => setTodos((prev) => prev.filter((t) => t.id !== id));
  const clearDone = () => setTodos((prev) => prev.filter((t) => !t.done));

  return h(
    "main",
    { className: "todo-app" },
    h("h1", null, "할 일 목록"),
    h(TodoForm, { text, onTextChange: setText, onAdd: addTodo }),
    h(FilterBar, { filter, counts, onFilterChange: setFilter, onClearDone: clearDone }),
    h(TodoList, { todos: visible, onToggle: toggleTodo, onRemove: removeTodo })
  );
}
