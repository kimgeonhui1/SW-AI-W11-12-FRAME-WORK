"""Browser E2E for 2-4 player rooms: four independent browser sessions (separate contexts = separate guests).

Starts its own DBMS/Redis/API/static servers on free ports with a temporary DB. After every step each
screen is compared with that player's own server state (seat layout, stacks, turn, own/other cards, pot,
board, badges). Covers: 4-seat lobby + auto start, several hands (4-way showdown, raise/fold, all-ins with
side pots), a server 4xx (stale version) followed by unlocked controls, cash-out from the UI, profiles vs
the stored ledger. Only servers started here are stopped at the end.
"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT, SHOTS = sys.argv[1], sys.argv[2]
os.makedirs(SHOTS, exist_ok=True)
PY = sys.executable


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


DB, RD, API, STATIC = (free_port() for _ in range(4))
data = tempfile.mkdtemp(prefix="jpl-e2e4-db-")
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
procs = {}


def spawn(name, cwd, *args):
    log = open(os.path.join(SHOTS, f"server_{name}.log"), "w")
    procs[name] = subprocess.Popen([PY, "-B", *args], cwd=os.path.join(ROOT, cwd), env=env, stdout=log, stderr=log)


def wait_port(port):
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close(); return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port {port} did not open")


spawn("dbms", "dbms", "-m", "mini_dbms.server", "--data-dir", data, "--host", "127.0.0.1", "--port", str(DB))
spawn("redis", "redis", "-m", "mini_redis.server", "--host", "127.0.0.1", "--port", str(RD))
spawn("api", "poker_demo", "server.py", "--host", "127.0.0.1", "--port", str(API), "--dbms", f"http://127.0.0.1:{DB}", "--redis", f"http://127.0.0.1:{RD}")
spawn("static", "react", "-m", "http.server", str(STATIC), "--bind", "127.0.0.1")
for port in (DB, RD, API, STATIC):
    wait_port(port)

URL = f"http://127.0.0.1:{STATIC}/room.html?api=http://127.0.0.1:{API}"
SPOTS = {2: ["bottom", "top"], 3: ["bottom", "left", "right"], 4: ["bottom", "left", "top", "right"]}
results = []


def check(name, cond, detail=""):
    results.append({"name": name, "ok": bool(cond), "detail": "" if cond else str(detail)[:600]})
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)[:400]), flush=True)
    return bool(cond)


def get(path, token):
    req = urllib.request.Request(f"http://127.0.0.1:{API}{path}", headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


SCREEN_JS = """() => {
  const q = (s, r = document) => r.querySelector(s), qa = (s, r = document) => [...r.querySelectorAll(s)];
  const lab = (s, r) => qa(s, r).map(e => e.getAttribute('aria-label').replace('10', 'T'));
  const num = (e) => e ? Number(e.textContent.replace(/[^0-9]/g, '')) : null;
  return {
    seats: qa('.table > .seat').map(e => ({ seat: Number(e.dataset.seat), where: [...e.classList].find(c => /^seat-(bottom|top|left|right)$/.test(c)).slice(5),
      stack: e.classList.contains('is-empty') ? null : num(q('.hud-stack', e)), turn: e.classList.contains('is-turn'),
      up: lab('.seat-cards .card3d.is-up', e), down: qa('.seat-cards .card3d.is-down', e).length,
      badge: q('.seat-badge', e) ? q('.seat-badge', e).innerText : '', name: q('.hud-name', e).innerText })),
    board: lab('.board .card3d.is-up'), pot: num(q('.pot-value')), potSplit: q('.pot-split') ? q('.pot-split').innerText : '',
    status: q('.status') ? q('.status').innerText : '', notice: qa('.notice').map(e => e.innerText).join(' | '),
    buttons: qa('.controls button').filter(b => !b.disabled).map(b => b.innerText.trim()),
    hand: q('.hand-label') ? q('.hand-label').innerText : '',
  };
}"""


class Player:
    def __init__(self, browser, name):
        self.name = name
        self.ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        self.page = self.ctx.new_page()
        self.errors, self.action_requests = [], 0
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.on("request", lambda r: setattr(self, "action_requests", self.action_requests + (r.url.endswith("/action") and r.method == "POST")))
        self.code = None

    def sign_in(self):
        self.page.goto(URL)
        self.page.get_by_label("닉네임").fill(self.name)
        self.page.get_by_role("button", name="입장").click()
        self.page.get_by_role("button", name=re.compile("^새 방 만들기")).wait_for()

    @property
    def token(self):
        return self.page.evaluate("JSON.parse(localStorage.getItem('jungle-poker-lab.guest.v1')).guest_token")

    def screen(self):
        return self.page.evaluate(SCREEN_JS)

    def server(self):
        return get(f"/api/rooms/{self.code}/state?after=0", self.token)["state"]

    def click(self, prefix):
        self.page.locator(".controls button:not([disabled])", has_text=re.compile("^" + prefix)).first.click()


def mismatch(sc, st):
    problems = []
    you, cap = st["you"]["seat"], st["capacity"]
    want = {(you + i) % cap: w for i, w in enumerate(SPOTS[cap])}
    got = {s["seat"]: s["where"] for s in sc["seats"]}
    if got != want: problems.append(("layout", got, want))
    for s in sc["seats"]:
        srv = st["seats"][s["seat"]]
        if srv["occupied"] and s["stack"] != srv["stack"]: problems.append(("stack", s["seat"], s["stack"], srv["stack"]))
        if s["turn"] != (st["phase"] == "playing" and st["turnSeat"] == s["seat"]): problems.append(("turn", s["seat"], s["turn"]))
        if srv["cards"]:
            if s["up"] != srv["cards"]: problems.append(("cards", s["seat"], s["up"], srv["cards"]))
        elif st["phase"] != "lobby" and st["street"] and srv["inHand"] and (s["up"] or s["down"] != 2):
            problems.append(("hidden", s["seat"], s["up"], s["down"]))
        if srv["folded"] and s["badge"] != "폴드": problems.append(("fold badge", s["seat"], s["badge"]))
        if srv["allIn"] and not srv["folded"] and s["badge"] != "올인": problems.append(("all-in badge", s["seat"], s["badge"]))
    if st["phase"] != "lobby":
        if sc["pot"] != st["pot"]: problems.append(("pot", sc["pot"], st["pot"]))
        if sc["board"] != st["board"]: problems.append(("board", sc["board"], st["board"]))
        if len(st["pots"]) > 1 and not sc["potSplit"].startswith("메인"): problems.append(("pots", sc["potSplit"], st["pots"]))
    return problems


def synced(p, label, timeout=15):
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        st = p.server(); sc = p.screen()
        last = (mismatch(sc, st), sc, st)
        if not last[0]:
            return st, sc
        p.page.wait_for_timeout(250)
    check(f"{p.name}: screen equals server ({label})", False, last[0])
    return last[2], last[1]


def all_synced(players, label):
    out = [synced(p, label) for p in players]
    check(f"all {len(players)} screens equal their server state ({label})", True)
    return out


def owner(players, st):
    for p in players:
        if p.seat == st["turnSeat"]:
            return p


def play_hand(players, choose, label, max_steps=40):
    for step in range(max_steps):
        st = players[0].server()
        if st["phase"] != "playing":
            return st
        p = owner(players, st)
        synced(p, f"{label} step {step}")
        p.page.locator(".controls button:not([disabled])").first.wait_for()
        choice = choose(p, p.screen()["buttons"], st, step)
        if isinstance(choice, tuple):
            p.page.locator(".wager-number").fill(str(choice[1]))
            p.click(choice[0])
        else:
            p.click(choice)
        p.page.wait_for_timeout(150)
    raise AssertionError("hand did not end")


def first(buttons, *prefixes):
    for prefix in prefixes:
        if any(b.startswith(prefix) for b in buttons):
            return prefix
    raise AssertionError((buttons, prefixes))


def ready_all(players, hand_no):
    for p in players:
        if any(b.startswith("다음 판 준비") for b in p.screen()["buttons"]):
            p.click("다음 판 준비")
    players[0].page.locator(".hand-label", has_text=f"HAND {hand_no + 1}").wait_for(timeout=15000)


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])
        A, B, C, D = players = [Player(browser, n) for n in ("Alpha", "Bravo", "Carol", "Delta")]
        for p in players:
            p.sign_in()
        check("four independent guests", len({p.token for p in players}) == 4)
        A.page.get_by_role("button", name="4인").click()
        A.page.get_by_role("button", name=re.compile("^새 방 만들기")).click()
        A.page.locator(".big-code").wait_for()
        code = A.page.locator(".big-code").inner_text().strip()
        for p in players:
            p.code = code
        for p in (B, C, D):
            p.page.get_by_label("방 코드").fill(code)
            p.page.locator(".preview").wait_for()
            check(f"{p.name}: public preview shows capacity", "/4명" in p.page.locator(".preview").inner_text(), p.page.locator(".preview").inner_text())
            p.page.get_by_role("button", name="코드로 참가").click()
            p.page.locator(".big-code").wait_for()
        for p in players:
            p.seat = p.server()["you"]["seat"]
        check("seats 0..3 in join order", [p.seat for p in players] == [0, 1, 2, 3], [p.seat for p in players])
        all_synced(players, "lobby with four")
        check("host sees the start button, others do not",
              any(b.startswith("준비한 사람끼리") for b in A.page.locator(".controls button").all_inner_texts())
              and not any(b.startswith("준비한 사람끼리") for b in B.page.locator(".controls button").all_inner_texts()))
        A.page.screenshot(path=f"{SHOTS}/01_lobby_A.png")
        for p in players:
            p.page.get_by_role("button", name="준비", exact=True).click()
        A.page.locator(".hand-label", has_text="HAND 1").wait_for()
        for i, p in enumerate(players):
            st, sc = synced(p, "hand 1 dealt")
            p.page.screenshot(path=f"{SHOTS}/02_hand1_{p.name}.png")
        check("button 0, SB 1, BB 2, UTG 3 acts first", (st["seats"][0]["isButton"], st["seats"][1]["isSmallBlind"], st["seats"][2]["isBigBlind"], st["turnSeat"]) == (True, True, True, 3))

        # hand 1: everyone calls/checks to a 4-way showdown
        st = play_hand(players, lambda p, b, st, i: first(b, "체크", "콜"), "hand 1")
        for p in players:
            st, sc = synced(p, "hand 1 showdown")
        check("hand 1: showdown reveals all four hands to everyone", all(all(s["up"] for s in p.screen()["seats"]) for p in players))
        check("hand 1: result line names the pot", "팟" in A.screen()["status"] or "메인" in A.screen()["status"], A.screen()["status"])
        A.page.screenshot(path=f"{SHOTS}/03_hand1_showdown_A.png")
        ready_all(players, 1)

        # hand 2: first actor raises to 100, seats with odd index fold, the rest call, then checks
        def h2(p, b, st, i):
            if i == 0: return ("레이즈", 100)
            if st["street"] == "preflop" and p.seat % 2 == 1 and "폴드" in [x[:2] for x in b]: return "폴드"
            return first(b, "체크", "콜")
        st = play_hand(players, h2, "hand 2")
        for p in players:
            synced(p, "hand 2 end")
        folded_seen = [s for s in C.screen()["seats"] if s["badge"] == "폴드"]
        check("hand 2: folded hands stay hidden for others", all(not s["up"] for s in folded_seen if s["seat"] != C.seat), folded_seen)
        # cash-out from the UI between hands: Delta leaves with its chips, cannot sit again; the other three continue
        st = A.server()
        leaver = D
        chips = st["seats"][leaver.seat]["stack"]
        leaver.click("칩 정산하고 나가기")
        leaver.page.get_by_role("button", name=re.compile("^새 방 만들기")).wait_for()
        check("cash-out shows the amount", f"{chips:,}" in leaver.page.locator(".notice").inner_text(), leaver.page.locator(".notice").inner_text())
        players = [A, B, C]
        st, sc = synced(A, "after cash-out")
        check("others see the seat freed", not st["seats"][leaver.seat]["occupied"] and next(s for s in sc["seats"] if s["seat"] == leaver.seat)["stack"] is None)
        leaver.page.get_by_label("방 코드").fill(code)
        leaver.page.get_by_role("button", name="코드로 참가").click()
        leaver.page.locator(".notice", has_text="다시 앉을 수 없습니다").wait_for(timeout=5000)
        check("no re-seat after cash-out in the same match", "다시 앉을 수 없습니다" in leaver.page.locator(".notice").inner_text(), leaver.page.locator(".notice").inner_text())
        A.page.screenshot(path=f"{SHOTS}/035_after_cashout_A.png")
        ready_all(players, 2)

        # hand 3: a server 4xx (stale version) must not lock the controls; then everybody all-in
        st = players[0].server()
        p = owner(players, st)
        synced(p, "hand 3 before stale")
        def stale(route):
            body = json.loads(route.request.post_data); body["expected_version"] = 1
            route.continue_(post_data=json.dumps(body))
        p.page.route("**/action", stale, times=1)
        p.click(first(p.screen()["buttons"], "콜", "체크"))
        p.page.locator(".notice").first.wait_for(timeout=5000)
        p.page.wait_for_timeout(400)
        sc = p.screen()
        check("stale action 4xx: notice shown, no retry lock, actions still enabled",
              sc["notice"] and not any(b.startswith("같은 요청") for b in sc["buttons"]) and any(b.startswith(("콜", "체크", "폴드")) for b in sc["buttons"]), sc)
        check("stale action changed nothing", p.server()["gameVersion"] == st["gameVersion"])
        before = p.action_requests
        st = play_hand(players, lambda p, b, st, i: first(b, "올인", "콜", "체크"), "hand 3 all-in")
        check("after the 4xx the same player acted normally", p.action_requests > before)
        for q in players:
            st, sc = synced(q, "hand 3 end")
        res = st["result"]
        check("hand 3: chips conserved on screen", sum(s["stack"] or 0 for s in A.screen()["seats"]) == 4000 - chips, A.screen()["seats"])
        if len(res["pots"]) > 1:
            check("hand 3: side pots listed in the result line", "사이드1" in A.screen()["status"], A.screen()["status"])
        A.page.screenshot(path=f"{SHOTS}/04_hand3_result_A.png")
        A.page.get_by_role("button", name="2D로 보기").click(); A.page.wait_for_timeout(700)
        A.page.screenshot(path=f"{SHOTS}/05_hand3_result_A_2d.png")
        A.page.get_by_role("button", name="3D로 보기").click()
        print("hand 3 pots:", [(p_["amount"], p_["eligible"], p_["winners"]) for p_ in res["pots"]], "stacks:", [s["stack"] for s in st["seats"]], flush=True)

        # after the all-in hand: busted seats are marked, the match ends when one player has chips left
        busted = [q for q in players if st["seats"][q.seat]["stack"] == 0]
        check("busted seats show 칩 없음", all(next(s for s in A.screen()["seats"] if s["seat"] == q.seat)["badge"] == "칩 없음" for q in busted), A.screen()["seats"])
        if final_phase := A.server()["phase"]:
            if final_phase == "match_over":
                check("match over is announced", "매치 종료" in A.page.locator(".controls").inner_text(), A.page.locator(".controls").inner_text())
            elif final_phase == "hand_over":
                live = [q for q in players if st["seats"][q.seat]["stack"] > 0]
                ready_all(live, 3)
                st = play_hand(live, lambda p, b, st, i: first(b, "체크", "콜"), "hand 4 heads-up after busts")
                for q in players:
                    synced(q, "hand 4 end")
                check("hand 4: busted player was not dealt in", all(not A.server()["seats"][q.seat]["inHand"] for q in busted))
        # stored ledger vs profiles vs screens
        rows = [json.loads(line)["row"] for line in open(os.path.join(data, "room_hand_results.rows"), encoding="utf-8")]
        seat_rows = [json.loads(line)["row"] for line in open(os.path.join(data, "room_seat_events.rows"), encoding="utf-8")]
        check("ledger: hands 1..N stored once", [r["hand_no"] for r in rows] == list(range(1, len(rows) + 1)), [r["hand_no"] for r in rows])
        buy = sum(r["amount"] for r in seat_rows if r["kind"] == "buyin"); out = sum(r["amount"] for r in seat_rows if r["kind"] != "buyin")
        final = A.server()
        check("table chips == buy-ins - cash-outs", sum(s["stack"] for s in final["seats"] if s["occupied"]) == buy - out, (buy, out, [s["stack"] for s in final["seats"]]))
        for q in (A, B, C, D):
            nets = []
            for r in rows:
                for part in json.loads(r["participants"]):
                    if part["seat"] == q.seat:
                        nets.append(part["end"] - part["start"])
            prof = get("/api/profile", q.token)["profile"]["online"]
            check(f"{q.name}: profile equals the ledger", (prof["hands"], prof["wins"], prof["losses"], prof["draws"])
                  == (len(nets), sum(n > 0 for n in nets), sum(n < 0 for n in nets), sum(n == 0 for n in nets)), (prof, nets))
        for q in (A, B, C, D):
            real = [e for e in q.errors if not any(s in e for s in ("Failed to load resource", "409", "Failed to fetch"))]
            check(f"{q.name}: no script errors in console", not real, real[:3])
        browser.close()
finally:
    for name, proc in procs.items():
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
    json.dump({"results": results, "ports": {"dbms": DB, "redis": RD, "api": API, "static": STATIC}, "data": data},
              open(os.path.join(SHOTS, "e2e4_results.json"), "w"), ensure_ascii=False, indent=1)
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; servers stopped: {sorted(procs)}")
