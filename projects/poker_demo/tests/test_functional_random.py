"""Seeded random state-transition test for two-human rooms (verification of 6e117d0).

10 seeds x 200 steps. A step is one of: a legal action, an invalid request, a duplicate resend,
a stale request, a turn timeout, a storage fault switch, an API restart or a DBMS restart.

Checked after every step (independently of the implementation's own arithmetic):
  chips never negative and stack0 + stack1 + pot == 2000 + stored rebuys (stack = chips in front,
  pot = chips put in this hand; seats[].committed sums to pot; rules v2 pays a busted player one
  1,000-chip rebuy after '다음 라운드 시작'), both views agree on public fields, no card appears
  twice, a player's responses never contain the opponent's hole cards before a showdown, rejected
  requests leave the whole view unchanged, and accepted actions map 1:1 to action events.
At every hand end: the payout is recomputed from the contributions just before the end (pot =
2 x the smaller contribution, the excess is returned) and, at a showdown, the winner is decided by
an evaluator written separately from engine.py.
At the end: the DBMS ledger is an unbroken chain, a confirmed result never changes, and both
players' profiles equal the ledger counted from each player's own seat.

On failure the seed and the step log are written to tests/random_failures/<seed>.json.
"""
from collections import Counter
from functools import partial
from itertools import combinations
import json
import os
import random
import unittest

import test_rooms
import test_server as integration
from engine import PokerEngine
from rooms import match_key_for, replay_ledger
from test_rooms import A, B

RANKS = "23456789TJQKA"
SUITS = "♠♥♦♣"
FULL = [r + s for r in RANKS for s in SUITS]
STEPS = 200
SEEDS = (11, 23, 37, 41, 59, 61, 73, 89, 97, 20261117)


def score5(cards):
    """Independent 5-card score: (category, tiebreak ranks...). Written without looking at engine.py's code path."""
    values = sorted((RANKS.index(c[0]) + 2 for c in cards), reverse=True)
    counts = Counter(values)
    by_count = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    distinct = sorted(set(values), reverse=True)
    straight = 0
    if len(distinct) == 5 and distinct[0] - distinct[4] == 4:
        straight = distinct[0]
    elif distinct == [14, 5, 4, 3, 2]:
        straight = 5
    shape = [count for _, count in by_count]
    ordered = [value for value, _ in by_count]
    if straight and flush:
        return (8, straight)
    if shape == [4, 1]:
        return (7, *ordered)
    if shape == [3, 2]:
        return (6, *ordered)
    if flush:
        return (5, *values)
    if straight:
        return (4, straight)
    if shape == [3, 1, 1]:
        return (3, *ordered)
    if shape == [2, 2, 1]:
        return (2, *ordered)
    if shape == [2, 1, 1, 1]:
        return (1, *ordered)
    return (0, *values)


def best7(cards):
    return max(score5(list(combo)) for combo in combinations(cards, 5))


