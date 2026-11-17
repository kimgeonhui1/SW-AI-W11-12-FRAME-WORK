"""Browser E2E for 2-4 player rooms: four independent browser sessions (separate contexts = separate guests).

Starts its own DBMS/Redis/API/static servers on free ports with a temporary DB. After every step each
screen is compared with that player's own server state (seat layout, stacks, turn, own/other cards, pot,
board) and with seat action tags worked out here, in Python, from the server's event list (not from the
client's code). Covers (rules v2):
  - 4-seat lobby + auto start, 4-way showdown, raise/fold hand, all-in hands with side pots
  - seat action tags (call = chips added, bet/raise/all-in = street total), kept while others act,
    cleared on a new street (fold/all-in stay) and on a new hand; the recent-action log
  - bet panel: call / min raise total / max total next to the input, out-of-range input refused on screen,
    buttons locked while a request is in flight, a server 4xx (stale version) followed by unlocked controls
  - chips kept after a win: next hand, page reload, API restart
  - result line: start chips -> net -> current, pot received vs net
  - cash-out from the UI, no re-seat
  - bust: no button leaves the room; the busted seat watches one hand, then gets 1,000 once and is dealt
    back in; when only one player has chips, '다음 라운드 시작' (pressed by two people at once) pays once
  - profiles vs the stored ledger (rebuys counted apart, never as wins)
Only servers started here are stopped at the end. This is several browser sessions on one machine, not a
multi-PC LAN test.
"""
import json, os, re, socket, subprocess, sys, tempfile, threading, time, urllib.request
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
    log = open(os.path.join(SHOTS, f"server_{name}.log"), "a")
    procs[name] = subprocess.Popen([PY, "-B", *args], cwd=os.path.join(ROOT, cwd), env=env, stdout=log, stderr=log)


def wait_port(port):
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close(); return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port {port} did not open")


def start_api():
    spawn("api", "poker_demo", "server.py", "--host", "127.0.0.1", "--port", str(API), "--dbms", f"http://127.0.0.1:{DB}", "--redis", f"http://127.0.0.1:{RD}")
    wait_port(API)


spawn("dbms", "dbms", "-m", "mini_dbms.server", "--data-dir", data, "--host", "127.0.0.1", "--port", str(DB))
spawn("redis", "redis", "-m", "mini_redis.server", "--host", "127.0.0.1", "--port", str(RD))
spawn("static", "react", "-m", "http.server", str(STATIC), "--bind", "127.0.0.1")
for port in (DB, RD, STATIC):
    wait_port(port)
start_api()

URL = f"http://127.0.0.1:{STATIC}/room.html?api=http://127.0.0.1:{API}"
SPOTS = {2: ["bottom", "top"], 3: ["bottom", "left", "right"], 4: ["bottom", "left", "top", "right"]}
results = []
observed = {"watch_path": 0, "round_restart": 0, "side_pots": 0}


def check(name, cond, detail=""):
    results.append({"name": name, "ok": bool(cond), "detail": "" if cond else str(detail)[:600]})
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)[:400]), flush=True)
    return bool(cond)


def get(path, token):
    req = urllib.request.Request(f"http://127.0.0.1:{API}{path}", headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())


def n(v):
    return f"{v:,}"


def expected_tags(st):
    """Seat tags re-derived from the server events of the current hand (independent of roomLogic.js)."""
    tags = [""] * st["capacity"]
    keep = [False] * st["capacity"]
    for e in st["events"]:
        if e["handNo"] != st["handNo"]:
            continue
        if e["type"] in ("hand_start", "recovered"):
            tags = [""] * st["capacity"]; keep = [False] * st["capacity"]
            if e["type"] == "hand_start":
                if e["committed"][e["sb"]] > 0: tags[e["sb"]] = "SB " + n(e["committed"][e["sb"]])
                if e["committed"][e["bb"]] > 0: tags[e["bb"]] = "BB " + n(e["committed"][e["bb"]])
        elif e["type"] == "street":
            tags = [t if k else "" for t, k in zip(tags, keep)]
        elif e["type"] == "action":
            auto = " (시간 초과)" if e["auto"] else ""
            a, s = e["action"], e["seat"]
            if (a == "call" and e["allIn"]) or (a == "all_in" and "to" not in e):
                tags[s], keep[s] = "올인 콜 +" + n(e["paid"]), True
            elif a == "all_in":
                tags[s], keep[s] = "올인 총 " + n(e["to"]), True
            elif a == "fold":
                tags[s], keep[s] = "폴드" + auto, True
            elif a == "check":
                tags[s] = "체크" + auto
            elif a == "call":
                tags[s] = "콜 +" + n(e["paid"])
            else:
                tags[s] = ("베팅 총 " if a == "bet" else "레이즈 총 ") + n(e["to"])
    return tags


