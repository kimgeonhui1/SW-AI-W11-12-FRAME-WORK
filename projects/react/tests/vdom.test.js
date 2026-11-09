// [vdom.test.js] h / domToVdom / createElement 단위 테스트 (브라우저에서 vdom.test.html로 실행)
//
// ── 단위 테스트란? ──
// 함수 하나하나에 "이런 입력을 넣으면 이런 결과가 나와야 한다"를 코드로 적어 두고 자동으로 확인하는 것.
// 나중에 코드를 고쳤을 때 이 페이지만 다시 열면, 예전에 되던 게 깨졌는지 바로 알 수 있다.
//
// ── 왜 Node.js가 아니라 브라우저에서 돌리나? ──
// domToVdom / createElement 는 document, Node 같은 "브라우저에만 있는" 객체를 쓴다.
// 그래서 외부 테스트 라이브러리(Jest 등) 없이, 브라우저에서 직접 돌리는 아주 작은 테스트 도구를 아래에 만들었다.

// 테스트할 함수 3개를 vdom.js에서 가져온다. (../ = 한 폴더 위로 올라가기)
import { h, domToVdom, createElement, setProp, removeProp } from "../src/core/vdom.js";

// 각 테스트의 결과({ name, ok, message })를 모아 두는 배열. 마지막에 화면에 출력한다.
const results = [];

/**
 * 테스트 하나를 실행하는 함수
 * @param name 테스트 이름 (화면에 보일 설명)
 * @param fn   실제 검사 코드를 담은 함수
 *
 * fn 안에서 assertEqual이 실패하면 에러를 "던지고(throw)", 그걸 catch에서 받아 실패로 기록한다.
 * try/catch를 쓰는 이유: 테스트 하나가 실패해도 나머지 테스트는 계속 실행되게 하려고.
 */
function test(name, fn) {
  try {
    // 검사 코드 실행. 에러 없이 끝나면 아래 줄로 내려간다
    fn();
    // 에러가 없었으면 성공으로 기록
    results.push({ name, ok: true });
  } catch (e) {
    // 에러가 났으면 실패로 기록하고, 에러 메시지(기대값/실제값)도 같이 저장
    results.push({ name, ok: false, message: e.message });
  }
}

/**
 * 객체를 "키 이름순으로 정렬한" JSON 문자열로 바꾸는 함수
 *
 * 그냥 JSON.stringify를 쓰면 키를 넣은 순서대로 문자열이 만들어져서,
 * { id: "a", className: "b" } 와 { className: "b", id: "a" } 처럼 내용이 같아도 다른 문자열이 된다.
 * 그래서 객체를 만날 때마다 키를 정렬한 새 객체로 바꿔서 직렬화한다. (배열은 순서 자체가 의미라서 그대로 둔다)
 * ※ 함수는 JSON에 담기지 않는다. onClick 같은 함수 props는 이 방법으로 비교할 수 없으니 직접 실행해서 확인한다.
 */
function stableStringify(value) {
  return JSON.stringify(value, (key, v) =>
    v && typeof v === "object" && !Array.isArray(v)
      ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, v[k]]))
      : v
  );
}

/**
 * 두 값이 같은지 검사하는 함수. 다르면 에러를 던진다.
 * @param actual   실제로 나온 값
 * @param expected 나와야 하는 값 (정답)
 * @param msg      실패했을 때 앞에 붙일 설명 (생략 가능)
 *
 * 객체는 === 로 비교하면 "같은 객체(같은 메모리)인지"를 보기 때문에 내용이 같아도 false가 나온다.
 * 그래서 stableStringify로 문자열로 바꿔서 "내용"을 비교한다.
 */
function assertEqual(actual, expected, msg = "") {
  // 실제 값을 문자열로 변환. 예) { type: "div" } → '{"type":"div"}'
  const a = stableStringify(actual);
  // 정답 값을 문자열로 변환
  const e = stableStringify(expected);
  // 둘이 다르면 에러를 던진다 → test()의 catch로 가서 실패로 기록됨
  // 메시지에 정답(expected)과 실제(actual)를 함께 넣어서 어디가 틀렸는지 보이게 한다
  if (a !== e) throw new Error(`${msg}\n  expected: ${e}\n  actual:   ${a}`);
}

