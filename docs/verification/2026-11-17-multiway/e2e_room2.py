"""Browser E2E (2 players) from the 6e117d0 verification, adapted 2026-11-17: picks "2인" on create, reads room_hand_results.

Starts its own DBMS/Redis/API/static servers on free ports with a temporary DB, compares both
screens with the server state after every step, and checks the UI-specific risks:
click during replay, 2D/3D and bloom toggles, tab freeze/return, resize, double click,
offline action + retry (no permanent lock), previous-hand residue, card suit occlusion and
HUD clipping at 375 px. Only servers started here are stopped at the end.
"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request
from playwright.sync_api import sync_playwright

ROOT = sys.argv[1]
SHOTS = sys.argv[2]
os.makedirs(SHOTS, exist_ok=True)
PY = sys.executable


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


DB, RD, API, STATIC = (free_port() for _ in range(4))
data = tempfile.mkdtemp(prefix="jpl-e2e-db-")
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
results = []
findings = []


def check(name, cond, detail=""):
    results.append({"name": name, "ok": bool(cond), "detail": "" if cond else str(detail)[:600]})
    print(("ok   " if cond else "FAIL ") + name + ("" if cond else "  " + str(detail)[:300]), flush=True)
    return bool(cond)


def server_state(token, code):
    req = urllib.request.Request(f"http://127.0.0.1:{API}/api/rooms/{code}/state?after=0", headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())["state"]


SCREEN_JS = """() => {
  const q = (s) => document.querySelector(s), qa = (s) => [...document.querySelectorAll(s)];
  const num = (s) => { const e = q(s); return e ? Number(e.textContent.replace(/[^0-9]/g, '')) : null; };
  const lab = (s) => qa(s).map(e => e.getAttribute('aria-label').replace('10', 'T'));
  const turn = q('.seat-bottom.is-turn') ? 'bottom' : q('.seat-top.is-turn') ? 'top' : null;
  const controls = q('.controls');
  return {
    board: lab('.board .card3d.is-up'), pot: num('.pot-value'),
    bottom: num('.seat-bottom .hud-stack'), top: num('.seat-top .hud-stack'), turn,
    mine: lab('.seat-bottom .card3d.is-up'), oppUp: lab('.seat-top .card3d.is-up'), oppDown: qa('.seat-top .card3d.is-down').length,
    status: q('.status') ? q('.status').innerText : '', hand: q('.hand-label') ? q('.hand-label').innerText : '',
    buttons: controls ? qa('.controls button').filter(b => !b.disabled).map(b => b.innerText.trim()) : [],
    controlsText: controls ? controls.innerText : '', fly: qa('.fly').length, winner: qa('.is-winner').length,
    hudLast: qa('.hud-last').map(e => e.innerText), arena: q('.arena') ? q('.arena').className : '',
    overflowX: document.documentElement.scrollWidth > innerWidth,
  };
}"""

# Visibility of rank/suit on every face-up card: the topmost element at the glyph centre must be
# inside the same card (all pointer-events enabled only for this measurement), and the glyph must
# lie inside the card face and the viewport.
SUIT_JS = """() => {
  const st = document.createElement('style'); st.textContent = '*{pointer-events:auto !important}'; document.head.append(st);
  const out = [...document.querySelectorAll('.card3d.is-up')].map(c => {
    const face = c.querySelector('.card-face'); const fr = face.getBoundingClientRect();
    const probe = (el) => { const r = el.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const hit = document.elementFromPoint(x, y);
      return { hitOwn: !!hit && c.contains(hit), hit: hit ? (hit.className || hit.tagName) + '' : null,
        inside: r.left >= fr.left - 1 && r.right <= fr.right + 1 && r.top >= fr.top - 1 && r.bottom <= fr.bottom + 1,
        inView: r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight, w: Math.round(r.width), h: Math.round(r.height) }; };
    const where = c.closest('.seat-top') ? 'top' : c.closest('.seat-bottom') ? 'bottom' : 'board';
    return { label: c.getAttribute('aria-label'), where, rank: probe(face.querySelector('b')), suit: probe(face.querySelector('span')) };
  });
  st.remove(); return out;
}"""

HUD_JS = """() => {
  const st = document.createElement('style'); st.textContent = '*{pointer-events:auto !important}'; document.head.append(st);
  const a = document.querySelector('.arena').getBoundingClientRect();
  const out = [...document.querySelectorAll('.hud')].map(h => {
    const r = h.getBoundingClientRect(); const where = h.closest('.seat-top') ? 'top' : 'bottom';
    const parts = ['.hud-name', '.hud-stack', '.presence', '.hud-pos', '.turn-clock'].map(s => h.querySelector(s)).filter(Boolean).map(el => {
      const e = el.getBoundingClientRect(); const hit = document.elementFromPoint(e.left + e.width / 2, e.top + e.height / 2);
      return { sel: el.className, visible: !!hit && h.contains(hit), truncated: el.scrollWidth > el.clientWidth + 1,
        inArena: e.left >= a.left - 1 && e.right <= a.right + 1 && e.top >= a.top - 1 && e.bottom <= a.bottom + 1,
        inView: e.left >= 0 && e.right <= innerWidth, by: hit ? (hit.className || hit.tagName) + '' : null };
    });
    return { where, rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)],
      inArena: r.left >= a.left - 1 && r.right <= a.right + 1 && r.top >= a.top - 1 && r.bottom <= a.bottom + 1, parts };
  });
  st.remove(); return { arena: [Math.round(a.left), Math.round(a.top), Math.round(a.right), Math.round(a.bottom)], width: innerWidth, huds: out };
}"""


class Player:
    def __init__(self, browser, name, viewport):
        self.name = name
        self.ctx = browser.new_context(viewport=viewport)
        self.page = self.ctx.new_page()
        self.errors, self.action_requests = [], 0
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        self.page.on("request", self._on_request)
        self.code = None

    def _on_request(self, r):
        if r.url.endswith("/action") and r.method == "POST":
            self.action_requests += 1

    def sign_in(self):
        self.page.goto(URL)
        self.page.get_by_label("닉네임").fill(self.name)
        self.page.get_by_role("button", name="입장").click()
        self.page.get_by_role("button", name="새 방 만들기").wait_for()

    @property
    def token(self):
        return self.page.evaluate("JSON.parse(localStorage.getItem('jungle-poker-lab.guest.v1')).guest_token")

    def screen(self):
        return self.page.evaluate(SCREEN_JS)

    def server(self):
        return server_state(self.token, self.code)

    def click(self, prefix):
        self.page.locator(".controls button:not([disabled])", has_text=re.compile("^" + prefix)).first.click()


def mismatch(p, sc, st):
    you, other = st["you"]["seat"], 1 - st["you"]["seat"]
    problems = []
    if st["phase"] != "lobby":
        if sc["pot"] != st["pot"]: problems.append(("pot", sc["pot"], st["pot"]))
        if sc["board"] != st["board"]: problems.append(("board", sc["board"], st["board"]))
    if sc["bottom"] != st["seats"][you]["stack"]: problems.append(("my stack", sc["bottom"], st["seats"][you]["stack"]))
    if st["seats"][other]["occupied"] and sc["top"] != st["seats"][other]["stack"]: problems.append(("opp stack", sc["top"], st["seats"][other]["stack"]))
    want_turn = None if st["phase"] != "playing" else ("bottom" if st["turnSeat"] == you else "top")
    if sc["turn"] != want_turn: problems.append(("turn", sc["turn"], want_turn))
    if st["phase"] != "lobby" and sc["mine"] != (st["seats"][you]["cards"] or []): problems.append(("my cards", sc["mine"], st["seats"][you]["cards"]))
    opp = st["seats"][other]["cards"]
    if opp and sc["oppUp"] != opp: problems.append(("opp cards", sc["oppUp"], opp))
    if not opp and st["phase"] in ("playing", "hand_over", "match_over") and st["street"] and (sc["oppUp"] or sc["oppDown"] != 2):
        problems.append(("opp hidden", sc["oppUp"], sc["oppDown"]))
    if st["result"] and st["phase"] in ("hand_over", "match_over"):
        w = st["result"]["winnerSeat"]
        word = "무승부" if w is None else ("승리" if w == you else "패배")
        if word not in sc["status"]: problems.append(("result", sc["status"], word))
    return problems


def synced(p, label, timeout=12):
    """Wait until the screen equals the server state, then record one comparison."""
    end = time.time() + timeout
    while True:
        st, sc = p.server(), p.screen()
        bad = mismatch(p, sc, st)
        if not bad and "재생하는 중" not in sc["controlsText"]:
            break
        if time.time() > end:
            break
        p.page.wait_for_timeout(250)
    check(f"{p.name} screen == server ({label})", not bad, bad)
    return sc, st


def both(a, b, label):
    sa, ta = synced(a, label)
    sb, tb = synced(b, label)
    check(f"both screens agree ({label})", (sa["pot"], sa["board"], sa["bottom"], sa["top"]) == (sb["pot"], sb["board"], sb["top"], sb["bottom"]),
          (sa["pot"], sa["board"], sa["bottom"], sa["top"], sb["pot"], sb["board"], sb["top"], sb["bottom"]))
    check(f"chips conserved on screen ({label})", sa["bottom"] + sa["top"] + (sa["pot"] or 0) == 2000, (sa["bottom"], sa["top"], sa["pot"]))
    return ta


def actor(a, b):
    st = a.server()
    if st["phase"] != "playing":
        return None, None
    return (a, b) if st["turnSeat"] == st["you"]["seat"] else (b, a)


def suits(p, label):
    cards = p.page.evaluate(SUIT_JS)
    # Geometry only: glyphs inside the card face and the viewport. Occlusion by other elements is checked
    # with the pixel comparison tool (tools/pixel_occlusion.py); hit-testing is unreliable here because
    # seats use pointer-events:none and 3D hit order can differ from paint order.
    bad = [c for c in cards if not (c["rank"]["inside"] and c["suit"]["inside"] and c["suit"]["inView"] and c["rank"]["inView"])]
    check(f"{p.name}: rank and suit inside every face-up card and on screen ({label}, {len(cards)} cards)", not bad, bad[:4])
    if bad:
        findings.append({"kind": "card", "who": p.name, "label": label, "cards": bad})
    return cards


def huds(p, label):
    info = p.page.evaluate(HUD_JS)
    bad = []
    for h in info["huds"]:
        if not h["inArena"]:
            bad.append({"where": h["where"], "rect": h["rect"], "arena": info["arena"]})
        for part in h["parts"]:
            if not (part["visible"] and part["inArena"] and part["inView"]) or part["truncated"]:
                bad.append({"where": h["where"], **part})
    check(f"{p.name}: HUD fully visible inside the table ({label}, width {info['width']})", not bad, bad[:4])
    if bad:
        findings.append({"kind": "hud", "who": p.name, "label": label, "issues": bad, "arena": info["arena"]})


def play_hand(a, b, plan, label):
    """plan(names, st) -> button prefix (and optional wager). Plays until the hand ends."""
    for _ in range(30):
        st = a.server()
        if st["phase"] != "playing":
            return st
        p, _ = actor(a, b)
        synced(p, f"{label} before action", timeout=10)
        names = p.screen()["buttons"]
        choice = plan(names, p.server())
        if isinstance(choice, tuple):
            p.page.locator(".wager-number").fill(str(choice[1]))
            p.click(choice[0])
        else:
            p.click(choice)
        p.page.wait_for_timeout(300)
    raise RuntimeError("hand did not end")


passive = lambda names, st: next(x for x in ("체크", "콜") if any(n.startswith(x) for n in names))

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])
        A = Player(browser, "Alpha", {"width": 1280, "height": 900})
        B = Player(browser, "Bravo", {"width": 375, "height": 812})
        A.sign_in(); B.sign_in()
        A.page.get_by_role("button", name="2인").click()
        A.page.get_by_role("button", name="새 방 만들기").click()
        A.page.locator(".big-code").wait_for()
        code = A.page.locator(".big-code").inner_text().strip()
        A.code = B.code = code
        B.page.get_by_label("방 코드").fill(code)
        B.page.get_by_role("button", name="코드로 참가").click()
        B.page.locator(".big-code").wait_for()
        A.page.locator(".seat-top .hud-name", has_text="Bravo").wait_for()
        check("lobby: joiner appears on host screen without reload", True)
        A.page.get_by_role("button", name="준비", exact=True).click()
        B.page.locator(".seat-top .presence", has_text="준비 완료").wait_for()
        B.page.get_by_role("button", name="준비", exact=True).click()
        both(A, B, "hand 1 start")
        sa, sb = A.screen(), B.screen()
        check("hand 1: residue-free start (no flights, no winner glow, no last action)", sa["fly"] == 0 and sa["winner"] == 0 and not sa["hudLast"], sa)
        A.page.screenshot(path=f"{SHOTS}/01_A_desktop_3d_hand1.png"); B.page.screenshot(path=f"{SHOTS}/01_B_mobile375_hand1.png", full_page=True)
        suits(A, "hand 1 own cards 3D desktop"); suits(B, "hand 1 own cards 3D 375")
        huds(A, "hand 1 desktop 3D"); huds(B, "hand 1 375 3D")

        # click during replay: B acts, A must not get clickable actions until its replay ends
        p, o = actor(A, B)  # hand 1: A (seat 0, button) acts first
        before_req = A.action_requests
        p.click("콜")
        seen_buttons_during_replay = []
        for _ in range(8):
            sc = o.screen()
            if "재생하는 중" in sc["controlsText"]:
                seen_buttons_during_replay += [x for x in sc["buttons"] if re.match("^(폴드|체크|콜|레이즈|베팅|올인)", x)]
            o.page.wait_for_timeout(60)
        check("during replay the waiting screen offers no action buttons", not seen_buttons_during_replay, seen_buttons_during_replay)
        # toggle 2D and bloom on B while its replay may still be running, then keep playing
        B.page.get_by_role("button", name="2D로 보기").click()
        B.page.get_by_role("button", name=re.compile("^빛 번짐")).click()
        both(A, B, "after call + toggles")
        check("B view switched to 2D with bloom", "view-2d" in B.screen()["arena"] and "bloom-on" in B.screen()["arena"], B.screen()["arena"])
        B.page.screenshot(path=f"{SHOTS}/02_B_375_2d_bloom.png", full_page=True)
        suits(B, "375 2D bloom"); huds(B, "375 2D")
        st = play_hand(A, B, passive, "hand 1")
        both(A, B, "hand 1 end")
        A.page.wait_for_timeout(600)
        A.page.screenshot(path=f"{SHOTS}/03_A_showdown_3d.png"); B.page.screenshot(path=f"{SHOTS}/03_B_showdown_375_2d.png", full_page=True)
        if st["street"] == "showdown":
            suits(A, "showdown 3D desktop (both hands + board)"); suits(B, "showdown 375 2D (both hands + board)")
        # B back to 3D at 375 and check the showdown table there too
        B.page.get_by_role("button", name="3D로 보기").click(); B.page.wait_for_timeout(700)
        B.page.screenshot(path=f"{SHOTS}/04_B_showdown_375_3d.png", full_page=True)
        if st["street"] == "showdown":
            suits(B, "showdown 375 3D")
        huds(B, "hand end 375 3D")

        # hand 2: raise through the number field, reload mid-hand, resize, freeze/return
        for p in (A, B):
            p.click("다음 판 준비")
        A.page.locator(".hand-label", has_text="HAND 2").wait_for()
        both(A, B, "hand 2 start")
        sa = A.screen()
        check("hand 2: previous hand fully cleared (board, flights, winner, last action)", sa["board"] == [] and sa["fly"] == 0 and sa["winner"] == 0 and not sa["hudLast"], sa)
        p, o = actor(A, B)
        p.page.locator(".wager-number").fill("120")
        p.click("레이즈 120")
        both(A, B, "hand 2 raise 120")
        check("opponent is offered call 100 after raise to 120", any(x.startswith("콜 100") for x in o.screen()["buttons"]), o.screen()["buttons"])
        # resize the desktop player to 375 and back during the hand
        A.page.set_viewport_size({"width": 375, "height": 812}); A.page.wait_for_timeout(600)
        check("A at 375: no horizontal overflow", not A.screen()["overflowX"])
        huds(A, "A resized to 375 mid-hand"); suits(A, "A resized to 375 mid-hand")
        A.page.screenshot(path=f"{SHOTS}/05_A_resized_375.png", full_page=True)
        A.page.set_viewport_size({"width": 1280, "height": 900}); A.page.wait_for_timeout(400)
        # reload B (refresh) mid-hand
        mine = B.screen()["mine"]
        B.page.reload(); B.page.locator(".pot-value").wait_for()
        sb, tb = synced(B, "after refresh")
        check("refresh keeps own seat and cards, opponent hidden", sb["mine"] == mine and sb["oppUp"] == [], (sb["mine"], mine, sb["oppUp"]))
        # freeze A's tab (like a backgrounded/discarded tab) while B acts, then return
        cdp = A.ctx.new_cdp_session(A.page)
        cdp.send("Page.setWebLifecycleState", {"state": "frozen"})
        o_player = B if actor(A, B)[0] is B else None
        if o_player:
            o_player.click("콜")
        time.sleep(10)
        # headless Chrome keeps running a "frozen" page's fetch loop, so this is not a real background tab;
        # only the return path is asserted here (recorded as unverified in the report)
        cdp.send("Page.setWebLifecycleState", {"state": "active"})
        both(A, B, "after tab return")
        A.page.screenshot(path=f"{SHOTS}/06_A_after_tab_return.png")

        # offline action -> retry button -> no permanent lock -> applied once
        p, o = actor(A, B)
        server_before = p.server()
        p.ctx.set_offline(True)
        p.click(next(x for x in ("체크", "콜") if any(n.startswith(x) for n in p.screen()["buttons"])))
        p.page.locator(".btn-retry").wait_for(timeout=8000)
        try:
            o.page.locator(".seat-top .presence", has_text="연결 끊김").wait_for(timeout=15000)
            gone = True
        except Exception:
            gone = False
        check("opponent screen shows the offline player as disconnected", gone)
        check("offline: action not applied on the server", p.server()["gameVersion"] == server_before["gameVersion"])
        p.page.screenshot(path=f"{SHOTS}/07_{p.name}_offline_retry.png", full_page=True)
        p.ctx.set_offline(False)
        p.page.locator(".link-ok").wait_for(timeout=15000)
        req_before = p.action_requests
        p.page.locator(".btn-retry").click()
        p.page.wait_for_timeout(1500)
        after = p.server()
        n_actions = lambda st: len([e for e in st["events"] if e["type"] == "action" and e["handNo"] == st["handNo"]])
        check("retry applied exactly once", n_actions(after) == n_actions(server_before) + 1 or after["handNo"] > server_before["handNo"], (n_actions(server_before), n_actions(after)))
        check("controls usable again after retry (no permanent lock)", p.page.locator(".btn-retry").count() == 0 and (p.screen()["buttons"] != [] ), p.screen()["buttons"])
        st = play_hand(A, B, passive, "hand 2")
        both(A, B, "hand 2 end")

        # hand 3: double click and fold; folded cards never revealed
        for p in (A, B):
            p.click("다음 판 준비")
        A.page.locator(".hand-label", has_text="HAND 3").wait_for()
        both(A, B, "hand 3 start")
        p, o = actor(A, B)
        synced(p, "hand 3 before double click")
        before = p.action_requests
        p.page.locator(".controls button", has_text=re.compile("^콜")).first.dblclick()
        p.page.wait_for_timeout(1200)
        check("double click sends one action request", p.action_requests - before == 1, p.action_requests - before)
        p2, o2 = actor(A, B)
        hidden = p2.screen()["mine"]
        synced(p2, "before fold")
        p2.click("폴드")
        both(A, B, "hand 3 fold")
        check("fold: winner never sees folded cards", o2.screen()["oppUp"] == [], o2.screen()["oppUp"])

        # hands 4-5 quickly, then all-in to finish the match
        for hand in (4, 5):
            for p in (A, B):
                p.click("다음 판 준비")
            A.page.locator(".hand-label", has_text=f"HAND {hand}").wait_for()
            sa = A.screen()
            check(f"hand {hand}: previous hand cleared", sa["board"] == [] and sa["fly"] == 0 and sa["winner"] == 0, sa)
            play_hand(A, B, passive, f"hand {hand}")
            both(A, B, f"hand {hand} end")
        for p in (A, B):
            p.click("다음 판 준비")
        A.page.locator(".hand-label", has_text="HAND 6").wait_for()
        both(A, B, "hand 6 start")
        st = play_hand(A, B, lambda names, st: "올인" if any(n.startswith("올인") for n in names) else next(x for x in ("콜", "체크") if any(n.startswith(x) for n in names)), "hand 6 all-in")
        both(A, B, "hand 6 end")
        A.page.wait_for_timeout(800)
        A.page.screenshot(path=f"{SHOTS}/08_A_final.png"); B.page.screenshot(path=f"{SHOTS}/08_B_final_375.png", full_page=True)
        if A.server()["street"] == "showdown":
            suits(A, "final showdown desktop 3D"); suits(B, "final showdown 375 3D")
        # profile vs ledger
        prof = lambda p: json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{API}/api/profile", headers={"Authorization": "Bearer " + p.token}), timeout=5).read())["profile"]
        pa, pb = prof(A), prof(B)
        rows = [json.loads(line)["row"] for line in open(os.path.join(data, "room_hand_results.rows"), encoding="utf-8")]
        check("ledger: hands 1..N stored once", [r["hand_no"] for r in rows] == list(range(1, len(rows) + 1)), [r["hand_no"] for r in rows])
        for r in rows:
            parts = {x["seat"]: x for x in json.loads(r["participants"])}
            r["end_a"], r["end_b"] = parts[0]["end"], parts[1]["end"]
            net = parts[0]["end"] - parts[0]["start"]
            r["winner"] = "human" if net > 0 else "bot" if net < 0 else "tie"
        wins_a = sum(r["winner"] == "human" for r in rows); wins_b = sum(r["winner"] == "bot" for r in rows); ties = sum(r["winner"] == "tie" for r in rows)
        check("profiles equal the ledger for host and participant",
              (pa["online"]["hands"], pa["online"]["wins"], pa["online"]["losses"], pb["online"]["wins"], pb["online"]["losses"], pa["online"]["draws"])
              == (len(rows), wins_a, wins_b, wins_b, wins_a, ties), (pa["online"], pb["online"], len(rows), wins_a, wins_b, ties))
        last = rows[-1]
        check("final screen stacks equal the last stored hand", (A.screen()["bottom"], A.screen()["top"]) == (last["end_a"], last["end_b"]), (A.screen(), last))
        for p in (A, B):
            real = [e for e in p.errors if not any(s in e for s in ("Failed to load resource", "ERR_INTERNET_DISCONNECTED", "Failed to fetch", "ERR_NETWORK_CHANGED"))]
            check(f"{p.name}: no script errors in console", not real, real[:3])
        browser.close()
finally:
    for name, proc in procs.items():
        proc.terminate()
        try: proc.wait(5)
        except Exception: proc.kill()
    json.dump({"results": results, "findings": findings, "ports": {"dbms": DB, "redis": RD, "api": API, "static": STATIC}, "data": data},
              open(os.path.join(SHOTS, "e2e_results.json"), "w"), ensure_ascii=False, indent=1)
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed; servers stopped: {sorted(procs)}")
