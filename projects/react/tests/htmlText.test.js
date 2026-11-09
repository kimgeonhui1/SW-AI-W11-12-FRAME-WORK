// [htmlText.test.js] htmlToVdom / vdomToHtml 단위 테스트 (브라우저에서 htmlText.test.html로 실행)

import { h } from "../src/core/vdom.js";
import { htmlToVdom, vdomToHtml } from "../src/phase1/htmlText.js";

const results = [];

function test(name, fn) {
  try {
    fn();
    results.push({ name, ok: true });
  } catch (e) {
    results.push({ name, ok: false, message: e.message });
  }
}

function stableStringify(value) {
  return JSON.stringify(value, (key, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]]))
      : v
  );
}

function assertEqual(actual, expected, msg = "") {
  const a = stableStringify(actual);
  const e = stableStringify(expected);
  if (a !== e) throw new Error(`${msg}\n  기대: ${e}\n  실제: ${a}`);
}

test("htmlToVdom: 여러 최상위 태그를 루트 <div>로 감쌈", () => {
  assertEqual(htmlToVdom("<p>a</p>\n<p>b</p>"), h("div", null, h("p", null, "a"), h("p", null, "b")));
});

test("vdomToHtml: 자식이 전부 요소면 줄바꿈 + 들여쓰기", () => {
  const root = h("div", null, h("ul", { id: "x" }, h("li", null, "A"), h("li", null, "B")), h("p", null, "C"));
  assertEqual(vdomToHtml(root), '<ul id="x">\n  <li>A</li>\n  <li>B</li>\n</ul>\n<p>C</p>');
});

test("vdomToHtml: 텍스트가 섞이면 한 줄 그대로 (줄바꿈이 글자 내용이 되지 않게)", () => {
  assertEqual(vdomToHtml(h("div", null, h("p", null, "총 ", h("b", null, "2"), "개"))), "<p>총 <b>2</b>개</p>");
});

test("vdomToHtml: 속성 (class / boolean / style / 함수·false 제외)", () => {
  const root = h("div", null, h("input", { className: "a", type: "checkbox", checked: true, disabled: false, onClick: () => {} }), h("p", { style: { fontSize: "12px", "--gap": "4px" } }, "x"));
  assertEqual(vdomToHtml(root), '<input class="a" type="checkbox" checked>\n<p style="font-size: 12px; --gap: 4px">x</p>');
});

test("vdomToHtml: 특수문자 이스케이프", () => {
  assertEqual(vdomToHtml(h("div", null, h("p", { title: 'a "b" & c' }, "1 < 2 & 3"))), '<p title="a &quot;b&quot; &amp; c">1 &lt; 2 &amp; 3</p>');
});

// 핵심 약속: 테스트 영역에 보여 준 HTML을 그대로 다시 읽으면 같은 VDOM이어야 한다
// (그래야 로드 직후 / 뒤로가기 직후 Patch를 눌러도 "변경 없음"이 된다)
const ROUND_TRIP = [
  `<h3 class="title">할 일 목록</h3>
<ul id="todo">
  <li>Virtual DOM 만들기</li>
  <li>Diff 구현</li>
</ul>
<p style="color: gray;">총 <b>2</b>개</p>
<input value="입력값" />
<label><input type="checkbox" checked /> 완료</label>`,
  "<p>a <b>b</b> <i>c</i></p>",
  "<pre>\n\n  들여쓰기\n    유지</pre>",
  "<textarea>\n첫 줄 줄바꿈\n</textarea>",
  '<select><option value="a">A</option><option value="b" selected>B</option></select>',
  '<select multiple><option selected>A</option><option>B</option><option selected>C</option></select>',
  "<table><tr><td>1</td><td>2</td></tr></table>",
  '<p title="&quot;따옴표&quot; &amp;">1 &lt; 2 &amp;&amp; 3 &gt; 2</p>',
  "<div><!-- 주석 --><span>a</span>b<!-- c -->c</div>",
  '<div style="--gap: 4px; background-color: red">x</div>',
  '<input value="a &quot;b&quot;"><input type="range" min="0" max="500" value="300"><br>',
  "<ul><li><ul><li>깊은</li></ul></li></ul>",
  "텍스트만",
  "",
  // 2차 리뷰 이후 추가: 파서가 안쪽을 글자 그대로 읽는 태그 (이스케이프하면 깨지던 경우)
  "<style>.a > .b { color: red & blue; }</style>",
  "<script>if (a < b && c) {}</script>",
  "<noscript><b>x</b> & y</noscript>",
  "<xmp><b>x</b></xmp>",
  "<iframe>a < b</iframe>",
  "<p>앞</p><plaintext>a < b</plaintext>",
  "<div><ul><li>x</li></ul><section><plaintext>a</div>",
  // 리뷰가 제안했지만 원래부터 통과하던 경우 (회귀 방지용)
  "<pre>\n\n<span>a</span></pre>",
  "<textarea>&lt;b&gt;안녕&lt;/b&gt;</textarea>",
  "안녕\n<p>반가워</p>",
  '<svg viewBox="0 0 10 10"><circle r="1"></circle></svg>',
  "a&nbsp;b",
  "<p><div>a</div></p>",
];

test("왕복: htmlToVdom(vdomToHtml(v)) === v", () => {
  ROUND_TRIP.forEach((html, i) => {
    const vdom = htmlToVdom(html);
    assertEqual(htmlToVdom(vdomToHtml(vdom)), vdom, `샘플 ${i}: ${JSON.stringify(html)}`);
  });
});

const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const passed = results.filter((r) => r.ok).length;
document.getElementById("results").innerHTML =
  `<h2>${passed} / ${results.length} passed</h2>` +
  results
    .map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`)
    .join("");
console.table(results);
