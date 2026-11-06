// [tests/runner.js] 외부 라이브러리 없이 만든 아주 작은 테스트 러너

/**
 * 사용법
 *   import { describe, test, assert, assertEqual } from "./runner.js";
 *   describe("묶음 이름", () => {
 *     test("테스트 이름", () => { assertEqual(1 + 1, 2); });
 *   });
 *   await run(document.getElementById("output"));
 *
 * - test 안에서 예외가 나면 실패, 아니면 통과
 * - 결과는 화면에 그리고, window.__testResults 에도 저장한다 (자동 확인용)
 */

const suites = []; // [{ name, tests: [{ name, fn }] }]
let currentSuite = null;

/** 테스트 묶음 */
export function describe(name, body) {
  currentSuite = { name, tests: [] };
  suites.push(currentSuite);
  body();
  currentSuite = null;
}

/** 테스트 하나 등록 */
export function test(name, fn) {
  if (!currentSuite) throw new Error("test() 는 describe() 안에서 호출해야 합니다.");
  currentSuite.tests.push({ name, fn });
}

/** 조건이 참인지 확인 */
export function assert(condition, message = "assert 실패") {
  if (!condition) throw new Error(message);
}

/**
 * 깊은 비교 (VNode · 배열 · 평범한 객체 · 원시값)
 * 객체는 키 순서와 상관없이 키 집합과 값이 같으면 같다고 본다.
 */
export function deepEqual(a, b) {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null || typeof a !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  if (Array.isArray(a)) {
    return a.length === b.length && a.every((item, i) => deepEqual(item, b[i]));
  }
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  return keysA.length === keysB.length && keysA.every((key) => key in b && deepEqual(a[key], b[key]));
}

/** 두 값이 깊게 같은지 확인. 다르면 두 값을 JSON 으로 보여 준다 */
export function assertEqual(actual, expected, message = "") {
  if (!deepEqual(actual, expected)) {
    throw new Error(
      `${message ? message + "\n" : ""}기댓값: ${JSON.stringify(expected)}\n실제값: ${JSON.stringify(actual)}`,
    );
  }
}

/**
 * 모든 테스트 실행 후 결과를 output 요소에 그린다.
 * @returns {{passed:number, failed:number, total:number, failures:Array}}
 */
export async function run(output) {
  const result = { passed: 0, failed: 0, total: 0, failures: [], ms: 0 };
  const started = performance.now();

  for (const suite of suites) {
    const section = document.createElement("section");
    const title = document.createElement("h2");
    title.textContent = suite.name;
    const list = document.createElement("ul");
    section.append(title, list);

    for (const t of suite.tests) {
      result.total += 1;
      const li = document.createElement("li");
      try {
        await t.fn();
        result.passed += 1;
        li.className = "pass";
        li.textContent = `✔ ${t.name}`;
      } catch (err) {
        result.failed += 1;
        result.failures.push({ suite: suite.name, test: t.name, error: String(err && err.message) });
        li.className = "fail";
        li.textContent = `✘ ${t.name}`;
        const pre = document.createElement("pre");
        pre.textContent = String(err && err.stack ? err.stack : err);
        li.append(pre);
        console.error(`[테스트 실패] ${suite.name} › ${t.name}`, err);
      }
      list.append(li);
    }
    output.append(section);
  }

  result.ms = Math.round(performance.now() - started);
  window.__testResults = result;
  return result;
}
