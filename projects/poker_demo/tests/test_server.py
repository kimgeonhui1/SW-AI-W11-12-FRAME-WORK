import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

PROJECTS = Path(__file__).resolve().parents[2]
for project in ("poker_demo", "dbms", "redis"):
    sys.path.insert(0, str(PROJECTS / project))

from mini_dbms import Database
from mini_dbms.server import BoundedSQLHTTPServer
from mini_redis.server import make_handler
from mini_redis.store import MiniRedis
from server import Demo, Handler


class PokerHTTPIntegrationTests(unittest.TestCase):
    @classmethod
    def _start(cls, server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return thread

    def _install_demo(self):
        self.demo = Demo(f"http://127.0.0.1:{self.dbms.server_port}", f"http://127.0.0.1:{self.redis.server_port}")
        self.service_calls = []
        original_call = self.demo._call

        def count_call(*args, **kwargs):
            self.service_calls.append((args[0], args[1], args[2]))
            return original_call(*args, **kwargs)

        self.demo._call = count_call
        self.api.RequestHandlerClass.demo = self.demo

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Database(self.tmp.name)
        self.dbms = BoundedSQLHTTPServer(("127.0.0.1", 0), self.database, workers=4, queue_size=32)
        self.dbms_thread = self._start(self.dbms)
        self.redis_store = MiniRedis()
        self.redis = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.redis_store))
        self.redis_thread = self._start(self.redis)
        self.api = ThreadingHTTPServer(("127.0.0.1", 0), type("TestPokerHandler", (Handler,), {"demo": None}))
        self.api_thread = self._start(self.api)
        self._install_demo()
        self.token = "A" * 43  # deterministic test-only 256-bit token-shaped value
        self.user = None

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.api_thread.join(2)
        self.redis.shutdown()
        self.redis.server_close()
        self.redis_thread.join(2)
        self.dbms.shutdown()
        self.dbms.server_close()
        self.dbms_thread.join(2)
        self.tmp.cleanup()

    def request(self, path, body=None, raw=None, auth=True, method="POST"):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if auth and self.token:
            headers["Authorization"] = "Bearer " + self.token
        if method == "GET":
            conn.request("GET", path, headers=headers)
        else:
            data = raw if raw is not None else json.dumps(body or {}, ensure_ascii=False)
            conn.request("POST", path, data, headers)
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        return response.status, payload

    def register(self):
        status, result = self.request("/api/guest", {"guest_token": self.token, "display_name": "Test Mira"}, auth=False)
        self.assertEqual(status, 200, result)
        self.user = result["user"]
        return result

    @staticmethod
    def start_body(request_id="start-request-0001"):
        return {"request_id": request_id}

    def start(self):
        if self.user is None:
            self.register()
        status, result = self.request("/api/game/start", self.start_body())
        self.assertEqual(status, 200, result)
        return result

    def action(self, name, action_id, to=None):
        body = {"action": name, "action_id": action_id}
        if to is not None:
            body["to"] = to
        return self.request("/api/game/action", body)

    def test_guest_identity_is_stable_and_client_user_id_is_not_accepted(self):
        first = self.register()
        rows_before = len(self.database.tables["guest_users"].rows)
        status, second = self.request("/api/guest", {"guest_token": self.token, "display_name": "Test Mira"}, auth=False)
        self.assertEqual(status, 200, second)
        self.assertEqual(first["user"]["userId"], second["user"]["userId"])
        self.assertEqual(len(self.database.tables["guest_users"].rows), rows_before)
        status, unauthorized = self.request("/api/profile", method="GET", auth=False)
        self.assertEqual(status, 401)
        status, forged = self.request("/api/game/start", {"request_id": "forged-start-001", "user_id": "someone-else"})
        self.assertEqual(status, 400)
        self.assertEqual(forged["error"], "invalid_start_request")

    def test_each_guest_gets_an_independent_server_game(self):
        first_game = self.start()["game"]
        first_token = self.token
        self.token = "B" * 43
        self.user = None
        second_game = self.start()["game"]
        self.assertNotEqual(first_game["matchKey"], second_game["matchKey"])
        self.assertEqual((second_game["pot"], second_game["humanStack"]), (30, 990))
        self.token = first_token
        status, state = self.request("/api/game", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(state["game"]["matchKey"], first_game["matchKey"])

    def test_start_blinds_redis_and_trace_id_are_real_and_private_cards_stay_private(self):
        result = self.start()
        game = result["game"]
        self.assertEqual((game["phase"], game["pot"], game["turn"]), ("preflop", 30, "human"))
        self.assertEqual(len(game["humanCards"]), 2)
        self.assertEqual(game["botCards"], [])
        current = [event for event in result["traces"] if event["traceId"] == result["traceId"]]
        self.assertEqual({event["service"] for event in current}, {"Mini DBMS", "Mini Redis"})
        self.assertEqual(len(self.database.tables["matches"].rows), 1)
        cache_key = "poker:public:" + self.user["userId"] + ":" + game["matchKey"]
        cache = self.redis_store.get(cache_key)
        self.assertIsNotNone(cache)
        self.assertNotIn("humanCards", cache)
        self.assertNotIn("botCards", cache)
        self.assertNotIn(self.token, json.dumps(result["traces"]))
        self.assertFalse(any("A♠" in json.dumps(event) for event in result["traces"]))

    def test_server_validates_bet_and_auto_runs_bot_and_next_street(self):
        self.start()
        status, bad = self.action("raise", "bad-raise-0001", 30)
        self.assertEqual(status, 400)
        self.assertIn("minimum raise", bad["message"])
        rejected = [event for event in bad["traces"] if event.get("actionId") == "bad-raise-0001" and event["service"] == "Poker Server"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual((rejected[0]["service"], rejected[0]["outcome"]), ("Poker Server", "rejected"))
        self.assertEqual(rejected[0]["input"], {"action": "raise", "to": 30})
        self.assertGreaterEqual(rejected[0]["durationMs"], 0)

        status, result = self.action("raise", "valid-raise-0001", 40)
        self.assertEqual(status, 200, result)
        game = result["game"]
        self.assertEqual((game["phase"], len(game["board"]), game["turn"]), ("flop", 3, "human"))
        self.assertEqual((game["humanStack"], game["botStack"], game["pot"]), (960, 960, 80))
        self.assertTrue(any(action["player"] == "bot" and action["action"] == "call" for action in game["actions"]))
        action_events = [event for event in result["traces"] if event.get("actionId") == "valid-raise-0001"]
        self.assertEqual({event["service"] for event in action_events}, {"Poker Server", "Mini DBMS", "Mini Redis"})
        self.assertEqual(len({event["traceId"] for event in action_events}), 1)
        self.assertTrue(all(isinstance(event.get("durationMs"), (int, float)) for event in action_events))
        encoded_trace = json.dumps(action_events)
        for private_field in ("humanCards", "botCards", "guest_token", "Authorization"):
            self.assertNotIn(private_field, encoded_trace)

    def test_action_retry_is_idempotent_and_action_id_body_mismatch_is_rejected(self):
        self.start()
        payload = {"action": "raise", "action_id": "replay-key-0001", "to": 40}
        status, first = self.request("/api/game/action", payload)
        self.assertEqual(status, 200)
        redis_calls = len([call for call in self.service_calls if call[0] == "Mini Redis"])
        db_calls = len([call for call in self.service_calls if call[0] == "Mini DBMS"])
        status, replay = self.request("/api/game/action", payload)
        self.assertEqual(status, 200)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["game"]["humanStack"], replay["game"]["humanStack"])
        self.assertEqual(len([call for call in self.service_calls if call[0] == "Mini Redis"]), redis_calls)
        # Every protected request still performs a DBMS-backed token lookup.
        self.assertEqual(len([call for call in self.service_calls if call[0] == "Mini DBMS"]), db_calls + 1)
        status, changed = self.request("/api/game/action", {**payload, "to": 80})
        self.assertEqual(status, 409)
        self.assertEqual(self.database.tables["matches"].index.size, 1)

    def test_lost_result_ack_retries_atomic_insert_without_duplicate_settlement(self):
        self.start()
        original_call = self.demo._call
        lost_ack = {"done": False}

        def lose_durable_ack(service, method, url, body=None, trace_id=None):
            if (not lost_ack["done"] and service == "Mini DBMS" and method == "POST"
                    and url.endswith("/sql/insert-once") and body.get("sql", "").startswith("INSERT INTO hand_results")):
                saved, trace = original_call(service, method, url, body, trace_id)
                lost_ack["done"] = True
                trace["outcome"] = "unavailable"
                trace.pop("status", None)
                trace["detail"] = "simulated lost response after durable append"
                return None, trace
            return original_call(service, method, url, body, trace_id)

        self.demo._call = lose_durable_ack
        action = {"action": "fold", "action_id": "lost-ack-fold-0001"}
        status, uncertain = self.request("/api/game/action", action)
        self.assertEqual(status, 503)
        self.assertEqual(uncertain["game"]["recordStatus"], "unknown")
        self.assertEqual(len(self.database.tables["hand_results"].rows), 1)
        self.demo._call = original_call
        status, retried = self.request("/api/game/action", action)
        self.assertEqual(status, 200, retried)
        self.assertTrue(retried["replayed"])
        self.assertEqual(retried["game"]["recordStatus"], "confirmed")
        self.assertEqual(len(self.database.tables["hand_results"].rows), 1)
        self.assertEqual(retried["game"]["humanStack"] + retried["game"]["botStack"], 2000)

    def test_fold_and_showdown_are_durable_once_then_profile_survives_api_restart(self):
        self.start()
        status, folded = self.action("fold", "fold-action-0001")
        self.assertEqual(status, 200)
        self.assertEqual((folded["game"]["phase"], folded["game"]["result"]["winner"], folded["game"]["recordStatus"]), ("complete", "bot", "confirmed"))
        self.assertEqual(len(self.database.tables["hand_results"].rows), 1)
        old_user_id = self.user["userId"]

        self._install_demo()  # Simulates a Poker API process restart; DBMS/Redis remain authoritative for persisted records.
        status, profile = self.request("/api/profile", method="GET")
        self.assertEqual(status, 200, profile)
        self.assertEqual(profile["profile"]["userId"], old_user_id)
        self.assertEqual(profile["profile"]["practice"], {"matches": 1, "hands": 1, "wins": 0, "losses": 1, "draws": 0})
        self.assertEqual(len(profile["profile"]["recentGames"]), 1)
        status, resumed = self.request("/api/game", method="GET")
        self.assertEqual(status, 200)
        self.assertIsNone(resumed["game"])  # an unfinished in-memory hand is discarded; finished records remain

        # Start the same idempotent match request after restart and replay history into next-hand stacks.
        status, next_state = self.request("/api/game/start", self.start_body())
        self.assertEqual(status, 200, next_state)
        self.assertEqual((next_state["game"]["handNo"], next_state["game"]["button"]), (2, "bot"))

    def test_profile_counts_completed_showdown_and_next_hand_preserves_chip_chain(self):
        self.start()
        status, current = self.action("call", "preflop-call-0001")
        self.assertEqual(status, 200)
        for number in range(3):
            status, current = self.action("check", f"street-check-{number:04d}")
            self.assertEqual(status, 200, current)
        self.assertEqual(current["game"]["phase"], "showdown")
        self.assertTrue(current["game"]["botCardsRevealed"])
        self.assertEqual(current["game"]["humanStack"] + current["game"]["botStack"], 2000)
        self.assertEqual(len(self.database.tables["hand_results"].rows), 1)
        final_action = {"action": "check", "action_id": "street-check-0002"}
        status, replay = self.request("/api/game/action", final_action)
        self.assertEqual(status, 200)
        self.assertTrue(replay["replayed"])
        self.assertEqual(len(self.database.tables["hand_results"].rows), 1)
        status, profile = self.request("/api/profile", method="GET")
        self.assertEqual(status, 200)
        practice = profile["profile"]["practice"]
        self.assertEqual(practice["hands"], 1)
        self.assertEqual(practice["wins"] + practice["losses"] + practice["draws"], 1)
        status, next_hand = self.request("/api/game/next", {"request_id": "next-hand-0001"})
        self.assertEqual(status, 200, next_hand)
        self.assertEqual(next_hand["game"]["handNo"], 2)
        self.assertEqual(next_hand["game"]["startingHumanStack"] + next_hand["game"]["startingBotStack"], 2000)
        status, second_fold = self.action("fold", "second-hand-fold-0001")
        self.assertEqual(status, 200, second_fold)
        result_rows = self.database.tables["hand_results"].rows
        self.assertEqual(len(result_rows), 2)
        self.assertEqual(result_rows[1][0]["prev_result_id"], result_rows[0][0]["id"])
        self.assertEqual(result_rows[1][0]["hand_no"], 2)
        status, updated_profile = self.request("/api/profile", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(updated_profile["profile"]["practice"]["hands"], 2)

    def test_redis_outage_does_not_prevent_permanent_hand_record(self):
        self.start()
        self.demo.redis_url = "http://127.0.0.1:1"
        status, folded = self.action("fold", "redis-down-fold-0001")
        self.assertEqual(status, 200, folded)
        self.assertEqual(folded["game"]["recordStatus"], "confirmed")
        self.assertEqual(len(self.database.tables["hand_results"].rows), 1)
        status, profile = self.request("/api/profile", method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(profile["profile"]["practice"]["hands"], 1)


if __name__ == "__main__":
    unittest.main()
