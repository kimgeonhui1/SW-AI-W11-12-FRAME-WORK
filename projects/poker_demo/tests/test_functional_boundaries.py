"""Functional boundary tests (two-seat rooms) added for the 2026-11-17 verification of feat/poker-ui (6e117d0).

Only cases the existing suites do not cover. Expected values are worked out by hand in the
comments (blinds 10/20, 1000 chips each, seat 0 is the button in odd hands) and are not read
back from the implementation. Decks are injected through the test fixture only; no API is added.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import http.client
import json
import socket
import threading
import time
import unittest

import test_rooms
import test_server as integration
from engine import PokerEngine, RuleError
from rooms import match_key_for
from test_engine import deck_with_prefix
from test_rooms import A, B, C, DECK



def rows_of(table):
    return [dict(row) for row, _ in table.rows]


class FunctionalBoundaryTests(unittest.TestCase):
    _start = classmethod(integration.PokerHTTPIntegrationTests._start.__func__)
    _install_demo = integration.PokerHTTPIntegrationTests._install_demo
    tearDown = integration.PokerHTTPIntegrationTests.tearDown
    setUp = test_rooms.RoomTests.setUp
    wire_rooms = test_rooms.RoomTests.wire_rooms
    call = test_rooms.RoomTests.call
    new_id = test_rooms.RoomTests.new_id
    state = test_rooms.RoomTests.state
    create_and_join = test_rooms.RoomTests.create_and_join
    ready = test_rooms.RoomTests.ready
    start_match = test_rooms.RoomTests.start_match
    act = test_rooms.RoomTests.act
    play_to_showdown = test_rooms.RoomTests.play_to_showdown
    ledger = test_rooms.RoomTests.ledger
    fault_dbms = test_rooms.RoomTests.fault_dbms

    # ── helpers ────────────────────────────────────────────────────────────

    def raw(self, path, body=None, headers=None, method=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=10)
        method = method or ("GET" if body is None else "POST")
        data = None if method == "GET" else json.dumps(body or {}).encode()
        conn.request(method, path, data, {"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        text = response.read().decode("utf-8")
        conn.close()
        return response.status, text

    def frozen(self, token, code):
        """Everything a player can see, to prove a rejected request changed nothing."""
        view = self.state(token, code, after=0)
        return json.dumps(view, sort_keys=True, ensure_ascii=False), len(self.ledger()), len(self.database.tables["room_matches"].rows)

    def use_deck(self, deck):
        self.rooms.deck_factory = lambda: list(deck)

    def stacks(self, code):
        return [seat["stack"] for seat in self.state(A, code)["seats"]]

    # ── 1. rooms, seats, auth ─────────────────────────────────────────────

    def test_two_players_racing_for_the_last_seat_get_exactly_one_seat(self):
        for attempt in range(5):
            status, created = self.call(A, "/api/rooms", {"request_id": f"race-room-{attempt:04d}", "max_seats": 2})
            code = created["state"]["code"]
            barrier = threading.Barrier(2)

            def join(token):
                barrier.wait(5)
                return self.call(token, f"/api/rooms/{code}/join", {})

            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(join, (B, C)))
            statuses = sorted(status for status, _ in results)
            self.assertEqual(statuses, [200, 409], results)
            loser = next(body for status, body in results if status == 409)
            self.assertEqual(loser["error"], "room_full")
            seats = self.state(A, code)["seats"]
            winner_name = next(body["state"]["you"]["name"] for status, body in results if status == 200)
            self.assertEqual([seat["name"] for seat in seats], ["Alpha", winner_name])

    def test_simultaneous_ready_and_next_hand_requests_start_exactly_one_hand(self):
        code = self.create_and_join()
        self.ready(A, code, 0)
        barrier = threading.Barrier(6)

        def ready_b(_):
            barrier.wait(5)
            return self.ready(B, code, 0)

        with ThreadPoolExecutor(6) as pool:
            results = list(pool.map(ready_b, range(6)))
        self.assertEqual(sorted(status for status, _ in results)[0], 200)
        view = self.state(A, code, after=0)
        self.assertEqual(view["handNo"], 1)
        self.assertEqual([e["type"] for e in view["events"]].count("hand_start"), 1)
        self.assertEqual(len(self.database.tables["room_matches"].rows), 1)
        self.play_to_showdown(code)
        # both players press "next hand" many times at once while the automatic timer also expires
        self.clock.now += self.rooms.NEXT_HAND_SECONDS + 1
        barrier = threading.Barrier(8)

        def ready_any(index):
            barrier.wait(5)
            return self.ready((A, B)[index % 2], code, 1)

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(ready_any, range(8)))
        view = self.state(A, code, after=0)
        self.assertEqual(view["handNo"], 2)
        self.assertEqual([e["type"] for e in view["events"]].count("hand_start"), 2)
        self.assertEqual(len(self.ledger()), 1)  # hand 1 stored once; hand 2 running

    def test_every_authenticated_route_rejects_bad_tokens_and_changes_nothing(self):
        code = self.start_match()
        before = self.frozen(A, code)
        version = self.state(A, code)["gameVersion"]
        routes = [
            ("/api/rooms", {"request_id": "bad-token-room-01"}),
            (f"/api/rooms/{code}/join", {}),
            (f"/api/rooms/{code}/ready", {"ready": True, "hand_no": 1}),
            (f"/api/rooms/{code}/leave", {}),
            (f"/api/rooms/{code}/action", {"action_id": "bad-token-act-01", "expected_version": version, "action": "fold"}),
            (f"/api/rooms/{code}/state", None),
            ("/api/profile", None),
        ]
        bad_headers = [
            {},
            {"Authorization": "Bearer "},
            {"Authorization": "Bearer short"},
            {"Authorization": "Bearer " + "A" * 42 + "!"},
            {"Authorization": "Bearer " + "Z" * 43},  # well-formed but never registered
            {"Authorization": "Basic " + A},
            {"Authorization": A},  # missing scheme
        ]
        for path, body in routes:
            for headers in bad_headers:
                status, text = self.raw(path, body, headers)
                self.assertEqual(status, 401, (path, headers, text))
                self.assertNotIn('"state"', text)
        self.assertEqual(self.frozen(A, code), before)

    def test_no_private_card_or_deck_leaks_through_any_response_cache_or_record(self):
        # seat 0: 2♦ 3♦, seat 1: A♠ K♠; board Q♠ J♠ T♠ 4♦ 5♥ (DECK from test_rooms)
        seat1_cards, seat0_cards = ("A♠", "K♠"), ("2♦", "3♦")
        bodies_a, bodies_b = [], []

        def a(path, body=None):
            status, result = self.call(A, path, body)
            bodies_a.append(self.last_raw)
            return status, result

        def b(path, body=None):
            status, result = self.call(B, path, body)
            bodies_b.append(self.last_raw)
            return status, result

        status, created = a("/api/rooms", {"request_id": "leak-room-0001", "max_seats": 2})
        code = created["state"]["code"]
        b(f"/api/rooms/{code}/join", {})
        a(f"/api/rooms/{code}/ready", {"ready": True, "hand_no": 0})
        b(f"/api/rooms/{code}/ready", {"ready": True, "hand_no": 0})
        a(f"/api/rooms/{code}/state?after=0")
        b(f"/api/rooms/{code}/state?after=0")
        a(f"/api/rooms/{code}/join", {})  # refresh path
        b(f"/api/rooms/{code}/join", {})
        version = self.state(A, code)["gameVersion"]
        a(f"/api/rooms/{code}/action", {"action_id": "leak-wrong-turn", "expected_version": version, "action": "raise", "to": 1})  # error with state
        b(f"/api/rooms/{code}/action", {"action_id": "leak-not-turn01", "expected_version": version, "action": "check"})  # 409 with state
        a(f"/api/rooms/{code}/action", {"action_id": "leak-call-00001", "expected_version": version, "action": "call"})
        version = self.state(B, code)["gameVersion"]
        b(f"/api/rooms/{code}/action", {"action_id": "leak-raise-0001", "expected_version": version, "action": "raise", "to": 100})
        version = self.state(A, code)["gameVersion"]
        a(f"/api/rooms/{code}/action", {"action_id": "leak-fold-00001", "expected_version": version, "action": "fold"})
        a(f"/api/rooms/{code}/state?after=0")
        b(f"/api/rooms/{code}/state?after=0")
        a("/api/profile")
        b("/api/profile")
        status, _ = self.call(C, f"/api/rooms/{code}/state")
        public = self.raw(f"/api/rooms/{code}/public")[1]
        cache = json.dumps(self.redis_store.get("poker:room:" + code), ensure_ascii=False)
        ledger = json.dumps(self.ledger(), ensure_ascii=False)
        # A must never see B's cards, B never A's (hand ended by fold, so no reveal at all)
        for text in bodies_a:
            for card in seat1_cards:
                self.assertNotIn(card, text)
        for text in bodies_b:
            for card in seat0_cards:
                self.assertNotIn(card, text)
        for text in bodies_a + bodies_b + [public, cache, ledger]:
            self.assertNotIn('"deck"', text)
            self.assertNotIn('"holes"', text)
            self.assertNotIn("Q♠", text)  # the undealt flop must never travel (hand ended preflop)
        for text in (public, cache, ledger):
            for card in seat0_cards + seat1_cards:
                self.assertNotIn(card, text)
        self.assertEqual(status, 403)

    # ── 2. rules and settlement (independent arithmetic) ──────────────────

    def test_fold_on_every_street_and_button_blind_rotation(self):
        code = self.start_match()
        expected = [1000, 1000]

        def hand_start_event(view):
            return [e for e in view["events"] if e["type"] == "hand_start"][-1]

        # hand 1, button seat 0 posts SB 10, seat 1 posts BB 20. Seat 0 folds preflop:
        # BB's unmatched 10 comes back, seat 1 wins the 10+10 matched -> +10 / -10
        view = self.state(A, code, after=0)
        self.assertEqual((hand_start_event(view)["button"], hand_start_event(view)["stacks"]), (0, [990, 980]))
        self.assertEqual(self.act(A, code, "fold")[0], 200)
        expected = [expected[0] - 10, expected[1] + 10]
        self.assertEqual(self.stacks(code), expected)
        result = self.state(A, code)["result"]
        self.assertEqual((result["winnerSeat"], result["reason"], result["pot"]), (1, "fold", 20))

        # hand 2, button seat 1 (SB 10), seat 0 BB 20. Seat 1 calls, seat 0 checks.
        # Flop: seat 0 bets 40, seat 1 folds -> seat 0 wins seat 1's 20, its own 40 comes back
        self.ready(A, code, 1)
        self.ready(B, code, 1)
        view = self.state(A, code, after=0)
        self.assertEqual((hand_start_event(view)["button"], hand_start_event(view)["stacks"]), (1, [expected[0] - 20, expected[1] - 10]))
        self.act(B, code, "call")
        self.act(A, code, "check")
        self.assertEqual(self.state(A, code)["street"], "flop")
        self.act(A, code, "bet", to=40)
        self.act(B, code, "fold")
        expected = [expected[0] + 20, expected[1] - 20]
        self.assertEqual(self.stacks(code), expected)
        self.assertEqual(self.state(A, code)["result"]["pot"], 40)

        # hand 3, button seat 0. Call/check, flop check/check, turn: seat 1 bets 50, seat 0 folds
        self.ready(A, code, 2)
        self.ready(B, code, 2)
        self.act(A, code, "call")
        self.act(B, code, "check")
        self.act(B, code, "check")
        self.act(A, code, "check")
        self.assertEqual(self.state(A, code)["street"], "turn")
        self.act(B, code, "bet", to=50)
        self.act(A, code, "fold")
        expected = [expected[0] - 20, expected[1] + 20]
        self.assertEqual(self.stacks(code), expected)

        # hand 4, button seat 1. Down to the river, seat 0 bets 100, seat 1 folds
        self.ready(A, code, 3)
        self.ready(B, code, 3)
        self.act(B, code, "call")
        self.act(A, code, "check")
        for _ in range(2):
            self.act(A, code, "check")
            self.act(B, code, "check")
        self.assertEqual(self.state(A, code)["street"], "river")
        self.act(A, code, "bet", to=100)
        self.act(B, code, "fold")
        expected = [expected[0] + 20, expected[1] - 20]
        self.assertEqual(self.stacks(code), expected)
        self.assertEqual(sum(expected), 2000)
        rows = self.ledger()
        self.assertEqual([(r["end_a"], r["end_b"]) for r in rows][-1], tuple(expected))
        self.assertEqual([r["reason"] for r in rows], ["fold"] * 4)

    def test_minimum_raise_and_stack_limits_at_the_exact_boundary(self):
        code = self.start_match()
        # preflop: SB faces 20 -> minimum raise is to 40, maximum is its whole 1000
        view = self.state(A, code)
        self.assertEqual((view["toCall"], view["minRaiseTo"], view["maxRaiseTo"]), (10, 40, 1000))
        before = self.frozen(A, code)
        self.assertEqual(self.act(A, code, "raise", to=39)[1]["error"], "illegal_action")
        self.assertEqual(self.act(A, code, "raise", to=1001)[1]["error"], "illegal_action")
        self.assertEqual(self.frozen(A, code), before)
        self.assertEqual(self.act(A, code, "raise", to=40)[0], 200)
        # BB faces 40 (raise size 20) -> minimum re-raise to 60
        view = self.state(B, code)
        self.assertEqual((view["toCall"], view["minRaiseTo"], view["maxRaiseTo"]), (20, 60, 1000))
        self.assertEqual(self.act(B, code, "raise", to=59)[0], 400)
        self.assertEqual(self.act(B, code, "raise", to=200)[0], 200)  # raise size 160
        # seat 0 faces 200 -> minimum re-raise is 200 + 160 = 360
        view = self.state(A, code)
        self.assertEqual((view["toCall"], view["minRaiseTo"]), (160, 360))
        self.assertEqual(self.act(A, code, "raise", to=359)[0], 400)
        self.assertEqual(self.act(A, code, "call")[0], 200)
        # flop: first to act is seat 1; no bet yet -> minimum bet is the big blind 20, max = 800 left
        view = self.state(B, code)
        self.assertEqual((view["street"], view["minRaiseTo"], view["maxRaiseTo"]), ("flop", 20, 800))
        self.assertEqual(self.act(B, code, "bet", to=19)[0], 400)
        self.assertEqual(self.act(B, code, "raise", to=40)[1]["error"], "illegal_action")  # nothing to raise yet
        # a raise to exactly the whole stack is an all-in and is allowed
        status, result = self.act(B, code, "bet", to=800)
        self.assertEqual(status, 200, result)
        last = [e for e in self.state(A, code, after=0)["events"] if e["type"] == "action"][-1]
        self.assertEqual((last["seat"], last["paid"], last["allIn"]), (1, 800, True))
        self.assertEqual(self.stacks(code), [800, 0])
        self.assertEqual(self.state(A, code)["pot"], 1200)

    def test_rejected_bet_values_and_malformed_actions_change_nothing(self):
        code = self.start_match()
        version = self.state(A, code)["gameVersion"]
        before = self.frozen(A, code)
        path = f"/api/rooms/{code}/action"
        cases = []
        for value in (-40, 0, 40.5, 40.0, "60", None, True, False, [], {}, 10 ** 30, 2 ** 63, -(2 ** 63)):
            cases.append({"action_id": self.new_id(), "expected_version": version, "action": "raise", "to": value})
        cases += [
            {"action_id": self.new_id(), "expected_version": version, "action": "raise"},  # no target
            {"action_id": self.new_id(), "expected_version": version, "action": "call", "to": 20},  # target on call
            {"action_id": self.new_id(), "expected_version": version, "action": "CALL"},
            {"action_id": self.new_id(), "expected_version": version, "action": "check "},
            {"action_id": self.new_id(), "expected_version": version, "action": None},
            {"action_id": self.new_id(), "expected_version": str(version), "action": "call"},
            {"action_id": self.new_id(), "expected_version": True, "action": "call"},
            {"action_id": self.new_id(), "action": "call"},
            {"action_id": "short", "expected_version": version, "action": "call"},
            {"action_id": 12345678, "expected_version": version, "action": "call"},
            {"action_id": self.new_id(), "expected_version": version, "action": "call", "seat": 1},  # extra field
            {"action_id": self.new_id(), "expected_version": version, "action": "check"},  # not legal facing the BB
        ]
        for body in cases:
            status, result = self.call(A, path, body)
            self.assertIn(status, (400,), (body, result))
            self.assertEqual(self.frozen(A, code), before, body)
        # the same id that was rejected can still be used later for a legal action
        status, result = self.call(A, path, {"action_id": "reuse-after-reject", "expected_version": version, "action": "call"})
        self.assertEqual(status, 200, result)

    def test_engine_unequal_all_ins_return_the_unmatched_amount(self):
        # button/SB human 300 chips, BB bot 1000. Human calls (290 -> 280 left), bot shoves to 1000,
        # human can only call 280 more (300 total). 700 of the bot's shove is unmatched and returns.
        # Human: A♠ A♥, bot: 2♦ 7♣, board K♠ 9♦ 4♣ J♥ 3♠ -> pair of aces beats king high.
        deck = deck_with_prefix("A♠", "2♦", "A♥", "7♣", "8♣", "K♠", "9♦", "4♣", "8♦", "J♥", "8♥", "3♠")
        engine = PokerEngine(starting_stacks={"human": 300, "bot": 1000}, deck_factory=lambda: list(deck))
        engine.start_hand()
        engine.act("human", "call")
        engine.act("bot", "all_in")
        state = engine.snapshot()
        self.assertEqual((state["toCall"], state["legalActions"]), (280, ["fold", "call", "all_in"]))
        state = engine.act("human", "call")
        self.assertTrue(state["handOver"])
        self.assertEqual((state["result"]["pot"], state["result"]["winner"]), (600, "human"))
        self.assertEqual((state["humanStack"], state["botStack"]), (600, 700))
        self.assertEqual(len(state["board"]), 5)

    def test_engine_odd_stack_tie_splits_exactly(self):
        # Both hold a royal flush on the board. Human shoves 333 (odd), bot calls: pot 666 splits 333/333.
        deck = deck_with_prefix("2♦", "4♦", "3♣", "5♣", "6♥", "A♠", "K♠", "Q♠", "6♦", "J♠", "7♥", "T♠")
        engine = PokerEngine(starting_stacks={"human": 333, "bot": 1000}, deck_factory=lambda: list(deck))
        engine.start_hand()
        engine.act("human", "all_in")
        state = engine.act("bot", "call")
        self.assertEqual(state["result"]["winner"], "tie")
        self.assertEqual(state["result"]["payouts"], {"human": 333, "bot": 333})
        self.assertEqual((state["humanStack"], state["botStack"]), (333, 1000))

    def test_engine_short_all_in_bet_below_big_blind_cannot_be_reraised(self):
        # Bot has 35: after the 20 BB it has 15. On the flop it shoves 15 (< BB). Human may only call or fold.
        deck = deck_with_prefix("A♠", "2♦", "A♥", "7♣", "8♣", "K♠", "9♦", "4♣", "8♦", "J♥", "8♥", "3♠")
        engine = PokerEngine(starting_stacks={"human": 1000, "bot": 35}, deck_factory=lambda: list(deck))
        engine.start_hand()
        engine.act("human", "call")
        engine.act("bot", "check")
        self.assertEqual((engine.phase, engine.turn), ("flop", "bot"))
        engine.act("bot", "all_in")
        state = engine.snapshot()
        self.assertEqual((state["toCall"], state["legalActions"]), (15, ["fold", "call", "all_in"]))
        with self.assertRaises(RuleError):
            engine.act("human", "raise", 100)
        state = engine.act("human", "call")
        self.assertEqual((state["result"]["pot"], state["humanStack"], state["botStack"]), (70, 1035, 0))
        self.assertTrue(state["matchOver"])

    # ── 3. timing and overlap ──────────────────────────────────────────────

    def test_turn_deadline_boundary_action_before_and_timeout_at_the_deadline(self):
        code = self.start_match()
        self.clock.now += self.rooms.TURN_SECONDS - 0.001
        self.assertEqual(self.act(A, code, "call")[0], 200)  # just in time
        version = self.state(B, code)["gameVersion"]
        self.clock.now += self.rooms.TURN_SECONDS  # exactly at seat 1's deadline
        status, result = self.act(B, code, "raise", to=100, version=version)
        self.assertEqual((status, result["error"]), (409, "stale_state"))  # the server's timeout came first
        events = [e for e in self.state(A, code, after=0)["events"] if e["type"] == "action"]
        self.assertEqual([(e["seat"], e["action"], e["auto"]) for e in events], [(0, "call", False), (1, "check", True)])
        self.assertEqual(self.stacks(code), [980, 980])

    def test_ready_that_arrives_after_the_automatic_start_is_rejected_once(self):
        code = self.start_match()
        self.play_to_showdown(code)
        # keep both players connected (presence lasts 8 s) while the 12 s timer runs out
        self.clock.now += 7
        self.state(A, code), self.state(B, code)
        self.clock.now += self.rooms.NEXT_HAND_SECONDS - 7 + 0.5
        status, result = self.ready(A, code, 1)  # the timer fires inside this request first
        self.assertEqual((status, result["error"]), (409, "hand_active"))
        self.assertEqual(self.state(B, code)["handNo"], 2)
        status, result = self.act(A, code, "fold", version=self.state(A, code)["gameVersion"] - 1)
        self.assertEqual(status, 409)

    def test_both_players_away_then_back_applies_one_timeout_and_waits_for_both(self):
        code = self.start_match()
        self.clock.now += 300  # both stopped polling for five minutes
        view = self.state(A, code, after=0)
        autos = [e for e in view["events"] if e["type"] == "action" and e["auto"]]
        self.assertEqual([(e["seat"], e["action"]) for e in autos], [(0, "fold")])  # SB facing the BB folds once
        self.assertEqual(view["phase"], "hand_over")
        self.assertEqual([seat["connected"] for seat in view["seats"]], [True, False])
        self.clock.now += self.rooms.NEXT_HAND_SECONDS + 5
        self.assertEqual(self.state(A, code)["phase"], "hand_over")  # no hand dealt to an absent player
        self.state(B, code)
        self.assertEqual(self.state(A, code)["handNo"], 2)
        self.assertEqual(self.stacks(code), [990 - 20, 1010 - 10])  # hand 2 blinds: seat 1 button
        self.assertEqual(len(self.ledger()), 1)

    # ── 4. network, storage, recovery ──────────────────────────────────────

    def test_response_lost_after_processing_is_replayed_not_reapplied(self):
        code = self.start_match()
        version = self.state(A, code)["gameVersion"]
        body = json.dumps({"action_id": "lost-reply-0001", "expected_version": version, "action": "raise", "to": 100}).encode()
        sock = socket.create_connection(("127.0.0.1", self.api.server_port), timeout=5)
        sock.sendall(b"POST /api/rooms/" + code.encode() + b"/action HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                     b"Authorization: Bearer " + A.encode() + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
        sock.close()  # the client never reads the answer
        for _ in range(50):
            if self.state(B, code)["gameVersion"] > version:
                break
            time.sleep(0.05)
        self.assertEqual(self.state(B, code)["gameVersion"], version + 1)  # the server did process it
        status, result = self.act(A, code, "raise", to=100, action_id="lost-reply-0001", version=version)
        self.assertEqual((status, result.get("replayed")), (200, True))
        self.assertEqual(self.stacks(code), [900, 980])
        # a request that never left the client is simply sent for the first time later
        status, result = self.act(B, code, "call", action_id="never-sent-0001")
        self.assertEqual((status, result.get("replayed")), (200, None))
        self.assertEqual(self.stacks(code), [900, 900])

    def check_record_and_recovered_chips_agree(self, durable):
        code = self.start_match()
        original = self.fault_dbms("room_hand_results", durable=durable)
        end = self.play_to_showdown(code)  # seat 1 wins 40 at showdown
        self.assertEqual((end["recordStatus"], [s["stack"] for s in end["seats"]]), ("unknown", [980, 1020]))
        self.demo._call = original
        self._install_demo()  # API restarts while the result is still unconfirmed
        self.wire_rooms()
        a, b = self.state(A, code), self.state(B, code)
        rows = self.ledger()
        expected = [980, 1020] if durable else [1000, 1000]
        self.assertEqual(len(rows), 1 if durable else 0)
        self.assertEqual([s["stack"] for s in a["seats"]], expected)
        self.assertEqual([s["stack"] for s in b["seats"]], expected)
        pa = self.call(A, "/api/profile")[1]["profile"]
        pb = self.call(B, "/api/profile")[1]["profile"]
        if durable:
            self.assertEqual((pa["online"]["hands"], pa["online"]["losses"], pb["online"]["wins"]), (1, 1, 1))
            self.assertEqual((pa["recentOnline"][0]["endStack"], pb["recentOnline"][0]["endStack"]), tuple(expected))
        else:
            self.assertEqual((pa["online"]["hands"], pb["online"]["hands"]), (0, 0))
        # play continues from exactly those stacks and the next hand is stored once
        self.ready(A, code, a["handNo"])
        self.ready(B, code, a["handNo"])
        self.assertEqual(self.state(A, code)["handNo"], a["handNo"] + 1)
        view = self.state(A, code)
        self.act((A, B)[view["turnSeat"]], code, "fold")
        rows = self.ledger()
        self.assertEqual(len(rows), 2 if durable else 1)
        self.assertEqual((rows[-1]["start_a"], rows[-1]["start_b"]), tuple(expected))

    def test_stored_but_unacknowledged_result_then_api_restart_keeps_record_and_chips_consistent(self):
        self.check_record_and_recovered_chips_agree(durable=True)

    def test_unstored_result_then_api_restart_voids_the_hand_in_record_and_chips_alike(self):
        self.check_record_and_recovered_chips_agree(durable=False)

    def test_stale_preview_cache_never_grants_a_seat(self):
        code = self.create_and_join()
        self.call(B, f"/api/rooms/{code}/leave", {})
        stale = self.redis_store.get("poker:room:" + code)  # lobby with one free seat
        self.assertEqual(sum(seat["occupied"] for seat in stale["seats"]), 1)
        self.call(B, f"/api/rooms/{code}/join", {})
        self.ready(A, code, 0)
        self.ready(B, code, 0)
        self.redis_store.set("poker:room:" + code, stale, 30)  # an old value is put back into the cache
        status, public = self.call(None, f"/api/rooms/{code}/public")
        self.assertEqual((public["cache"], public["room"]["phase"]), ("HIT", "lobby"))  # preview may be stale
        status, result = self.call(C, f"/api/rooms/{code}/join", {})
        self.assertEqual((status, result["error"]), (409, "room_full"))  # the preview shows a free seat; the server knows better
        self.assertEqual(self.call(C, f"/api/rooms/{code}/state")[0], 403)
        self.assertEqual(self.state(A, code)["phase"], "playing")

    def test_redis_ttl_expiry_and_redis_restart_only_cause_a_miss(self):
        code = self.start_match()
        redis_now = [1000.0]
        self.redis_store._clock = lambda: redis_now[0]
        self.act(A, code, "call")  # written with the fake Redis clock
        self.assertEqual(self.call(None, f"/api/rooms/{code}/public")[1]["cache"], "HIT")
        redis_now[0] += self.rooms.PUBLIC_TTL_SECONDS + 1
        status, public = self.call(None, f"/api/rooms/{code}/public")
        self.assertEqual((public["cache"], public["room"]["pot"]), ("MISS", 40))
        self.assertEqual(self.call(None, f"/api/rooms/{code}/public")[1]["cache"], "HIT")
        # Redis restarts with an empty store
        self.redis.shutdown()
        self.redis.server_close()
        self.redis_thread.join(2)
        self.redis_store = integration.MiniRedis()
        self.redis = integration.ThreadingHTTPServer(("127.0.0.1", self.redis.server_port), integration.make_handler(self.redis_store))
        self.redis_thread = self._start(self.redis)
        self.assertEqual(self.call(None, f"/api/rooms/{code}/public")[1]["cache"], "MISS")
        self.assertEqual(self.call(None, f"/api/rooms/{code}/public")[1]["cache"], "HIT")
        self.assertEqual(self.act(B, code, "check")[0], 200)
        self.assertEqual(self.state(A, code)["street"], "flop")


if __name__ == "__main__":
    unittest.main()
