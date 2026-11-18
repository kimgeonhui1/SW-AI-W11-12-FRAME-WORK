"""Randomized two-human play with storage faults and restarts.

Each run plays many hands with random legal actions while it injects, at random moments:
  - Mini DBMS down when a hand result or a rebuy is written (row not stored, no reply)
  - lost DBMS reply (row stored, reply lost)
  - Poker API restart (all memory lost; rooms are rebuilt from the DBMS)
  - Mini DBMS restart (table files reopened)
  - turn timeouts, duplicate resends and stale requests

A bust leads to round_over; a player presses '다음 라운드 시작' (sometimes both, sometimes twice),
which pays the busted player's one 1,000-chip rebuy.

After every step it checks that no chip was created or lost (2,000 + stored rebuys) and that both
players see the same table; at the end it checks the DBMS ledger: one row per completed hand,
an unbroken chain, and the same final stacks the players were shown when the hand was
confirmed (so no hand was paid twice).
"""
from collections import Counter
from functools import partial
import random
import unittest

import test_server as integration
from engine import PokerEngine, RANKS, SUITS
from rooms import match_key_for, replay_ledger
import test_rooms
from test_rooms import A, B

FULL_DECK = [rank + suit for rank in RANKS for suit in SUITS]


class RoomFaultSoakTests(unittest.TestCase):
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
        self.deck_rng = random.Random(0)  # replaced per run; setUp already builds an engine factory
        self.fault = None
        test_rooms.RoomTests.setUp(self)

    def wire_rooms(self):
        test_rooms.RoomTests.wire_rooms(self)
        rng = self.deck_rng
        self.rooms.deck_factory = lambda: rng.sample(FULL_DECK, 52)

    def arm_faults(self):
        original = self.demo._call

        def call(service, method, url, body=None, trace_id=None):
            rebuy = body and body.get("sql", "").startswith("INSERT INTO room_seat_events") and "rebuy" in body.get("params", [])
            if self.fault and service == "Mini DBMS" and body and (body.get("sql", "").startswith("INSERT INTO room_hand_results") or rebuy):
                if self.fault == "lost_reply":
                    original(service, method, url, body, trace_id)
                return None, {"traceId": trace_id, "service": service, "method": method, "path": "/sql/insert-once", "outcome": "unavailable"}
            return original(service, method, url, body, trace_id)

        self.demo._call = call

    def restart_api(self):
        self._install_demo()
        self.wire_rooms()
        self.arm_faults()

    def restart_dbms(self):
        self.dbms.shutdown()
        self.dbms.server_close()
        self.dbms_thread.join(2)
        self.database = integration.Database(self.tmp.name)  # files are re-read and checked
        self.dbms = integration.BoundedSQLHTTPServer(("127.0.0.1", 0), self.database, workers=4, queue_size=32)
        self.dbms_thread = self._start(self.dbms)
        self.demo.dbms_url = f"http://127.0.0.1:{self.dbms.server_port}"

    def replayed(self, code):
        key = match_key_for(code)
        seat_rows = [dict(r) for r, _ in self.database.tables["room_seat_events"].rows if r["match_key"] == key]
        hand_rows = [dict(r) for r, _ in self.database.tables["room_hand_results"].rows if r["match_key"] == key]
        return replay_ledger(key, seat_rows, hand_rows)

    def rows_for(self, code):
        key = match_key_for(code)
        return sorted((row for row in self.ledger() if row["match_key"] == key), key=lambda row: row["id"])

    def rebuys_after(self, code, hand_no):
        """Chips paid as rebuys right after hand `hand_no`, per seat."""
        key = match_key_for(code)
        paid = [0, 0]
        for row, _ in self.database.tables["room_seat_events"].rows:
            if row["match_key"] == key and row["kind"] == "rebuy" and row["after_hand"] == hand_no:
                paid[row["seat"]] += row["amount"]
        return paid

    def check(self, code, a, b, observed, after_restart=False):
        for key in ("gameVersion", "phase", "handNo", "board", "pot", "recordStatus"):
            self.assertEqual(a[key], b[key], key)
        stacks = [seat["stack"] for seat in a["seats"]]
        self.assertEqual(stacks, [seat["stack"] for seat in b["seats"]])
        rows = self.rows_for(code)
        history = self.replayed(code)  # raises on a broken chain, duplicate key or chips that do not add up
        self.assertEqual(sum(stacks) + a["pot"], 2000 + history["rebuys"], (code, a["phase"], stacks, a["pot"]))
        self.assertTrue(all(value >= 0 for value in stacks))
        last = rows[-1] if rows else None
        ledger_stacks = [history["stacks"][history["seats"][seat]] for seat in (0, 1)]
        self.assertNotEqual(a["recordStatus"], "blocked")
        if after_restart:
            self.assertTrue(a["recovered"])
            self.assertIn(a["phase"], ("hand_over", "round_over"))
            self.assertEqual((stacks, a["pot"], a["handNo"]), (ledger_stacks, 0, history["hand_no"]))
        if a["phase"] in ("hand_over", "round_over") and a["recordStatus"] == "confirmed":
            self.assertEqual((last["hand_no"], ledger_stacks), (a["handNo"], stacks))
            # what the hand itself paid, without any rebuy given after it
            paid = self.rebuys_after(code, a["handNo"])
            ends = [stacks[i] - paid[i] for i in (0, 1)]
            seen = observed.setdefault((code, a["handNo"]), ends)
            self.assertEqual(seen, ends, "a confirmed hand changed its result")
            self.assertEqual(ends, [last["end_a"], last["end_b"]])
        if a["recordStatus"] == "unknown":
            self.assertIn(history["hand_no"], (a["handNo"] - 1, a["handNo"]))

    # Each seed runs in its own fresh services and DBMS files (setUp/tearDown per test).
    def test_seed_20261116_no_chip_loss_or_double_payout(self):
        self.run_soak(20261116)

    def test_seed_7_no_chip_loss_or_double_payout(self):
        self.run_soak(7)

    def test_seed_99_no_chip_loss_or_double_payout(self):
        self.run_soak(99)

    def run_soak(self, seed, steps=320):
        rng = random.Random(seed)
        self.deck_rng = random.Random(seed + 1)
        self.fault = None
        self.wire_rooms()
        self.arm_faults()
        stats = Counter()
        observed = {}
        codes = [self.start_match()]
        restarted = False
        for _ in range(steps):
            code = codes[-1]
            a, b = self.state(A, code), self.state(B, code)
            self.check(code, a, b, observed, after_restart=restarted)
            restarted = False
            roll = rng.random()
            if roll < 0.04:
                self.restart_api()
                stats["api_restart"] += 1
                restarted = True
                continue
            if roll < 0.06:
                self.restart_dbms()
                stats["dbms_restart"] += 1
                continue
            if self.fault is None and roll < 0.12:
                self.fault = rng.choice(["down", "lost_reply"])
                stats["fault_" + self.fault] += 1
            elif self.fault and rng.random() < 0.3:
                self.fault = None
            if a["phase"] == "round_over" and a["recordStatus"] == "unknown":
                self.assertFalse(a["canNextRound"])  # no rebuy before the hand that caused it is on record
                stats["waited_for_storage"] += 1
                self.clock.now += self.rooms.STORAGE_RETRY_SECONDS + 1
                continue
            if a["phase"] == "round_over":
                stats["round_restarts"] += 1
                presser = rng.choice((A, B))
                status, result = self.call(presser, f"/api/rooms/{code}/next-round", {"hand_no": a["handNo"]})
                self.assertIn(status, (200, 503), result)  # 503 when the rebuy row could not be confirmed
                if status == 200 and rng.random() < 0.5:  # the other player (or a second tab) presses too
                    status, again = self.call(B if presser == A else A, f"/api/rooms/{code}/next-round", {"hand_no": a["handNo"]})
                    self.assertEqual((status, again["error"]), (409, "not_round_over"))
                    stats["round_restart_duplicates"] += 1
                if rng.random() < 0.03:
                    codes.append(self.start_match())  # sometimes the players open a new room
                continue
            if a["phase"] == "hand_over":
                if a["recordStatus"] == "unknown":
                    stats["waited_for_storage"] += 1
                    self.clock.now += self.rooms.STORAGE_RETRY_SECONDS + 1
                    continue
                for token in (A, B):
                    self.ready(token, code, a["handNo"])
                continue
            if rng.random() < 0.04:
                self.clock.now += self.rooms.TURN_SECONDS + 1
                stats["timeouts"] += 1
                continue
            token = (A, B)[a["turnSeat"]]
            mine = a if token == A else b
            legal = mine["legalActions"]
            weights = {"check": 6, "call": 6, "fold": 1, "bet": 3, "raise": 2, "all_in": 0.5}
            action = rng.choices(legal, [weights[name] for name in legal])[0]
            to = None
            if action in ("bet", "raise"):
                low, high = mine["minRaiseTo"], mine["maxRaiseTo"]
                to = rng.choice([low, min(high, low * 2), rng.randint(low, high)])
            action_id = self.new_id()
            status, result = self.act(token, code, action, to=to, action_id=action_id, version=mine["gameVersion"])
            self.assertEqual(status, 200, result)
            stats["actions"] += 1
            if rng.random() < 0.2:  # the same request arrives again (double click / resend)
                status, again = self.act(token, code, action, to=to, action_id=action_id, version=mine["gameVersion"])
                self.assertEqual((status, again.get("replayed")), (200, True))
                self.assertEqual(again["state"]["gameVersion"], result["state"]["gameVersion"])
                stats["duplicates"] += 1
            if rng.random() < 0.1:  # a late click made for the turn that just passed
                status, late = self.act(token, code, action, to=to, version=mine["gameVersion"])
                self.assertEqual(status, 409, late)
                stats["stale"] += 1
        self.fault = None
        self.assertGreater(stats["round_restarts"], 0, stats)  # the new rule was exercised
        # final ledger: every match is an unbroken chain and agrees with what the players were shown
        for code in codes:
            rows = self.rows_for(code)
            history = self.replayed(code)
            self.assertEqual([row["hand_no"] for row in rows], list(range(1, history["hand_no"] + 1)))
            for row in rows:
                self.assertEqual(row["start_a"] + row["start_b"], row["end_a"] + row["end_b"])
                if (code, row["hand_no"]) in observed:
                    self.assertEqual(observed[(code, row["hand_no"])], [row["end_a"], row["end_b"]])
        self.assertEqual(len({row["operation_key"] for row in self.ledger()}), len(self.ledger()))
        self.assertEqual(len(self.database.tables["room_matches"].rows), len(codes))
        for scenario in ("api_restart", "dbms_restart", "fault_down", "fault_lost_reply", "timeouts", "duplicates", "stale", "waited_for_storage"):
            self.assertGreater(stats[scenario], 0, (scenario, dict(stats)))
        print(f"\n  seed {seed}: {dict(stats)}, hands stored {len(self.ledger())}, matches {len(codes)}", flush=True)


if __name__ == "__main__":
    unittest.main()