/**
 * HTML 문자열을 실제 DOM 요소로 바꿔 주는 도우미
 * 예) parse("<p>hi</p>") → 실제 <p> 요소
 *
 * <template> 태그를 쓰는 이유: template 안에 넣은 HTML은 브라우저가 해석(파싱)만 하고 화면에는 그리지 않는다.
 * 그래서 테스트용 DOM을 문서를 더럽히지 않고 만들 수 있다.
 */
function parse(html) {
  // 빈 <template> 요소를 만든다
  const t = document.createElement("template");
  // innerHTML에 HTML 문자열을 넣으면 브라우저가 그걸 해석해서 실제 노드들로 만들어 준다
  t.innerHTML = html;
  // t.content = template 안의 내용물, firstElementChild = 그중 첫 번째 "요소" (텍스트 노드는 건너뜀)
  return t.content.firstElementChild;
}

// ======================================================================
// h 테스트 : 객체를 올바른 모양으로 만드는지
// ======================================================================

// 가장 기본: h("div", {id}, "hi") 가 팀 규약 모양을 만드는지
test("h: 기본 형식 {type, props, children}", () => {
  assertEqual(h("div", { id: "a" }, "hi"), { type: "div", props: { id: "a" }, children: ["hi"] });
});

// props 자리에 null을 넣거나 아예 안 넣어도 props가 빈 객체 {}가 되는지
test("h: props가 null/생략이면 {}", () => {
  assertEqual(h("div", null).props, {}); // null을 넣은 경우
  assertEqual(h("div").props, {}); // 생략한 경우 (기본값 {} 사용)
});

// 자식으로 배열(또는 배열 안의 배열)이 들어와도 한 줄로 펼쳐지는지
// 실제로 items.map(...) 결과를 자식으로 넘길 때 이런 모양이 된다
test("h: 중첩 배열 children 평탄화", () => {
  // [li A, [li B]] → 펼치면 [li A, li B]
  const vnode = h("ul", {}, [h("li", {}, "A"), [h("li", {}, "B")]]);
  // 각 li의 첫 번째 자식(글자)만 뽑아서 ["A", "B"]인지 확인
  assertEqual(vnode.children.map((c) => c.children[0]), ["A", "B"]);
});

// null/undefined/true/false는 버려지고, 숫자는 문자열이 되는지
// 숫자 0은 "아무것도 아님"이 아니라 화면에 "0"으로 보여야 하므로 버리면 안 된다 (흔한 실수 포인트)
// (사이에 <b>를 넣은 이유: 텍스트끼리 붙어 있으면 하나로 합쳐지는 규칙 때문에 각각 확인하기 어렵다)
test("h: null/undefined/boolean 제거, 숫자는 문자열로", () => {
  assertEqual(h("p", {}, null, undefined, false, true, 0, h("b", {}), 42).children, [
    "0",
    { type: "b", props: {}, children: [] },
    "42",
  ]);
});

// ======================================================================
// domToVdom 테스트 : 실제 DOM을 올바른 객체로 읽어 오는지 (특히 공백 처리)
// ======================================================================

// HTML을 줄바꿈 + 들여쓰기해서 쓰면 태그 사이에 "\n    " 텍스트 노드가 생긴다.
// 그런 노드는 버리고 li 두 개만 남는지 확인
test("domToVdom: 줄바꿈 들여쓰기 공백 노드 제거", () => {
  // 백틱(`)으로 감싼 문자열은 여러 줄을 그대로 쓸 수 있다 → 실제 HTML 파일처럼 들여쓰기가 들어감
  const el = parse(`<ul>
    <li>A</li>
    <li>B</li>
  </ul>`);
  assertEqual(domToVdom(el), {
    type: "ul",
    props: {},
    children: [
      { type: "li", props: {}, children: ["A"] },
      { type: "li", props: {}, children: ["B"] },
    ],
  });
});

