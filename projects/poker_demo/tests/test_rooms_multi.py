"""3-4 person rooms over real HTTP with disposable DBMS files. Expected chips are worked out by hand."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest

import test_rooms
import test_server as integration
from rooms import BUY_IN, match_key_for, replay_ledger
from test_engine import deck_with_prefix
from test_rooms import A, B, C

D = "D" * 43
E = "E" * 43
R = test_rooms.RoomTests

# Hand 1 (button 0, SB 1, BB 2, UTG 3; dealt 1,2,3,0): seat1 A♠A♥ beats seat0 K♠K♥ on 2♣ 7♦ 9♥ 4♠ 3♦.
HAND1 = deck_with_prefix("A♠", "Q♣", "J♣", "K♠", "A♥", "Q♦", "J♦", "K♥", "8♣", "2♣", "7♦", "9♥", "8♦", "4♠", "8♥", "3♦")
# Hand 2 (button 1, SB 2, BB 3, UTG 0; dealt 2,3,0,1): seat0 A♠A♥ > seat2 K♠K♥ > seat3 Q♠Q♥ > seat1 4♣5♥
# on 2♣ 7♦ 9♥ J♠ 3♦.
# 3-handed bust (button 0, SB 1, BB 2; dealt 1,2,0): seat1 A♠A♥ > seat0 K♠K♥ > seat2 Q♣Q♦ on 2♣ 7♦ 9♥ 4♠ 3♦.
BUST3 = deck_with_prefix("A♠", "Q♣", "K♠", "A♥", "Q♦", "K♥", "8♣", "2♣", "7♦", "9♥", "8♦", "4♠", "8♥", "3♦")
HAND2 = deck_with_prefix("K♠", "Q♠", "A♠", "4♣", "K♥", "Q♥", "A♥", "5♥", "8♣", "2♣", "7♦", "9♥", "8♦", "J♠", "8♥", "3♦")


class MultiRoomTests(unittest.TestCase):
    _start = classmethod(integration.PokerHTTPIntegrationTests._start.__func__)
    _install_demo = integration.PokerHTTPIntegrationTests._install_demo
    tearDown = integration.PokerHTTPIntegrationTests.tearDown
    call = R.call
    new_id = R.new_id
    state = R.state
    act = R.act
    ledger = R.ledger
    fault_dbms = R.fault_dbms

    def setUp(self):
        integration.PokerHTTPIntegrationTests.setUp(self)
        self.clock = test_rooms.FakeClock()
        self.decks = []
        self.wire_rooms()
        self.ids = 0
        for token, name in ((A, "Alpha"), (B, "Bravo"), (C, "Carol"), (D, "Delta"), (E, "Echo")):
            status, result = self.call(None, "/api/guest", {"guest_token": token, "display_name": name})
            self.assertEqual(status, 200, result)

    def wire_rooms(self):
        self.rooms = self.demo.rooms
        self.rooms.clock = self.clock
        fallback = test_rooms.DECK

        def deck():
            return list(self.decks.pop(0)) if self.decks else list(fallback)

        self.rooms.deck_factory = deck

    def restart_api(self):
        self._install_demo()
        self.wire_rooms()

    def create(self, token=A, seats=4):
        status, result = self.call(token, "/api/rooms", {"request_id": self.new_id("create"), "max_seats": seats})
        self.assertEqual(status, 200, result)
        return result["state"]["code"]

    def join(self, token, code):
        return self.call(token, f"/api/rooms/{code}/join", {})

    def ready(self, token, code, hand_no=None, value=True):
        if hand_no is None:
            hand_no = self.state(token, code)["handNo"]
        return self.call(token, f"/api/rooms/{code}/ready", {"ready": value, "hand_no": hand_no})

    def table(self, players=(A, B, C, D)):
        code = self.create(players[0])
        for token in players[1:]:
            self.assertEqual(self.join(token, code)[0], 200)
        for token in players:
            self.ready(token, code, 0)
        self.assertEqual(self.state(A, code)["phase"], "playing")
        return code

    def turn_token(self, code, tokens=(A, B, C, D, E)):
        view = self.state(A, code)
        seat = view["turnSeat"]
        for token in tokens:
            if self.state(token, code)["you"]["seat"] == seat:
                return token
        raise AssertionError("nobody owns the turn")

    def play(self, code, *steps):
        """steps: (token, action[, to]); asserts it is that token's turn."""
        for token, action, *rest in steps:
            view = self.state(token, code)
            self.assertTrue(view["seats"][view["you"]["seat"]]["isTurn"], (token[:1], action, view["turnSeat"]))
            status, result = self.act(token, code, action, to=rest[0] if rest else None)
            self.assertEqual(status, 200, (token[:1], action, result))

    def stacks(self, code):
        return [s["stack"] for s in self.state(A, code)["seats"]]

    def replayed(self, code):
        key = match_key_for(code)
        seats = [dict(r) for r, _ in self.database.tables["room_seat_events"].rows if r["match_key"] == key]
        hands = [dict(r) for r, _ in self.database.tables["room_hand_results"].rows if r["match_key"] == key]
        return replay_ledger(key, seats, hands)

    def two_hand_side_pots(self):
        self.decks = [HAND1, HAND2]
        code = self.table()
        view = self.state(A, code, after=0)
        start = [e for e in view["events"] if e["type"] == "hand_start"][0]
        self.assertEqual((start["button"], start["sb"], start["bb"], start["participants"]), (0, 1, 2, [0, 1, 2, 3]))
        self.assertEqual(view["turnSeat"], 3)  # UTG left of the big blind
        # hand 1: limp around, flop 80 x4, turn 100 (D folds), river 100 (C folds); B beats A.
        self.play(code, (D, "call"), (A, "call"), (B, "call"), (C, "check"),
                  (B, "bet", 80), (C, "call"), (D, "call"), (A, "call"),
                  (B, "bet", 100), (C, "call"), (D, "fold"), (A, "call"),
                  (B, "bet", 100), (C, "fold"), (A, "call"))
        # A lost 300, C 200, D 100; B won 600
        self.assertEqual(self.stacks(code), [700, 1600, 800, 900])
        for token in (A, B, C, D):
            self.ready(token, code, 1)
        view = self.state(A, code, after=0)
        start = [e for e in view["events"] if e["type"] == "hand_start"][-1]
        self.assertEqual((start["button"], start["sb"], start["bb"]), (1, 2, 3))
        # hand 2: everybody all-in: 700 / 1600 / 800 / 900
        self.play(code, (A, "all_in"), (B, "all_in"), (C, "all_in"), (D, "all_in"))
        return code

    # ── seats, start, host ─────────────────────────────────────────────────

    def test_lobby_start_rules_host_and_capacity(self):
        code = self.create()
        for token in (B, C):
            self.join(token, code)
        self.ready(A, code, 0)
        self.ready(B, code, 0)
        self.assertEqual(self.state(A, code)["phase"], "lobby")  # C not ready, so no automatic start
        self.assertTrue(self.state(A, code)["canStart"])
        self.assertFalse(self.state(B, code)["canStart"])
        status, result = self.call(B, f"/api/rooms/{code}/start", {"hand_no": 0})
        self.assertEqual((status, result["error"]), (403, "not_host"))
        status, result = self.call(A, f"/api/rooms/{code}/start", {"hand_no": 0})
        self.assertEqual(status, 200, result)
        view = result["state"]
        self.assertEqual(view["phase"], "playing")
        self.assertEqual([s["inHand"] for s in view["seats"]], [True, True, False, False])  # C sits out
        self.assertEqual(self.state(C, code)["seats"][2]["cards"], None)
        # C readies during the hand and is dealt into the next one
        self.assertEqual(self.ready(C, code, 1)[0], 200)
        token = self.turn_token(code)
        self.act(token, code, "fold")
        for t in (A, B):
            self.ready(t, code, 1)
        self.assertEqual([s["inHand"] for s in self.state(A, code)["seats"]], [True, True, True, False])
        self.assertEqual(self.state(A, code)["handNo"], 2)

    def test_auto_start_when_everybody_is_ready_and_host_passes_on_in_the_lobby(self):
        code = self.create()
        self.join(B, code)
        self.join(C, code)
        status, result = self.call(A, f"/api/rooms/{code}/start", {"hand_no": 0})
        self.assertEqual((status, result["error"]), (409, "not_enough_ready"))
        self.call(A, f"/api/rooms/{code}/leave", {})
        view = self.state(B, code)
        self.assertEqual((view["hostSeat"], view["you"]["isHost"]), (1, True))
        self.ready(B, code, 0)
        self.ready(C, code, 0)
        self.assertEqual(self.state(C, code)["phase"], "playing")
        matches = [r for r, _ in self.database.tables["room_matches"].rows]
        buyins = {r["seat"]: r["user_db"] for r, _ in self.database.tables["room_seat_events"].rows if r["kind"] == "buyin"}
        self.assertEqual([m["host_user"] for m in matches], [buyins[1]])
        self.assertEqual(sorted(buyins), [1, 2])  # A left before the match and never bought in

    def test_three_players_racing_for_the_last_two_seats(self):
        for attempt in range(4):
            code = self.create(A, seats=3)
            barrier = threading.Barrier(3)

            def join(token):
                barrier.wait(5)
                return self.join(token, code)

            with ThreadPoolExecutor(3) as pool:
                results = list(pool.map(join, (B, C, D)))
            self.assertEqual(sorted(s for s, _ in results), [200, 200, 409])
            seats = [s["name"] for s in self.state(A, code)["seats"]]
            self.assertEqual(len(set(seats)), 3)

    def test_capacity_must_be_two_to_four(self):
        for bad in (1, 5, "4", True, None):
            status, _ = self.call(A, "/api/rooms", {"request_id": self.new_id("bad"), "max_seats": bad})
            self.assertEqual(status, 400, bad)
        self.assertEqual(self.state(A, self.create())["capacity"], 4)

    # ── rules and settlement ───────────────────────────────────────────────

    def test_four_players_side_pots_with_different_winners(self):
        code = self.two_hand_side_pots()
        view = self.state(A, code, after=0)
        self.assertEqual(view["phase"], "hand_over")
        # contributions 700/1600/800/900: 700 of seat 1 returns; main 2800 (all) -> seat 0,
        # side 300 (1,2,3) -> seat 2, side 200 (1,3) -> seat 3
        pots = [(p["amount"], p["eligible"], p["winners"]) for p in view["result"]["pots"]]
        self.assertEqual(pots, [(2800, [0, 1, 2, 3], [0]), (300, [1, 2, 3], [2]), (200, [1, 3], [3])])
        self.assertEqual(self.stacks(code), [2800, 700, 300, 200])
        self.assertEqual(sum(self.stacks(code)), 4 * BUY_IN)
        returned = [e for e in view["events"] if e["type"] == "returned"]
        self.assertEqual([(e["seat"], e["amount"]) for e in returned], [(1, 700)])
        self.assertEqual([len(e["board"]) for e in view["events"] if e["type"] == "street" and e["handNo"] == 2], [3, 4, 5])
        # all hands still in are shown at the showdown, to everyone
        for token in (A, B, C, D):
            self.assertTrue(all(s["cards"] for s in self.state(token, code)["seats"]))
        rows = self.ledger()
        self.assertEqual([r["hand_no"] for r in rows], [1, 2])
        ledger = self.replayed(code)
        self.assertEqual(sorted(ledger["stacks"].values()), [200, 300, 700, 2800])

    def test_private_cards_in_a_four_player_room(self):
        self.decks = [HAND1]
        code = self.table()
        raws, views = {}, {}
        for token in (A, B, C, D):
            views[token] = self.state(token, code, after=0)
            raws[token] = self.last_raw
        holes = {t: views[t]["seats"][views[t]["you"]["seat"]]["cards"] for t in (A, B, C, D)}
        self.assertEqual(len({c for cards in holes.values() for c in cards}), 8)
        for viewer in (A, B, C, D):
            for owner in (A, B, C, D):
                if owner != viewer:
                    for card in holes[owner]:
                        self.assertNotIn(card, raws[viewer])
            self.assertEqual(sum(1 for s in views[viewer]["seats"] if s["cards"]), 1)
        cached = json.dumps(self.redis_store.get("poker:room:" + code), ensure_ascii=False)
        public = self.call(None, f"/api/rooms/{code}/public")[1]
        for cards in holes.values():
            for card in cards:
                self.assertNotIn(card, cached)
                self.assertNotIn(card, json.dumps(public, ensure_ascii=False))
        # play hand 1 to its showdown between A and B: C and D folded and are never revealed
        self.play(code, (D, "call"), (A, "call"), (B, "call"), (C, "check"),
                  (B, "bet", 80), (C, "call"), (D, "call"), (A, "call"),
                  (B, "bet", 100), (C, "call"), (D, "fold"), (A, "call"),
                  (B, "bet", 100), (C, "fold"), (A, "call"))
        for viewer in (A, B, C, D):
            view = self.state(viewer, code, after=0)
            raw = self.last_raw
            shown = {s["seat"] for s in view["seats"] if s["cards"]}
            me = view["you"]["seat"]
            self.assertEqual(shown, {0, 1} | {me})
            for owner in (C, D):
                if owner != viewer:
                    for card in holes[owner]:
                        self.assertNotIn(card, raw)
        for row in self.ledger():
            for cards in holes.values():
                for card in cards:
                    self.assertNotIn(card, row["participants"] + row["pots"] + row["public_actions"])

    def test_three_way_fold_order_timeout_and_heads_up_after_a_bust(self):
        code = self.table((A, B, C))
        # 3-handed: button 0 is first pre-flop
        view = self.state(A, code)
        self.assertEqual((view["turnSeat"], [s["isButton"] for s in view["seats"]][:3]), (0, [True, False, False]))
        self.play(code, (A, "raise", 100))
        self.clock.now += self.rooms.TURN_SECONDS + 1  # B (SB) faces 100 and times out -> fold
        view = self.state(C, code, after=0)
        auto = [e for e in view["events"] if e["type"] == "action" and e["auto"]]
        self.assertEqual([(e["seat"], e["action"]) for e in auto], [(1, "fold")])
        self.assertEqual(view["turnSeat"], 2)
        self.play(code, (C, "fold"))
        # A wins B's 10 and C's 20; its own 100 is matched by nobody and 80 returns
        self.assertEqual(self.stacks(code)[:3], [1030, 990, 980])
        self.assertEqual(sum(self.stacks(code)), 3000)

    # ── rules v2: bust -> watch one hand -> one 1,000-chip rebuy ─────────

    def bust_alpha(self, two=False):
        """3-handed hand 1 (button 0): A (KK) all-in, B (AA) calls; C folds, or calls too when `two`.
        A busts (and C too when `two`), B wins; worked out by hand from the deck below."""
        self.decks = [BUST3]
        code = self.table((A, B, C))
        self.play(code, (A, "all_in"), (B, "call"), (C, "call" if two else "fold"))
        return code

    def rebuy_rows(self):
        return [dict(r) for r, _ in self.database.tables["room_seat_events"].rows if r["kind"] == "rebuy"]

    def finish_hand(self, code, tokens):
        for _ in range(3):
            if self.state(A, code)["phase"] != "playing":
                return
            self.act(self.turn_token(code, tokens), code, "fold")

    def test_bust_watches_one_hand_then_one_rebuy_and_is_dealt_back_in(self):
        code = self.bust_alpha()
        view = self.state(A, code)
        self.assertEqual([s["stack"] for s in view["seats"]][:3], [0, 2020, 980])
        me = view["seats"][0]
        self.assertEqual((view["phase"], me["busted"], me["bustHand"], me["rebuyAfterHand"], me["connected"]),
                         ("hand_over", True, 1, 2, True))
        self.assertEqual(self.ready(A, code, 1)[1]["error"], "busted")  # cannot skip the wait
        for t in (B, C):
            self.ready(t, code, 1)
        view = self.state(A, code)
        self.assertEqual((view["handNo"], [s["inHand"] for s in view["seats"]][:3]), (2, [False, True, True]))  # A watches hand 2
        # refresh / reconnect / repeated requests during the watched hand change nothing
        for _ in range(3):
            self.assertEqual(self.join(A, code)[0], 200)
            self.state(A, code)
        self.assertEqual(self.ready(A, code, 2)[1]["error"], "busted")
        self.assertEqual((self.state(A, code)["seats"][0]["stack"], self.rebuy_rows()), (0, []))
        self.finish_hand(code, (B, C))
        view = self.state(A, code)
        self.assertEqual((view["phase"], view["recordStatus"]), ("hand_over", "confirmed"))
        me = view["seats"][0]
        self.assertEqual((me["stack"], me["busted"], me["sittingIn"], me["bustHand"]), (1000, False, True, None))
        self.assertEqual([(r["seat"], r["amount"], r["after_hand"]) for r in self.rebuy_rows()], [(0, 1000, 2)])
        for _ in range(3):  # back automatically, without pressing anything (everyone keeps polling)
            self.clock.now += self.rooms.NEXT_HAND_SECONDS / 3 + 0.1
            for t in (A, B, C):
                self.state(t, code)
        view = self.state(A, code)
        self.assertEqual((view["handNo"], [s["inHand"] for s in view["seats"]][:3]), (3, [True, True, True]))
        ledger = self.replayed(code)
        self.assertEqual((ledger["buy_ins"], ledger["rebuys"], ledger["cash_outs"]), (3000, 1000, 0))
        self.assertEqual(sum(s["stack"] for s in view["seats"]) + view["pot"], 4000)
        online = self.call(A, "/api/profile")[1]["profile"]["online"]
        self.assertEqual((online["hands"], online["losses"], online["wins"], online["rebuys"]), (1, 1, 0, 1))

    def check_rebuy_storage_fault(self, durable, restart):
        code = self.bust_alpha()
        for t in (B, C):
            self.ready(t, code, 1)
        original = self.demo._call

        def flaky(service, method, url, body=None, trace_id=None):
            if service == "Mini DBMS" and body and body.get("sql", "").startswith("INSERT INTO room_seat_events") and "rebuy" in body.get("params", []):
                if durable:
                    original(service, method, url, body, trace_id)  # stored, but the reply is lost
                return None, {"traceId": trace_id, "service": service, "method": method, "path": "/sql/insert-once", "outcome": "unavailable"}
            return original(service, method, url, body, trace_id)

        self.demo._call = flaky
        self.finish_hand(code, (B, C))
        view = self.state(A, code)
        self.assertEqual((view["phase"], view["seats"][0]["stack"]), ("hand_over", 0))  # not paid until confirmed
        for t in (B, C):
            self.ready(t, code, 2)
        self.clock.now += self.rooms.NEXT_HAND_SECONDS + 1
        self.assertEqual(self.state(B, code)["handNo"], 2)  # the next hand waits for the rebuy record
        self.assertEqual(self.join(D, code)[1]["error"], "result_storage_pending")
        self.assertEqual(len(self.rebuy_rows()), 1 if durable else 0)
        if restart:
            self.restart_api()
        else:
            self.demo._call = original
            self.clock.now += self.rooms.STORAGE_RETRY_SECONDS + 1
        view = self.state(A, code)
        me = view["seats"][0]
        self.assertEqual(me["stack"] + me["committed"], 1000)  # paid once (the next hand may already have taken a blind)
        self.assertEqual([(r["seat"], r["after_hand"]) for r in self.rebuy_rows()], [(0, 2)])  # exactly one row
        ledger = self.replayed(code)
        self.assertEqual(sum(s["stack"] for s in view["seats"]) + view["pot"], 3000 + ledger["rebuys"])
        self.assertEqual(ledger["rebuys"], 1000)

    def test_rebuy_storage_down_then_retry_pays_once(self):
        self.check_rebuy_storage_fault(durable=False, restart=False)

    def test_rebuy_lost_reply_then_retry_pays_once(self):
        self.check_rebuy_storage_fault(durable=True, restart=False)

    def test_rebuy_unstored_then_restart_pays_once(self):
        self.check_rebuy_storage_fault(durable=False, restart=True)

    def test_rebuy_lost_reply_then_restart_pays_once(self):
        self.check_rebuy_storage_fault(durable=True, restart=True)

    def test_restart_while_watching_keeps_the_wait(self):
        code = self.bust_alpha()
        self.restart_api()
        view = self.state(A, code)
        self.assertEqual((view["phase"], view["seats"][0]["stack"], view["seats"][0]["rebuyAfterHand"]), ("hand_over", 0, 2))
        self.assertEqual(self.rebuy_rows(), [])  # a restart does not shorten the wait

    def test_two_bust_at_once_next_round_pays_each_once(self):
        code = self.bust_alpha(two=True)
        view = self.state(C, code)
        self.assertEqual([s["stack"] for s in view["seats"]][:3], [0, 3000, 0])
        self.assertEqual((view["phase"], view["canNextRound"]), ("round_over", True))
        for token in (A, B, C):  # every hand that reached the showdown is shown, also in round_over
            self.assertEqual([bool(s["cards"]) for s in self.state(token, code)["seats"]][:3], [True, True, True], token)
        self.assertEqual(self.ready(B, code, 1)[0], 200)  # the winner is ready; still nobody to play with
        self.assertEqual(self.state(B, code)["phase"], "round_over")
        self.restart_api()  # survives a restart before anyone presses
        view = self.state(C, code)
        self.assertEqual((view["phase"], view["canNextRound"]), ("round_over", True))
        body = {"hand_no": 1}
        with ThreadPoolExecutor(6) as pool:  # everyone presses at once, some twice
            results = list(pool.map(lambda t: self.call(t, f"/api/rooms/{code}/next-round", body), (A, B, C, A, B, C)))
        self.assertEqual(sorted(st for st, _ in results), [200, 409, 409, 409, 409, 409])
        view = self.state(A, code)
        self.assertEqual(([s["stack"] for s in view["seats"]][:3], view["phase"]), ([1000, 3000, 1000], "hand_over"))
        self.assertEqual(sorted((r["seat"], r["after_hand"]) for r in self.rebuy_rows()), [(0, 1), (2, 1)])
        ledger = self.replayed(code)
        self.assertEqual((ledger["buy_ins"], ledger["rebuys"]), (3000, 2000))
        for t in (A, B, C):
            self.ready(t, code, 1)
        self.assertEqual([s["inHand"] for s in self.state(A, code)["seats"]][:3], [True, True, True])
        self.restart_api()
        self.assertEqual(self.replayed(code)["rebuys"], 2000)  # nothing paid again on recovery
        profiles = {t: self.call(t, "/api/profile")[1]["profile"]["online"] for t in (A, B, C)}
        self.assertEqual([profiles[t]["rebuys"] for t in (A, B, C)], [1, 0, 1])
        self.assertEqual([profiles[t]["wins"] for t in (A, B, C)], [0, 1, 0])

    def test_next_round_rules(self):
        code = self.bust_alpha()
        # chip holders B and C remain: no round_over, the button is not offered
        view = self.state(A, code)
        self.assertEqual((view["phase"], view["canNextRound"]), ("hand_over", False))
        status, result = self.call(A, f"/api/rooms/{code}/next-round", {"hand_no": 1})
        self.assertEqual((status, result["error"]), (409, "not_round_over"))
        for bad in ({}, {"hand_no": "1"}, {"hand_no": True}, {"hand_no": 1, "x": 1}):
            self.assertEqual(self.call(A, f"/api/rooms/{code}/next-round", bad)[0], 400, bad)
        self.assertEqual(self.call(D, f"/api/rooms/{code}/next-round", {"hand_no": 1})[1]["error"], "not_seated")
        # C cashes out: only B has chips -> round_over; A is paid at the restart
        status, result = self.call(C, f"/api/rooms/{code}/leave", {})
        self.assertEqual((status, result["cashOut"]), (200, 980))
        view = self.state(A, code)
        self.assertEqual((view["phase"], view["canNextRound"]), ("round_over", True))
        self.assertEqual(self.call(A, f"/api/rooms/{code}/next-round", {"hand_no": 1})[0], 200)
        view = self.state(B, code)
        self.assertEqual(([s["stack"] for s in view["seats"]][:3], view["phase"]), ([1000, 2020, 0], "hand_over"))
        ledger = self.replayed(code)
        self.assertEqual(sum(ledger["stacks"].values()), ledger["buy_ins"] + ledger["rebuys"] - ledger["cash_outs"])

    # ── joining, leaving, restart ─────────────────────────────────────────

    def test_mid_hand_join_leave_cash_out_and_restart_keep_every_chip(self):
        code = self.table((A, B, C))
        status, result = self.join(D, code)  # joins while hand 1 is running
        self.assertEqual(status, 200, result)
        me = result["state"]["seats"][3]
        self.assertEqual((me["stack"], me["inHand"], me["cards"]), (1000, False, None))
        self.assertEqual(self.ready(D, code, 1)[0], 200)
        # B cannot leave in the middle of its own hand
        status, result = self.call(B, f"/api/rooms/{code}/leave", {})
        self.assertEqual((status, result["error"]), (409, "match_in_progress"))
        token = self.turn_token(code, (A, B, C))
        self.act(token, code, "fold")
        token = self.turn_token(code, (A, B, C))
        self.act(token, code, "fold")
        hand1 = self.stacks(code)
        self.assertEqual(sum(hand1), 4000)
        # between hands B cashes out what it has and cannot sit down again in this match
        b_chips = hand1[1]
        status, result = self.call(B, f"/api/rooms/{code}/leave", {})
        self.assertEqual((status, result["cashOut"]), (200, b_chips))
        self.assertEqual(self.join(B, code)[1]["error"], "left_match")
        for t in (A, C, D):
            self.ready(t, code, 1)
        view = self.state(A, code)
        self.assertEqual([s["inHand"] for s in view["seats"]], [True, False, True, True])
        ledger = self.replayed(code)
        self.assertEqual((ledger["buy_ins"], ledger["cash_outs"]), (4000, b_chips))
        # a new player takes B's seat later: buy-in recorded, cash-out kept separate
        token = self.turn_token(code, (A, C, D))
        self.act(token, code, "fold")
        token = self.turn_token(code, (A, C, D))
        self.act(token, code, "fold")
        self.assertEqual(self.join(E, code)[0], 200)
        on_table = sum(s["stack"] for s in self.state(A, code)["seats"] if s["occupied"])
        ledger = self.replayed(code)
        self.assertEqual(on_table, ledger["buy_ins"] - ledger["cash_outs"])
        self.assertEqual((ledger["buy_ins"], ledger["cash_outs"]), (5000, b_chips))
        # restart: seats, chips, the cash-out and the late buy-in all come back
        before = {s["name"]: s["stack"] for s in self.state(A, code)["seats"] if s["occupied"]}
        self.restart_api()
        view = self.state(E, code)
        self.assertTrue(view["recovered"])
        self.assertEqual({s["name"]: s["stack"] for s in view["seats"] if s["occupied"]}, before)
        self.assertEqual(view["you"]["seat"], 1)
        self.assertEqual(self.join(B, code)[1]["error"], "left_match")

    def test_restart_mid_hand_voids_it_for_all_four_and_records_agree(self):
        code = self.two_hand_side_pots()  # hands 1 and 2 stored
        for t in (A, B, C, D):
            self.ready(t, code, 2)
        token = self.turn_token(code)
        self.act(token, code, "call")  # hand 3 in progress
        self.restart_api()
        view = self.state(A, code)
        self.assertEqual((view["phase"], view["handNo"], view["pot"]), ("hand_over", 2, 0))
        self.assertEqual(self.stacks(code), [2800, 700, 300, 200])
        profiles = {t: self.call(t, "/api/profile")[1]["profile"] for t in (A, B, C, D)}
        rows = self.ledger()
        for t, seat in ((A, 0), (B, 1), (C, 2), (D, 3)):
            online = profiles[t]["online"]
            nets = [json_net(r, seat) for r in rows]
            self.assertEqual(online["hands"], 2)
            self.assertEqual((online["wins"], online["losses"], online["draws"]),
                             (sum(n > 0 for n in nets), sum(n < 0 for n in nets), sum(n == 0 for n in nets)))
            self.assertEqual(profiles[t]["recentOnline"][0]["endStack"], self.stacks(code)[seat])
            self.assertEqual(profiles[t]["recentOnline"][0]["players"], 4)

    def check_storage_fault(self, durable):
        code = self.table((A, B, C))
        original = self.fault_dbms("room_hand_results", durable=durable)
        self.play(code, (A, "raise", 100), (B, "call"), (C, "fold"))
        for _ in range(3):
            self.play(code, (B, "check"), (A, "check"))
        view = self.state(A, code)
        self.assertEqual((view["phase"], view["recordStatus"]), ("hand_over", "unknown"))
        shown = self.stacks(code)
        self.assertEqual(sum(shown), 3000)
        # nobody may join or leave until the hand is on record
        self.assertEqual(self.join(D, code)[1]["error"], "result_storage_pending")
        self.assertEqual(self.call(C, f"/api/rooms/{code}/leave", {})[1]["error"], "result_storage_pending")
        for t in (A, B, C):
            self.ready(t, code, 1)
        self.assertEqual(self.state(A, code)["phase"], "hand_over")
        self.demo._call = original
        self.restart_api()  # the API restarts before the retry
        view = self.state(A, code)
        expected = shown if durable else [1000, 1000, 1000]
        self.assertEqual(self.stacks(code)[:3], expected[:3])
        self.assertEqual(len(self.ledger()), 1 if durable else 0)
        for t, seat in ((A, 0), (B, 1), (C, 2)):
            online = self.call(t, "/api/profile")[1]["profile"]["online"]
            self.assertEqual(online["hands"], 1 if durable else 0)
            if durable:
                self.assertEqual(self.call(t, "/api/profile")[1]["profile"]["recentOnline"][0]["endStack"], expected[seat])

    def test_lost_reply_then_restart_keeps_the_stored_hand(self):
        self.check_storage_fault(durable=True)

    def test_unstored_hand_then_restart_voids_it_for_everyone(self):
        self.check_storage_fault(durable=False)

    # ── concurrency, duplicates, presence ───────────────────────────────────

    def test_duplicate_and_racing_actions_from_four_players_apply_once(self):
        code = self.table()
        view = self.state(D, code)  # UTG
        body = {"action_id": "multi-dup-0001", "expected_version": view["gameVersion"], "action": "raise", "to": 100}
        with ThreadPoolExecutor(6) as pool:
            results = list(pool.map(lambda _: self.call(D, f"/api/rooms/{code}/action", body), range(6)))
        self.assertTrue(all(s == 200 for s, _ in results))
        self.assertEqual(sum(1 for _, r in results if not r.get("replayed")), 1)
        version = self.state(A, code)["gameVersion"]
        # everybody fires at the same version; only the seat on turn (A, the button) succeeds
        bodies = [(t, {"action_id": f"race-{i:04d}-{t[0]}", "expected_version": version, "action": "call"}) for i, t in enumerate((A, B, C, D) * 2)]
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda tb: self.call(tb[0], f"/api/rooms/{code}/action", tb[1]), bodies))
        self.assertEqual(sorted(s for s, _ in results).count(200), 1)
        actions = [e for e in self.state(A, code, after=0)["events"] if e["type"] == "action"]
        self.assertEqual([(e["seat"], e["action"]) for e in actions], [(3, "raise"), (0, "call")])
        self.assertEqual(sum(self.stacks(code)) + self.state(A, code)["pot"], 4000)

    def test_disconnected_player_sits_out_the_next_hand(self):
        code = self.table((A, B, C))
        for _ in range(2):
            token = self.turn_token(code, (A, B, C))
            self.act(token, code, "fold")
        self.clock.now += self.rooms.PRESENCE_SECONDS + 1
        self.state(A, code)
        self.state(B, code)  # C stopped polling
        view = self.state(A, code)
        self.assertFalse(view["seats"][2]["connected"])
        self.clock.now += self.rooms.NEXT_HAND_SECONDS
        self.state(A, code)
        view = self.state(B, code)
        self.assertEqual(view["handNo"], 2)
        self.assertEqual([s["inHand"] for s in view["seats"]][:3], [True, True, False])
        self.assertEqual(view["seats"][2]["stack"], self.stacks(code)[2])

    def test_a_token_from_another_room_has_no_rights_here(self):
        first = self.table((A, B))
        second = self.create(C)
        self.join(D, second)
        version = self.state(A, first)["gameVersion"]
        for path, body in ((f"/api/rooms/{first}/action", {"action_id": "cross-room-01", "expected_version": version, "action": "fold"}),
                           (f"/api/rooms/{first}/ready", {"ready": True, "hand_no": 1}),
                           (f"/api/rooms/{first}/state", None)):
            status, result = self.call(C, path, body)
            self.assertEqual((status, result["error"]), (403, "not_seated"))
        self.assertEqual(self.state(A, first)["gameVersion"], version)


del R  # keep unittest from collecting the imported two-seat suite twice


def json_net(row, seat):
    for p in json.loads(row["participants"]):
        if p["seat"] == seat:
            return p["end"] - p["start"]
    return None


if __name__ == "__main__":
    unittest.main()