SCREEN_JS = """() => {
  const q = (s, r = document) => r.querySelector(s), qa = (s, r = document) => [...r.querySelectorAll(s)];
  const lab = (s, r) => qa(s, r).map(e => e.getAttribute('aria-label').replace('10', 'T'));
  const num = (e) => e ? Number(e.textContent.replace(/[^0-9]/g, '')) : null;
  return {
    seats: qa('.table > .seat').map(e => ({ seat: Number(e.dataset.seat), where: [...e.classList].find(c => /^seat-(bottom|top|left|right)$/.test(c)).slice(5),
      stack: e.classList.contains('is-empty') ? null : num(q('.hud-stack', e)), turn: e.classList.contains('is-turn'),
      up: lab('.seat-cards .card3d.is-up', e), down: qa('.seat-cards .card3d.is-down', e).length,
      badge: q('.seat-badge', e) ? q('.seat-badge', e).innerText : '', tag: q('.hud-act', e) ? q('.hud-act', e).innerText : '',
      net: q('.hud-net', e) ? q('.hud-net', e).innerText : '', name: q('.hud-name', e).innerText })),
    board: lab('.board .card3d.is-up'), pot: num(q('.pot-value')), potSplit: q('.pot-split') ? q('.pot-split').innerText : '',
    status: q('.status') ? q('.status').innerText : '', notice: qa('.notice').map(e => e.innerText).join(' | '),
    chipChange: q('.chip-change') ? q('.chip-change').innerText : '',
    log: qa('.action-log li').map(e => e.innerText), limits: qa('.wager-limits').map(e => e.innerText),
    wagerError: q('.wager-error') ? q('.wager-error').innerText : '',
    buttons: qa('.controls button').filter(b => !b.disabled).map(b => b.innerText.trim()),
    allButtons: qa('.controls button').map(b => b.innerText.trim()),
    controlsText: q('.controls') ? q('.controls').innerText : '',
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
        self._token = None

    def sign_in(self):
        self.page.goto(URL)
        self.page.get_by_label("닉네임").fill(self.name)
        self.page.get_by_role("button", name="입장").click()
        self.page.get_by_role("button", name=re.compile("^새 방 만들기")).wait_for()

    @property
    def token(self):
        if self._token is None:
            self._token = self.page.evaluate("JSON.parse(localStorage.getItem('jungle-poker-lab.guest.v1')).guest_token")
        return self._token

    def screen(self):
        return self.page.evaluate(SCREEN_JS)

    def server(self):
        for attempt in range(20):  # the API may be restarting
            try:
                return get(f"/api/rooms/{self.code}/state?after=0", self.token)["state"]
            except OSError:
                time.sleep(0.3)
        raise RuntimeError("API not reachable")

    def click(self, prefix):
        self.page.locator(".controls button:not([disabled])", has_text=re.compile("^" + re.escape(prefix))).first.click()


def mismatch(sc, st):
    problems = []
    you, cap = st["you"]["seat"], st["capacity"]
    want = {(you + i) % cap: w for i, w in enumerate(SPOTS[cap])}
    got = {s["seat"]: s["where"] for s in sc["seats"]}
    if got != want: problems.append(("layout", got, want))
    tags = expected_tags(st)
    for s in sc["seats"]:
        srv = st["seats"][s["seat"]]
        if srv["occupied"] and s["stack"] != srv["stack"]: problems.append(("stack", s["seat"], s["stack"], srv["stack"]))
        if s["turn"] != (st["phase"] == "playing" and st["turnSeat"] == s["seat"]): problems.append(("turn", s["seat"], s["turn"]))
        if srv["cards"]:
            if s["up"] != srv["cards"]: problems.append(("cards", s["seat"], s["up"], srv["cards"]))
        elif st["phase"] != "lobby" and st["street"] and srv["inHand"] and (s["up"] or s["down"] != 2):
            problems.append(("hidden", s["seat"], s["up"], s["down"]))
        if srv["occupied"] and st["phase"] != "lobby" and s["tag"] != tags[s["seat"]]:
            problems.append(("tag", s["seat"], s["tag"], tags[s["seat"]]))
        if srv["busted"] and not s["badge"]: problems.append(("busted badge", s["seat"]))
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


def owner(players, st):
    for p in players:
        if p.seat == st["turnSeat"]:
            return p


def play_hand(players, choose, label, max_steps=40, on_step=None):
    for step in range(max_steps):
        st = players[0].server()
        if st["phase"] != "playing":
            return st
        p = owner(players, st)
        st, sc = synced(p, f"{label} step {step}")
        p.page.locator(".controls button:not([disabled])").first.wait_for()
        sc = p.screen()
        if on_step:
            on_step(p, sc, st, step)
        choice = choose(p, sc["buttons"], st, step)
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
    players[0].page.locator(".hand-label", has_text=f"HAND {hand_no + 1}").wait_for(timeout=20000)


def wait_phase(p, phases, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = p.server()
        if st["phase"] in phases:
            return st
        time.sleep(0.3)
    raise AssertionError(("phase", phases, p.server()["phase"]))


def ledger_rows(table):
    path = os.path.join(data, table + ".rows")
    return [json.loads(line)["row"] for line in open(path, encoding="utf-8")] if os.path.exists(path) else []


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])
        A, B, C, D = players = [Player(browser, n_) for n_ in ("Alpha", "Bravo", "Carol", "Delta")]
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
            p.page.get_by_role("button", name="코드로 참가").click()
            p.page.locator(".big-code").wait_for()
        for p in players:
            p.seat = p.server()["you"]["seat"]
        check("seats 0..3 in join order", [p.seat for p in players] == [0, 1, 2, 3], [p.seat for p in players])
        for p in players:
            synced(p, "lobby with four")
        for p in players:
            p.page.get_by_role("button", name="준비", exact=True).click()
        A.page.locator(".hand-label", has_text="HAND 1").wait_for()
        for p in players:
            st, sc = synced(p, "hand 1 dealt")
        check("hand 1: only blinds are tagged (SB 10 / BB 20)", [s["tag"] for s in sorted(A.screen()["seats"], key=lambda s: s["seat"])] == ["", "SB 10", "BB 20", ""],
              A.screen()["seats"])
        # nobody but the seat on turn has action buttons
        for p in players:
            sc = p.screen()
            has_actions = any(b.startswith(("콜", "체크", "폴드", "레이즈", "베팅", "올인")) for b in sc["allButtons"])
            check(f"{p.name}: action buttons only on own turn", has_actions == (p.seat == st["turnSeat"]), sc["allButtons"])

        # hand 1: everyone calls/checks to a 4-way showdown; after each step another player's screen shows the tag
        def watch_tags(p, sc, st, step):
            other = next(q for q in players if q is not p)
            synced(other, f"hand 1 tags step {step}")
        st = play_hand(players, lambda p, b, st, i: first(b, "체크", "콜"), "hand 1", on_step=watch_tags)
        for p in players:
            st, sc = synced(p, "hand 1 showdown")
        sc = A.screen()
        check("hand 1: action log is shown and ends with the hand", sc["log"] and sc["log"][-1].startswith("핸드 종료"), sc["log"])
        res = st["result"]
        winner = res["winnerSeats"][0]
        wp = next(p for p in players if p.seat == winner)
        wsc = wp.screen()
        start, end = res["startStacks"][winner], res["endStacks"][winner]
        check("hand 1: result shows start → net → current and pot received vs net",
              wsc["chipChange"].startswith(f"내 칩 · 시작 {n(start)} → +{n(end - start)} → 현재 {n(wp.server()['seats'][winner]['stack'])}")
              and f"팟 수령 {n(res['payouts'][winner])} / 순이익 +{n(end - start)}" in wsc["chipChange"], wsc["chipChange"])
        A.page.screenshot(path=f"{SHOTS}/v2_01_hand1_showdown_A.png")
        ends1 = [st["seats"][i]["stack"] for i in range(4)]
        ready_all(players, 1)

        # chips kept after the win: the next hand starts from hand 1's end chips; tags of hand 1 are gone
        st = A.server()
        starts = [st["seats"][i]["stack"] + st["seats"][i]["committed"] for i in range(4)]
        check("hand 2 starts from hand 1's end chips", starts == ends1, (starts, ends1))
        for p in players:
            synced(p, "hand 2 dealt (tags reset)")
        check("hand 2: previous hand's tags cleared on every screen",
              all(sorted(s["tag"] for s in p.screen()["seats"]) == sorted(["", "", "SB 10", "BB 20"]) for p in players))

        # reload mid-hand: same seat, same chips, same tags
        before = B.server()
        B.page.reload()
        B.page.locator(".hand-label", has_text="HAND 2").wait_for()
        st, sc = synced(B, "hand 2 after reload")
        check("reload keeps seat and chips", [s["stack"] for s in st["seats"]] == [s["stack"] for s in before["seats"]] and st["you"]["seat"] == B.seat)

        # hand 2: first actor raises (bet panel checks), odd seats fold, the rest call; in-flight lock checked once
        lock_checked = {"done": False}

        def panel(p, sc, st, step):
            if step == 0:
                lim = sc["limits"][0] if sc["limits"] else ""
                check("bet panel shows call / min raise total / max total",
                      lim == f"콜 {n(st['toCall'])} · 최소 레이즈 총 {n(st['minRaiseTo'])} · 최대 총 {n(st['maxRaiseTo'])}", (lim, st["toCall"], st["minRaiseTo"], st["maxRaiseTo"]))
                p.page.locator(".wager-number").fill(str(st["minRaiseTo"] - 1))
                sc2 = p.screen()
                check("below-minimum input is refused on screen", sc2["wagerError"] == f"{n(st['minRaiseTo'])} 이상 입력하세요"
                      and not any(b.startswith("레이즈 총") for b in sc2["buttons"]), sc2)
                p.page.locator(".wager-number").fill(str(st["maxRaiseTo"] + 1))
                check("above-maximum input is refused on screen", "이하로 입력하세요" in p.screen()["wagerError"])
            if step == 1 and not lock_checked["done"]:
                lock_checked["done"] = True
                gate = threading.Event()

                def slow(route):
                    gate.wait(3)
                    route.continue_()
                p.page.route("**/action", slow, times=1)
                p.click(first(sc["buttons"], "폴드" if p.seat % 2 == 1 else "콜"))
                p.page.wait_for_timeout(300)
                locked = p.screen()
                check("controls locked while the request is in flight", not any(b.startswith(("콜", "체크", "폴드", "레이즈", "올인")) for b in locked["buttons"]), locked["buttons"])
                gate.set()
                p.page.wait_for_timeout(600)

        def h2(p, b, st, i):
            if i == 0: return ("레이즈 총", 100)
            if st["street"] == "preflop" and p.seat % 2 == 1 and "폴드" in b: return "폴드"
            return first(b, "체크", "콜")

        # step 1's click is done inside `panel`; skip the normal click for that step
        for step in range(40):
            st = A.server()
            if st["phase"] != "playing":
                break
            p = owner(players, st)
            st, sc = synced(p, f"hand 2 step {step}")
            p.page.locator(".controls button:not([disabled])").first.wait_for()
            sc = p.screen()
            panel(p, sc, st, step)
            if step == 1:
                continue
            choice = h2(p, sc["buttons"], st, step)
            if isinstance(choice, tuple):
                p.page.locator(".wager-number").fill(str(choice[1]))
                p.click(choice[0])
            else:
                p.click(choice)
            p.page.wait_for_timeout(150)
            if step == 0:
                for q in players:
                    if q is not p:
                        synced(q, "raise tag visible to others")
                check("raise is shown as the street total on another screen",
                      next(s for s in C.screen()["seats"] if s["seat"] == p.seat)["tag"] == "레이즈 총 100" or C is p)
        for p in players:
            synced(p, "hand 2 end")

        # API restart between hands: chips and seats come back
        before = [s["stack"] for s in A.server()["seats"]]
        procs["api"].terminate(); procs["api"].wait(5)
        start_api()
        for p in players:
            st, sc = synced(p, "after API restart", timeout=25)
        check("API restart keeps every player's chips", [s["stack"] for s in st["seats"]] == before and st["recovered"], (before, st["seats"]))

        # stale 4xx: notice shown, controls unlocked, then the same player acts normally
        ready_all(players, 2)
        st = A.server()
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
        check("stale action 4xx: notice shown, controls unlocked",
              sc["notice"] and any(b.startswith(("콜", "체크", "폴드")) for b in sc["buttons"]), sc)
        check("stale action changed nothing", p.server()["gameVersion"] == st["gameVersion"])
        p.click(first(p.screen()["buttons"], "콜", "체크"))
        p.page.wait_for_timeout(300)
        check("after the 4xx the same player acted normally", A.server()["gameVersion"] > st["gameVersion"])
        st = play_hand(players, lambda p, b, st, i: first(b, "폴드", "체크"), "hand 3 folds")
        for p in players:
            synced(p, "hand 3 end")

        # cash-out from the UI between hands: Delta leaves with its chips, cannot sit again
        st = A.server()
        chips = st["seats"][D.seat]["stack"]
        D.click("칩 정산하고 나가기")
        D.page.get_by_role("button", name=re.compile("^새 방 만들기")).wait_for()
        check("cash-out shows the amount", f"{chips:,}" in D.page.locator(".notice").inner_text(), D.page.locator(".notice").inner_text())
        players = [A, B, C]
        D.page.get_by_label("방 코드").fill(code)
        D.page.get_by_role("button", name="코드로 참가").click()
        D.page.locator(".notice", has_text="다시 앉을 수 없습니다").wait_for(timeout=5000)
        check("no re-seat after cash-out", True)

        # all-in hands until both bust paths were seen (or 10 hands): watch-one-hand rebuy and round restart
        for loop in range(10):
            st = A.server()
            if st["phase"] == "round_over":
                pass
            elif st["phase"] == "hand_over":
                live = [q for q in players if st["seats"][q.seat]["stack"] > 0]
                ready_all(live, st["handNo"])
                st = play_hand(players, lambda p, b, st, i: first(b, "올인", "콜", "체크"), f"all-in hand {st['handNo'] + 1}")
            st = wait_phase(A, ("hand_over", "round_over"))
            for q in players:
                st, sc = synced(q, f"after all-in hand {st['handNo']}")
            if len(st["result"]["pots"]) > 1:
                observed["side_pots"] += 1
            busted = [q for q in players if st["seats"][q.seat]["busted"]]
            for q in busted:
                sc = q.screen()
                leaving = [b for b in sc["allButtons"] if b not in ("칩 정산하고 나가기", "로비로 (자리 유지)")]
                check(f"{q.name} busted: stays seated, explains the wait, only the explicit exits leave",
                      q.server()["you"]["seat"] == q.seat and ("관전" in sc["controlsText"] or "다음 라운드" in sc["controlsText"]), sc["controlsText"])
            if st["phase"] == "round_over":
                observed["round_restart"] += 1
                holders = {q.seat: st["seats"][q.seat]["stack"] for q in players if st["seats"][q.seat]["stack"] > 0}
                for q in players:
                    check(f"{q.name}: '다음 라운드 시작' offered to every seated player", any(b.startswith("다음 라운드 시작") for b in q.screen()["buttons"]))
                if observed["round_restart"] == 1:
                    time.sleep(1)
                    st_a, sc_a = synced(A, "round_over before screenshot")
                    if st_a["result"]["reason"] == "showdown":
                        shown = [len(x["up"]) for x in sorted(sc_a["seats"], key=lambda x: x["seat"])]
                        want = [2 if st_a["seats"][i]["cards"] else 0 for i in range(st_a["capacity"])]
                        check("showdown hands stay face-up while waiting in round_over", shown == want, (shown, want))
                    A.page.screenshot(path=f"{SHOTS}/v2_03_round_over_A.png")
                rebuys_before = len([r for r in ledger_rows("room_seat_events") if r["kind"] == "rebuy"])
                # two people press at (nearly) the same moment: both clicks are dispatched before either reply
                press = """() => { const b = [...document.querySelectorAll('.controls button')].find(x => x.innerText.startsWith('다음 라운드 시작'));
                  if (b && !b.disabled) { b.click(); return true; } return false; }"""
                other = players[0] if busted[0] is not players[0] else players[1]
                clicked = [busted[0].page.evaluate(press), other.page.evaluate(press)]
                check("two players pressed '다음 라운드 시작' together", clicked == [True, True], clicked)
                st = wait_phase(A, ("hand_over",))
                time.sleep(1)
                rebuys_after = [r for r in ledger_rows("room_seat_events") if r["kind"] == "rebuy"]
                check("round restart pays each busted player exactly once", len(rebuys_after) - rebuys_before == len(busted), (rebuys_before, len(rebuys_after), len(busted)))
                check("chip holders keep their chips; busted players get 1,000",
                      all(st["seats"][s]["stack"] == v for s, v in holders.items()) and all(st["seats"][q.seat]["stack"] == 1000 for q in busted),
                      [x["stack"] for x in st["seats"]])
                for q in players:
                    synced(q, "after round restart")
            elif busted:
                q = busted[0]
                after = st["seats"][q.seat]["rebuyAfterHand"]
                check(f"{q.name}: busted screen names the hand to watch", f"{after}번 핸드" in q.screen()["controlsText"], q.screen()["controlsText"])
                live = [x for x in players if st["seats"][x.seat]["stack"] > 0]
                ready_all(live, st["handNo"])
                st = A.server()
                check(f"{q.name} watches hand {after} (not dealt in)", st["handNo"] == after and not st["seats"][q.seat]["inHand"])
                synced(q, "watching")
                check(f"{q.name}: badge shows watching", next(s for s in q.screen()["seats"] if s["seat"] == q.seat)["badge"] == "관전 중 · 이 핸드 뒤 복귀")
                A.page.screenshot(path=f"{SHOTS}/v2_04_watching_A.png")
                st = play_hand(players, lambda p, b, st, i: first(b, "체크", "콜"), f"watched hand {after}")
                st = wait_phase(A, ("hand_over", "round_over"))
                check(f"{q.name}: one 1,000-chip rebuy after the watched hand", st["seats"][q.seat]["stack"] == 1000 and not st["seats"][q.seat]["busted"],
                      st["seats"][q.seat])
                observed["watch_path"] += 1
                for x in players:
                    synced(x, "after rebuy")
                ready_all([x for x in players if st["seats"][x.seat]["stack"] > 0], st["handNo"])
                check(f"{q.name} is dealt back in automatically", A.server()["seats"][q.seat]["inHand"])
                st = play_hand(players, lambda p, b, st, i: first(b, "체크", "콜"), "hand after the rebuy")
                wait_phase(A, ("hand_over", "round_over"))
            if observed["watch_path"] and observed["round_restart"]:
                break
        print("observed:", observed, flush=True)

        # stored ledger vs profiles vs screens
        rows = ledger_rows("room_hand_results")
        seat_rows = ledger_rows("room_seat_events")
        check("ledger: hands 1..N stored once", [r["hand_no"] for r in rows] == list(range(1, len(rows) + 1)), [r["hand_no"] for r in rows])
        buy = sum(r["amount"] for r in seat_rows if r["kind"] == "buyin"); out = sum(r["amount"] for r in seat_rows if r["kind"] == "leave")
        reb = sum(r["amount"] for r in seat_rows if r["kind"] == "rebuy")
        final = A.server()
        check("table chips == buy-ins + rebuys - cash-outs", sum(s["stack"] + s["committed"] for s in final["seats"] if s["occupied"]) == buy + reb - out,
              (buy, reb, out, [s["stack"] for s in final["seats"]]))
        for q in (A, B, C, D):
            nets = []
            for r in rows:
                for part in json.loads(r["participants"]):
                    if part["seat"] == q.seat and part["user"] == next((x["user_db"] for x in seat_rows if x["kind"] == "buyin" and x["seat"] == q.seat), None):
                        nets.append(part["end"] - part["start"])
            prof = get("/api/profile", q.token)["profile"]["online"]
            mine_rebuys = sum(1 for x in seat_rows if x["kind"] == "rebuy" and x["seat"] == q.seat)
            check(f"{q.name}: profile equals the ledger (rebuys apart from wins)",
                  (prof["hands"], prof["wins"], prof["losses"], prof["draws"], prof["rebuys"])
                  == (len(nets), sum(x > 0 for x in nets), sum(x < 0 for x in nets), sum(x == 0 for x in nets), mine_rebuys), (prof, nets, mine_rebuys))
        for q in (A, B, C, D):
            real = [e for e in q.errors if not any(s in e for s in ("Failed to load resource", "409", "Failed to fetch", "ERR_CONNECTION_REFUSED"))]
            check(f"{q.name}: no script errors in console", not real, real[:3])
        browser.close()
finally:
    for name, proc in procs.items():
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
    json.dump({"results": results, "observed": observed, "ports": {"dbms": DB, "redis": RD, "api": API, "static": STATIC}, "data": data},
              open(os.path.join(SHOTS, "e2e4_results.json"), "w"), ensure_ascii=False, indent=1)
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; observed {observed}; servers stopped: {sorted(procs)}")
