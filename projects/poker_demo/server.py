"""HTTP adapter for Poker Lab, Mini DBMS guest profiles and Mini Redis cache."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

from engine import PokerEngine, RuleError
from rooms import RoomService


MAX_BODY_BYTES = 8192
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
RESULT_COLUMNS = ("id", "operation_key", "payload_hash", "schema_version", "match_key", "hand_no",
                  "prev_result_id", "start_a", "start_b", "end_a", "end_b", "winner", "reason",
                  "board", "public_actions", "rules_version")


class GameSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.engine = None
        self.match_key = None
        self.db_id = None
        self.last_result_id = 0
        self.pending_result = None
        self.storage_blocked = False
        self.record_status = "not_started"
        self.start_replays = {}
        self.next_replays = {}
        self.action_replays = {}


class Demo:
    def __init__(self, dbms_url, redis_url):
        self.dbms_url = dbms_url.rstrip("/")
        self.redis_url = redis_url.rstrip("/")
        self.guard = threading.RLock()
        self.trace_guard = threading.RLock()
        self.registration_lock = threading.RLock()
        self.sessions = {}
        self.traces_by_user = {}
        self.unknown_guest_ops = set()
        self.rooms = RoomService(self)  # two-human rooms; the practice-bot routes below are unchanged

    def _call(self, service, method, url, body=None, trace_id=None):
        started = time.perf_counter()
        trace = {"traceId": trace_id, "service": service, "method": method, "path": urlsplit(url).path,
                 "input": {"method": method, "path": urlsplit(url).path}}

        def finish():
            trace["durationMs"] = round((time.perf_counter() - started) * 1000, 3)
            trace["result"] = {"status": trace.get("status"), "outcome": trace.get("outcome")}
            if trace.get("detail"):
                trace["result"]["detail"] = trace["detail"]

        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=2) as response:
                payload = json.loads(response.read())
                trace["status"] = response.status
                trace["outcome"] = "hit" if service == "Mini Redis" and method == "GET" else "ok"
                finish()
                return payload, trace
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read())
            except Exception:
                payload = {}
            finally:
                exc.close()
            trace["status"] = exc.code
            trace["outcome"] = "miss" if service == "Mini Redis" and method == "GET" and exc.code == 404 else "http_error"
            trace["detail"] = "MISS · key absent" if trace["outcome"] == "miss" else payload.get("error", "HTTP error")
            finish()
            return payload, trace
        except (URLError, TimeoutError, OSError, ValueError):
            # Trace records contain route and outcome only; never request data or secrets.
            trace["outcome"] = "unavailable"
            trace["detail"] = "service unavailable or response outcome unknown"
            finish()
            return None, trace

    def _record(self, user_id, traces):
        if not traces:
            return
        with self.trace_guard:
            events = self.traces_by_user.setdefault(user_id, [])
            events.extend(traces)
            del events[:-200]

    def _record_action_validation(self, user_id, trace_id, action_id, action, target, accepted, duration_ms, detail=None, state=None):
        event = {
            "traceId": trace_id,
            "actionId": action_id,
            "service": "Poker Server",
            "method": "VALIDATE_ACTION",
            "path": "/api/game/action",
            "outcome": "ok" if accepted else "rejected",
            "input": {"action": action, **({"to": target} if target is not None else {})},
            "result": {"accepted": accepted},
            "durationMs": round(duration_ms, 3),
        }
        if detail:
            event["result"]["detail"] = detail
        if state:
            event["result"].update(state)
        self._record(user_id, [event])

    def _traces(self, user_id):
        with self.trace_guard:
            return list(self.traces_by_user.get(user_id, []))

    def _session(self, user_id):
        with self.guard:
            return self.sessions.setdefault(user_id, GameSession())

    def _sql(self, sql, params, trace_id, endpoint="/sql"):
        return self._call("Mini DBMS", "POST", self.dbms_url + endpoint, {"sql": sql, "params": params}, trace_id)

    def _insert_once(self, sql, values, key_column, trace_id):
        return self._call("Mini DBMS", "POST", self.dbms_url + "/sql/insert-once",
                          {"sql": sql, "params": values, "keyColumn": key_column}, trace_id)

    @staticmethod
    def _user_id(token_hash):
        suffix = hashlib.sha256(("poker-lab-guest-v1:" + token_hash).encode("ascii")).hexdigest()[:32]
        return "guest_" + suffix

    @staticmethod
    def _now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _hash_fields(fields):
        raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _error(status, code, message, traces=None, trace_id=None):
        result = {"status": status, "error": code, "message": message, "traces": list(traces or [])}
        if trace_id:
            result["traceId"] = trace_id
        return result

    @staticmethod
    def _user_view(row):
        return {"dbId": row["id"], "userId": row["user_id"], "displayName": row["display_name"], "createdAt": row["created_at"]}

    def _find_guest(self, token_hash, trace_id):
        payload, trace = self._sql("SELECT id, user_id, display_name, created_at FROM guest_users WHERE token_hash = ?",
                                   [token_hash], trace_id)
        if trace["outcome"] != "ok":
            return None, trace, "unavailable"
        rows = payload.get("result", {}).get("rows", [])
        if len(rows) > 1:
            trace["outcome"] = "http_error"
            trace["detail"] = "duplicate guest token records"
            return None, trace, "duplicate"
        return (rows[0] if rows else None), trace, "ok"

    def register_guest(self, payload, trace_id):
        if not isinstance(payload, dict) or set(payload) != {"guest_token", "display_name"}:
            return self._error(400, "invalid_guest_request", "guest_token and display_name are required", trace_id=trace_id)
        token = payload["guest_token"]
        name = payload["display_name"]
        if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
            return self._error(400, "invalid_guest_token", "guest_token must be a 256-bit base64url value", trace_id=trace_id)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 24 or any(ord(ch) < 32 for ch in name):
            return self._error(400, "invalid_display_name", "display_name must contain 1 to 24 printable characters", trace_id=trace_id)
        name = name.strip()
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        user_id = self._user_id(token_hash)
        sql = "INSERT INTO guest_users (user_id, token_hash, display_name, created_at) VALUES (?, ?, ?, ?)"
        with self.registration_lock:
            saved, insert_trace = self._insert_once(sql, [user_id, token_hash, name, self._now()], "token_hash", trace_id)
            traces = [insert_trace]
            if insert_trace["outcome"] == "http_error" and insert_trace.get("status") == 409:
                row, lookup_trace, lookup = self._find_guest(token_hash, trace_id)
                traces.append(lookup_trace)
                if lookup == "ok" and row and row["user_id"] == user_id and row["display_name"] == name:
                    saved = {"result": {"insertedId": row["id"], "created": False}}
                elif lookup == "ok" and row:
                    self._record(user_id, traces)
                    return self._error(409, "guest_name_immutable", "this guest account already has a different display name", traces, trace_id)
                else:
                    self._record(user_id, traces)
                    return self._error(503, "guest_storage_unknown", "guest record could not be confirmed; retry with the same token and name", traces, trace_id)
            elif insert_trace["outcome"] != "ok":
                self._record(user_id, traces)
                return self._error(503, "guest_storage_unknown", "guest record outcome is unknown; retry with the same token and name", traces, trace_id)

            row, lookup_trace, lookup = self._find_guest(token_hash, trace_id)
            traces.append(lookup_trace)
            self._record(user_id, traces)
            if lookup != "ok" or row is None or row["user_id"] != user_id or row["display_name"] != name:
                return self._error(503, "guest_storage_unknown", "guest record was not confirmed", traces, trace_id)
            return {"user": self._user_view(row), "traces": traces, "traceId": trace_id,
                    "created": bool(saved.get("result", {}).get("created", False))}

    def authenticate(self, token, trace_id):
        if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
            return None, self._error(401, "guest_auth_required", "valid guest Authorization is required", trace_id=trace_id)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        row, trace, status = self._find_guest(token_hash, trace_id)
        if status != "ok":
            return None, self._error(503, "guest_store_unavailable", "Mini DBMS could not confirm this guest", [trace], trace_id)
        if row is None:
            return None, self._error(401, "guest_auth_invalid", "guest token is not registered", [trace], trace_id)
        user = self._user_view(row)
        self._record(user["userId"], [trace])
        return user, None

    @staticmethod
    def _request_id(payload, name):
        value = payload.get(name) if isinstance(payload, dict) else None
        if not isinstance(value, str) or not 8 <= len(value) <= 128:
            raise ValueError(f"{name} must be a string between 8 and 128 characters")
        return value

    @staticmethod
    def _digest(payload):
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(stable).hexdigest()

    def _game(self, session):
        if not session.engine:
            return None
        game = session.engine.snapshot()
        game["matchKey"] = session.match_key
        game["dbId"] = session.db_id
        game["recordStatus"] = session.record_status
        return game

    def _response(self, user, session, trace_id, replayed=False):
        result = {"game": self._game(session), "traces": self._traces(user["userId"]), "traceId": trace_id}
        if replayed:
            result["replayed"] = True
        return result

    def _cache_public(self, user, session, trace_id):
        state = self._game(session)
        value = {"userId": user["userId"], "matchKey": state["matchKey"], "handNo": state["handNo"],
                 "phase": state["phase"], "turn": state["turn"], "humanStack": state["humanStack"],
                 "botStack": state["botStack"], "pot": state["pot"], "board": state["board"],
                 "handOver": state["handOver"]}
        key = quote("poker:public:" + user["userId"] + ":" + session.match_key, safe="")
        _, get_trace = self._call("Mini Redis", "GET", self.redis_url + "/keys/" + key, trace_id=trace_id)
        _, put_trace = self._call("Mini Redis", "PUT", self.redis_url + "/keys/" + key,
                                  {"value": value, "ttl": 300}, trace_id=trace_id)
        traces = [get_trace, put_trace]
        self._record(user["userId"], traces)
        return traces

    def _load_match_results(self, user, match_key, trace_id):
        sql = "SELECT " + ", ".join(RESULT_COLUMNS) + " FROM hand_results WHERE match_key = ?"
        payload, trace = self._sql(sql, [match_key], trace_id)
        self._record(user["userId"], [trace])
        if trace["outcome"] != "ok":
            return None, trace
        try:
            history = self._validated_rows(match_key, payload.get("result", {}).get("rows", []))
            return history, trace
        except (ValueError, TypeError, KeyError) as exc:
            validation = {"traceId": trace_id, "service": "Poker Server", "method": "VALIDATE",
                          "path": "/hand-results", "outcome": "http_error", "detail": str(exc)}
            self._record(user["userId"], [validation])
            return None, validation

    def start(self, user, payload, trace_id):
        if not isinstance(payload, dict) or set(payload) != {"request_id"}:
            return self._error(400, "invalid_start_request", "start accepts only request_id", trace_id=trace_id)
        try:
            request_id = self._request_id(payload, "request_id")
        except ValueError as exc:
            return self._error(400, "invalid_start_request", str(exc), trace_id=trace_id)
        digest = self._digest(payload)
        session = self._session(user["userId"])
        with session.lock:
            replay = session.start_replays.get(request_id)
            if replay:
                if replay[0] != digest:
                    return self._error(409, "request_id_reused", "request_id was used with a different body", trace_id=trace_id)
                if session.pending_result and not self._persist_pending_result(user, session, trace_id):
                    return self._pending_storage_error(user, session, trace_id)
                if session.storage_blocked:
                    return self._pending_storage_error(user, session, trace_id)
                return self._response(user, session, trace_id, replayed=True)
            # Never replace a terminal engine while its result is unresolved.
            if session.pending_result and not self._persist_pending_result(user, session, trace_id):
                return self._pending_storage_error(user, session, trace_id)
            if session.storage_blocked:
                return self._pending_storage_error(user, session, trace_id)
            if session.engine and not session.engine.snapshot()["matchOver"]:
                return self._error(409, "match_active", "finish the current match before starting another", self._traces(user["userId"]), trace_id)

            match_key = hashlib.sha256(("poker-match-v1:" + user["userId"] + ":" + request_id).encode("utf-8")).hexdigest()[:32]
            sql = "INSERT INTO matches (match_key, player_a, player_b, initial_a, initial_b, blinds, rules_version) VALUES (?, ?, ?, ?, ?, ?, ?)"
            saved, match_trace = self._insert_once(sql, [match_key, user["dbId"], -1, 1000, 1000, "10/20", "poker-lab-holdem-v1"], "match_key", trace_id)
            self._record(user["userId"], [match_trace])
            if match_trace["outcome"] != "ok":
                return self._error(503, "match_storage_unknown", "match INSERT could not be confirmed; retry with the same request_id", self._traces(user["userId"]), trace_id)
            db_id = saved.get("result", {}).get("insertedId")
            history, history_trace = self._load_match_results(user, match_key, trace_id)
            if history is None:
                return self._error(503, "history_recovery_failed", "stored hand history failed validation; no fresh game was started", self._traces(user["userId"]), trace_id)
            stacks = {"human": history["stacks"][0], "bot": history["stacks"][1]}
            engine = PokerEngine(starting_stacks=stacks)
            if history["hand_no"]:
                engine.restore_for_next_hand(stacks, history["hand_no"])
            try:
                engine.start_hand()
            except (RuleError, ValueError) as exc:
                return self._error(409, "match_unavailable", str(exc), self._traces(user["userId"]), trace_id)
            session.engine = engine
            session.match_key = match_key
            session.db_id = db_id
            session.last_result_id = history["last_id"]
            session.pending_result = None
            session.storage_blocked = False
            session.record_status = "not_saved"
            session.action_replays = {}
            session.next_replays = {}
            response = self._finish_transition(user, session, trace_id)
            session.start_replays[request_id] = (digest, response)
            return response

    def next_hand(self, user, payload, trace_id):
        if not isinstance(payload, dict) or set(payload) != {"request_id"}:
            return self._error(400, "invalid_next_request", "next accepts only request_id", trace_id=trace_id)
        try:
            request_id = self._request_id(payload, "request_id")
        except ValueError as exc:
            return self._error(400, "invalid_next_request", str(exc), trace_id=trace_id)
        digest = self._digest(payload)
        session = self._session(user["userId"])
        with session.lock:
            replay = session.next_replays.get(request_id)
            if replay:
                if replay[0] != digest:
                    return self._error(409, "request_id_reused", "request_id was used with a different body", trace_id=trace_id)
                if session.pending_result and not self._persist_pending_result(user, session, trace_id):
                    return self._pending_storage_error(user, session, trace_id)
                return self._response(user, session, trace_id, replayed=True)
            if session.pending_result and not self._persist_pending_result(user, session, trace_id):
                return self._pending_storage_error(user, session, trace_id)
            if session.storage_blocked:
                return self._error(503, "result_storage_blocked", "stored result conflicts with the durable hand ledger", self._traces(user["userId"]), trace_id)
            if not session.engine or not session.engine.hand_over:
                return self._error(409, "hand_active", "the current hand must finish first", self._traces(user["userId"]), trace_id)
            if session.engine.snapshot()["matchOver"]:
                return self._error(409, "match_over", "a player has no chips; start a new match", self._traces(user["userId"]), trace_id)
            try:
                session.engine.start_hand()
            except (RuleError, ValueError) as exc:
                return self._error(409, "hand_unavailable", str(exc), self._traces(user["userId"]), trace_id)
            session.record_status = "not_saved"
            response = self._finish_transition(user, session, trace_id)
            session.next_replays[request_id] = (digest, response)
            return response

    def action(self, user, payload, trace_id):
        if not isinstance(payload, dict):
            return self._error(400, "invalid_action", "body must be an object", trace_id=trace_id)
        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or not 8 <= len(action_id) <= 128:
            return self._error(400, "invalid_action", "action_id is required", trace_id=trace_id)
        allowed = {"action_id", "action", "to"}
        action = payload.get("action")
        target = payload.get("to")
        if set(payload) - allowed or action not in ("fold", "check", "call", "bet", "raise", "all_in"):
            return self._error(400, "invalid_action", "unsupported action or request field", trace_id=trace_id)
        if action in ("bet", "raise") and (not isinstance(target, int) or isinstance(target, bool)):
            return self._error(400, "invalid_action", "to must be an integer chip target", trace_id=trace_id)
        if action not in ("bet", "raise") and "to" in payload:
            return self._error(400, "invalid_action", "to is only valid for bet or raise", trace_id=trace_id)
        digest = self._digest(payload)
        session = self._session(user["userId"])
        with session.lock:
            replay = session.action_replays.get(action_id)
            if replay:
                if replay[0] != digest:
                    return self._error(409, "request_id_reused", "action_id was used with a different body", trace_id=trace_id)
                if session.pending_result and not self._persist_pending_result(user, session, trace_id):
                    return self._pending_storage_error(user, session, trace_id)
                return self._response(user, session, trace_id, replayed=True)
            if session.pending_result and not self._persist_pending_result(user, session, trace_id):
                return self._pending_storage_error(user, session, trace_id)
            if session.storage_blocked:
                return self._error(503, "result_storage_blocked", "stored result conflicts with the durable hand ledger", self._traces(user["userId"]), trace_id)
            if not session.engine:
                return self._error(409, "no_match", "start a match first", self._traces(user["userId"]), trace_id)
            validation_started = time.perf_counter()
            try:
                session.engine.act("human", action, target)
            except RuleError as exc:
                message = str(exc)
                status = 409 if "turn" in message or "active hand" in message or "legal in the current state" in message else 400
                self._record_action_validation(user["userId"], trace_id, action_id, action, target, False,
                                               (time.perf_counter() - validation_started) * 1000, detail=message)
                return self._error(status, "invalid_action", message, self._traces(user["userId"]), trace_id)
            state = session.engine.snapshot()
            self._record_action_validation(
                user["userId"], trace_id, action_id, action, target, True,
                (time.perf_counter() - validation_started) * 1000,
                state={key: state[key] for key in ("phase", "turn", "pot", "humanStack", "botStack")},
            )
            response = self._finish_transition(user, session, trace_id)
            session.action_replays[action_id] = (digest, response)
            return response

    def _finish_transition(self, user, session, trace_id):
        """Finish start/next/action under the session lock, including blind-only runouts.

        Callers remember even UNKNOWN responses so retrying cannot deal or act twice.
        """
        self._run_bot_until_human(session)
        storage_ok = True
        if session.engine.hand_over:
            storage_ok = self._persist_pending_result(user, session, trace_id)
        self._cache_public(user, session, trace_id)
        if not storage_ok:
            return self._pending_storage_error(user, session, trace_id)
        return self._response(user, session, trace_id)

    def _make_result(self, user, session):
        engine = session.engine
        state = engine.snapshot()
        result = state["result"]
        if not result or not state["handOver"]:
            raise ValueError("hand result requested before settlement")
        operation_key = f"{session.match_key}:hand:{state['handNo']}:result"
        public_actions = {"button": state["button"], "actions": state["actions"]}
        fields = {
            "operation_key": operation_key,
            "schema_version": 1,
            "match_key": session.match_key,
            "hand_no": state["handNo"],
            "prev_result_id": session.last_result_id,
            "start_a": state["startingHumanStack"],
            "start_b": state["startingBotStack"],
            "end_a": state["humanStack"],
            "end_b": state["botStack"],
            "winner": result["winner"],
            "reason": result["reason"],
            "board": json.dumps(state["board"], ensure_ascii=False, separators=(",", ":")),
            "public_actions": json.dumps(public_actions, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "rules_version": "poker-lab-holdem-v1",
        }
        fields["payload_hash"] = self._hash_fields(fields)
        sql = "INSERT INTO hand_results (operation_key, payload_hash, schema_version, match_key, hand_no, prev_result_id, start_a, start_b, end_a, end_b, winner, reason, board, public_actions, rules_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        ordered = [fields[column] for column in ("operation_key", "payload_hash", "schema_version", "match_key", "hand_no", "prev_result_id", "start_a", "start_b", "end_a", "end_b", "winner", "reason", "board", "public_actions", "rules_version")]
        return {"sql": sql, "params": ordered, "operation_key": operation_key, "payload_hash": fields["payload_hash"]}

    def _persist_pending_result(self, user, session, trace_id):
        if session.storage_blocked:
            return False
        if session.pending_result is None:
            session.pending_result = self._make_result(user, session)
        session.record_status = "pending"
        pending = session.pending_result
        saved, trace = self._insert_once(pending["sql"], pending["params"], "operation_key", trace_id)
        self._record(user["userId"], [trace])
        if trace["outcome"] == "ok":
            session.last_result_id = saved["result"]["insertedId"]
            session.pending_result = None
            session.record_status = "confirmed"
            return True
        if trace["outcome"] == "http_error" and trace.get("status") == 409:
            session.storage_blocked = True
            session.record_status = "blocked"
            return False
        session.record_status = "unknown"
        return False

    def _pending_storage_error(self, user, session, trace_id):
        result = self._error(503, "result_storage_unknown" if not session.storage_blocked else "result_storage_blocked",
                             "the result append is unresolved; no next hand or different action is accepted",
                             self._traces(user["userId"]), trace_id)
        result["game"] = self._game(session)
        return result

    def _run_bot_until_human(self, session):
        while session.engine and session.engine.turn == "bot" and not session.engine.hand_over:
            legal = session.engine.legal_actions("bot")
            # Practice bot: checks when free and calls the contestable amount otherwise.
            session.engine.act("bot", "check" if "check" in legal else "call")

    def snapshot(self, user, trace_id):
        session = self._session(user["userId"])
        with session.lock:
            return self._response(user, session, trace_id)

    def _validated_rows(self, match_key, rows):
        ordered = sorted(rows, key=lambda row: row["id"])
        previous_id = 0
        previous_stacks = (1000, 1000)
        expected_hand = 1
        seen = set()
        for row in ordered:
            if row["operation_key"] in seen:
                raise ValueError("duplicate hand result operation key")
            seen.add(row["operation_key"])
            fields = {key: row[key] for key in RESULT_COLUMNS if key not in ("id", "payload_hash")}
            if row["payload_hash"] != self._hash_fields(fields):
                raise ValueError("hand result payload hash mismatch")
            board = json.loads(row["board"])
            actions = json.loads(row["public_actions"])
            if (row["match_key"] != match_key or row["hand_no"] != expected_hand
                    or row["operation_key"] != f"{match_key}:hand:{expected_hand}:result"
                    or row["prev_result_id"] != previous_id
                    or (row["start_a"], row["start_b"]) != previous_stacks
                    or row["winner"] not in ("human", "bot", "tie")
                    or row["reason"] not in ("fold", "showdown")
                    or row["end_a"] + row["end_b"] != row["start_a"] + row["start_b"]
                    or not isinstance(board, list) or len(board) not in (0, 3, 4, 5)
                    or len(set(board)) != len(board)
                    or not isinstance(actions, dict) or actions.get("button") not in ("human", "bot")
                    or not isinstance(actions.get("actions"), list)
                    or (row["reason"] == "showdown" and len(board) != 5)
                    or (row["reason"] == "fold" and row["winner"] == "tie")):
                raise ValueError("hand result chain is inconsistent")
            for action in actions["actions"]:
                if (not isinstance(action, dict) or set(action) - {"player", "action", "street", "to", "paid", "allIn", "fullRaise"}
                        or action.get("player") not in ("human", "bot")):
                    raise ValueError("private data found in public action log")
            if row["reason"] == "fold" and (
                not actions["actions"] or actions["actions"][-1].get("action") != "fold"
                or actions["actions"][-1].get("player") == row["winner"]
            ):
                raise ValueError("fold result does not match its final action")
            previous_id = row["id"]
            previous_stacks = (row["end_a"], row["end_b"])
            expected_hand += 1
        return {"rows": ordered, "last_id": previous_id, "stacks": previous_stacks, "hand_no": expected_hand - 1}

    def profile(self, user, trace_id):
        """Practice (vs bot) and online (two-human room) records for this guest, from the DBMS ledger only.

        In `matches`, player_a is seat 0 (engine side "human") and player_b is seat 1 (engine
        side "bot"); practice matches store player_b = -1. Every hand is counted from the
        user's own seat, so a room participant in seat 1 gets their own wins and stacks.
        """
        unavailable = lambda message: self._error(503, "profile_store_unavailable", message, self._traces(user["userId"]), trace_id)
        matches = {}
        for column in ("player_a", "player_b"):
            payload, trace = self._sql("SELECT id, match_key, player_a, player_b FROM matches WHERE " + column + " = ?", [user["dbId"]], trace_id)
            self._record(user["userId"], [trace])
            if trace["outcome"] != "ok":
                return unavailable("Mini DBMS could not load matches")
            for row in payload.get("result", {}).get("rows", []):
                matches[row["id"]] = row
        totals = {mode: {"matches": 0, "hands": 0, "wins": 0, "losses": 0, "draws": 0} for mode in ("practice", "online")}
        recent = {"practice": [], "online": []}
        names = {}
        for match in sorted(matches.values(), key=lambda row: row["id"]):
            seat = 0 if match["player_a"] == user["dbId"] else 1
            side = ("human", "bot")[seat]
            mode = "practice" if match["player_b"] == -1 else "online"
            opponent = None
            if mode == "online":
                other = match["player_b"] if seat == 0 else match["player_a"]
                if other not in names:
                    payload, trace = self._sql("SELECT id, display_name FROM guest_users WHERE id = ?", [other], trace_id)
                    self._record(user["userId"], [trace])
                    rows = payload.get("result", {}).get("rows", []) if trace["outcome"] == "ok" else None
                    if not rows:
                        return unavailable("Mini DBMS could not load the opponent of an online match")
                    names[other] = rows[0]["display_name"]
                opponent = names[other]
            sql = "SELECT " + ", ".join(RESULT_COLUMNS) + " FROM hand_results WHERE match_key = ?"
            payload, trace = self._sql(sql, [match["match_key"]], trace_id)
            self._record(user["userId"], [trace])
            if trace["outcome"] != "ok":
                return unavailable("Mini DBMS could not load completed hands")
            try:
                history = self._validated_rows(match["match_key"], payload.get("result", {}).get("rows", []))
            except (ValueError, TypeError, KeyError):
                return self._error(503, "profile_data_corrupt", "stored hand history failed validation", self._traces(user["userId"]), trace_id)
            bucket = totals[mode]
            bucket["matches"] += 1
            for row in history["rows"]:
                result = "draw" if row["winner"] == "tie" else "win" if row["winner"] == side else "loss"
                bucket["hands"] += 1
                bucket[{"win": "wins", "loss": "losses", "draw": "draws"}[result]] += 1
                entry = {"matchKey": match["match_key"], "id": row["id"], "handNo": row["hand_no"], "mode": mode, "seat": seat,
                         "result": result, "winner": row["winner"], "reason": row["reason"],
                         "startStack": row["start_a"] if seat == 0 else row["start_b"],
                         "endStack": row["end_a"] if seat == 0 else row["end_b"],
                         "board": json.loads(row["board"])}
                if opponent is not None:
                    entry["opponent"] = opponent
                recent[mode].append(entry)
        # 2-4 seat rooms: every match this guest bought into; each hand counted from the guest's own seat
        # by net chips (win > 0, loss < 0, draw = 0).
        payload, trace = self._sql("SELECT match_key, kind FROM room_seat_events WHERE user_db = ?", [user["dbId"]], trace_id)
        self._record(user["userId"], [trace])
        if trace["outcome"] != "ok":
            return unavailable("Mini DBMS could not load room seats")
        joined = sorted({row["match_key"] for row in payload.get("result", {}).get("rows", []) if row["kind"] == "buyin"})
        # free rebuys are counted on their own: they are never winnings (per-hand net uses only hand start/end chips)
        totals["online"]["rebuys"] = sum(1 for row in payload.get("result", {}).get("rows", []) if row["kind"] == "rebuy")
        for match_key in joined:
            ledger, error = self.rooms.load_ledger(match_key, trace_id)
            if ledger is None:
                if error == "unavailable":
                    return unavailable("Mini DBMS could not load room hands")
                return self._error(503, "profile_data_corrupt", "stored room history failed validation", self._traces(user["userId"]), trace_id)
            totals["online"]["matches"] += 1
            for row in ledger["hands"]:
                participants = json.loads(row["participants"])
                mine = next((p for p in participants if p["user"] == user["dbId"]), None)
                if mine is None:
                    continue
                others = [p["user"] for p in participants if p["user"] != user["dbId"]]
                for other in others:
                    if other not in names:
                        found, trace = self._sql("SELECT id, display_name FROM guest_users WHERE id = ?", [other], trace_id)
                        rows = found.get("result", {}).get("rows", []) if trace["outcome"] == "ok" else None
                        if not rows:
                            return unavailable("Mini DBMS could not load a room opponent")
                        names[other] = rows[0]["display_name"]
                net = mine["end"] - mine["start"]
                result = "win" if net > 0 else "loss" if net < 0 else "draw"
                totals["online"]["hands"] += 1
                totals["online"][{"win": "wins", "loss": "losses", "draw": "draws"}[result]] += 1
                recent["online"].append({
                    "matchKey": match_key, "id": row["id"], "source": "room", "handNo": row["hand_no"], "mode": "online",
                    "seat": mine["seat"], "result": result, "net": net, "reason": row["reason"],
                    "startStack": mine["start"], "endStack": mine["end"], "board": json.loads(row["board"]),
                    "players": len(participants), "opponents": [names[o] for o in others],
                    "opponent": ", ".join(names[o] for o in others)})
        for rows in recent.values():
            # rows of the 2-4 seat tables are newer than any row of the earlier two-seat tables
            rows.sort(key=lambda row: (row.get("source") == "room", row["id"]), reverse=True)
        profile = {
            "userId": user["userId"], "displayName": user["displayName"], "createdAt": user["createdAt"],
            "practice": totals["practice"],
            "online": totals["online"],
            "recentGames": recent["practice"][:10],  # practice only, kept for the existing practice screen
            "recentOnline": recent["online"][:10],
            "rank": {"enabled": False, "rating": None, "tier": None, "season": None},
        }
        return {"profile": profile, "traces": self._traces(user["userId"]), "traceId": trace_id}


class Handler(BaseHTTPRequestHandler):
    demo = None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def _bearer(self):
        value = self.headers.get("Authorization", "")
        prefix = "Bearer "
        return value[len(prefix):] if value.startswith(prefix) else None

    def _auth(self, trace_id):
        return self.demo.authenticate(self._bearer(), trace_id)

    def _rooms(self, method, payload, trace_id):
        """Multiplayer rooms: /api/rooms... Only GET .../public is readable without a guest token."""
        url = urlsplit(self.path)
        parts = [part for part in url.path[len("/api/rooms"):].split("/") if part]
        user = None
        if not (method == "GET" and len(parts) == 2 and parts[1] == "public"):
            user, error = self._auth(trace_id)
            if error:
                return self._send(error.get("status", 401), error)
        status, body = self.demo.rooms.dispatch(method, parts, parse_qs(url.query), payload, user, trace_id)
        return self._send(status, body)

    @staticmethod
    def _is_rooms_path(path):
        path = urlsplit(path).path
        return path == "/api/rooms" or path.startswith("/api/rooms/")

    def do_GET(self):
        trace_id = uuid.uuid4().hex
        if self._is_rooms_path(self.path):
            try:
                return self._rooms("GET", None, trace_id)
            except Exception:
                return self._send(500, {"error": "internal_error"})
        if self.path not in ("/api/game", "/api/profile"):
            return self._send(404, {"error": "not_found"})
        user, error = self._auth(trace_id)
        if error:
            return self._send(error.get("status", 401), error)
        result = self.demo.snapshot(user, trace_id) if self.path == "/api/game" else self.demo.profile(user, trace_id)
        return self._send(result.get("status", 200), result)

    def do_POST(self):
        try:
            length = self.headers.get("Content-Length")
            if length is None:
                return self._send(411, {"error": "length_required"})
            size = int(length)
            if size < 0 or size > MAX_BODY_BYTES:
                return self._send(413, {"error": "request_too_large"})
            payload = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload, dict):
                return self._send(400, {"error": "invalid_request", "message": "body must be an object"})
            trace_id = uuid.uuid4().hex
            if self.path == "/api/guest":
                result = self.demo.register_guest(payload, trace_id)
                return self._send(result.get("status", 200), result)
            if self._is_rooms_path(self.path):
                return self._rooms("POST", payload, trace_id)
            if self.path not in ("/api/game/start", "/api/game/next", "/api/game/action"):
                return self._send(404, {"error": "not_found"})
            user, error = self._auth(trace_id)
            if error:
                return self._send(error.get("status", 401), error)
            if self.path == "/api/game/start":
                result = self.demo.start(user, payload, trace_id)
            elif self.path == "/api/game/next":
                result = self.demo.next_hand(user, payload, trace_id)
            else:
                result = self.demo.action(user, payload, trace_id)
                action_id = payload.get("action_id")
                for event in result.get("traces", []):
                    if event.get("traceId") == trace_id:
                        event["actionId"] = action_id
            return self._send(result.get("status", 200), result)
        except (ValueError, json.JSONDecodeError):
            return self._send(400, {"error": "invalid_request", "message": "body must be valid JSON"})
        except Exception:
            return self._send(500, {"error": "internal_error"})

    def _send(self, status, value):
        if getattr(self, "_disconnected", False):
            return  # the client is gone; never write a second response to it
        raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
        try:
            self._write_response(status, raw)
        except (BrokenPipeError, ConnectionResetError):
            self._disconnected = True  # client closed the connection before reading the answer
            self.close_connection = True

    def _write_response(self, status, raw):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):
        # BaseHTTPRequestHandler would print request targets; keep bearer tokens out of logs.
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18784)
    parser.add_argument("--dbms", default="http://127.0.0.1:18783")
    parser.add_argument("--redis", default="http://127.0.0.1:6382")
    args = parser.parse_args()
    demo = Demo(args.dbms, args.redis)
    handler = type("PokerHandler", (Handler,), {"demo": demo})
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Poker Lab API listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
