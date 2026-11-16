"""Room-based two-human multiplayer for JUNGLE POKER LAB.

Flow: player action -> server validates under the room lock -> durable append (DBMS)
and public cache write (Redis) -> every seated client receives the same ordered
events and version through GET .../state (long polling).

The two-seat PokerEngine is reused unchanged: seat 0 is the engine's "human" side and
seat 1 is its "bot" side. Those names are internal ledger identifiers only; both seats
are people here. The server owns deck, turn, legal actions, chips, pot and results.
A viewer receives only their own hole cards until a showdown reveals both hands.
"""
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import quote

from engine import PokerEngine, RuleError

SEAT_IDS = ("human", "bot")  # engine side for seat 0 / seat 1
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L look-alikes
CODE_LENGTH = 6
STREET_SIZES = (("flop", 3), ("turn", 4), ("river", 5))
RULES_VERSION = "poker-lab-holdem-v1"
ACTIONS = ("fold", "check", "call", "bet", "raise", "all_in")


def match_key_for(code):
    """One room is one match; the durable match key is derived from the room code."""
    return hashlib.sha256(("poker-room-v1:" + code).encode("ascii")).hexdigest()[:32]


class Room:
    """In-memory authoritative state of one room. Mutated only while holding `cond`."""

    def __init__(self, code):
        self.code = code
        self.cond = threading.Condition(threading.RLock())
        self.seats = [None, None]  # {"userId", "dbId", "name"}
        self.ready = [False, False]
        self.last_seen = [None, None]
        self.connected = [False, False]
        self.phase = "lobby"  # lobby | playing | hand_over | match_over
        # Counters start from the wall clock (ms) instead of 0. A room rebuilt after a server
        # restart therefore continues with larger numbers than any client saw before, so an
        # old cursor or an action made for the lost hand can never match the new state.
        base = int(time.time() * 1000)
        self.instance = secrets.token_hex(4)  # changes when the room object is rebuilt
        self.version = base  # any visible change (sync cursor)
        self.game_version = base  # game transitions only (hand start, action, timeout)
        self.events = []
        self.event_seq = base
        self.notice = ""
        self.turn_deadline = None
        self.next_deadline = None
        self.retry_at = 0.0
        self.action_replays = {}
        self.recovered = False
        # Attribute names below match server.GameSession so Demo's result-ledger
        # helpers (_make_result / _persist_pending_result) are reused as they are.
        self.engine = None
        self.match_key = None
        self.db_id = None
        self.last_result_id = 0
        self.pending_result = None
        self.storage_blocked = False
        self.record_status = "not_started"

    def seat_of(self, user):
        for index, seat in enumerate(self.seats):
            if seat and seat["userId"] == user["userId"]:
                return index
        return None


