"""JUNGLE POKER LAB test bots: fill a room with 1-3 bots so one person can test multiplayer alone.

TEST ONLY. Bots are ordinary guests: they register with POST /api/guest and then use exactly the
public room API a browser uses (join, state, ready, action, next-round, leave). They never touch server
memory or files and never see anyone else's hole cards (the server does not send them).

  python poker_test_bots.py --room ABC234 [--bots 3] [--mode basic|allin] [--seed 42]
                            [--api http://127.0.0.1:18784] [--log bots.log] [--hands N] [--minutes M]

Behaviour
  - acts only when the server says it is the bot's turn, only with an action the server lists in
    legalActions and an amount inside [minRaiseTo, maxRaiseTo]; waits 1-2 s first so people can read
    the action on screen; one request per game version (no double actions)
  - basic mode: mostly check/call, sometimes fold or a legal raise
  - allin mode: goes all-in whenever that is legal (to test bust -> watch one hand -> 1,000 rebuy)
  - follows the room rules: readies in the lobby and between hands, waits while busted (the server
    deals it back in), presses '다음 라운드 시작' after a few seconds when the room waits in round_over
  - stopping (Ctrl+C, --hands, --minutes): a bot in a running hand keeps playing until the hand ends,
    then leaves normally (cash-out); in the lobby it just leaves. Gives up after --exit-timeout seconds.
  - every decision, amount, server answer and error is logged with a timestamp
Only the Python standard library is used.
"""
import argparse
import base64
import json
import os
import random
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

MODES = ("basic", "allin")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class Log:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.file = open(path, "a", encoding="utf-8") if path else None

    def __call__(self, who, message):
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}.{int(time.time() * 1000) % 1000:03d} [{who}] {message}"
        with self.lock:
            try:
                print(line, flush=True)
            except UnicodeEncodeError:  # old console code page: keep running, the file has the exact text
                print(line.encode("ascii", "replace").decode("ascii"), flush=True)
            if self.file:
                self.file.write(line + "\n")
                self.file.flush()


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"{status} {body.get('error')}")
        self.status = status
        self.body = body


class Client:
    def __init__(self, api, token=None):
        self.api = api.rstrip("/")
        self.token = token

    def call(self, path, body=None, timeout=12):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.api + path, data=data, method="POST" if body is not None else "GET")
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except ValueError:
                payload = {"error": "http_" + str(error.code)}
            raise ApiError(error.code, payload) from None