// <b>a</b> 와 <i>b</i> 사이의 스페이스 한 칸은 화면에 "a b"로 보이는 띄어쓰기라서 지우면 안 된다
// (줄바꿈이 없는 공백은 보존한다는 규칙)
test("domToVdom: 같은 줄의 인라인 사이 공백은 보존", () => {
  const el = parse(`<p><b>a</b> <i>b</i></p>`);
  // 자식: [b, " ", i] → 두 번째(인덱스 1)가 " " 인지
  assertEqual(domToVdom(el).children[1], " ");
});

// 글자가 있는 텍스트는 앞뒤 공백까지 원문 그대로 둔다 (trim 하지 않음)
// trim 하면 "Hello" 뒤 공백이 사라져 화면에 "Helloworld"로 붙어 버린다
test("domToVdom: 글자가 있는 텍스트는 원문 그대로 (trim 안 함)", () => {
  // 맨 끝 "\n"만 있는 텍스트 노드는 공백+줄바꿈뿐이라 제거된다 → 자식은 2개
  const el = parse(`<p>\n  Hello <b>world</b>\n</p>`);
  assertEqual(domToVdom(el).children, ["\n  Hello ", { type: "b", props: {}, children: ["world"] }]);
});

// <pre> 안에서는 줄바꿈 공백도 화면 내용이므로 지우지 않는다.
// <pre> 바로 아래뿐 아니라 그 안의 자손 요소(<span>)들 사이에서도 마찬가지
test("domToVdom: <pre> 안(자손 포함)은 줄바꿈 공백도 보존", () => {
  const el = parse(`<pre><span>a</span>\n  <span>b</span></pre>`);
  // 자식: [span a, "\n  ", span b] → 3개
  assertEqual(domToVdom(el).children.length, 3);
  // 가운데 공백 노드가 살아 있는지
  assertEqual(domToVdom(el).children[1], "\n  ");
});

// <textarea>의 자식 텍스트는 입력창의 초기값이라 공백도 지우면 안 된다
test("domToVdom: <textarea> 내용 보존", () => {
  // 브라우저 HTML 파서는 <textarea> 바로 뒤의 첫 줄바꿈 하나를 자동으로 없앤다 (HTML 표준 규칙)
  // → "\n" 하나만 넣으면 텍스트가 아예 없어서 자식이 [] 가 된다
  const el = parse(`<textarea>\n</textarea>`);
  // → "\n\n  " 을 넣으면 첫 "\n"이 먹히고 "\n  " 이 남는다. 이건 줄바꿈 공백이지만 textarea 안이라 보존돼야 함
  const el2 = parse(`<textarea>\n\n  </textarea>`);
  assertEqual(domToVdom(el).children, []);
  assertEqual(domToVdom(el2).children, ["\n  "]);
});

// <!-- 주석 --> 은 화면에 안 보이므로 버려지는지
test("domToVdom: 주석 노드 제거", () => {
  const el = parse(`<div><!-- c -->x</div>`);
  // 주석은 빠지고 텍스트 "x"만 남아야 한다
  assertEqual(domToVdom(el).children, ["x"]);
});

// 태그를 대문자로 써도 소문자 "label"로 통일되는지,
// class → className, for → htmlFor 로 이름이 바뀌는지, 그 외 속성(data-id)은 그대로인지
test("domToVdom: 태그 소문자, class → className, for → htmlFor", () => {
  const el = parse(`<LABEL class="a b" for="x" data-id="1">t</LABEL>`);
  assertEqual(domToVdom(el), { type: "label", props: { className: "a b", htmlFor: "x", "data-id": "1" }, children: ["t"] });
});

// ======================================================================
// createElement 테스트 : 객체를 보고 실제 DOM을 올바르게 만드는지
// ======================================================================

// 문자열을 넣으면 텍스트 노드(nodeType 3)가 나오고, 글자가 그대로 들어 있는지
test("createElement: 문자열 → 텍스트 노드", () => {
  const node = createElement("hi");
  // [노드 종류, 글자] 를 한꺼번에 비교
  assertEqual([node.nodeType, node.textContent], [Node.TEXT_NODE, "hi"]);
});

