"""Test bots E2E: one browser person + 3 test bots (tools/test-bots/poker_test_bots.py) in a 4-seat room.

Checks: several hands complete; bots act only on their turn (no not_your_turn), never twice for one game
version, only with legal actions/amounts (no 400 illegal_action); all-in mode drives bust -> watch one hand
-> 1,000 rebuy -> back in and/or 다음 라운드 시작; stopping the bots mid-hand lets them finish the hand and
cash out; their seats are freed and chips = buy-ins + rebuys - cash-outs. This is bots + one browser on one
machine, not a multi-PC LAN test. (server set-up shared with e2e_room4.py)
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



BOTS = os.path.join(ROOT, "..", "tools", "test-bots", "poker_test_bots.py")


def run_bots(code, mode, seed, hands, log):
    return subprocess.Popen([PY, "-B", BOTS, "--room", code, "--bots", "3", "--mode", mode, "--seed", str(seed),
                             "--api", f"http://127.0.0.1:{API}", "--log", log, "--hands", str(hands),
                             "--min-delay", "0.4", "--max-delay", "0.8", "--next-round-delay", "3"],
                            stdout=open(log + ".out", "w"), stderr=subprocess.STDOUT)


def human_loop(p, until, timeout=240):
    """The person checks/calls on their turn and readies between hands, until until(state) is true."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = p.server()
        if until(st):
            return st
        me = st["seats"][st["you"]["seat"]]
        sc = p.screen()
        if st["phase"] == "playing" and st["turnSeat"] == p.seat:
            try:
                p.click(first(sc["buttons"], "체크", "콜", "올인", "폴드"))
            except Exception:
                pass
        elif st["phase"] == "hand_over" and not me["ready"] and not me["busted"] and any(b.startswith("다음 판 준비") for b in sc["buttons"]):
            p.click("다음 판 준비")
        time.sleep(0.4)
    raise AssertionError(("timeout", p.server()["phase"], p.server()["handNo"]))


def rows(table):
    path = os.path.join(data, table + ".rows")
    return [json.loads(line)["row"] for line in open(path, encoding="utf-8")] if os.path.exists(path) else []


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])
        H = Player(browser, "Human")
        H.sign_in()
        H.page.get_by_role("button", name="4인").click()
        H.page.get_by_role("button", name=re.compile("^새 방 만들기")).click()
        H.page.locator(".big-code").wait_for()
        code = H.page.locator(".big-code").inner_text().strip()
        H.code = code
        H.seat = 0
        # ── run 1: basic mode, 6 hands ──
        log1 = os.path.join(SHOTS, "bots_basic.log")
        bots = run_bots(code, "basic", 11, 6, log1)
        H.page.locator(".hud-name", has_text="TEST BOT 3").wait_for(timeout=15000)
        H.page.get_by_role("button", name="준비", exact=True).click()
        st = human_loop(H, lambda st: st["handNo"] >= 6 and st["phase"] != "playing")
        synced(H, "after 6 hands with bots")
        H.page.screenshot(path=f"{SHOTS}/bots_basic_table.png")
        bots.wait(180)
        text = open(log1, encoding="utf-8").read()
        check("basic: 6 hands completed with 1 person + 3 bots", st["handNo"] >= 6, st["handNo"])
        check("basic: bots exited by themselves after the hand limit", bots.returncode is not None, bots.returncode)
        check("basic: no bot errors (no illegal action, no 4xx except expected stale)", "ERROR" not in text, [l for l in text.splitlines() if "ERROR" in l][:5])
        check("basic: bots never acted out of turn", "not_your_turn" not in text)
        acted = [l for l in text.splitlines() if l.endswith("→ 200") and " · " in l and "hand " in l]
        check("basic: bots acted many times", len(acted) >= 10, len(acted))
        events = H.server()["events"]
        acts = [e for e in events if e["type"] == "action"]
        check("basic: every action event is unique (no double action)", len({e["seq"] for e in acts}) == len(acts))
        st = H.server()
        check("basic: bots left and their seats are free", [s["occupied"] for s in st["seats"]] == [True, False, False, False], [s["name"] for s in st["seats"]])
        seat_rows = rows("room_seat_events")
        leaves = [r for r in seat_rows if r["kind"] == "leave"]
        check("basic: each bot's cash-out was recorded", len(leaves) == 3, leaves)
        buy = sum(r["amount"] for r in seat_rows if r["kind"] == "buyin"); reb = sum(r["amount"] for r in seat_rows if r["kind"] == "rebuy")
        out = sum(r["amount"] for r in leaves)
        check("basic: chips on the table = buy-ins + rebuys - cash-outs", sum(s["stack"] for s in st["seats"] if s["occupied"]) == buy + reb - out, (buy, reb, out))
        # ── run 2: all-in mode, mid-hand stop (Ctrl+C equivalent) ──
        log2 = os.path.join(SHOTS, "bots_allin.log")
        bots = run_bots(code, "allin", 23, 0, log2)
        H.page.locator(".hud-name", has_text="TEST BOT 3").wait_for(timeout=15000)
        start_hand = H.server()["handNo"]
        st = human_loop(H, lambda st: "received the 1,000 rebuy" in open(log2, encoding="utf-8").read() and st["phase"] == "playing"
                        and st["handNo"] > start_hand + 2, timeout=360)
        text = open(log2, encoding="utf-8").read()
        rebuys = [r for r in rows("room_seat_events") if r["kind"] == "rebuy"]
        check("allin: busts happened and rebuys were paid (each bust once)", len(rebuys) >= 2 and len({(r['user_db'], r['operation_key']) for r in rebuys}) == len(rebuys), len(rebuys))
        bot_rebuys = text.count("received the 1,000 rebuy")
        check("allin: a bot busted, waited and came back with the rebuy (from its own log)", "busted in hand" in text and bot_rebuys >= 1, bot_rebuys)
        H.page.screenshot(path=f"{SHOTS}/bots_allin_table.png")
        # stop while a hand is running: bots must finish it, then leave
        bots.send_signal(2)  # SIGINT = Ctrl+C
        human_loop(H, lambda st: bots.poll() is not None, timeout=180)
        text = open(log2, encoding="utf-8").read()
        check("allin: stop request handled (finish hand, then leave)", "Ctrl+C: stopping" in text and text.count("left the room") == 3, text[-800:])
        check("allin: no bot errors", "ERROR" not in text, [l for l in text.splitlines() if "ERROR" in l][:5])
        check("allin: never out of turn", "not_your_turn" not in text)
        st = H.server()
        check("allin: all bot seats free afterwards", [s["occupied"] for s in st["seats"]] == [True, False, False, False], [s["name"] for s in st["seats"]])
        seat_rows = rows("room_seat_events")
        buy = sum(r["amount"] for r in seat_rows if r["kind"] == "buyin"); reb = sum(r["amount"] for r in seat_rows if r["kind"] == "rebuy")
        out = sum(r["amount"] for r in seat_rows if r["kind"] == "leave")
        check("allin: chips on the table = buy-ins + rebuys - cash-outs", sum(s["stack"] for s in st["seats"] if s["occupied"]) == buy + reb - out, (buy, reb, out))
        check("allin: 6 cash-outs recorded over both runs", len([r for r in seat_rows if r["kind"] == "leave"]) == 6)
        browser.close()
finally:
    for name, proc in procs.items():
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
    json.dump({"results": results}, open(os.path.join(SHOTS, "bots_results.json"), "w"), ensure_ascii=False, indent=1)
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; servers stopped: {sorted(procs)}")