class RoomService:
    TURN_SECONDS = 30.0  # a player who does not act in time is checked, or folded when facing a bet
    NEXT_HAND_SECONDS = 12.0  # next hand starts when both are ready, or automatically after this wait
    PRESENCE_SECONDS = 8.0  # a seat whose last state request started longer ago than this is shown as disconnected
    STORAGE_RETRY_SECONDS = 2.0
    # Upper bound of one waiting state request. It must stay below PRESENCE_SECONDS: a live
    # client starts a new request at least this often, while a vanished client (closed lid,
    # lost network) cannot be told apart from a waiting one until its request ends.
    MAX_WAIT_SECONDS = 5.0
    PUBLIC_TTL_SECONDS = 30
    REDIS_BACKOFF_SECONDS = 5.0  # after a Redis failure, skip Redis for a while so play is not slowed
    MAX_ROOMS = 500
    MAX_EVENTS = 300

    def __init__(self, demo, clock=time.monotonic, engine_factory=PokerEngine):
        self.demo = demo
        self.clock = clock
        self.engine_factory = engine_factory
        self.guard = threading.RLock()
        self.rooms = {}
        self.create_replays = {}
        self.redis_skip_until = 0.0

    # ── HTTP entry ──────────────────────────────────────────────────────────

    def dispatch(self, method, parts, query, payload, user, trace_id):
        """parts: path segments after /api/rooms. Returns (status, body)."""
        try:
            if method == "POST" and not parts:
                return self.create(user, payload, trace_id)
            if len(parts) != 2:
                return self._err(404, "not_found", "unknown room route")
            code = parts[0].upper()
            if len(code) != CODE_LENGTH or any(ch not in CODE_ALPHABET for ch in code):
                return self._err(404, "room_not_found", "방 코드를 확인하세요")
            verb = parts[1]
            if method == "GET" and verb == "public":
                return self.public(code, trace_id)
            if user is None:
                return self._err(401, "guest_auth_required", "valid guest Authorization is required")
            if method == "GET" and verb == "state":
                return self.state(user, code, query, trace_id)
            if method == "POST" and verb == "join":
                return self.join(user, code, trace_id)
            if method == "POST" and verb == "leave":
                return self.leave(user, code, trace_id)
            if method == "POST" and verb == "ready":
                return self.set_ready(user, code, payload, trace_id)
            if method == "POST" and verb == "action":
                return self.action(user, code, payload, trace_id)
            return self._err(404, "not_found", "unknown room route")
        except _Stop as stop:
            return stop.status, stop.body

    @staticmethod
    def _err(status, code, message, state=None):
        body = {"error": code, "message": message}
        if state is not None:
            body["state"] = state
        return status, body

    # ── rooms and seats ─────────────────────────────────────────────────────

    def create(self, user, payload, trace_id):
        if user is None:
            return self._err(401, "guest_auth_required", "valid guest Authorization is required")
        if not isinstance(payload, dict) or set(payload) != {"request_id"}:
            return self._err(400, "invalid_create_request", "create accepts only request_id")
        try:
            request_id = self.demo._request_id(payload, "request_id")
        except ValueError as exc:
            return self._err(400, "invalid_create_request", str(exc))
        with self.guard:
            replay_key = (user["userId"], request_id)
            code = self.create_replays.get(replay_key)
            room = self.rooms.get(code) if code else None
            if room is None:
                if len(self.rooms) >= self.MAX_ROOMS:
                    return self._err(503, "too_many_rooms", "방이 너무 많습니다. 잠시 뒤 다시 시도하세요")
                code = self._new_code(trace_id)
                room = Room(code)
                with room.cond:
                    self._sit(room, 0, user)
                    room.notice = "상대에게 방 코드를 알려 주세요."
                    self._bump(room, trace_id)
                self.rooms[code] = room
                self.create_replays[replay_key] = code
                if len(self.create_replays) > 4 * self.MAX_ROOMS:
                    self.create_replays.clear()
                    self.create_replays[replay_key] = code
        with room.cond:
            seat = room.seat_of(user)
            if seat is None:  # the creator left and someone else owns the room now
                return self._err(409, "room_left", "이미 나간 방입니다. 새 방을 만드세요")
            return 200, {"state": self._view(room, seat, 0)}

    def _new_code(self, trace_id):
        for _ in range(20):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code in self.rooms:
                continue
            # A code whose match already exists in the DBMS belongs to an earlier room.
            payload, trace = self.demo._sql("SELECT id FROM matches WHERE match_key = ?", [match_key_for(code)], trace_id)
            if trace["outcome"] != "ok":
                raise _Stop(503, {"error": "room_store_unavailable", "message": "Mini DBMS에 연결할 수 없어 방을 만들 수 없습니다"})
            if not payload.get("result", {}).get("rows"):
                return code
        raise _Stop(503, {"error": "room_code_exhausted", "message": "방 코드를 만들지 못했습니다"})

    def _sit(self, room, seat, user):
        room.seats[seat] = {"userId": user["userId"], "dbId": user["dbId"], "name": user["displayName"]}
        room.ready[seat] = False
        room.last_seen[seat] = self.clock()
        room.connected[seat] = True

    def _room(self, code, trace_id):
        """Find a room; after a server restart, rebuild a started match from the DBMS ledger."""
        with self.guard:
            room = self.rooms.get(code)
            if room is None:
                room = self._recover(code, trace_id)
                if room is not None:
                    self.rooms[code] = room
        if room is None:
            raise _Stop(404, {"error": "room_not_found", "message": "방을 찾을 수 없습니다. 코드를 확인하거나 새 방을 만드세요"})
        return room

    def join(self, user, code, trace_id):
        room = self._room(code, trace_id)
        with room.cond:
            seat = room.seat_of(user)
            if seat is None:
                if room.phase != "lobby":
                    return self._err(409, "room_in_progress", "이미 게임이 진행 중인 방입니다")
                free = [index for index, value in enumerate(room.seats) if value is None]
                if not free:
                    return self._err(409, "room_full", "방이 가득 찼습니다")
                seat = free[0]
                self._sit(room, seat, user)
                room.notice = "두 사람 모두 준비를 누르면 시작합니다."
                self._bump(room, trace_id)
            return 200, {"state": self._view(room, seat, 0)}

    def leave(self, user, code, trace_id):
        room = self._room(code, trace_id)
        with self.guard, room.cond:
            seat = room.seat_of(user)
            if seat is None:
                return 200, {"left": True}
            if room.phase != "lobby":
                return self._err(409, "match_in_progress", "게임이 시작된 뒤에는 자리를 비울 수 없습니다. 창을 닫으면 차례마다 제한 시간 뒤 자동 처리됩니다",
                                 self._view(room, seat, 0))
            room.seats[seat] = None
            room.ready[seat] = False
            room.connected[seat] = False
            room.last_seen[seat] = None
            room.notice = "상대가 방을 나갔습니다."
            self._bump(room, trace_id)
            if room.seats == [None, None]:
                self.rooms.pop(code, None)
            return 200, {"left": True}

    def set_ready(self, user, code, payload, trace_id):
        if (not isinstance(payload, dict) or set(payload) != {"ready", "hand_no"} or not isinstance(payload["ready"], bool)
                or not isinstance(payload["hand_no"], int) or isinstance(payload["hand_no"], bool)):
            return self._err(400, "invalid_ready_request", "ready(boolean) and hand_no(integer) are required")
        room = self._room(code, trace_id)
        with room.cond:
            seat = self._seat_or_stop(room, user)
            self._seen(room, seat)
            self._tick(room, trace_id)
            if room.phase == "playing":
                return self._err(409, "hand_active", "핸드가 진행 중입니다", self._view(room, seat, 0))
            if room.phase == "match_over":
                return self._err(409, "match_over", "매치가 끝났습니다. 새 방을 만드세요", self._view(room, seat, 0))
            # hand_no pins the request to the hand it was made for, so a late duplicate
            # cannot mark the player ready for a later hand.
            if payload["hand_no"] != self._hand_no(room):
                return self._err(409, "stale_state", "이미 다음 상태로 넘어갔습니다", self._view(room, seat, 0))
            if room.ready[seat] != payload["ready"]:
                room.ready[seat] = payload["ready"]
                self._bump(room, trace_id)
            error = self._advance(room, trace_id)
            if error:
                return self._err(error[0], error[1], error[2], self._view(room, seat, 0))
            return 200, {"state": self._view(room, seat, 0)}

    def _seat_or_stop(self, room, user):
        seat = room.seat_of(user)
        if seat is None:
            # Knowing the room code is not enough: only the seat owner's token may act.
            raise _Stop(403, {"error": "not_seated", "message": "이 방의 좌석 소유자가 아닙니다"})
        return seat

    # ── game transitions (always under room.cond) ───────────────────────────

    @staticmethod
    def _hand_no(room):
        return room.engine.hand_no if room.engine else 0

    def _advance(self, room, trace_id):
        """Start the match or the next hand when its conditions hold. Returns an error tuple or None."""
        now = self.clock()
        if room.phase == "lobby":
            if all(room.seats) and all(room.ready):
                return self._start_match(room, trace_id)
            return None
        if room.phase != "hand_over" or room.record_status not in ("confirmed", "not_saved") or room.pending_result:
            return None
        both_ready = all(room.ready)
        timed = room.next_deadline is not None and now >= room.next_deadline and all(room.connected)
        if both_ready or timed:
            self._start_hand(room, trace_id)
        return None

    def _start_match(self, room, trace_id):
        match_key = match_key_for(room.code)
        sql = "INSERT INTO matches (match_key, player_a, player_b, initial_a, initial_b, blinds, rules_version) VALUES (?, ?, ?, ?, ?, ?, ?)"
        values = [match_key, room.seats[0]["dbId"], room.seats[1]["dbId"], 1000, 1000, "10/20", RULES_VERSION]
        saved, trace = self.demo._insert_once(sql, values, "match_key", trace_id)
        if trace["outcome"] != "ok":
            # Seats are durable only once this row exists, so the match does not start without it.
            room.ready = [False, False]
            room.notice = "매치 기록을 저장하지 못해 시작하지 못했습니다. 다시 준비를 눌러 주세요."
            self._bump(room, trace_id)
            return (503, "match_storage_unknown", "매치 저장을 확인하지 못했습니다. 다시 준비를 눌러 주세요")
        room.match_key = match_key
        room.db_id = saved["result"]["insertedId"]
        room.engine = self.engine_factory()
        room.record_status = "not_saved"
        self._start_hand(room, trace_id)
        return None

    def _start_hand(self, room, trace_id):
        engine = room.engine
        engine.start_hand()
        room.phase = "playing"
        room.ready = [False, False]
        room.record_status = "not_saved"
        room.next_deadline = None
        room.recovered = False  # the restart notice is only shown until play resumes
        room.action_replays = {}
        room.game_version += 1
        hand = engine.hand
        button = SEAT_IDS.index(hand["button"])
        room.notice = f"{engine.hand_no}번째 핸드 · 블라인드 {engine.small_blind}/{engine.big_blind}"
        # The engine may already have run a blind-only all-in to showdown, so the chips
        # shown for "hand_start" are derived from the starting stacks and the blinds.
        start = [hand["start_stacks"][side] for side in SEAT_IDS]
        blinds = [0, 0]
        blinds[button] = min(engine.small_blind, start[button])
        blinds[1 - button] = min(engine.big_blind, start[1 - button])
        running = {"stacks": [start[i] - blinds[i] for i in range(2)], "committed": blinds}
        self._event(room, "hand_start", running, button=button, smallBlind=engine.small_blind, bigBlind=engine.big_blind)
        self._after_step(room, [], 0, running, trace_id)

    @staticmethod
    def _running(room):
        """Chips as the engine holds them right now (valid while a hand is being played)."""
        engine = room.engine
        return {"stacks": [engine.stacks[side] for side in SEAT_IDS],
                "committed": [engine.hand["total_bets"][side] for side in SEAT_IDS]}

    def _event(self, room, kind, running=None, **fields):
        """Append one public event. `running` gives the chips right after this event;
        without it the engine's current (settled) values are used."""
        engine = room.engine
        hand = engine.hand if engine else None
        if running is None:
            running = self._running(room) if hand else {"stacks": [engine.stacks[side] for side in SEAT_IDS] if engine else [0, 0], "committed": [0, 0]}
        room.event_seq += 1
        event = {
            "seq": room.event_seq, "type": kind, "gameVersion": room.game_version, "handNo": self._hand_no(room),
            "board": list(hand["board"]) if hand else [],
            "pot": sum(running["committed"]),
            "stacks": list(running["stacks"]),
            "committed": list(running["committed"]),
        }
        event.update(fields)
        room.events.append(event)
        del room.events[:-self.MAX_EVENTS]
        return event

    def _after_step(self, room, board_before, actions_before, running, trace_id, auto=False):
        """Publish what the engine just did as ordered public events, then settle or arm the turn timer.

        One engine step can contain an action, several streets and the payout. `running`
        (chips before the step) is advanced event by event, so each event shows the table
        exactly as it was at that moment; only "hand_end" shows the settled stacks.
        """
        engine = room.engine
        hand = engine.hand
        board = list(hand["board"])
        for action in hand["actions"][actions_before:]:
            seat = SEAT_IDS.index(action["player"])
            paid = action.get("paid", 0)
            running["stacks"][seat] -= paid
            running["committed"][seat] += paid
            fields = {"seat": seat, "action": action["action"], "paid": paid,
                      "allIn": bool(action.get("allIn")), "auto": auto}
            if "to" in action:
                fields["to"] = action["to"]
            event = self._event(room, "action", running, **fields)
            event["board"] = list(board_before)
        for street, size in STREET_SIZES:
            if len(board_before) < size <= len(board):
                event = self._event(room, "street", running, street=street)
                event["board"] = board[:size]
        if engine.hand_over:
            result = hand["result"]
            winner = result["winner"]
            self._event(room, "hand_end", reason=result["reason"], potWon=result["pot"],
                        winnerSeat=None if winner == "tie" else SEAT_IDS.index(winner),
                        payouts=[result["payouts"][side] for side in SEAT_IDS])
            room.turn_deadline = None
            room.phase = "match_over" if any(engine.stacks[side] == 0 for side in SEAT_IDS) else "hand_over"
            room.notice = self._result_text(room)
            self._persist(room, trace_id)
        else:
            room.turn_deadline = self.clock() + self.TURN_SECONDS
        self._bump(room, trace_id)

    def _result_text(self, room):
        result = room.engine.hand["result"]
        if result["winner"] == "tie":
            return f"무승부 · 팟 {result['pot']}칩을 나눴습니다."
        name = room.seats[SEAT_IDS.index(result["winner"])]["name"]
        how = "상대 폴드" if result["reason"] == "fold" else "쇼다운 " + result["hands"][result["winner"]]
        return f"{name} 승리 ({how}) · {result['pot']}칩"

    def _persist(self, room, trace_id):
        """Append the completed hand once. Until it is confirmed, no next hand starts."""
        ok = self.demo._persist_pending_result({"userId": "room:" + room.code}, room, trace_id)
        now = self.clock()
        if ok:
            room.next_deadline = now + self.NEXT_HAND_SECONDS
        else:
            room.retry_at = now + self.STORAGE_RETRY_SECONDS
            room.notice += " · 결과 저장 확인 중(확인될 때까지 다음 판이 시작되지 않습니다)"
        return ok

    def action(self, user, code, payload, trace_id):
        allowed = {"action_id", "expected_version", "action", "to"}
        if (not isinstance(payload, dict) or not {"action_id", "expected_version", "action"} <= set(payload) or set(payload) - allowed
                or payload["action"] not in ACTIONS
                or not isinstance(payload["expected_version"], int) or isinstance(payload["expected_version"], bool)):
            return self._err(400, "invalid_action_request", "action_id, expected_version and a known action are required")
        try:
            action_id = self.demo._request_id(payload, "action_id")
        except ValueError as exc:
            return self._err(400, "invalid_action_request", str(exc))
        target = payload.get("to")
        if payload["action"] in ("bet", "raise"):
            if not isinstance(target, int) or isinstance(target, bool) or target <= 0:
                return self._err(400, "invalid_action_request", "bet and raise need a positive integer 'to'")
        elif "to" in payload:
            return self._err(400, "invalid_action_request", "'to' is only for bet and raise")
        digest = self.demo._digest({key: payload[key] for key in payload if key != "action_id"})

        room = self._room(code, trace_id)
        with room.cond:
            seat = self._seat_or_stop(room, user)
            self._seen(room, seat)
            self._tick(room, trace_id)  # an expired turn is settled first; the late request then fails as stale
            replay_key = (user["userId"], action_id)
            previous = room.action_replays.get(replay_key)
            if previous is not None:
                if previous != digest:
                    return self._err(409, "request_id_reused", "action_id was used with a different body", self._view(room, seat, 0))
                # Same request again (double click / resend): nothing is applied twice.
                return 200, {"state": self._view(room, seat, 0), "replayed": True}
            if room.phase != "playing":
                return self._err(409, "hand_not_active", "진행 중인 핸드가 없습니다", self._view(room, seat, 0))
            if payload["expected_version"] != room.game_version:
                return self._err(409, "stale_state", "상태가 이미 바뀌었습니다. 화면을 갱신했습니다", self._view(room, seat, 0))
            side = SEAT_IDS[seat]
            engine = room.engine
            if engine.turn != side:
                return self._err(409, "not_your_turn", "상대 차례입니다", self._view(room, seat, 0))
            board_before = list(engine.hand["board"])
            actions_before = len(engine.hand["actions"])
            running = self._running(room)
            try:
                engine.act(side, payload["action"], target)
            except RuleError as exc:
                return self._err(400, "illegal_action", str(exc), self._view(room, seat, 0))
            room.action_replays[replay_key] = digest
            room.game_version += 1
            self._after_step(room, board_before, actions_before, running, trace_id)
            return 200, {"state": self._view(room, seat, 0)}

    # ── time: presence, turn timeout, storage retry, next hand ──────────────

    def _seen(self, room, seat):
        room.last_seen[seat] = self.clock()

    def _tick(self, room, trace_id=None):
        now = self.clock()
        connected = [bool(room.seats[i]) and room.last_seen[i] is not None and now - room.last_seen[i] < self.PRESENCE_SECONDS
                     for i in range(2)]
        if connected != room.connected:
            room.connected = connected
            self._bump(room, trace_id)
        if room.phase == "playing" and room.turn_deadline is not None and now >= room.turn_deadline:
            self._timeout_turn(room, trace_id)
        if room.phase in ("hand_over", "match_over") and room.pending_result and not room.storage_blocked and now >= room.retry_at:
            room.notice = self._result_text(room)
            self._persist(room, trace_id)
            self._bump(room, trace_id)
        self._advance(room, trace_id)

    def _timeout_turn(self, room, trace_id):
        """Timeout rule, applied only by the server clock: check when free, otherwise fold."""
        engine = room.engine
        side = engine.turn
        action = "check" if "check" in engine.legal_actions(side) else "fold"
        board_before = list(engine.hand["board"])
        actions_before = len(engine.hand["actions"])
        running = self._running(room)
        engine.act(side, action)
        room.game_version += 1
        self._after_step(room, board_before, actions_before, running, trace_id, auto=True)

    def tick(self, code):
        """Apply time-based rules now (used by tests and by waiting state requests)."""
        room = self.rooms.get(code)
        if room is not None:
            with room.cond:
                self._tick(room)

    def state(self, user, code, query, trace_id):
        try:
            since = int(query["since"][0]) if "since" in query else None
            after = int(query.get("after", ["0"])[0])
            wait = float(query.get("wait", ["0"])[0])
        except (ValueError, TypeError):
            return self._err(400, "invalid_state_request", "since/after must be integers and wait a number")
        if not (0 <= wait <= 3600) or after < 0:  # also rejects NaN
            return self._err(400, "invalid_state_request", "wait and after must be non-negative")
        room = self._room(code, trace_id)
        with room.cond:
            seat = self._seat_or_stop(room, user)
            self._seen(room, seat)  # presence is refreshed when a request starts, not while it waits
            self._tick(room, trace_id)
            end = time.monotonic() + min(wait, self.MAX_WAIT_SECONDS)
            while since is not None and room.version <= since:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                room.cond.wait(min(remaining, 0.5))
                self._tick(room, trace_id)
            return 200, {"state": self._view(room, seat, after)}

    # ── projections ─────────────────────────────────────────────────────────

    def _view(self, room, seat, after):
        """State for one seat owner. Never contains the opponent's hole cards before showdown, nor the deck."""
        engine = room.engine
        hand = engine.hand if engine else None
        now = self.clock()
        revealed = bool(hand and hand["phase"] == "showdown")
        seats = []
        for index, info in enumerate(room.seats):
            side = SEAT_IDS[index]
            entry = {"seat": index, "occupied": bool(info), "name": info["name"] if info else None,
                     "connected": room.connected[index], "ready": room.ready[index],
                     "stack": engine.stacks[side] if engine else (1000 if info else 0),
                     "committed": hand["total_bets"][side] if hand else 0,
                     "streetBet": hand["street_bets"][side] if hand else 0,
                     "isButton": bool(hand and hand["button"] == side),
                     "isTurn": bool(engine and room.phase == "playing" and engine.turn == side),
                     "cardCount": 2 if hand else 0, "cards": None}
            if hand and (index == seat or revealed):
                entry["cards"] = list(hand["holes"][side])
            seats.append(entry)
        me = SEAT_IDS[seat]
        my_turn = bool(engine and room.phase == "playing" and engine.turn == me)
        result = None
        if hand and hand["result"]:
            raw = hand["result"]
            result = {"winnerSeat": None if raw["winner"] == "tie" else SEAT_IDS.index(raw["winner"]),
                      "reason": raw["reason"], "pot": raw["pot"],
                      "payouts": [raw["payouts"][side] for side in SEAT_IDS],
                      "hands": [raw["hands"][side] for side in SEAT_IDS] if "hands" in raw else None}
        remaining = None
        if room.phase == "playing" and room.turn_deadline is not None:
            remaining = max(0, int((room.turn_deadline - now) * 1000))
        next_in = None
        if room.phase == "hand_over" and room.next_deadline is not None:
            next_in = max(0, int((room.next_deadline - now) * 1000))
        return {
            "code": room.code, "instance": room.instance, "version": room.version, "gameVersion": room.game_version, "phase": room.phase,
            "you": {"seat": seat, "name": room.seats[seat]["name"]},
            "seats": seats, "handNo": self._hand_no(room),
            "street": hand["phase"] if hand else None,
            "board": list(hand["board"]) if hand else [],
            "pot": sum(hand["total_bets"].values()) if hand else 0,
            "turnSeat": SEAT_IDS.index(engine.turn) if engine and room.phase == "playing" and engine.turn else None,
            "turnRemainingMs": remaining, "turnSeconds": self.TURN_SECONDS, "nextHandInMs": next_in,
            "legalActions": engine.legal_actions(me) if my_turn else [],
            "toCall": engine._to_call(me) if my_turn else 0,
            "minRaiseTo": engine._raise_bounds(me)[0] if my_turn else None,
            "maxRaiseTo": engine._raise_bounds(me)[1] if my_turn else None,
            "result": result, "recordStatus": room.record_status, "notice": room.notice,
            "recovered": room.recovered,
            "lastEventSeq": room.event_seq,
            "events": [dict(event) for event in room.events if event["seq"] > after],
        }

    def _public(self, room):
        """What anyone holding the code may see (join preview). No cards except the shared board."""
        engine = room.engine
        hand = engine.hand if engine else None
        return {
            "code": room.code, "version": room.version, "phase": room.phase, "handNo": self._hand_no(room),
            "seats": [{"seat": index, "occupied": bool(info), "name": info["name"] if info else None,
                       "connected": room.connected[index], "ready": room.ready[index],
                       "stack": engine.stacks[SEAT_IDS[index]] if engine else (1000 if info else 0)}
                      for index, info in enumerate(room.seats)],
            "board": list(hand["board"]) if hand else [],
            "pot": sum(hand["total_bets"].values()) if hand else 0,
        }

    # ── Mini Redis: public preview cache (never authoritative) ──────────────

    def _redis_url(self, code):
        return self.demo.redis_url + "/keys/" + quote("poker:room:" + code, safe="")

    def _redis_put(self, room, trace_id):
        if time.monotonic() < self.redis_skip_until:
            return False
        _, trace = self.demo._call("Mini Redis", "PUT", self._redis_url(room.code),
                                   {"value": self._public(room), "ttl": self.PUBLIC_TTL_SECONDS}, trace_id)
        if trace["outcome"] != "ok":
            # Redis trouble never blocks or changes the game; stale previews expire by TTL.
            self.redis_skip_until = time.monotonic() + self.REDIS_BACKOFF_SECONDS
            return False
        return True

    def _bump(self, room, trace_id=None):
        """Every visible change: new version, refresh the public cache, wake waiting clients."""
        room.version += 1
        self._redis_put(room, trace_id)
        room.cond.notify_all()

    def public(self, code, trace_id):
        cache = "BYPASS"
        if time.monotonic() >= self.redis_skip_until:
            payload, trace = self.demo._call("Mini Redis", "GET", self._redis_url(code), trace_id=trace_id)
            if trace["outcome"] == "hit" and isinstance(payload, dict) and isinstance(payload.get("value"), dict) \
                    and payload["value"].get("code") == code:
                return 200, {"room": payload["value"], "cache": "HIT"}
            if trace["outcome"] == "miss":
                cache = "MISS"
            else:
                self.redis_skip_until = time.monotonic() + self.REDIS_BACKOFF_SECONDS
        with self.guard:
            room = self.rooms.get(code)
        if room is None:
            return self._err(404, "room_not_found", "방을 찾을 수 없습니다")
        with room.cond:
            value = self._public(room)
            if cache == "MISS":
                self._redis_put(room, trace_id)
        return 200, {"room": value, "cache": cache}

    # ── recovery after a server restart ─────────────────────────────────────

    def _recover(self, code, trace_id):
        """Rebuild a started match from the DBMS: seats from `matches`, chips from confirmed `hand_results`.

        A hand that was in progress when the server stopped is void: its deck and bets
        lived only in memory, so play resumes from the last confirmed hand's stacks.
        A room that had not started (lobby) is not stored and cannot be recovered.
        """
        match_key = match_key_for(code)
        payload, trace = self.demo._sql("SELECT id, match_key, player_a, player_b FROM matches WHERE match_key = ?", [match_key], trace_id)
        if trace["outcome"] != "ok":
            raise _Stop(503, {"error": "room_store_unavailable", "message": "Mini DBMS에 연결할 수 없어 방을 확인하지 못했습니다"})
        rows = payload.get("result", {}).get("rows", [])
        if not rows:
            return None
        if len(rows) != 1:
            raise _Stop(503, {"error": "room_recovery_failed", "message": "매치 기록이 올바르지 않습니다"})
        match = rows[0]
        room = Room(code)
        for seat, column in enumerate(("player_a", "player_b")):
            found, trace = self.demo._sql("SELECT id, user_id, display_name FROM guest_users WHERE id = ?", [match[column]], trace_id)
            users = found.get("result", {}).get("rows", []) if trace["outcome"] == "ok" else []
            if len(users) != 1:
                raise _Stop(503, {"error": "room_recovery_failed", "message": "좌석 소유자 기록을 확인하지 못했습니다"})
            room.seats[seat] = {"userId": users[0]["user_id"], "dbId": users[0]["id"], "name": users[0]["display_name"]}
        history, _ = self.demo._load_match_results({"userId": "room:" + code}, match_key, trace_id)
        if history is None:
            raise _Stop(503, {"error": "room_recovery_failed", "message": "핸드 기록을 검증하지 못해 방을 복구하지 않았습니다"})
        engine = self.engine_factory()
        stacks = {"human": history["stacks"][0], "bot": history["stacks"][1]}
        if history["hand_no"]:
            engine.restore_for_next_hand(stacks, history["hand_no"])
        room.engine = engine
        room.match_key = match_key
        room.db_id = match["id"]
        room.last_result_id = history["last_id"]
        room.record_status = "confirmed" if history["hand_no"] else "not_saved"
        room.phase = "match_over" if min(stacks.values()) == 0 else "hand_over"
        room.recovered = True
        room.next_deadline = self.clock() + self.NEXT_HAND_SECONDS
        room.notice = "서버가 다시 시작되어, 진행 중이던 핸드는 무효 처리하고 마지막으로 저장된 칩에서 이어갑니다."
        with room.cond:
            self._event(room, "recovered")
            room.version += 1
        return room


class _Stop(Exception):
    def __init__(self, status, body):
        super().__init__(body.get("error"))
        self.status = status
        self.body = body
