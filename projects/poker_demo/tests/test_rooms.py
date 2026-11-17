"""Two-human room play over real HTTP: two independent client sessions, disposable DBMS files.

These tests use two sessions on one machine. They do not prove play between two
different computers; that needs a separate manual check on a shared server.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import http.client
import json
import threading
import time
import unittest

import test_server as integration
from engine import PokerEngine
from test_engine import deck_with_prefix

A, B, C = "A" * 43, "B" * 43, "C" * 43
# Hand 1 (seat 0 is the button): seat 0 holds 2♦ 3♦, seat 1 holds A♠ K♠, board Q♠ J♠ T♠ 4♦ 5♥ -> seat 1 wins.
# Hand 2 (seat 1 is the button): the hole cards swap, so seat 0 wins.
# Cards are dealt one at a time starting left of the button (heads-up: the big blind first).
DECK = deck_with_prefix("A♠", "2♦", "K♠", "3♦", "4♥", "Q♠", "J♠", "T♠", "6♥", "4♦", "7♥", "5♥")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RoomTests(unittest.TestCase):
    # Reuse the real-services fixture without inheriting (and re-running) the bot-mode tests.
    _start = classmethod(integration.PokerHTTPIntegrationTests._start.__func__)
    _install_demo = integration.PokerHTTPIntegrationTests._install_demo
    tearDown = integration.PokerHTTPIntegrationTests.tearDown

    def setUp(self):
        integration.PokerHTTPIntegrationTests.setUp(self)
        self.clock = FakeClock()
        self.wire_rooms()
        self.ids = 0
        for token, name in ((A, "Alpha"), (B, "Bravo"), (C, "Carol")):
            status, result = self.call(None, "/api/guest", {"guest_token": token, "display_name": name})
            self.assertEqual(status, 200, result)

    def wire_rooms(self):
        self.rooms = self.demo.rooms
        self.rooms.clock = self.clock
        self.rooms.deck_factory = lambda: list(DECK)

    def call(self, token, path, body=None, method=None, timeout=10):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=timeout)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        method = method or ("GET" if body is None else "POST")
        conn.request(method, path, None if method == "GET" else json.dumps(body or {}, ensure_ascii=False).encode("utf-8"), headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        self.last_raw = raw
        return response.status, json.loads(raw)

    def new_id(self, prefix="act"):
        self.ids += 1
        return f"{prefix}-{self.ids:08d}"

    def state(self, token, code, **query):
        suffix = "&".join(f"{key}={value}" for key, value in query.items())
        status, result = self.call(token, f"/api/rooms/{code}/state" + ("?" + suffix if suffix else ""))
        self.assertEqual(status, 200, result)
        return result["state"]

    def create_and_join(self):
        status, result = self.call(A, "/api/rooms", {"request_id": self.new_id("create"), "max_seats": 2})
        self.assertEqual(status, 200, result)
        code = result["state"]["code"]
        status, result = self.call(B, f"/api/rooms/{code}/join", {})
        self.assertEqual(status, 200, result)
        return code

    def ready(self, token, code, hand_no, value=True):
        return self.call(token, f"/api/rooms/{code}/ready", {"ready": value, "hand_no": hand_no})

    def start_match(self):
        code = self.create_and_join()
        self.assertEqual(self.ready(A, code, 0)[0], 200)
        status, result = self.ready(B, code, 0)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["state"]["phase"], "playing")
        return code

    def act(self, token, code, action, to=None, action_id=None, version=None):
        if version is None:
            version = self.state(token, code)["gameVersion"]
        body = {"action_id": action_id or self.new_id(), "expected_version": version, "action": action}
        if to is not None:
            body["to"] = to
        return self.call(token, f"/api/rooms/{code}/action", body)

    def play_to_showdown(self, code):
        """Call preflop, then check every street. Whoever is on turn acts."""
        for _ in range(12):
            view = self.state(A, code)
            if view["phase"] != "playing":
                return view
            token = (A, B)[view["turnSeat"]]
            mine = self.state(token, code)
            action = "call" if "call" in mine["legalActions"] else "check"
            status, result = self.act(token, code, action)
            self.assertEqual(status, 200, result)
        self.fail("hand did not finish")

    def ledger(self):
        """Stored room hands; two-seat views (start_a/b, end_a/b, winner) are derived for the two-seat tests."""
        rows = []
        for row, _ in self.database.tables["room_hand_results"].rows:
            row = dict(row)
            seats = {p["seat"]: p for p in json.loads(row["participants"])}
            if set(seats) == {0, 1}:
                row.update(start_a=seats[0]["start"], start_b=seats[1]["start"], end_a=seats[0]["end"], end_b=seats[1]["end"])
                net = row["end_a"] - row["start_a"]
                row["winner"] = "human" if net > 0 else "bot" if net < 0 else "tie"
            rows.append(row)
        return rows

    def fault_dbms(self, table, durable=False):
        """Make INSERTs into one table look unanswered. durable=True: the row is stored but the reply is lost."""
        original = self.demo._call

        def call(service, method, url, body=None, trace_id=None):
            if service == "Mini DBMS" and body and body.get("sql", "").startswith("INSERT INTO " + table):
                if durable:
                    original(service, method, url, body, trace_id)
                return None, {"traceId": trace_id, "service": service, "method": method, "path": "/sql/insert-once", "outcome": "unavailable"}
            return original(service, method, url, body, trace_id)

        self.demo._call = call
        return original

    # ── room, seats, start ──────────────────────────────────────────────────

    def test_create_join_ready_start_and_both_views_agree(self):
        status, created = self.call(A, "/api/rooms", {"request_id": "create-0000001", "max_seats": 2})
        self.assertEqual(status, 200, created)
        code = created["state"]["code"]
        self.assertEqual(created["state"]["you"], {"seat": 0, "name": "Alpha", "isHost": True})
        self.assertEqual(created["state"]["phase"], "lobby")
        # a double-clicked create returns the same room
        self.assertEqual(self.call(A, "/api/rooms", {"request_id": "create-0000001", "max_seats": 2})[1]["state"]["code"], code)
        self.assertEqual(len(self.rooms.rooms), 1)

        status, joined = self.call(B, f"/api/rooms/{code.lower()}/join", {})  # codes are case-insensitive
        self.assertEqual(status, 200, joined)
        self.assertEqual(joined["state"]["you"], {"seat": 1, "name": "Bravo", "isHost": False})
        self.assertEqual(self.call(B, f"/api/rooms/{code}/join", {})[1]["state"]["you"]["seat"], 1)  # idempotent

        status, result = self.ready(A, code, 0)
        self.assertEqual(result["state"]["phase"], "lobby")
        self.assertEqual([seat["ready"] for seat in result["state"]["seats"]], [True, False])
        status, result = self.ready(B, code, 0)
        self.assertEqual(result["state"]["phase"], "playing")

        a, b = self.state(A, code), self.state(B, code)
        for key in ("version", "gameVersion", "phase", "handNo", "street", "board", "pot", "turnSeat", "events", "lastEventSeq"):
            self.assertEqual(a[key], b[key], key)
        self.assertEqual((a["handNo"], a["pot"], a["turnSeat"]), (1, 30, 0))
        self.assertEqual([seat["stack"] for seat in a["seats"]], [990, 980])
        self.assertEqual([seat["name"] for seat in b["seats"]], ["Alpha", "Bravo"])
        self.assertEqual(a["legalActions"], ["fold", "call", "raise", "all_in"])
        self.assertEqual(b["legalActions"], [])  # only the player on turn is offered actions
        self.assertEqual(a["events"][0]["type"], "hand_start")
        matches = [row for row, _ in self.database.tables["room_matches"].rows]
        self.assertEqual((len(matches), matches[0]["capacity"]), (1, 2))
        buy_ins = [row for row, _ in self.database.tables["room_seat_events"].rows]
        self.assertEqual(sorted((r["kind"], r["seat"], r["amount"]) for r in buy_ins), [("buyin", 0, 1000), ("buyin", 1, 1000)])
        self.assertNotEqual(buy_ins[0]["user_db"], buy_ins[1]["user_db"])

    def test_hole_cards_are_private_in_every_response_and_cache(self):
        code = self.start_match()
        a = self.state(A, code, after=0)
        raw_a = self.last_raw
        b = self.state(B, code, after=0)
        raw_b = self.last_raw
        self.assertEqual(a["seats"][0]["cards"], ["2♦", "3♦"])
        self.assertIsNone(a["seats"][1]["cards"])
        self.assertEqual(b["seats"][1]["cards"], ["A♠", "K♠"])
        self.assertIsNone(b["seats"][0]["cards"])
        for card in ("A♠", "K♠", "Q♠", "4♥"):  # opponent cards, a future board card, a burn card
            self.assertNotIn(card, raw_a)
        for card in ("2♦", "3♦", "Q♠", "4♥"):
            self.assertNotIn(card, raw_b)
        self.assertNotIn("deck", raw_a)
        # action responses and error responses carry the same per-seat view
        status, result = self.act(A, code, "call")
        self.assertNotIn("A♠", self.last_raw)
        status, result = self.act(A, code, "check")  # not A's turn now
        self.assertEqual(status, 409)
        self.assertNotIn("A♠", self.last_raw)
        # public preview and the Redis value never contain hole cards
        status, public = self.call(None, f"/api/rooms/{code}/public")
        self.assertEqual(status, 200, public)
        for card in ("A♠", "K♠", "2♦", "3♦"):
            self.assertNotIn(card, self.last_raw)
        cached = json.dumps(self.redis_store.get("poker:room:" + code), ensure_ascii=False)
        for card in ("A♠", "K♠", "2♦", "3♦", "deck", "holes"):
            self.assertNotIn(card, cached)

    def test_full_hand_showdown_is_identical_on_both_screens_and_stored_once(self):
        code = self.start_match()
        self.play_to_showdown(code)
        a, b = self.state(A, code, after=0), self.state(B, code, after=0)
        self.assertEqual(a["events"], b["events"])  # same ordered events for both clients
        for key in ("version", "gameVersion", "phase", "board", "pot", "result", "recordStatus"):
            self.assertEqual(a[key], b[key], key)
        self.assertEqual(a["phase"], "hand_over")
        self.assertEqual(a["board"], ["Q♠", "J♠", "T♠", "4♦", "5♥"])
        self.assertEqual(a["result"]["winnerSeat"], 1)
        self.assertEqual(a["result"]["payouts"], [0, 40])
        self.assertEqual([seat["stack"] for seat in a["seats"]], [980, 1020])
        self.assertEqual(a["seats"][1]["cards"], ["A♠", "K♠"])  # showdown reveals both hands to both players
        self.assertEqual(b["seats"][0]["cards"], ["2♦", "3♦"])
        self.assertEqual(a["recordStatus"], "confirmed")
        types = [event["type"] for event in a["events"]]
        self.assertEqual(types, ["hand_start", "action", "action", "street", "action", "action", "street",
                                 "action", "action", "street", "action", "action", "hand_end"])
        first = a["events"][0]["seq"]
        self.assertEqual([event["seq"] for event in a["events"]], list(range(first, first + len(types))))  # gapless order
        for event in a["events"]:  # events are public: the only cards in them are board cards
            self.assertFalse(set(event) & {"cards", "holes", "deck"})
        # each event shows the table as it was at that moment; chips reach the winner only at hand_end
        for event in a["events"][:-1]:
            self.assertEqual(sum(event["stacks"]) + event["pot"], 2000, event)
            self.assertEqual(event["pot"], sum(event["committed"]))
        self.assertEqual((a["events"][0]["stacks"], a["events"][0]["pot"]), ([990, 980], 30))
        self.assertEqual((a["events"][-2]["stacks"], a["events"][-2]["pot"], len(a["events"][-2]["board"])), ([980, 980], 40, 5))
        self.assertEqual((a["events"][-1]["stacks"], a["events"][-1]["pot"]), ([980, 1020], 0))
        self.assertEqual([len(e["board"]) for e in a["events"] if e["type"] == "street"], [3, 4, 5])
        rows = self.ledger()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["start_a"], rows[0]["start_b"], rows[0]["end_a"], rows[0]["end_b"]), (1000, 1000, 980, 1020))

    def test_several_hands_in_a_row_with_alternating_button(self):
        code = self.start_match()
        self.play_to_showdown(code)
        self.assertEqual(self.ready(A, code, 1)[1]["state"]["phase"], "hand_over")
        status, result = self.ready(B, code, 1)
        self.assertEqual(result["state"]["phase"], "playing")
        self.assertEqual(result["state"]["handNo"], 2)
        view = self.state(B, code)
        self.assertEqual([seat["isButton"] for seat in view["seats"]], [False, True])
        self.assertEqual(view["turnSeat"], 1)
        self.assertEqual(self.state(A, code)["seats"][0]["cards"], ["A♠", "K♠"])
        status, result = self.act(B, code, "fold")
        self.assertEqual(status, 200, result)
        result = result["state"]["result"]
        self.assertEqual({k: result[k] for k in ("winnerSeat", "reason", "pot", "payouts", "hands")},
                         {"winnerSeat": 0, "reason": "fold", "pot": 20, "payouts": [20, 0], "hands": None})  # the unmatched 10 went back
        self.assertIsNone(self.state(B, code)["seats"][0]["cards"])  # no reveal after a fold
        self.ready(A, code, 2)
        self.ready(B, code, 2)
        end = self.play_to_showdown(code)
        self.assertEqual(end["handNo"], 3)
        rows = self.ledger()
        self.assertEqual([row["hand_no"] for row in rows], [1, 2, 3])
        self.assertEqual([row["prev_result_id"] for row in rows], [0, rows[0]["id"], rows[1]["id"]])
        for row in rows:
            self.assertEqual(row["end_a"] + row["end_b"], 2000)
        self.assertEqual([seat["stack"] for seat in end["seats"]], [rows[-1]["end_a"], rows[-1]["end_b"]])

    def test_auto_next_hand_after_wait_when_both_connected(self):
        code = self.start_match()
        self.play_to_showdown(code)
        self.clock.now += self.rooms.NEXT_HAND_SECONDS - 1
        self.state(A, code), self.state(B, code)
        self.assertEqual(self.state(A, code)["phase"], "hand_over")
        self.clock.now += 2
        self.state(B, code)
        self.assertEqual(self.state(A, code)["handNo"], 2)

    # ── ownership ───────────────────────────────────────────────────────────

    def test_room_code_alone_gives_no_seat_rights(self):
        code = self.start_match()
        version = self.state(A, code)["gameVersion"]
        for path, body in ((f"/api/rooms/{code}/state", None),
                           (f"/api/rooms/{code}/action", {"action_id": "intruder-0001", "expected_version": version, "action": "fold"}),
                           (f"/api/rooms/{code}/ready", {"ready": True, "hand_no": 1})):
            status, result = self.call(C, path, body)
            self.assertEqual((status, result["error"]), (403, "not_seated"), path)
            self.assertNotIn("state", result)
            status, result = self.call(None, path, body)
            self.assertEqual(status, 401, path)
        self.assertEqual(self.call(C, f"/api/rooms/{code}/join", {})[1]["error"], "room_full")  # a free seat would be joinable mid-match
        self.assertEqual(self.state(A, code)["gameVersion"], version)  # nothing changed
        # B cannot act for A: the seat comes from the token, not from the request
        status, result = self.act(B, code, "fold", version=version)
        self.assertEqual((status, result["error"]), (409, "not_your_turn"))

    def test_full_room_unknown_room_and_bad_requests(self):
        code = self.create_and_join()
        self.assertEqual(self.call(C, f"/api/rooms/{code}/join", {})[1]["error"], "room_full")
        self.assertEqual(self.call(A, "/api/rooms/ZZZZZZ/join", {})[0], 404)
        self.assertEqual(self.call(A, "/api/rooms/bad!/join", {})[0], 404)
        self.assertEqual(self.call(A, "/api/rooms", {"request_id": "x"})[0], 400)
        self.assertEqual(self.call(A, f"/api/rooms/{code}/ready", {"ready": "yes", "hand_no": 0})[0], 400)
        self.assertEqual(self.call(A, f"/api/rooms/{code}/action", {"action_id": "bad-00000001", "expected_version": 0, "action": "steal"})[0], 400)
        self.assertEqual(self.call(A, f"/api/rooms/{code}/action", {"action_id": "bad-00000002", "expected_version": 0, "action": "bet"})[0], 400)
        self.assertEqual(self.call(A, f"/api/rooms/{code}/state?since=abc")[0], 400)
        self.assertEqual(self.call(A, f"/api/rooms/{code}/state?wait=nan")[0], 400)
        self.assertEqual(self.call(A, f"/api/rooms/{code}/action", {"action_id": "early-0000001", "expected_version": 0, "action": "fold"})[1]["error"], "hand_not_active")

    def test_leave_frees_a_lobby_seat_but_not_a_running_match(self):
        code = self.create_and_join()
        self.assertEqual(self.call(B, f"/api/rooms/{code}/leave", {})[0], 200)
        self.assertEqual(self.state(A, code)["seats"][1]["occupied"], False)
        self.assertEqual(self.call(C, f"/api/rooms/{code}/join", {})[1]["state"]["you"]["seat"], 1)
        self.ready(A, code, 0)
        self.ready(C, code, 0)
        status, result = self.call(C, f"/api/rooms/{code}/leave", {})
        self.assertEqual((status, result["error"]), (409, "match_in_progress"))

    # ── duplicates, stale and concurrent requests ───────────────────────────

    def test_duplicate_and_stale_actions_do_not_move_chips_twice(self):
        code = self.start_match()
        version = self.state(A, code)["gameVersion"]
        status, first = self.act(A, code, "raise", to=60, action_id="raise-00000001", version=version)
        self.assertEqual(status, 200, first)
        self.assertEqual(first["state"]["seats"][0]["stack"], 940)
        status, again = self.act(A, code, "raise", to=60, action_id="raise-00000001", version=version)  # resend
        self.assertEqual(status, 200, again)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["state"]["seats"][0]["stack"], 940)
        self.assertEqual(again["state"]["gameVersion"], version + 1)
        status, result = self.act(A, code, "raise", to=80, action_id="raise-00000001", version=version)  # same id, other body
        self.assertEqual((status, result["error"]), (409, "request_id_reused"))
        status, result = self.act(B, code, "call", version=version)  # request made for an older turn
        self.assertEqual((status, result["error"]), (409, "stale_state"))
        self.assertEqual(result["state"]["gameVersion"], version + 1)  # the reply carries the current state to resync
        status, result = self.act(B, code, "raise", to=61)  # below the minimum raise
        self.assertEqual((status, result["error"]), (400, "illegal_action"))
        view = self.state(B, code, after=0)
        self.assertEqual(len([event for event in view["events"] if event["type"] == "action"]), 1)
        self.assertEqual([seat["stack"] for seat in view["seats"]], [940, 980])
        self.assertEqual(view["pot"], 80)

    def test_concurrent_identical_and_competing_requests_apply_once(self):
        code = self.start_match()
        version = self.state(A, code)["gameVersion"]
        body = {"action_id": "same-00000001", "expected_version": version, "action": "call"}
        with ThreadPoolExecutor(8) as pool:
            same = list(pool.map(lambda _: self.call(A, f"/api/rooms/{code}/action", body), range(8)))
        self.assertTrue(all(status == 200 for status, _ in same), same)
        self.assertEqual(sum(1 for _, result in same if not result.get("replayed")), 1)
        view = self.state(A, code, after=0)
        self.assertEqual(len([event for event in view["events"] if event["type"] == "action"]), 1)
        self.assertEqual(view["pot"], 40)
        # B fires several different requests for the same turn: exactly one wins
        version = view["gameVersion"]
        bodies = [{"action_id": f"race-{n:08d}", "expected_version": version, "action": "check"} for n in range(8)]
        with ThreadPoolExecutor(8) as pool:
            race = list(pool.map(lambda item: self.call(B, f"/api/rooms/{code}/action", item), bodies))
        self.assertEqual(sorted(status for status, _ in race), [200] + [409] * 7)
        view = self.state(A, code, after=0)
        self.assertEqual(len([event for event in view["events"] if event["type"] == "action"]), 2)
        self.assertEqual(view["street"], "flop")
        self.assertEqual(sum(seat["stack"] for seat in view["seats"]) + view["pot"], 2000)

    def test_ready_for_an_old_hand_is_rejected(self):
        code = self.start_match()
        self.play_to_showdown(code)
        status, result = self.ready(A, code, 0)
        self.assertEqual((status, result["error"]), (409, "stale_state"))
        self.ready(A, code, 1)
        self.ready(B, code, 1)
        status, result = self.ready(A, code, 1)  # hand 2 is running
        self.assertEqual((status, result["error"]), (409, "hand_active"))

    # ── sync, reconnect ─────────────────────────────────────────────────────

    def test_waiting_client_is_woken_by_the_other_players_action(self):
        code = self.start_match()
        seen = self.state(B, code)
        box = {}

        def wait():
            started = time.monotonic()
            box["state"] = self.state(B, code, since=seen["version"], after=seen["lastEventSeq"], wait=8)
            box["elapsed"] = time.monotonic() - started

        thread = threading.Thread(target=wait)
        thread.start()
        time.sleep(0.4)
        self.assertEqual(self.act(A, code, "call")[0], 200)
        thread.join(6)
        self.assertFalse(thread.is_alive())
        self.assertLess(box["elapsed"], 4)
        self.assertGreater(box["state"]["version"], seen["version"])
        self.assertEqual([event["type"] for event in box["state"]["events"]], ["action"])  # only what B has not seen
        self.assertEqual(box["state"]["turnSeat"], 1)

    def test_wait_returns_unchanged_state_when_nothing_happens(self):
        code = self.start_match()
        seen = self.state(B, code)
        seen = self.state(B, code, since=seen["version"], wait=0)
        started = time.monotonic()
        later = self.state(B, code, since=seen["version"], after=seen["lastEventSeq"], wait=0.6)
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        self.assertEqual((later["version"], later["events"]), (seen["version"], []))

    def test_refresh_returns_to_own_seat_with_current_state(self):
        code = self.start_match()
        self.act(A, code, "call")
        self.act(B, code, "check")
        # a refreshed browser knows only its token and the room code
        status, result = self.call(B, f"/api/rooms/{code}/join", {})
        self.assertEqual(status, 200, result)
        view = result["state"]
        self.assertEqual(view["you"]["seat"], 1)
        self.assertEqual((view["street"], view["board"], view["pot"]), ("flop", ["Q♠", "J♠", "T♠"], 40))
        self.assertEqual(view["seats"][1]["cards"], ["A♠", "K♠"])
        self.assertIsNone(view["seats"][0]["cards"])
        self.assertEqual(view["legalActions"], ["fold", "check", "bet", "all_in"])
        # a second tab with the same token sees the same seat; its duplicate action is not applied twice
        tab1 = self.act(B, code, "check", action_id="tab-000000001", version=view["gameVersion"])
        tab2 = self.act(B, code, "check", action_id="tab-000000002", version=view["gameVersion"])
        self.assertEqual((tab1[0], tab2[0], tab2[1]["error"]), (200, 409, "stale_state"))

    def test_disconnect_is_shown_and_pauses_only_the_next_hand(self):
        code = self.start_match()
        self.play_to_showdown(code)
        self.clock.now += self.rooms.PRESENCE_SECONDS + 1
        view = self.state(A, code)  # only A is still polling
        self.assertEqual([seat["connected"] for seat in view["seats"]], [True, False])
        self.clock.now += self.rooms.NEXT_HAND_SECONDS + 5
        self.assertEqual(self.state(A, code)["phase"], "hand_over")  # no new hand is dealt to an absent player
        back = self.state(B, code)  # B returns
        self.assertEqual(back["you"]["seat"], 1)
        self.assertEqual(self.state(A, code)["phase"], "playing")
        self.assertEqual([seat["connected"] for seat in self.state(A, code)["seats"]], [True, True])

    # ── turn timeout ────────────────────────────────────────────────────────

    def test_timeout_folds_when_facing_a_bet_and_checks_when_free(self):
        code = self.start_match()
        view = self.state(A, code)
        self.assertEqual(view["turnRemainingMs"], 30000)
        self.clock.now += 29
        self.assertEqual(self.state(B, code)["phase"], "playing")
        self.clock.now += 2  # A (small blind, owes 10) never acted
        view = self.state(B, code, after=0)
        self.assertEqual(view["phase"], "hand_over")
        self.assertEqual(view["result"]["winnerSeat"], 1)
        timed = [event for event in view["events"] if event["type"] == "action"]
        self.assertEqual([(event["seat"], event["action"], event["auto"]) for event in timed], [(0, "fold", True)])
        self.assertEqual(len(self.ledger()), 1)
        # A's late click for that turn is rejected, not applied to the next state
        status, result = self.act(A, code, "call", version=view["gameVersion"] - 1)
        self.assertEqual(status, 409)

        self.ready(A, code, 1)
        self.ready(B, code, 1)
        self.assertEqual(self.act(B, code, "call")[0], 200)  # hand 2: B is the button and calls
        self.clock.now += 31  # A may check for free -> timeout checks
        view = self.state(B, code, after=0)
        last = [event for event in view["events"] if event["type"] == "action"][-1]
        self.assertEqual((last["seat"], last["action"], last["auto"]), (0, "check", True))
        self.assertEqual((view["phase"], view["street"]), ("playing", "flop"))

    # ── storage and cache failures ──────────────────────────────────────────

    def test_match_start_needs_a_confirmed_match_row(self):
        code = self.create_and_join()
        original = self.fault_dbms("room_matches")
        self.ready(A, code, 0)
        status, result = self.ready(B, code, 0)
        self.assertEqual((status, result["error"]), (503, "match_storage_unknown"))
        self.assertEqual(result["state"]["phase"], "lobby")
        self.assertEqual([seat["ready"] for seat in result["state"]["seats"]], [False, False])
        self.demo._call = original
        self.ready(A, code, 0)
        self.assertEqual(self.ready(B, code, 0)[1]["state"]["phase"], "playing")
        self.assertEqual(len(self.database.tables["room_matches"].rows), 1)

    def check_result_storage_failure(self, durable):
        code = self.start_match()
        original = self.fault_dbms("room_hand_results", durable=durable)
        end = self.play_to_showdown(code)
        self.assertEqual((end["phase"], end["recordStatus"]), ("hand_over", "unknown"))
        self.assertIn("결과 저장 확인 중", end["notice"])
        self.assertEqual([seat["stack"] for seat in end["seats"]], [980, 1020])  # result is decided, not yet durable
        self.ready(A, code, 1)
        status, result = self.ready(B, code, 1)
        self.assertEqual(result["state"]["phase"], "hand_over")  # next hand is blocked while unconfirmed
        self.clock.now += self.rooms.NEXT_HAND_SECONDS + 5
        self.assertEqual(self.state(A, code)["phase"], "hand_over")
        self.assertEqual(len(self.ledger()), 1 if durable else 0)
        self.demo._call = original
        self.clock.now += self.rooms.STORAGE_RETRY_SECONDS + 1
        view = self.state(A, code)  # the same row is retried, then play continues
        self.assertEqual(view["recordStatus"] if view["phase"] == "hand_over" else "confirmed", "confirmed")
        rows = self.ledger()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["end_a"], rows[0]["end_b"]), (980, 1020))
        self.assertEqual(self.state(B, code)["handNo"], 2)  # both were ready, so hand 2 starts after confirmation

    def test_dbms_down_at_hand_end_blocks_next_hand_until_confirmed(self):
        self.check_result_storage_failure(durable=False)

    def test_lost_dbms_reply_does_not_store_the_hand_twice(self):
        self.check_result_storage_failure(durable=True)

    def test_redis_outage_does_not_affect_play_or_records(self):
        code = self.start_match()
        self.redis.shutdown()
        self.redis.server_close()
        self.redis_thread.join(2)
        try:
            end = self.play_to_showdown(code)
            self.assertEqual((end["phase"], end["recordStatus"]), ("hand_over", "confirmed"))
            self.assertEqual(len(self.ledger()), 1)
            status, public = self.call(None, f"/api/rooms/{code}/public")
            self.assertEqual((status, public["cache"]), (200, "BYPASS"))
            self.assertEqual(public["room"]["phase"], "hand_over")
        finally:  # the base tearDown closes this server again
            self.redis = integration.ThreadingHTTPServer(("127.0.0.1", 0), integration.make_handler(self.redis_store))
            self.redis_thread = self._start(self.redis)

    def test_public_preview_is_read_from_redis_and_refilled_after_loss(self):
        code = self.start_match()
        status, public = self.call(None, f"/api/rooms/{code}/public")
        self.assertEqual((status, public["cache"]), (200, "HIT"))  # written at the last state change
        self.assertEqual(public["room"]["version"], self.state(A, code)["version"])
        self.assertEqual([seat["name"] for seat in public["room"]["seats"]], ["Alpha", "Bravo"])
        self.assertEqual(self.redis_store.ttl("poker:room:" + code), self.rooms.PUBLIC_TTL_SECONDS)
        self.redis_store.delete("poker:room:" + code)  # cache lost (expiry / restart)
        self.assertEqual(self.call(None, f"/api/rooms/{code}/public")[1]["cache"], "MISS")
        self.assertEqual(self.call(None, f"/api/rooms/{code}/public")[1]["cache"], "HIT")
        self.assertEqual(self.state(A, code)["phase"], "playing")  # authoritative state untouched
        self.act(A, code, "call")
        public = self.call(None, f"/api/rooms/{code}/public")[1]
        self.assertEqual((public["cache"], public["room"]["pot"]), ("HIT", 40))  # refreshed on every change

    # ── server restart ──────────────────────────────────────────────────────

    def test_api_restart_recovers_seats_and_confirmed_chips_only(self):
        code = self.start_match()
        self.play_to_showdown(code)
        self.ready(A, code, 1)
        self.ready(B, code, 1)
        self.assertEqual(self.act(B, code, "raise", to=200)[0], 200)  # hand 2 is in progress, B has 200 in the pot
        before = self.state(A, code)
        time.sleep(0.01)
        self._install_demo()  # new API process: memory is gone, DBMS files remain
        self.wire_rooms()
        status, result = self.call(C, f"/api/rooms/{code}/state")
        self.assertEqual((status, result["error"]), (403, "not_seated"))
        b = self.state(B, code)
        a = self.state(A, code)
        self.assertEqual((a["you"]["seat"], b["you"]["seat"]), (0, 1))
        self.assertTrue(a["recovered"])
        self.assertEqual((a["phase"], a["handNo"], a["board"], a["pot"]), ("hand_over", 1, [], 0))
        self.assertEqual([seat["stack"] for seat in a["seats"]], [980, 1020])  # the unfinished hand is void
        self.assertEqual([seat["name"] for seat in a["seats"]], ["Alpha", "Bravo"])
        self.assertIn("무효", a["notice"])
        # counters only move forward across the restart, so old cursors and old actions never match
        self.assertGreater(a["version"], before["version"])
        self.assertGreater(a["gameVersion"], before["gameVersion"])
        self.assertGreater(a["lastEventSeq"], before["lastEventSeq"])
        self.assertNotEqual(a["instance"], before["instance"])
        status, result = self.act(A, code, "call", version=before["gameVersion"])
        self.assertEqual((status, result["error"]), (409, "hand_not_active"))
        self.ready(A, code, 1)
        status, result = self.ready(B, code, 1)
        self.assertEqual((result["state"]["phase"], result["state"]["handNo"]), ("playing", 2))
        # the pre-restart action for hand 2 is still rejected now that a new hand 2 is running
        status, late = self.act(A, code, "call", version=before["gameVersion"])
        self.assertEqual((status, late["error"]), (409, "stale_state"))
        self.assertEqual(self.state(B, code)["seats"][1]["isButton"], True)
        self.assertFalse(self.state(B, code)["recovered"])  # the restart notice ends when play resumes
        self.assertEqual(self.act(B, code, "fold")[0], 200)
        rows = self.ledger()
        self.assertEqual([row["hand_no"] for row in rows], [1, 2])
        self.assertEqual(rows[1]["prev_result_id"], rows[0]["id"])
        self.assertEqual((rows[1]["start_a"], rows[1]["start_b"]), (980, 1020))
        self.assertEqual(len(self.database.tables["room_matches"].rows), 1)

    def test_api_restart_loses_a_room_that_never_started(self):
        code = self.create_and_join()
        self._install_demo()
        self.wire_rooms()
        status, result = self.call(A, f"/api/rooms/{code}/state")
        self.assertEqual((status, result["error"]), (404, "room_not_found"))

    # ── records ─────────────────────────────────────────────────────────────

    def profile(self, token):
        status, result = self.call(token, "/api/profile")
        self.assertEqual(status, 200, result)
        return result["profile"]

    def test_both_seats_get_their_own_online_record_separate_from_practice(self):
        code = self.start_match()
        self.play_to_showdown(code)  # hand 1: seat 1 (Bravo) wins at showdown
        self.ready(A, code, 1)
        self.ready(B, code, 1)
        self.act(B, code, "fold")  # hand 2: seat 0 (Alpha) wins by fold
        self.ready(A, code, 2)
        self.ready(B, code, 2)
        self.play_to_showdown(code)  # hand 3: same cards as hand 1, seat 1 wins
        a, b = self.profile(A), self.profile(B)
        empty = {"matches": 0, "hands": 0, "wins": 0, "losses": 0, "draws": 0}
        self.assertEqual(a["practice"], empty)
        self.assertEqual(b["practice"], empty)
        self.assertEqual(a["online"], {"matches": 1, "hands": 3, "wins": 1, "losses": 2, "draws": 0})
        self.assertEqual(b["online"], {"matches": 1, "hands": 3, "wins": 2, "losses": 1, "draws": 0})
        self.assertEqual((a["recentGames"], b["recentGames"]), ([], []))
        self.assertEqual([(g["handNo"], g["result"], g["seat"], g["opponent"]) for g in b["recentOnline"]],
                         [(3, "win", 1, "Alpha"), (2, "loss", 1, "Alpha"), (1, "win", 1, "Alpha")])
        self.assertEqual([g["result"] for g in a["recentOnline"]], ["loss", "win", "loss"])
        # stacks are reported from each player's own seat and agree with the table
        latest_a, latest_b = a["recentOnline"][0], b["recentOnline"][0]
        view = self.state(B, code)
        self.assertEqual((latest_a["endStack"], latest_b["endStack"]), (view["seats"][0]["stack"], view["seats"][1]["stack"]))
        self.assertEqual(latest_a["endStack"] + latest_b["endStack"], 2000)
        self.assertEqual(b["recentOnline"][-1]["startStack"], 1000)
        # a practice match against the bot is counted separately for the same guest
        status, result = self.call(B, "/api/game/start", {"request_id": "practice-start-01"})
        self.assertEqual(status, 200, result)
        status, result = self.call(B, "/api/game/action", {"action_id": "practice-fold-01", "action": "fold"})
        self.assertEqual(status, 200, result)
        b = self.profile(B)
        self.assertEqual(b["practice"], {"matches": 1, "hands": 1, "wins": 0, "losses": 1, "draws": 0})
        self.assertEqual(b["online"]["hands"], 3)
        self.assertEqual([(g["mode"], g["result"]) for g in b["recentGames"]], [("practice", "loss")])
        self.assertEqual(self.profile(C)["online"], empty)  # someone who never sat in the room

    def test_profile_reports_storage_outage_instead_of_wrong_numbers(self):
        code = self.start_match()
        self.play_to_showdown(code)
        original = self.demo._call

        def down(service, method, url, body=None, trace_id=None):
            if service == "Mini DBMS" and body and "hand_results" in body.get("sql", "") and body["sql"].startswith("SELECT"):
                return None, {"traceId": trace_id, "service": service, "method": method, "path": "/sql", "outcome": "unavailable"}
            return original(service, method, url, body, trace_id)

        self.demo._call = down
        status, result = self.call(B, "/api/profile")
        self.assertEqual((status, result["error"]), (503, "profile_store_unavailable"))

    def test_match_over_when_a_player_has_no_chips(self):
        code = self.start_match()
        self.assertEqual(self.act(A, code, "all_in")[0], 200)
        status, result = self.act(B, code, "call")
        self.assertEqual(status, 200, result)
        view = result["state"]
        self.assertEqual(view["phase"], "match_over")
        self.assertEqual([seat["stack"] for seat in view["seats"]], [0, 2000])
        self.assertEqual(len(view["board"]), 5)
        events = self.state(A, code, after=0)["events"]
        # the all-in call, three streets and the payout arrive as separate ordered events
        self.assertEqual([e["type"] for e in events], ["hand_start", "action", "action", "street", "street", "street", "hand_end"])
        self.assertEqual([(e["stacks"], e["pot"]) for e in events[1:3]], [([0, 980], 1020), ([0, 0], 2000)])
        self.assertEqual([len(e["board"]) for e in events[2:6]], [0, 3, 4, 5])
        self.assertEqual((events[5]["stacks"], events[5]["pot"]), ([0, 0], 2000))
        self.assertEqual((events[6]["stacks"], events[6]["pot"]), ([0, 2000], 0))
        status, result = self.ready(A, code, 1)
        self.assertEqual((status, result["error"]), (409, "match_over"))
        self.clock.now += 60
        self.assertEqual(self.state(A, code)["phase"], "match_over")


if __name__ == "__main__":
    unittest.main()