// 속성(className → class 변환 포함)과 자식(요소 + 텍스트)이 전부 만들어지는지
test("createElement: 속성·자식 재귀 생성", () => {
  const el = createElement(h("div", { className: "box", id: "a" }, h("span", {}, "x"), "y"));
  // outerHTML = 요소 자신을 포함한 HTML 문자열. 만들어진 결과를 HTML로 찍어서 비교한다
  assertEqual(el.outerHTML, `<div class="box" id="a"><span>x</span>y</div>`);
});

// value / checked 가 property로 들어가서 "실제 화면 상태"가 맞게 되는지
test("createElement: input value/checked는 property로 설정", () => {
  // 입력창의 현재 값이 "abc"인지
  const input = createElement(h("input", { value: "abc" }));
  assertEqual(input.value, "abc");
  // checked: true → 체크박스가 체크되어 있는지
  const box = createElement(h("input", { type: "checkbox", checked: true }));
  assertEqual(box.checked, true);
  // checked: false → 체크 안 되어 있는지
  const box2 = createElement(h("input", { type: "checkbox", checked: false }));
  assertEqual(box2.checked, false);
});

// disabled: true → disabled 속성이 붙음, false/null → 속성이 아예 안 붙음
test("createElement: boolean 속성 true → 빈 속성, false/null → 생략", () => {
  // hasAttribute(이름): 그 속성이 있는지 true/false로 알려 줌
  assertEqual(createElement(h("button", { disabled: true })).hasAttribute("disabled"), true);
  // attributes.length: 붙은 속성 개수. disabled=false, title=null 이면 0개여야 함
  assertEqual(createElement(h("button", { disabled: false, title: null })).attributes.length, 0);
});

// onClick 함수가 진짜 클릭 이벤트로 등록되는지
test("createElement: onClick → 이벤트 리스너", () => {
  // 클릭 횟수를 세는 변수
  let clicked = 0;
  // 클릭하면 clicked를 1 올리는 버튼 생성
  const btn = createElement(h("button", { onClick: () => clicked++ }));
  // .click(): 코드로 클릭을 흉내 낸다 (사람이 누른 것처럼 click 이벤트 발생)
  btn.click();
  // 한 번 눌렀으니 1이어야 함
  assertEqual(clicked, 1);
  // onClick이 HTML 속성(onClick="...")으로 잘못 붙지 않았는지도 확인
  assertEqual(btn.hasAttribute("onClick"), false);
});

// style 객체가 실제 인라인 스타일로 들어가는지
test("createElement: style 객체", () => {
  const el = createElement(h("div", { style: { color: "red" } }));
  assertEqual(el.style.color, "red");
});

// ======================================================================
// 왕복 테스트 : DOM → VDOM → DOM 으로 바꿨다가 다시 읽어도 똑같은지
// domToVdom과 createElement가 서로 정확히 "반대 동작"인지 확인하는, 가장 중요한 테스트
// ======================================================================
test("왕복: DOM → VDOM → DOM 이 같은 구조", () => {
  // 들여쓰기, 인라인 공백, 체크박스, <pre> 를 한꺼번에 섞은 HTML
  const el = parse(`<div class="card">
    <h1 id="t">제목 <small>부제</small></h1>
    <input type="checkbox" checked>
    <pre>  a\n  b</pre>
  </div>`);
  // 원본 DOM → VDOM → 새 DOM 으로 다시 만든다
  const restored = createElement(domToVdom(el));
  // 새 DOM을 다시 VDOM으로 읽었을 때, 원본을 읽은 VDOM과 똑같아야 한다
  assertEqual(domToVdom(restored), domToVdom(el));
  // 체크 상태(property)도 실제로 살아 있는지
  assertEqual(restored.querySelector("input").checked, true);
});

// ======================================================================
// 정규화 테스트 : "같은 화면이면 같은 VDOM"이 되는지 (diff가 헷갈리지 않게)
// ======================================================================

// 이웃한 텍스트는 하나로 합쳐지고, 빈 문자열은 버려지는지
test("h: 이웃한 텍스트/숫자는 하나로 합치고 빈 문자열은 제거", () => {
  assertEqual(h("p", {}, "점수: ", 100, "", "점").children, ["점수: 100점"]);
});