class Bot(threading.Thread):
    def __init__(self, index, args, log, stop):
        super().__init__(name=f"TEST BOT {index}", daemon=True)
        self.index = index
        self.args = args
        self.log = log
        self.stop = stop
        self.rng = random.Random(f"{args.seed}:{index}")  # same seed -> same choices for the same states
        token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")  # like the browser
        self.client = Client(args.api, token)
        self.code = args.room
        self.seat = None
        self.acted_version = None  # one action per game version
        self.readied = None  # (phase, handNo) already answered with ready
        self.round_seen_at = None
        self.left = False
        self.was_busted = False
        self.counts = {"actions": 0, "errors": 0, "stale": 0, "rebuys": 0}

    def say(self, message):
        self.log(self.name, message)

    # ── requests ──────────────────────────────────────────────────────────
    def post(self, path, body, what):
        try:
            result = self.client.call(path, body)
            return 200, result
        except ApiError as error:
            kind = error.body.get("error")
            expected = kind in ("stale_state", "not_your_turn", "hand_not_active", "not_round_over", "hand_active")
            self.counts["stale" if expected else "errors"] += 1
            self.say(f"{'skip' if expected else 'ERROR'} {what} → {error.status} {kind}: {error.body.get('message', '')}")
            return error.status, error.body
        except OSError as error:
            self.counts["errors"] += 1
            self.say(f"ERROR {what} → network: {error}")
            return None, {}

    def state(self, since=None, wait=5):
        query = "?after=0" if since is None else f"?since={since}&after=999999999999999&wait={wait}"
        return self.client.call(f"/api/rooms/{self.code}/state{query}", timeout=wait + 8)["state"]

    # ── decisions (only from what the server offers) ──────────────────────
    def choose(self, st):
        legal = st["legalActions"]
        low, high = st["minRaiseTo"], st["maxRaiseTo"]
        raise_name = "bet" if "bet" in legal else "raise" if "raise" in legal else None
        r = self.rng.random()
        if self.args.mode == "allin" and "all_in" in legal:
            return "all_in", None, "allin mode"
        if "check" in legal:
            if raise_name and r < 0.15:
                return raise_name, self.amount(low, high), "check spot, small raise"
            return "check", None, "check"
        # facing a bet
        if raise_name and r < 0.10:
            return raise_name, self.amount(low, high), "facing a bet, legal raise"
        if r < 0.22 and "fold" in legal:
            return "fold", None, "occasional fold"
        if "call" in legal:
            return "call", None, "call"
        if "all_in" in legal:  # cannot call without going all-in
            return "all_in", None, "call for less (all-in)"
        return "fold", None, "nothing else legal"

    def amount(self, low, high):
        top = min(high, low * 2)
        return self.rng.randint(low, max(low, top))

    # ── main loop ─────────────────────────────────────────────────────────
    def run(self):
        try:
            self._run()
        except Exception as error:  # a bot must never take the others down
            self.counts["errors"] += 1
            self.say(f"ERROR stopped: {type(error).__name__}: {error}")

    def _run(self):
        try:
            self.client.call("/api/guest", {"guest_token": self.client.token, "display_name": self.name})
        except (ApiError, OSError) as error:
            self.say(f"ERROR guest sign-in failed: {error}")
            return
        status, result = self.post(f"/api/rooms/{self.code}/join", {}, "join")
        if status != 200:
            self.say("could not take a seat; stopping")
            return
        st = result["state"]
        self.seat = st["you"]["seat"]
        self.say(f"seated at {self.seat} in room {self.code} (capacity {st['capacity']}, phase {st['phase']})")
        version = None
        stop_since = None
        while True:
            try:
                st = self.state(version)
            except ApiError as error:
                if error.status in (403, 404):
                    self.say(f"room or seat is gone ({error.body.get('error')}); stopping")
                    return
                self.say(f"ERROR state → {error.status} {error.body.get('error')}")
                time.sleep(1)
                continue
            except OSError as error:
                self.say(f"ERROR state → network: {error}")
                time.sleep(2)
                continue
            version = st["version"]
            if self.stop.is_set():
                stop_since = stop_since or time.monotonic()
                if self.try_leave(st):
                    return
                if time.monotonic() - stop_since > self.args.exit_timeout:
                    self.say("exit timeout: stopping without leaving (the server keeps the seat; timeouts apply)")
                    return
            self.step(st)

    def me(self, st):
        return st["seats"][st["you"]["seat"]]

    def step(self, st):
        me = self.me(st)
        phase = st["phase"]
        if me["busted"] and not self.was_busted:
            self.was_busted = True
            self.say(f"busted in hand {me['bustHand']}: " + ("waiting for 다음 라운드 시작" if phase == "round_over"
                     else f"watching hand {me['rebuyAfterHand']}, then the server pays 1,000 and deals me back in"))
        elif self.was_busted and not me["busted"] and me["stack"] + me["committed"] > 0:
            self.was_busted = False
            self.counts["rebuys"] += 1
            self.say(f"received the 1,000 rebuy; back in (stack {me['stack']:,})")
        if phase == "lobby":
            if not me["ready"] and not self.stop.is_set() and self.readied != ("lobby", 0):
                self.readied = ("lobby", 0)
                self.post(f"/api/rooms/{self.code}/ready", {"ready": True, "hand_no": 0}, "ready (lobby)")
        elif phase == "hand_over":
            if me["busted"]:
                return
            if not me["ready"] and not self.stop.is_set() and st["recordStatus"] != "unknown" and self.readied != ("hand", st["handNo"]):
                time.sleep(self.rng.uniform(0.5, 1.5))
                self.readied = ("hand", st["handNo"])
                self.post(f"/api/rooms/{self.code}/ready", {"ready": True, "hand_no": st["handNo"]}, f"ready for hand {st['handNo'] + 1}")
        elif phase == "round_over":
            if st["canNextRound"] and self.args.next_round_delay >= 0 and not self.stop.is_set():
                key = ("round", st["handNo"])
                if self.round_seen_at is None or self.round_seen_at[0] != key:
                    self.round_seen_at = (key, time.monotonic())
                    self.say(f"round_over after hand {st['handNo']}: will press '다음 라운드 시작' in {self.args.next_round_delay:.0f}s unless someone else does")
                elif time.monotonic() - self.round_seen_at[1] >= self.args.next_round_delay:
                    self.round_seen_at = (("done", st["handNo"]), time.monotonic())
                    status, _ = self.post(f"/api/rooms/{self.code}/next-round", {"hand_no": st["handNo"]}, "next-round")
                    if status == 200:
                        self.say(f"pressed 다음 라운드 시작 after hand {st['handNo']} → 200")
                else:
                    time.sleep(0.5)
        elif phase == "playing":
            if not me["inHand"] and not me["busted"] and not me["sittingIn"] and not self.stop.is_set() \
                    and self.readied != ("sit", st["handNo"]):
                self.readied = ("sit", st["handNo"])
                self.post(f"/api/rooms/{self.code}/ready", {"ready": True, "hand_no": st["handNo"]}, "sit in from the next hand")
            if st["turnSeat"] == st["you"]["seat"] and st["legalActions"] and st["gameVersion"] != self.acted_version:
                self.act(st)

    def act(self, st):
        time.sleep(self.rng.uniform(self.args.min_delay, self.args.max_delay))  # let people read the table
        fresh = self.state()  # decide on the latest state: the turn may have timed out meanwhile
        if fresh["turnSeat"] != fresh["you"]["seat"] or not fresh["legalActions"] or fresh["gameVersion"] == self.acted_version:
            return
        action, to, why = self.choose(fresh)
        self.acted_version = fresh["gameVersion"]
        body = {"action_id": str(uuid.uuid4()), "expected_version": fresh["gameVersion"], "action": action}
        if to is not None:
            body["to"] = to
        detail = f"hand {fresh['handNo']} {fresh['street']} · {action}" + (f" to {to}" if to is not None else "")
        limits = f"toCall {fresh['toCall']}, raise {fresh['minRaiseTo']}..{fresh['maxRaiseTo']}, legal {','.join(fresh['legalActions'])}"
        status, result = self.post(f"/api/rooms/{self.code}/action", body, detail)
        if status == 200:
            self.counts["actions"] += 1
            self.say(f"{detail} ({why}; {limits}) → 200")

    def try_leave(self, st):
        """Leave at the first moment the rules allow it. Returns True when the bot is done."""
        if self.left:
            return True
        me = self.me(st)
        if st["phase"] == "playing" and me["inHand"] and not me["folded"]:
            self.say("stopping: finishing the current hand first")
            if st["turnSeat"] == st["you"]["seat"] and st["gameVersion"] != self.acted_version:
                self.act(st)
            return False
        status, result = self.post(f"/api/rooms/{self.code}/leave", {}, "leave")
        if status == 200:
            self.left = True
            cash = result.get("cashOut")
            self.say("left the room" + (f" with {cash:,} chips (cash-out recorded)" if cash is not None else " (lobby seat freed)"))
            return True
        if status in (409, 503, None):  # in a hand or a record is being confirmed: try again shortly
            time.sleep(1)
            return False
        return True


