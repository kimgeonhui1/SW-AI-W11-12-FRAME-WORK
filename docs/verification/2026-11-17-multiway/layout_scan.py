"""Layout scan after merging feat/poker-ui 2a2108c: overlap and clipping at desktop/375px x 3D/2D, 2 and 4 seats.

Checks per screen: every name tag inside the table area (D1), key text not covered by another element
(sampled with elementFromPoint at 5 points), bet badges not overlapping board cards, the action log covering
nothing on the table. Bets are on the table while scanning (a raise and calls preflop, then a flop bet).
(the server set-up below is shared with e2e_room4.py)


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



LAYOUT_JS = """() => {
  // .seat has pointer-events:none; hit-testing must see the seat's pieces (same trick as e2e_room2.py HUD_JS)
  const st = document.createElement('style'); st.textContent = '*{pointer-events:auto !important}'; document.head.append(st);
  const arena = document.querySelector('.arena').getBoundingClientRect();
  const rect = (e) => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const visible = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return { ok: false, by: 'zero-size' };
    const pts = [[.5, .5], [.2, .5], [.8, .5], [.5, .25], [.5, .75]];
    for (const [fx, fy] of pts) {
      const x = r.left + r.width * fx, y = r.top + r.height * fy;
      if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return { ok: false, by: 'off-screen' };
      const top = document.elementFromPoint(x, y);
      if (!top || !(e === top || e.contains(top) || top.contains(e))) return { ok: false, by: top ? (top.className || top.tagName) : 'none', at: [fx, fy] };
    }
    return { ok: true };
  };
  const out = { problems: [] };
  for (const seat of document.querySelectorAll('.table > .seat:not(.is-empty)')) {
    const where = [...seat.classList].find(c => /^seat-(bottom|top|left|right)$/.test(c));
    const hud = seat.querySelector('.hud');
    const r = hud.getBoundingClientRect();
    if (r.left < arena.left - 1 || r.right > arena.right + 1 || r.top < arena.top - 1 || r.bottom > arena.bottom + 1)
      out.problems.push({ kind: 'hud-clipped', where, rect: rect(hud).map(Math.round), arena: rect(document.querySelector('.arena')).map(Math.round) });
    for (const sel of ['.hud-name', '.hud-stack', '.hud-act', '.bet-chip span', '.hud-pos']) {
      const e = seat.querySelector(sel);
      if (!e) continue;
      const v = visible(e);
      if (!v.ok) out.problems.push({ kind: 'covered', where, sel, by: v.by, at: v.at });
    }
  }
  for (const sel of ['.board .card3d.is-up', '.seat-bottom .seat-cards .card3d', '.pot-value']) {
    for (const e of document.querySelectorAll(sel)) { const v = visible(e); if (!v.ok) out.problems.push({ kind: 'covered', sel, by: v.by, at: v.at }); }
  }
  const board = [...document.querySelectorAll('.board .card3d')].map(rect);
  for (const chip of document.querySelectorAll('.bet-chip')) {
    const c = rect(chip);
    for (const b of board) if (c[0] < b[2] - 1 && c[2] > b[0] + 1 && c[1] < b[3] - 1 && c[3] > b[1] + 1)
      out.problems.push({ kind: 'bet-over-board', where: [...chip.parentNode.classList].join(' '), chip: c.map(Math.round), card: b.map(Math.round) });
  }
  out.badges = document.querySelectorAll('.bet-chip').length;
  out.tags = document.querySelectorAll('.hud-act').length;
  out.scrollX = document.documentElement.scrollWidth > innerWidth;
  if (out.scrollX) out.problems.push({ kind: 'horizontal-scroll' });
  st.remove();
  return out;
}"""

report = {}


def scan(p, label):
    for width, height in ((1280, 900), (375, 820)):
        p.page.set_viewport_size({"width": width, "height": height})
        for view in ("3d", "2d"):
            want = "2D로 보기" if view == "2d" else "3D로 보기"
            btn = p.page.get_by_role("button", name=want)
            if btn.count():
                btn.click()
            p.page.wait_for_timeout(900)
            res = p.page.evaluate(LAYOUT_JS)
            key = f"{label} · {width}px · {view.upper()}"
            report[key] = res
            p.page.screenshot(path=f"{SHOTS}/layout_{label}_{width}_{view}.png".replace(" ", "_"))
            d1 = [x for x in res["problems"] if x["kind"] == "hud-clipped" or (x["kind"] == "covered" and x["sel"] in (".hud-name", ".hud-stack"))]
            other = [x for x in res["problems"] if x not in d1]
            check(f"{key}: no overlap/cover (badges {res['badges']}, tags {res['tags']})", not other, other)
            check(f"{key}: name tags fully visible (D1)", not d1, d1)
    p.page.set_viewport_size({"width": 1280, "height": 900})
    p.page.get_by_role("button", name="3D로 보기").click() if p.page.get_by_role("button", name="3D로 보기").count() else None


def setup(players, seats):
    A = players[0]
    A.page.get_by_role("button", name=f"{seats}인").click()
    A.page.get_by_role("button", name=re.compile("^새 방 만들기")).click()
    A.page.locator(".big-code").wait_for()
    code = A.page.locator(".big-code").inner_text().strip()
    for p in players:
        p.code = code
    for p in players[1:]:
        p.page.get_by_label("방 코드").fill(code)
        p.page.get_by_role("button", name="코드로 참가").click()
        p.page.locator(".big-code").wait_for()
    for p in players:
        p.seat = p.server()["you"]["seat"]
        p.page.get_by_role("button", name="준비", exact=True).click()
    A.page.locator(".hand-label", has_text="HAND 1").wait_for()


def act_until(players, steps):
    """steps: list of button prefixes (or ('레이즈 총', amount)) for the seats in turn order."""
    for choice in steps:
        st = players[0].server()
        p = owner(players, st)
        synced(p, "layout step")
        p.page.locator(".controls button:not([disabled])").first.wait_for()
        if isinstance(choice, tuple):
            p.page.locator(".wager-number").fill(str(choice[1])); p.click(choice[0])
        else:
            p.click(first(p.screen()["buttons"], *choice.split("|")))
        p.page.wait_for_timeout(250)
    for p in players:
        synced(p, "layout settled")


try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])
        # 4 seats: preflop raise + calls (badges for everyone), then a flop bet + call (badges, tags, board)
        four = [Player(browser, n_) for n_ in ("Alpha", "Bravo", "Carol", "Delta")]
        for p in four: p.sign_in()
        setup(four, 4)
        act_until(four, [("레이즈 총", 80), "콜", "콜", "콜"])
        for p in four: scan(p, f"4인 {p.name} preflop")
        act_until(four, ["체크|베팅", ("베팅 총", 60)][:1])
        st = four[0].server()
        if st["phase"] == "playing" and st["street"] == "flop":
            act_until(four, [("베팅 총", 60)] if any(b.startswith("베팅") for b in owner(four, st).screen()["buttons"]) else ["콜|체크"])
        scan(four[0], "4인 Alpha flop")
        # 2 seats (준우's original layout): blinds + a raise
        two = [Player(browser, n_) for n_ in ("Echo", "Foxtrot")]
        for p in two: p.sign_in()
        setup(two, 2)
        act_until(two, [("레이즈 총", 60)])
        for p in two: scan(p, f"2인 {p.name} preflop")
        act_until(two, ["콜"])
        scan(two[0], "2인 Echo flop")
        browser.close()
finally:
    for name, proc in procs.items():
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
    json.dump({"results": results, "layout": report}, open(os.path.join(SHOTS, "layout_results.json"), "w"), ensure_ascii=False, indent=1)
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; servers stopped: {sorted(procs)}")