// 주석을 버리면 양옆 텍스트가 이웃하게 되는데, 그것도 합쳐지는지
test("domToVdom: 주석으로 나뉜 텍스트도 하나로 합침", () => {
  assertEqual(domToVdom(parse(`<p>a<!-- c -->b</p>`)).children, ["ab"]);
});

// HTML 문자열로 바꿨다가 브라우저가 다시 읽어도 VDOM이 똑같은지 (Phase 1 테스트 영역 편집과 같은 상황)
test("왕복: VDOM → HTML 문자열 → 다시 파싱 → VDOM 이 같음", () => {
  const vnode = h("p", { className: "score" }, "점수: ", 100, h("b", {}, "!"));
  const html = createElement(vnode).outerHTML;
  assertEqual(domToVdom(parse(html)), vnode);
});

// style 문자열을 camelCase 객체로 읽는지, 그걸 다시 DOM으로 만들어도 같은지
test("domToVdom: style 문자열 → camelCase 객체 (CSS 변수는 그대로)", () => {
  const el = parse(`<div style="color: red; font-size: 12px; --gap: 4px"></div>`);
  const expected = { color: "red", fontSize: "12px", "--gap": "4px" };
  assertEqual(domToVdom(el).props.style, expected);
  // 객체 → 실제 DOM → 다시 읽기
  assertEqual(domToVdom(createElement(domToVdom(el))).props.style, expected);
});

// ======================================================================
// 사용자 입력 상태(property) 테스트 : 화면에서 바꾼 값을 놓치지 않는지
// ======================================================================

// 사용자가 타이핑하거나 체크를 해제하면 attribute는 그대로이고 property만 바뀐다 → property를 읽어야 함
test("domToVdom: 사용자가 바꾼 input 값/체크 상태를 읽음", () => {
  const el = parse(`<div><input value="초기"><input type="checkbox" checked></div>`);
  const [text, box] = el.querySelectorAll("input");
  // 사용자가 입력한 것처럼 property만 바꾼다
  text.value = "입력함";
  box.checked = false;
  const vdom = domToVdom(el);
  assertEqual(vdom.children[0].props.value, "입력함");
  // 체크 해제 → checked가 아예 없어야 함
  assertEqual("checked" in vdom.children[1].props, false);
});

// textarea는 자식 텍스트가 초기값이고, 사용자가 바꾼 현재 값은 value로 들어가야 한다
test("domToVdom: textarea 현재 값 보존 (h로 만든 것 / 사용자가 바꾼 것)", () => {
  // h()로 value를 준 textarea → 다시 읽어도 value 유지
  const made = createElement(h("textarea", { value: "초기값" }));
  assertEqual(domToVdom(made).props.value, "초기값");
  assertEqual(createElement(domToVdom(made)).value, "초기값");
  // 원래 내용이 있는 textarea를 사용자가 수정
  const typed = parse(`<textarea>원래</textarea>`);
  typed.value = "수정함";
  assertEqual(domToVdom(typed), { type: "textarea", props: { value: "수정함" }, children: ["원래"] });
});

// select에서 사용자가 고른 option이 selected: true로 기록되는지, 다시 만들어도 같은 걸 고르는지
test("domToVdom: select에서 고른 option을 selected로 기록", () => {
  const el = parse(`<select><option value="a">A</option><option value="b">B</option></select>`);
  el.value = "b";
  const vdom = domToVdom(el);
  assertEqual(vdom.children.map((o) => o.props.selected === true), [false, true]);
  assertEqual(createElement(vdom).value, "b");
});

// option이 붙기 전에 select.value를 넣으면 무시되는 문제 → 자식을 먼저 붙이므로 정상 동작해야 함
test("createElement: select의 value prop", () => {
  const sel = createElement(h("select", { value: "b" }, h("option", { value: "a" }, "A"), h("option", { value: "b" }, "B")));
  assertEqual(sel.value, "b");
});

