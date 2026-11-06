// [history.js] Patch된 Virtual DOM 기록 관리 (뒤로가기 / 앞으로가기)

/**
 * State History — 브라우저의 뒤로가기/앞으로가기와 같은 방식으로 동작하는 기록 저장소
 *
 *   stack : 저장된 기록 배열. 각 기록 = { vdom, patchCount, label, time }
 *   index : 지금 화면에 보이는 기록의 위치 (-1 이면 아직 기록이 없음)
 *
 *   예) stack = [A, B, C], index = 2  → 현재 C
 *       undo()  → index = 1, B 반환
 *       push(D) → C 를 버리고 stack = [A, B, D], index = 2
 *       (뒤로 간 상태에서 새 기록을 만들면 "앞으로가기" 기록은 사라진다 = 분기)
 *
 * 깊은 복사 이유
 *   VNode 는 평범한 객체라서 참조를 그대로 저장하면, 바깥에서 객체를 수정했을 때
 *   과거 기록까지 같이 바뀌어 버린다. 그래서 넣을 때도, 꺼낼 때도 structuredClone 으로 복사한다.
 */

// 모듈 내부 상태 (밖에서는 아래 함수로만 접근)
let stack = [];
let index = -1;

/**
 * VNode 깊은 복사 (null 은 그대로)
 *
 * 처음에는 structuredClone 을 그대로 썼는데, structuredClone 도 내부에서 재귀로 내려가서
 * 깊이 수천 단계의 VDOM 에서 호출 스택이 넘쳤다 (Chrome 기준 약 5,000 단계에서 RangeError).
 * 그래서 VDOM 을 이루는 "배열" 과 "평범한 객체" 는 명시적 스택으로 직접 복사하고,
 * 그 밖의 값만 structuredClone 에 맡긴다. 결과는 structuredClone 과 같게 맞춘다.
 *   - 원시값(문자열 · 숫자 · null …)            → 그대로
 *   - 함수 · Symbol 등 복사할 수 없는 값          → structuredClone 이 DataCloneError 를 던짐 (예전과 같음)
 *   - Date · Map 같은 그 밖의 객체                → structuredClone 으로 복사 (이 값들은 깊지 않음)
 *   - 같은 객체를 여러 곳에서 쓰면(공유) 복사본에서도 하나의 객체를 공유, 순환 참조도 그대로 복사
 *   - 얼린(Object.freeze) 객체도 복사본은 얼리지 않음, 속성 이름 "__proto__" 도 평범한 속성으로 복사
 */
function clone(vdom) {
  if (vdom == null) return vdom;
  const copies = new Map(); // 원본 객체 → 복사본 (공유 · 순환 참조 처리)
  const stack = []; //         [원본, 복사본] — 속성을 아직 채우지 않은 복사본

  /** 값 하나의 복사본을 돌려준다. 배열 · 평범한 객체는 빈 껍데기만 만들고 내용은 스택에 맡긴다 */
  function copyOf(value) {
    if (value === null || (typeof value !== "object" && typeof value !== "function" && typeof value !== "symbol")) {
      return value; // 원시값
    }
    if (copies.has(value)) return copies.get(value);
    if (!isPlainContainer(value)) return structuredClone(value); // 함수 · Symbol 이면 DataCloneError
    const copy = Array.isArray(value) ? new Array(value.length) : {};
    copies.set(value, copy);
    stack.push([value, copy]);
    return copy;
  }

  const result = copyOf(vdom);
  while (stack.length > 0) {
    const [source, copy] = stack.pop();
    for (const key of Object.keys(source)) {
      // defineProperty: copy["__proto__"] = 값 은 프로토타입 설정이 되므로 평범한 속성으로 만든다
      Object.defineProperty(copy, key, { value: copyOf(source[key]), enumerable: true, writable: true, configurable: true });
    }
  }
  return result;
}

/** 직접 복사할 값인가: 배열, 또는 프로토타입이 Object.prototype · null 인 평범한 객체 */
function isPlainContainer(value) {
  if (Array.isArray(value)) return true;
  if (typeof value !== "object") return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/**
 * 새 기록 추가
 *
 * @param {object} vdom 저장할 Virtual DOM (복사해서 저장)
 * @param {{patchCount?: number, label?: string}} meta 화면 목록에 보여 줄 부가 정보
 *   patchCount : 이 기록을 만들 때 적용된 패치 개수
 *   label      : 기록 이름 (예: "초기 상태", "Patch #1")
 * @returns {number} 새 기록의 위치(index)
 */
export function push(vdom, meta) {
  // 1) 새 기록을 먼저 완성한다.
  //    복사(structuredClone)가 실패하면(함수 · Symbol 이 든 VDOM) 여기서 예외가 나고,
  //    아래의 "앞으로가기 기록 버리기" 는 실행되지 않으므로 History 가 그대로 남는다.
  const info = meta !== null && typeof meta === "object" ? meta : {}; // null · 문자열 등은 무시
  const entry = {
    vdom: clone(vdom),
    patchCount: Number.isFinite(info.patchCount) ? info.patchCount : 0,
    label: typeof info.label === "string" && info.label !== "" ? info.label : `기록 ${index + 2}`,
    time: Date.now(),
  };

  // 2) 현재 위치 뒤의 "앞으로가기" 기록을 버리고 새 기록을 붙인다.
  stack = stack.slice(0, index + 1);
  stack.push(entry);
  index = stack.length - 1;
  return index;
}

/**
 * 한 칸 뒤로 이동
 * @returns {object|null} 이동한 위치의 VNode 복사본. 맨 앞이라 이동할 수 없으면 null
 */
export function undo() {
  if (!canUndo()) return null;
  index -= 1;
  return current();
}

/**
 * 한 칸 앞으로 이동
 * @returns {object|null} 이동한 위치의 VNode 복사본. 맨 뒤라 이동할 수 없으면 null
 */
export function redo() {
  if (!canRedo()) return null;
  index += 1;
  return current();
}

/**
 * 특정 위치로 바로 이동 (History 목록 클릭)
 * @param {number} i 이동할 위치 (0부터)
 * @returns {object|null} 해당 VNode 복사본. 범위를 벗어나면 null (위치는 그대로)
 */
export function go(i) {
  if (!Number.isInteger(i) || i < 0 || i >= stack.length) return null;
  index = i;
  return current();
}

/** 현재 위치의 VNode 복사본 (기록이 없으면 null) */
export function current() {
  return index < 0 ? null : clone(stack[index].vdom);
}

/** 뒤로 갈 수 있는가 */
export function canUndo() {
  return index > 0;
}

/** 앞으로 갈 수 있는가 */
export function canRedo() {
  return index >= 0 && index < stack.length - 1;
}

/**
 * 현재 위치 정보
 * @returns {{index: number, length: number}} index 는 0부터 시작 (기록이 없으면 -1)
 */
export function position() {
  return { index, length: stack.length };
}

/**
 * 화면 목록용 기록 요약 (VNode 자체는 빼고 메타 정보만)
 * @returns {Array<{index:number, label:string, patchCount:number, time:number, active:boolean}>}
 */
export function entries() {
  return stack.map((entry, i) => ({
    index: i,
    label: entry.label,
    patchCount: entry.patchCount,
    time: entry.time,
    active: i === index,
  }));
}

/** 기록 전체 삭제 (테스트 · 초기화용) */
export function reset() {
  stack = [];
  index = -1;
}