def main(argv=None):
    parser = argparse.ArgumentParser(description="JUNGLE POKER LAB test bots (test only)")
    parser.add_argument("--room", required=True, help="room code (6 letters)")
    parser.add_argument("--bots", type=int, default=3, help="1-3")
    parser.add_argument("--mode", choices=MODES, default="basic")
    parser.add_argument("--seed", default=None, help="random seed (default: random, printed)")
    parser.add_argument("--api", default="http://127.0.0.1:18784")
    parser.add_argument("--log", default=None, help="also append the log to this file")
    parser.add_argument("--hands", type=int, default=0, help="stop after this many hands in the room (0 = no limit)")
    parser.add_argument("--minutes", type=float, default=0, help="stop after this many minutes (0 = no limit)")
    parser.add_argument("--min-delay", type=float, default=1.0)
    parser.add_argument("--max-delay", type=float, default=2.0)
    parser.add_argument("--next-round-delay", type=float, default=4.0, help="seconds before a bot presses 다음 라운드 시작 (-1 = never)")
    parser.add_argument("--exit-timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    args.room = args.room.strip().upper()
    if len(args.room) != 6 or any(ch not in CODE_ALPHABET for ch in args.room):
        parser.error("room code must be 6 letters/digits as shown on screen")
    if not 1 <= args.bots <= 3:
        parser.error("--bots must be 1-3")
    if not 0 <= args.min_delay <= args.max_delay:
        parser.error("delays must satisfy 0 <= min <= max")
    if args.seed is None:
        args.seed = str(random.SystemRandom().randrange(10 ** 6))
    log = Log(args.log)
    log("RUN", f"room {args.room} · bots {args.bots} · mode {args.mode} · seed {args.seed} · api {args.api} · pid {os.getpid()}")
    stop = threading.Event()
    bots = [Bot(i, args, log, stop) for i in range(1, args.bots + 1)]
    for bot in bots:
        bot.start()
        time.sleep(0.3)  # join one by one so seats fill in a stable order
    started = time.monotonic()
    try:
        while any(bot.is_alive() for bot in bots):
            time.sleep(0.5)
            if args.minutes and time.monotonic() - started > args.minutes * 60 and not stop.is_set():
                log("RUN", "time limit reached: stopping (bots finish their hand, then leave)")
                stop.set()
            if args.hands and not stop.is_set():
                try:
                    st = bots[0].client.call(f"/api/rooms/{args.room}/state?after=999999999999999") ["state"] if bots[0].seat is not None else None
                except (ApiError, OSError):
                    st = None
                if st and st["handNo"] >= args.hands and st["phase"] != "playing":
                    log("RUN", f"{args.hands} hands played: stopping")
                    stop.set()
    except KeyboardInterrupt:
        log("RUN", "Ctrl+C: stopping (bots finish their hand, then leave). Press Ctrl+C again to quit at once.")
        stop.set()
        try:
            while any(bot.is_alive() for bot in bots):
                time.sleep(0.5)
        except KeyboardInterrupt:
            log("RUN", "second Ctrl+C: quitting now (seats stay; the server's turn timeouts apply)")
    summary = ", ".join(f"{b.name}: {b.counts['actions']} actions, {b.counts['rebuys']} rebuys, {b.counts['errors']} errors, {b.counts['stale']} stale" for b in bots)
    log("RUN", "done · " + summary)
    return 1 if any(b.counts["errors"] for b in bots) else 0


if __name__ == "__main__":
    sys.exit(main())