// [회귀] value: undefined 를 받은 select가 el.value = "" 로 선택이 전부 풀리던 문제
test("createElement: select의 value가 undefined면 option 선택을 유지", () => {
  const first = createElement(h("select", { value: undefined }, h("option", { value: "a" }, "A")));
  const marked = createElement(h("select", { value: null }, h("option", { value: "a" }, "A"), h("option", { value: "b", selected: true }, "B")));
  assertEqual([first.value, marked.value], ["a", "b"]);
});

// [회귀] value를 max보다 먼저 넣으면 기본 max(100)에 걸려 값이 잘리던 문제
test("createElement: range input은 value 키가 앞에 있어도 max 적용 후 값 설정", () => {
  const range = createElement(h("input", { type: "range", value: "300", max: "500" }));
  assertEqual(range.value, "300");
});

// [회귀] multiple을 자식보다 늦게 넣으면 selected option이 마지막 하나만 남던 문제
test("createElement: select multiple의 selected option이 모두 선택", () => {
  const sel = createElement(h("select", { multiple: true }, h("option", { selected: true }, "a"), h("option", null, "b"), h("option", { selected: true }, "c")));
  assertEqual([...sel.selectedOptions].map((o) => o.value), ["a", "c"]);
});

// ======================================================================
// setProp / removeProp 테스트 : patch에서 속성을 "바꾸고 지울 때" 올바른지
// ======================================================================

// disabled: true → false 로 바뀌면 속성이 실제로 지워져야 버튼이 다시 눌린다
test("setProp: false/null이면 기존 속성을 제거", () => {
  const btn = createElement(h("button", { disabled: true, className: "a" }));
  setProp(btn, "disabled", false);
  removeProp(btn, "className");
  assertEqual([btn.hasAttribute("disabled"), btn.hasAttribute("class")], [false, false]);
});

// 렌더링마다 새 함수가 들어와도 리스너가 쌓이지 않고, 최신 핸들러만 한 번 실행되는지
test("setProp: 이벤트 핸들러 교체 시 중복 없이 최신 것만 실행, removeProp으로 해제", () => {
  let oldCount = 0;
  let newCount = 0;
  const btn = createElement(h("button", { onClick: () => oldCount++ }));
  // patch가 새 핸들러로 교체하는 상황
  setProp(btn, "onClick", () => newCount++);
  btn.click();
  assertEqual([oldCount, newCount], [0, 1], "교체 후 클릭");
  // 핸들러 제거 후에는 클릭해도 아무것도 실행되지 않아야 함
  removeProp(btn, "onClick");
  btn.click();
  assertEqual([oldCount, newCount], [0, 1], "제거 후 클릭");
});

// 이전 style에만 있던 키는 지워지고, style이 통째로 없어지면 속성도 사라지는지
test("setProp: style 갱신 시 이전 키 제거, removeProp으로 style 속성 제거", () => {
  const el = createElement(h("div", { style: { color: "red", fontSize: "12px" } }));
  setProp(el, "style", { color: "blue" }, { color: "red", fontSize: "12px" });
  assertEqual([el.style.color, el.style.fontSize], ["blue", ""]);
  removeProp(el, "style", { color: "blue" });
  assertEqual(el.hasAttribute("style"), false);
});

// input의 value를 지우면 화면 값과 attribute가 모두 비워지는지
test("removeProp: input value 제거", () => {
  const input = createElement(h("input", { value: "abc" }));
  removeProp(input, "value");
  assertEqual([input.value, input.hasAttribute("value")], ["", false]);
});

// ======================================================================
// 결과 출력
// ======================================================================

// 테스트 이름에 "<pre>" 같은 태그 글자가 있어서 HTML로 해석되지 않도록 이스케이프(무해한 글자로 바꾸기)
// & → &amp;  < → &lt;  > → &gt;  (순서 중요: &를 먼저 바꿔야 이미 바꾼 &lt;의 &가 다시 바뀌지 않는다)
// ======================================================================
// 보강: 이벤트 이름 / onChange / 숫자 style / SVG / ref / key
// ======================================================================

