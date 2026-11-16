"""Settlement regressions using real HTTP services and disposable DBMS files."""
import copy
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import unittest
from unittest.mock import patch

import test_server as integration
from engine import PokerEngine
from mini_dbms import Database
from test_engine import deck_with_prefix


class SettlementTests(integration.PokerHTTPIntegrationTests):
    def start_terminal_match(self):
        deck = deck_with_prefix("2♦", "A♠", "3♦", "K♠", "4♥", "Q♠", "J♠", "T♠", "6♥", "4♦", "7♥", "5♥")
        with patch("server.PokerEngine", partial(PokerEngine, deck_factory=lambda: list(deck))):
            return self.start()

    def prepare_short_stack(self, target=990):
        # Human loses a real, durably recorded hand, leaving 10 or 20 chips.
        deck = deck_with_prefix("2♦", "A♠", "3♦", "K♠", "4♥", "Q♠", "J♠", "T♠", "6♥", "4♦", "7♥", "5♥")
        with patch("server.PokerEngine", partial(PokerEngine, deck_factory=lambda: list(deck))):
            self.start()
        status, result = self.action("raise", "setup-raise-0001", target)
        self.assertEqual(status, 200, result)
        for number in range(3):
            status, result = self.action("check", f"setup-check-{number:04d}")
            self.assertEqual(status, 200, result)
        self.assertEqual(result["game"]["humanStack"], 1000 - target)
        self.assertEqual(result["game"]["recordStatus"], "confirmed")
        return result["game"]

    def fault_results(self, outcome="unavailable", durable=False):
        original = self.demo._call
        def call(service, method, url, body=None, trace_id=None):
            if service == "Mini DBMS" and body and body.get("sql", "").startswith("INSERT INTO hand_results"):
                if durable:
                    original(service, method, url, body, trace_id)
                trace = {"traceId": trace_id, "service": service, "method": method,
                         "path": "/sql/insert-once", "outcome": outcome}
                if outcome == "http_error":
                    trace["status"] = 409
                return None, trace
            return original(service, method, url, body, trace_id)
        self.demo._call = call
        return original

    def assert_ledger(self, expected):
        rows = [copy.deepcopy(row) for row, _ in self.database.tables["hand_results"].rows]
        self.assertEqual(len(rows), expected)
        self.assertEqual(len({row["operation_key"] for row in rows}), expected)
        for row in rows:
            self.assertEqual(row["start_a"] + row["start_b"], 2000)
            self.assertEqual(row["end_a"] + row["end_b"], 2000)
            self.assertGreaterEqual(min(row["end_a"], row["end_b"]), 0)
        if expected > 1:
            self.assertEqual(rows[-1]["prev_result_id"], rows[-2]["id"])
        return rows

    def automatic_hand(self, route, target):
        self.prepare_short_stack(target)
        if route == "start":
            self._install_demo()
            body = self.start_body()
        else:
            body = {"request_id": "automatic-next-0001"}
        status, result = self.request("/api/game/" + route, body)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["game"]["handOver"])
        self.assertEqual(result["game"]["handNo"], 2)
        self.assertEqual(result["game"]["recordStatus"], "confirmed")
        if target == 980:
            self.assertTrue(any(a["player"] == "bot" and a["action"] == "call" for a in result["game"]["actions"]))
        rows = self.assert_ledger(2)
        status, replay = self.request("/api/game/" + route, body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["game"], result["game"])
        self.assertEqual(self.assert_ledger(2), rows)
        reopened = Database(self.tmp.name)
        self.assertEqual(reopened.execute("SELECT id FROM hand_results")["rows"], [{"id": row["id"]} for row in rows])

    def test_next_blind_only_completion(self):
        self.automatic_hand("next", 990)

    def test_next_bot_call_completion(self):
        self.automatic_hand("next", 980)

    def test_recovered_start_blind_only_completion(self):
        self.automatic_hand("start", 990)

    def test_recovered_start_bot_call_completion(self):
        self.automatic_hand("start", 980)

    def automatic_unknown(self, route, durable):
        self.prepare_short_stack()
        if route == "start":
            self._install_demo()
            body = self.start_body()
        else:
            body = {"request_id": "unknown-next-0001"}
        original = self.fault_results(durable=durable)
        status, unknown = self.request("/api/game/" + route, body)
        self.assertEqual(status, 503, unknown)
        self.assertEqual(unknown["game"]["recordStatus"], "unknown")
        self.assert_ledger(2 if durable else 1)
        session = self.demo.sessions[self.user["userId"]]
        pending = copy.deepcopy(session.pending_result)
        for path, payload in (("start", {"request_id": "replacement-start"}),
                              ("next", {"request_id": "replacement-next"}),
                              ("action", {"action_id": "replacement-action", "action": "fold"})):
            status, blocked = self.request("/api/game/" + path, payload)
            self.assertEqual(status, 503, blocked)
            self.assertEqual(session.pending_result, pending)
            self.assertEqual(blocked["game"], unknown["game"])
        self.demo._call = original
        status, replay = self.request("/api/game/" + route, body)
        self.assertEqual(status, 200, replay)
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["game"]["recordStatus"], "confirmed")
        self.assertEqual(replay["game"]["handNo"], 2)
        self.assert_ledger(2)

    def test_next_unknown_before_append(self):
        self.automatic_unknown("next", False)

    def test_next_lost_ack(self):
        self.automatic_unknown("next", True)

    def test_start_unknown_before_append(self):
        self.automatic_unknown("start", False)

    def test_start_lost_ack(self):
        self.automatic_unknown("start", True)

    def test_new_match_cannot_discard_unknown_terminal_result(self):
        self.start_terminal_match()
        original = self.fault_results()
        status, unknown = self.action("all_in", "terminal-all-in-0001")
        self.assertEqual(status, 503, unknown)
        self.assertTrue(unknown["game"]["matchOver"])
        session = self.demo.sessions[self.user["userId"]]
        pending = copy.deepcopy(session.pending_result)
        status, blocked = self.request("/api/game/start", {"request_id": "new-match-blocked"})
        self.assertEqual(status, 503, blocked)
        self.assertEqual(session.pending_result, pending)
        self.assertEqual(len(self.database.tables["matches"].rows), 1)
        self.demo._call = original
        status, replay = self.action("all_in", "terminal-all-in-0001")
        self.assertEqual(status, 200, replay)
        self.assert_ledger(1)

    def test_start_retry_does_not_report_success_while_result_is_unknown(self):
        self.start()
        self.fault_results()
        self.action("fold", "unknown-fold-0001")
        status, result = self.request("/api/game/start", self.start_body())
        self.assertEqual(status, 503, result)
        self.assertEqual(result["game"]["recordStatus"], "unknown")

    def test_conflicting_result_blocks_start_and_all_retries(self):
        self.start_terminal_match()
        self.fault_results(outcome="http_error")
        status, result = self.action("all_in", "conflict-all-in-0001")
        self.assertEqual(status, 503, result)
        self.assertEqual(result["game"]["recordStatus"], "blocked")
        for body in (self.start_body(), {"request_id": "new-conflict-start"}):
            status, result = self.request("/api/game/start", body)
            self.assertEqual(status, 503, result)
            self.assertEqual(result["error"], "result_storage_blocked")
        self.assert_ledger(0)

    def test_concurrent_terminal_action_retries_append_once(self):
        self.start_terminal_match()
        body = {"action": "all_in", "action_id": "concurrent-all-in"}
        with ThreadPoolExecutor(max_workers=4) as clients:
            responses = list(clients.map(lambda _: self.request("/api/game/action", body), range(8)))
        for status, result in responses:
            self.assertEqual(status, 200, result)
            self.assertTrue(result["game"]["handOver"])
            self.assertEqual(result["game"]["humanStack"] + result["game"]["botStack"], 2000)
        self.assert_ledger(1)

    def test_restart_after_lost_ack_recovers_one_durable_result(self):
        self.start()
        self.fault_results(durable=True)
        status, result = self.action("fold", "restart-lost-ack")
        self.assertEqual(status, 503, result)
        rows = self.assert_ledger(1)
        self._install_demo()
        status, profile = self.request("/api/profile", method="GET")
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["profile"]["practice"]["hands"], 1)
        status, recovered = self.request("/api/game/start", self.start_body())
        self.assertEqual(status, 200, recovered)
        self.assertEqual(recovered["game"]["handNo"], 2)
        self.assertEqual(self.assert_ledger(1), rows)

    def test_restart_before_append_exposes_existing_volatile_pending_boundary(self):
        self.start()
        self.fault_results()
        status, result = self.action("fold", "restart-unsaved-fold")
        self.assertEqual(status, 503, result)
        self.assert_ledger(0)
        self._install_demo()
        status, state = self.request("/api/game", method="GET")
        self.assertEqual(status, 200, state)
        self.assertIsNone(state["game"])
        status, profile = self.request("/api/profile", method="GET")
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["profile"]["practice"]["hands"], 0)


    def test_new_active_hand_does_not_inherit_previous_confirmation(self):
        self.start()
        self.action("fold", "status-fold-0001")
        status, result = self.request("/api/game/next", {"request_id": "status-next-0001"})
        self.assertEqual(status, 200, result)
        self.assertFalse(result["game"]["handOver"])
        self.assertEqual(result["game"]["recordStatus"], "not_saved")
        self._install_demo()
        status, result = self.request("/api/game/start", self.start_body())
        self.assertEqual(status, 200, result)
        self.assertFalse(result["game"]["handOver"])
        self.assertEqual(result["game"]["recordStatus"], "not_saved")
        self.assert_ledger(1)

    def test_bot_river_check_tie_is_saved_once(self):
        self.start()
        self.action("fold", "tie-setup-fold-0001")
        session = self.demo.sessions[self.user["userId"]]
        deck = deck_with_prefix("2♦", "4♣", "3♦", "5♣", "6♥", "A♠", "K♠", "Q♠", "6♦", "J♠", "7♥", "T♠")
        session.engine.deck_factory = lambda: list(deck)
        status, result = self.request("/api/game/next", {"request_id": "tie-next-0001"})
        self.assertEqual(status, 200, result)
        for number in range(4):
            status, result = self.action("check", f"tie-check-{number:04d}")
            self.assertEqual(status, 200, result)
        game = result["game"]
        self.assertEqual(game["result"]["winner"], "tie")
        self.assertEqual(game["actions"][-1]["player"], "bot")
        self.assertEqual(game["recordStatus"], "confirmed")
        rows = self.assert_ledger(2)
        status, replay = self.action("check", "tie-check-0003")
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["game"], game)
        self.assertEqual(self.assert_ledger(2), rows)

    def test_dbms_fsync_failure_blocks_until_file_recovery_then_reuses_row(self):
        self.start()
        with patch("mini_dbms.storage.os.fsync", side_effect=OSError("test fsync failure")):
            status, unknown = self.action("fold", "fsync-failure-fold")
        self.assertEqual(status, 503, unknown)
        self.assertEqual(unknown["game"]["recordStatus"], "unknown")
        self.assertTrue(self.database.tables["hand_results"].failed)
        status, blocked = self.action("fold", "fsync-failure-fold")
        self.assertEqual(status, 503, blocked)
        # Rebuild the DBMS from its temporary files, retaining the API's exact pending row.
        # This is recovery after an injected exception, not a power-loss durability test.
        self.database = Database(self.tmp.name)
        self.dbms.database = self.database
        self.assert_ledger(1)
        status, replay = self.action("fold", "fsync-failure-fold")
        self.assertEqual(status, 200, replay)
        self.assertEqual(replay["game"]["recordStatus"], "confirmed")
        self.assert_ledger(1)


def load_tests(loader, tests, pattern):
    # Reuse HTTP fixtures without running inherited baseline tests twice.
    return unittest.TestSuite(SettlementTests(name) for name in sorted(SettlementTests.__dict__) if name.startswith("test_"))