class RandomRoomTransitions(unittest.TestCase):
    _start = classmethod(integration.PokerHTTPIntegrationTests._start.__func__)
    _install_demo = integration.PokerHTTPIntegrationTests._install_demo
    tearDown = integration.PokerHTTPIntegrationTests.tearDown
    call = test_rooms.RoomTests.call
    new_id = test_rooms.RoomTests.new_id
    state = test_rooms.RoomTests.state
    create_and_join = test_rooms.RoomTests.create_and_join
    ready = test_rooms.RoomTests.ready
    start_match = test_rooms.RoomTests.start_match
    act = test_rooms.RoomTests.act
    ledger = test_rooms.RoomTests.ledger

    def setUp(self):
        self.deck_rng = random.Random(0)
        self.fault = None
        test_rooms.RoomTests.setUp(self)

    def wire_rooms(self):
        test_rooms.RoomTests.wire_rooms(self)
        rng = self.deck_rng
        self.rooms.deck_factory = lambda: rng.sample(FULL, 52)
        original = self.demo._call

        def call(service, method, url, body=None, trace_id=None):
            if self.fault and service == "Mini DBMS" and body and body.get("sql", "").startswith("INSERT INTO room_hand_results"):
                if self.fault == "lost_reply":
                    original(service, method, url, body, trace_id)
                return None, {"traceId": trace_id, "service": service, "method": method, "path": "/sql/insert-once", "outcome": "unavailable"}
            return original(service, method, url, body, trace_id)

        self.demo._call = call

    # ── observation ────────────────────────────────────────────────────────

    def views(self, code):
        # poll both once first so a presence change caused by a clock jump is not seen by only one view
        self.state(A, code)
        self.state(B, code)
        a = self.state(A, code, after=0)
        raw_a = self.last_raw
        b = self.state(B, code, after=0)
        raw_b = self.last_raw
        return a, raw_a, b, raw_b

    @staticmethod
    def without_boards(raw):
        body = json.loads(raw)
        view = body["state"]
        view["board"] = []
        for event in view["events"]:
            event["board"] = []
        return json.dumps(body, ensure_ascii=False)

    @staticmethod
    def frozen(view):
        return json.dumps(view, sort_keys=True, ensure_ascii=False)

    def rebuys(self, code):
        key = match_key_for(code)
        return [dict(r) for r, _ in self.database.tables["room_seat_events"].rows if r["match_key"] == key and r["kind"] == "rebuy"]

    def check_invariants(self, a, raw_a, b, raw_b, total=2000):
        for key in ("version", "gameVersion", "phase", "handNo", "street", "board", "pot", "turnSeat", "result", "recordStatus", "lastEventSeq", "events"):
            self.assertEqual(a[key], b[key], key)
        stacks = [s["stack"] for s in a["seats"]]
        self.assertEqual(stacks, [s["stack"] for s in b["seats"]])
        self.assertTrue(all(v >= 0 for v in stacks), stacks)
        self.assertEqual(sum(s["committed"] for s in a["seats"]), a["pot"])
        self.assertEqual(sum(stacks) + a["pot"], total, (stacks, a["pot"]))
        mine_a, mine_b = a["seats"][0]["cards"] or [], b["seats"][1]["cards"] or []
        cards = mine_a + mine_b + a["board"]
        self.assertEqual(len(cards), len(set(cards)), cards)
        self.assertTrue(set(cards) <= set(FULL))
        if a["street"] != "showdown":
            # Public board cards (this hand's and earlier hands' boards inside events) may legitimately
            # equal a card that is now someone's hole card, so every board field is removed first and
            # the rest of the response, every other field included, is searched for the opponent's cards.
            for card in mine_b:
                self.assertNotIn(card, self.without_boards(raw_a), "A saw B's hole card")
            for card in mine_a:
                self.assertNotIn(card, self.without_boards(raw_b), "B saw A's hole card")
            self.assertIsNone(a["seats"][1]["cards"])
            self.assertIsNone(b["seats"][0]["cards"])
        for raw in (raw_a, raw_b):
            self.assertNotIn('"deck"', raw)
            self.assertNotIn('"holes"', raw)
        for event in a["events"]:
            self.assertTrue(all(v >= 0 for v in event["stacks"] + event["committed"]), event)
            if event["type"] != "hand_end":
                # an event from before a rebuy shows the smaller total of that moment
                self.assertIn(sum(event["stacks"]) + event["pot"], range(2000, total + 1, 1000), event)

    def check_settlement(self, view):
        """Recompute the finished hand from its events and the revealed cards."""
        events = [e for e in view["events"] if e["handNo"] == view["handNo"]]
        if not events or events[0]["type"] != "hand_start" or events[-1]["type"] != "hand_end":
            return False  # hand voided or events trimmed; nothing to recompute
        before, end = events[-2], events[-1]
        start = [before["stacks"][i] + before["committed"][i] for i in range(2)]
        matched = min(before["committed"])
        pot = 2 * matched
        self.assertEqual(end["potWon"], pot, events)
        result = view["result"]
        if result["reason"] == "fold":
            folds = [e for e in events if e["type"] == "action" and e["action"] == "fold"]
            self.assertEqual(len(folds), 1)
            winner = 1 - folds[0]["seat"]
            payouts = [0, 0]
            payouts[winner] = pot
        else:
            self.assertEqual(len(view["board"]), 5)
            hands = [view["seats"][i]["cards"] for i in range(2)]
            self.assertTrue(all(h and len(h) == 2 for h in hands))
            scores = [best7(hands[i] + view["board"]) for i in range(2)]
            if scores[0] == scores[1]:
                winner = None
                payouts = [pot // 2, pot // 2]
                self.assertEqual(pot % 2, 0)  # heads-up matched pots are always even
            else:
                winner = 0 if scores[0] > scores[1] else 1
                payouts = [0, 0]
                payouts[winner] = pot
        self.assertEqual(result["winnerSeat"], winner, (result, view["board"]))
        self.assertEqual(result["payouts"], payouts)
        final = [start[i] - matched + payouts[i] for i in range(2)]
        self.assertEqual(end["stacks"], final, events)
        self.assertEqual([s["stack"] for s in view["seats"]], final)
        return True

    # ── run ────────────────────────────────────────────────────────────────

    def run_seed(self, seed):
        log = []
        try:
            self._run_seed(seed, log)
        except BaseException:
            folder = os.path.join(os.path.dirname(__file__), "random_failures")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, f"{seed}.json"), "w", encoding="utf-8") as out:
                json.dump({"seed": seed, "steps": log}, out, ensure_ascii=False, indent=1)
            raise

    def _run_seed(self, seed, log):
        rng = random.Random(seed)
        self.deck_rng.seed(seed * 7919)
        stats = Counter()
        confirmed = {}
        settled = set()
        accepted = Counter()  # (instance, handNo) -> accepted non-replayed actions
        codes = [self.start_match()]
        for step in range(STEPS):
            code = codes[-1]
            a, raw_a, b, raw_b = self.views(code)
            paid = self.rebuys(code)
            self.check_invariants(a, raw_a, b, raw_b, 2000 + sum(r["amount"] for r in paid))
            key = (a["instance"], a["handNo"])
            if a["phase"] in ("hand_over", "round_over") and a["result"] and key not in settled:
                if self.check_settlement(a):
                    stats["settlements_checked"] += 1
                    hand_events = [e for e in a["events"] if e["handNo"] == a["handNo"] and e["type"] == "action" and not e["auto"]]
                    self.assertEqual(len(hand_events), accepted[key], "accepted actions != action events")
                settled.add(key)
            if a["recordStatus"] == "confirmed" and a["phase"] in ("hand_over", "round_over"):
                # the hand's own result: table chips minus rebuys paid right after this hand
                ends = [s["stack"] for s in a["seats"]]
                for r in paid:
                    if r["after_hand"] == a["handNo"]:
                        ends[r["seat"]] -= r["amount"]
                previous = confirmed.setdefault((code, a["handNo"]), ends)
                self.assertEqual(previous, ends, "a confirmed result changed")
            roll = rng.random()
            if roll < 0.03:
                log.append(("api_restart",))
                self._install_demo()
                self.wire_rooms()
                stats["api_restart"] += 1
                continue
            if roll < 0.05:
                log.append(("dbms_restart",))
                self.dbms.shutdown()
                self.dbms.server_close()
                self.dbms_thread.join(2)
                self.database = integration.Database(self.tmp.name)
                self.dbms = integration.BoundedSQLHTTPServer(("127.0.0.1", 0), self.database, workers=4, queue_size=32)
                self.dbms_thread = self._start(self.dbms)
                self.demo.dbms_url = f"http://127.0.0.1:{self.dbms.server_port}"
                stats["dbms_restart"] += 1
                continue
            if roll < 0.10:
                self.fault = None if self.fault else rng.choice(["down", "lost_reply"])
                log.append(("fault", self.fault))
                stats["fault_switch"] += 1
                continue
            if a["phase"] == "round_over":
                if a["recordStatus"] == "unknown":
                    self.assertFalse(a["canNextRound"])
                    log.append(("wait_storage",))
                    self.clock.now += self.rooms.STORAGE_RETRY_SECONDS + 1
                    stats["waited_for_storage"] += 1
                    continue
                log.append(("next_round", a["handNo"]))
                busted = [s["seat"] for s in a["seats"] if s["stack"] == 0]
                status, result = self.call(rng.choice((A, B)), f"/api/rooms/{code}/next-round", {"hand_no": a["handNo"]})
                self.assertEqual(status, 200, result)
                after = result["state"]
                self.assertEqual([after["seats"][i]["stack"] for i in busted], [1000] * len(busted))
                status, again = self.call(rng.choice((A, B)), f"/api/rooms/{code}/next-round", {"hand_no": a["handNo"]})
                self.assertEqual((status, again["error"]), (409, "not_round_over"))  # pressing twice pays once
                stats["round_restarts"] += 1
                continue
            if a["phase"] == "hand_over":
                if a["recordStatus"] == "unknown":
                    log.append(("wait_storage",))
                    self.clock.now += self.rooms.STORAGE_RETRY_SECONDS + 1
                    if rng.random() < 0.5:
                        self.fault = None
                    stats["waited_for_storage"] += 1
                    continue
                log.append(("ready_both", a["handNo"]))
                for token in (A, B):
                    self.ready(token, code, a["handNo"])
                continue
            if roll < 0.13:
                log.append(("timeout",))
                self.clock.now += self.rooms.TURN_SECONDS + 1
                stats["timeouts"] += 1
                continue
            on_turn = (A, B)[a["turnSeat"]]
            other = (A, B)[1 - a["turnSeat"]]
            mine = a if on_turn == A else b
            if roll < 0.25:  # invalid request: must change nothing
                before_a = self.frozen(self.state(A, code, after=0))
                kind = rng.choice(["wrong_turn", "below_min", "above_max", "zero", "negative", "fraction", "string", "stale"])
                version = mine["gameVersion"]
                if kind == "wrong_turn":
                    body = {"action": "check"}
                    token = other
                elif kind == "stale":
                    body = {"action": "fold"}
                    token, version = on_turn, version - 1
                else:
                    token = on_turn
                    bet = "bet" if "bet" in mine["legalActions"] else "raise"
                    low, high = mine["minRaiseTo"], mine["maxRaiseTo"]
                    if low is None:
                        continue
                    value = {"below_min": low - 1, "above_max": high + 1, "zero": 0, "negative": -low,
                             "fraction": low + 0.5, "string": str(low)}[kind]
                    body = {"action": bet, "to": value}
                    if kind == "below_min" and low - 1 >= high:  # an all-in short of the minimum is legal, so skip
                        continue
                status, result = self.call(token, f"/api/rooms/{code}/action",
                                           {"action_id": self.new_id(), "expected_version": version, **body})
                log.append(("invalid", kind, body, status))
                self.assertIn(status, (400, 409), (kind, body, result))
                self.assertEqual(self.frozen(self.state(A, code, after=0)), before_a, kind)
                stats["invalid_rejected"] += 1
                continue
            legal = mine["legalActions"]
            weights = {"check": 6, "call": 6, "fold": 1, "bet": 3, "raise": 2, "all_in": 0.6}
            action = rng.choices(legal, [weights[name] for name in legal])[0]
            to = None
            if action in ("bet", "raise"):
                low, high = mine["minRaiseTo"], mine["maxRaiseTo"]
                to = rng.choice([low, min(high, low + 1), rng.randint(low, high), high])
            action_id = self.new_id()
            status, result = self.act(on_turn, code, action, to=to, action_id=action_id, version=mine["gameVersion"])
            log.append(("act", a["turnSeat"], action, to, status))
            self.assertEqual(status, 200, (action, to, result))
            accepted[key] += 1
            stats["actions"] += 1
            if rng.random() < 0.2:
                status, again = self.act(on_turn, code, action, to=to, action_id=action_id, version=mine["gameVersion"])
                log.append(("resend", status))
                self.assertEqual((status, again.get("replayed")), (200, True))
                stats["duplicates"] += 1
        self.fault = None
        # final: ledger chain, confirmed results unchanged, profiles equal the ledger
        self.clock.now += self.rooms.STORAGE_RETRY_SECONDS + 1
        self.views(codes[-1])
        rows_all = self.ledger()
        self.assertEqual(len({r["operation_key"] for r in rows_all}), len(rows_all))
        expected = {A: Counter(), B: Counter()}
        latest = {}
        for code in codes:
            rows = sorted((r for r in rows_all if r["match_key"] == match_key_for(code)), key=lambda r: r["id"])
            history = replay_ledger(match_key_for(code), [dict(r) for r, _ in self.database.tables["room_seat_events"].rows if r["match_key"] == match_key_for(code)], [dict(r) for r, _ in self.database.tables["room_hand_results"].rows if r["match_key"] == match_key_for(code)])
            self.assertEqual([r["hand_no"] for r in rows], list(range(1, history["hand_no"] + 1)))
            for r in rows:
                if (code, r["hand_no"]) in confirmed:
                    self.assertEqual(confirmed[(code, r["hand_no"])], [r["end_a"], r["end_b"]])
                for token, side in ((A, "human"), (B, "bot")):
                    expected[token]["hands"] += 1
                    expected[token]["draws" if r["winner"] == "tie" else "wins" if r["winner"] == side else "losses"] += 1
            if rows:
                latest[code] = (rows[-1]["end_a"], rows[-1]["end_b"])
        for token, seat in ((A, 0), (B, 1)):
            profile = self.call(token, "/api/profile")[1]["profile"]
            online = profile["online"]
            self.assertEqual((online["hands"], online["wins"], online["losses"], online["draws"]),
                             (expected[token]["hands"], expected[token]["wins"], expected[token]["losses"], expected[token]["draws"]), token)
            self.assertEqual(online["matches"], len(codes))
            mine = sum(1 for code in codes for r in self.rebuys(code) if r["seat"] == seat)
            self.assertEqual(online["rebuys"], mine)  # counted apart, never as wins
            self.assertEqual(profile["practice"]["hands"], 0)
            if profile["recentOnline"]:
                newest = profile["recentOnline"][0]
                code = next(c for c in codes if match_key_for(c) == newest["matchKey"])
                self.assertEqual(newest["endStack"], latest[code][seat])
        print(f"\n  seed {seed}: {dict(stats)}, hands stored {len(rows_all)}, matches {len(codes)}", flush=True)


def _make(seed):
    def test(self):
        self.run_seed(seed)
    test.__name__ = f"test_seed_{seed}"
    return test


for _seed in SEEDS:
    setattr(RandomRoomTransitions, f"test_seed_{_seed}", _make(_seed))


if __name__ == "__main__":
    unittest.main()