test("onChange: 텍스트 입력은 글자마다(input 이벤트), checkbox는 change 이벤트", () => {
  const log = [];
  const text = createElement(h("input", { onChange: () => log.push("text") }));
  const area = createElement(h("textarea", { onChange: () => log.push("area") }));
  const box = createElement(h("input", { type: "checkbox", onChange: () => log.push("box") }));
  text.dispatchEvent(new Event("input"));
  area.dispatchEvent(new Event("input"));
  box.dispatchEvent(new Event("input")); // checkbox는 input 이벤트로는 실행되면 안 됨
  box.dispatchEvent(new Event("change"));
  assertEqual(log, ["text", "area", "box"]);
});

test("onChange와 onInput을 같이 써도 둘 다 실행, 하나를 지우면 나머지만 실행", () => {
  const log = [];
  const el = createElement(h("input", { onChange: () => log.push("change"), onInput: () => log.push("input") }));
  el.dispatchEvent(new Event("input"));
  removeProp(el, "onChange");
  el.dispatchEvent(new Event("input"));
  removeProp(el, "onInput");
  el.dispatchEvent(new Event("input"));
  assertEqual(log, ["change", "input", "input"]);
});

test("onDoubleClick → dblclick 이벤트", () => {
  let count = 0;
  const el = createElement(h("div", { onDoubleClick: () => count++ }));
  el.dispatchEvent(new Event("dblclick"));
  assertEqual(count, 1);
});

test("style: 숫자에는 px, 단위 없는 속성(opacity, zIndex, flex...)은 그대로", () => {
  const el = createElement(h("div", { style: { width: 100, marginTop: 8, opacity: 0.5, zIndex: 3, flexGrow: 2 } }));
  assertEqual([el.style.width, el.style.marginTop, el.style.opacity, el.style.zIndex, el.style.flexGrow], ["100px", "8px", "0.5", "3", "2"]);
});

test("SVG: svg와 자손은 SVG 이름공간, foreignObject 안은 다시 HTML / domToVdom 왕복", () => {
  const SVG = "http://www.w3.org/2000/svg";
  const vnode = h("svg", { viewBox: "0 0 10 10" }, h("circle", { r: "1", className: "dot" }), h("foreignObject", null, h("p", null, "html")));
  const el = createElement(vnode);
  const [circle, fo] = el.childNodes;
  assertEqual(
    [el.namespaceURI, circle.namespaceURI, fo.namespaceURI, fo.firstChild.namespaceURI],
    [SVG, SVG, SVG, "http://www.w3.org/1999/xhtml"]
  );
  // localName으로 읽어서 foreignObject / viewBox의 대소문자가 그대로 돌아와야 한다
  assertEqual(domToVdom(el), vnode);
});

test("ref: 객체 ref는 current에, 함수 ref는 인자로 요소를 받음 / key·ref는 DOM 속성이 아님", () => {
  const objRef = { current: null };
  let fnRefArg;
  const el = createElement(h("div", { ref: objRef, key: "k" }, h("span", { ref: (e) => (fnRefArg = e) })));
  assertEqual([objRef.current === el, fnRefArg === el.firstChild, el.hasAttribute("key"), el.hasAttribute("ref")], [true, true, false, false]);
  removeProp(el, "ref", objRef);
  assertEqual(objRef.current, null);
});

const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
// 성공한 테스트 개수 세기
const passed = results.filter((r) => r.ok).length;
// 결과를 넣을 자리 (vdom.test.html의 <div id="results">)
const out = document.getElementById("results");
// 결과 HTML을 만들어 넣는다
out.innerHTML =
  // 맨 위 제목: 예) "30 / 30 passed"
  `<h2>${passed} / ${results.length} passed</h2>` +
  // 테스트마다 한 줄씩. 성공은 class="ok"(초록 ✔), 실패는 class="fail"(빨강 ✘ + 에러 메시지)
  results
    .map((r) => `<pre class="${r.ok ? "ok" : "fail"}">${r.ok ? "✔" : "✘"} ${escape(r.name)}${r.ok ? "" : "\n" + escape(r.message)}</pre>`)
    // 배열을 하나의 문자열로 이어 붙인다 (사이에 아무것도 안 넣음)
    .join("");
// 개발자 도구(F12) 콘솔에도 표 형태로 결과를 출력
console.table(results);