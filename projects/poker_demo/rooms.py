"""Room-based multiplayer (2-4 people) for JUNGLE POKER LAB.

Flow: player action -> server validates under the room lock -> durable append (DBMS) and
public cache write (Redis) -> every seated client receives the same ordered events and version
through GET .../state (long polling).

The server owns deck, turn, legal actions, chips, pots and results (table.TableHand).
A viewer receives only their own hole cards; at a showdown the cards of every player still in
the hand are revealed, folded hands never.

Room rules (house rules marked; see MULTIPLAYER.md):
- capacity 2-4 seats (default 4); the creator is the host; a lobby host who leaves passes the
  host role to the lowest occupied seat.
- lobby: the match starts automatically when every seated player (at least 2) is ready, or when
  the host starts it with at least 2 ready players (the others sit out until they are ready).
- the participants of a running hand are fixed. A player who takes a free seat after the match
  started buys in for 1000 chips (recorded in the DBMS) and plays from the next hand once ready.
- a participant cannot leave during their hand; between hands (or while sitting out) leaving
  cashes out the remaining chips (recorded) and the player cannot sit in the same match again.
- a player disconnected when a hand is dealt sits that hand out; seat and chips stay.
- a seat with 0 chips is busted (spectating). The match ends when fewer than 2 seated players
  have chips.
"""
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import quote

from engine import RuleError, new_deck
from table import MAX_SEATS, MIN_SEATS, TableHand, build_pots, next_button

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L look-alikes
CODE_LENGTH = 6
STREET_SIZES = (("flop", 3), ("turn", 4), ("river", 5))
RULES_VERSION = "poker-lab-holdem-multi-v1"
ACTIONS = ("fold", "check", "call", "bet", "raise", "all_in")
BUY_IN = 1000
SMALL_BLIND, BIG_BLIND = 10, 20
HAND_COLUMNS = ("id", "operation_key", "payload_hash", "schema_version", "match_key", "hand_no", "prev_result_id",
                "button", "participants", "pots", "board", "public_actions", "reason", "rules_version")
SEAT_COLUMNS = ("id", "operation_key", "payload_hash", "match_key", "kind", "user_db", "seat", "amount", "after_hand")


def match_key_for(code):
    """One room is one match; the durable match key is derived from the room code."""
    return hashlib.sha256(("poker-room-v1:" + code).encode("ascii")).hexdigest()[:32]


def hash_fields(fields):
    raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LedgerError(ValueError):
    """Stored room records are inconsistent."""


def replay_ledger(match_key, seat_rows, hand_rows):
    """Rebuild seats and chips from stored records and check them; raises LedgerError on any mismatch.

    Returns {"seats": {seat: user_db}, "stacks": {user_db: chips}, "hands": [rows by hand_no],
    "last_id", "hand_no", "button", "left": {user_db}, "buy_ins", "cash_outs"}.
    """
    hands = sorted(hand_rows, key=lambda r: r["id"])
    events = sorted(seat_rows, key=lambda r: r["id"])
    seen = set()
    for row in hands + events:
        if row["match_key"] != match_key:
            raise LedgerError("record of another match")
        if row["operation_key"] in seen:
            raise LedgerError("duplicate operation key")
        seen.add(row["operation_key"])
    for row in hands:
        fields = {k: row[k] for k in HAND_COLUMNS if k not in ("id", "payload_hash")}
        if row["payload_hash"] != hash_fields(fields):
            raise LedgerError("hand result hash mismatch")
    for row in events:
        fields = {k: row[k] for k in SEAT_COLUMNS if k not in ("id", "payload_hash")}
        if row["payload_hash"] != hash_fields(fields) or row["kind"] not in ("buyin", "leave"):
            raise LedgerError("seat event hash mismatch")
    seats, stacks, left = {}, {}, set()
    buy_ins = cash_outs = 0
    previous_id, button = 0, None

    def apply_events(after):
        nonlocal buy_ins, cash_outs
        for row in [e for e in events if e["after_hand"] == after]:
            user = row["user_db"]
            if row["kind"] == "buyin":
                if user in stacks or user in left or row["seat"] in seats or row["amount"] != BUY_IN:
                    raise LedgerError("invalid buy-in")
                seats[row["seat"]] = user
                stacks[user] = row["amount"]
                buy_ins += row["amount"]
            else:
                if seats.get(row["seat"]) != user or stacks[user] != row["amount"]:
                    raise LedgerError("cash-out does not match the player's chips")
                del seats[row["seat"]]
                cash_outs += stacks.pop(user)
                left.add(user)

    apply_events(0)
    for number, row in enumerate(hands, 1):
        expected_key = f"{match_key}:hand:{number}:result"
        if row["hand_no"] != number or row["operation_key"] != expected_key or row["prev_result_id"] != previous_id:
            raise LedgerError("hand result chain is broken")
        participants = json.loads(row["participants"])
        pots = json.loads(row["pots"])
        board = json.loads(row["board"])
        actions = json.loads(row["public_actions"])
        if not MIN_SEATS <= len(participants) <= MAX_SEATS or len({p["seat"] for p in participants}) != len(participants):
            raise LedgerError("invalid participants")
        for p in participants:
            if seats.get(p["seat"]) != p["user"] or stacks.get(p["user"]) != p["start"] or p["end"] < 0:
                raise LedgerError("hand start does not match the chips on record")
        if sum(p["start"] for p in participants) != sum(p["end"] for p in participants):
            raise LedgerError("hand does not conserve chips")
        if sum(pot["amount"] for pot in pots) != sum(sum(a for _, a in pot["shares"]) for pot in pots):
            raise LedgerError("pot shares do not add up")
        if row["reason"] not in ("fold", "showdown") or not isinstance(board, list) or len(board) not in (0, 3, 4, 5) \
                or (row["reason"] == "showdown" and len(board) != 5):
            raise LedgerError("invalid board or reason")
        for action in actions.get("actions", []):
            if set(action) - {"seat", "action", "street", "to", "paid", "allIn", "fullRaise", "auto"}:
                raise LedgerError("private data in public actions")
        if row["button"] not in {p["seat"] for p in participants}:
            raise LedgerError("button is not a participant")
        for p in participants:
            stacks[p["user"]] = p["end"]
        previous_id = row["id"]
        button = row["button"]
        apply_events(number)
    if any(e["after_hand"] > len(hands) for e in events):
        raise LedgerError("seat event after an unknown hand")
    if sum(stacks.values()) != buy_ins - cash_outs:
        raise LedgerError("chips on the table differ from buy-ins minus cash-outs")
    return {"seats": seats, "stacks": stacks, "hands": hands, "last_id": previous_id, "hand_no": len(hands),
            "button": button, "left": left, "buy_ins": buy_ins, "cash_outs": cash_outs}


class Room:
    """In-memory authoritative state of one room. Mutated only while holding `cond`."""

    def __init__(self, code, capacity):
        self.code = code
        self.capacity = capacity
        self.cond = threading.Condition(threading.RLock())
        self.seats = [None] * capacity  # {"userId", "dbId", "name"}
        self.ready = [False] * capacity
        self.sitting_in = [False] * capacity  # takes part in the next hand (after the match started)
        self.stacks = [None] * capacity  # chips in front of each seated player between hands
        self.last_seen = [None] * capacity
        self.connected = [False] * capacity
        self.host = None
        self.left_users = set()  # userIds that cashed out of this match
        self.phase = "lobby"  # lobby | playing | hand_over | match_over
        # Counters start from the wall clock (ms): a room rebuilt after a restart continues with
        # larger numbers than any client saw, so old cursors and old actions never match.
        base = int(time.time() * 1000)
        self.instance = secrets.token_hex(4)
        self.version = base
        self.game_version = base
        self.events = []
        self.event_seq = base
        self.notice = ""
        self.turn_deadline = None
        self.next_deadline = None
        self.retry_at = 0.0
        self.action_replays = {}
        self.recovered = False
        self.hand = None
        self.hand_no = 0
        self.button = None
        self.match_key = None
        self.last_result_id = 0
        self.pending_result = None
        self.storage_blocked = False
        self.record_status = "not_started"

    def seat_of(self, user):
        for index, seat in enumerate(self.seats):
            if seat and seat["userId"] == user["userId"]:
                return index
        return None

    def occupied(self):
        return [i for i, s in enumerate(self.seats) if s]

    def in_hand(self, seat):
        return self.hand is not None and seat in self.hand.seats


class RoomService:
    TURN_SECONDS = 30.0  # a player who does not act in time is checked, or folded when facing a bet
    NEXT_HAND_SECONDS = 12.0  # next hand starts when all are ready, or automatically after this wait
    PRESENCE_SECONDS = 8.0  # a seat whose last state request started longer ago than this is disconnected
    STORAGE_RETRY_SECONDS = 2.0
    MAX_WAIT_SECONDS = 5.0  # must stay below PRESENCE_SECONDS
    PUBLIC_TTL_SECONDS = 30
    REDIS_BACKOFF_SECONDS = 5.0
    MAX_ROOMS = 500
    MAX_EVENTS = 300

    def __init__(self, demo, clock=time.monotonic, deck_factory=new_deck):
        self.demo = demo
        self.clock = clock
        self.deck_factory = deck_factory
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
            routes = {("GET", "state"): lambda: self.state(user, code, query, trace_id),
                      ("POST", "join"): lambda: self.join(user, code, trace_id),
                      ("POST", "leave"): lambda: self.leave(user, code, trace_id),
                      ("POST", "ready"): lambda: self.set_ready(user, code, payload, trace_id),
                      ("POST", "start"): lambda: self.host_start(user, code, payload, trace_id),
                      ("POST", "action"): lambda: self.action(user, code, payload, trace_id)}
            handler = routes.get((method, verb))
            return handler() if handler else self._err(404, "not_found", "unknown room route")
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
        if not isinstance(payload, dict) or "request_id" not in payload or set(payload) - {"request_id", "max_seats"}:
            return self._err(400, "invalid_create_request", "create accepts request_id and optional max_seats")
        capacity = payload.get("max_seats", MAX_SEATS)
        if not isinstance(capacity, int) or isinstance(capacity, bool) or not MIN_SEATS <= capacity <= MAX_SEATS:
            return self._err(400, "invalid_create_request", "max_seats must be an integer from 2 to 4")
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
                room = Room(code, capacity)
                with room.cond:
                    self._sit(room, 0, user)
                    room.host = 0
                    room.notice = "다른 사람에게 방 코드를 알려 주세요."
                    self._bump(room, trace_id)
                self.rooms[code] = room
                self.create_replays[replay_key] = code
                if len(self.create_replays) > 4 * self.MAX_ROOMS:
                    self.create_replays.clear()
                    self.create_replays[replay_key] = code
        with room.cond:
            seat = room.seat_of(user)
            if seat is None:
                return self._err(409, "room_left", "이미 나간 방입니다. 새 방을 만드세요")
            return 200, {"state": self._view(room, seat, 0)}

    def _new_code(self, trace_id):
        for _ in range(20):
            code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
            if code in self.rooms:
                continue
            payload, trace = self.demo._sql("SELECT id FROM room_matches WHERE match_key = ?", [match_key_for(code)], trace_id)
            if trace["outcome"] != "ok":
                raise _Stop(503, {"error": "room_store_unavailable", "message": "Mini DBMS에 연결할 수 없어 방을 만들 수 없습니다"})
            if not payload.get("result", {}).get("rows"):
                return code
        raise _Stop(503, {"error": "room_code_exhausted", "message": "방 코드를 만들지 못했습니다"})

    def _sit(self, room, seat, user, chips=None):
        room.seats[seat] = {"userId": user["userId"], "dbId": user["dbId"], "name": user["displayName"]}
        room.ready[seat] = False
        room.sitting_in[seat] = False
        room.stacks[seat] = chips
        room.last_seen[seat] = self.clock()
        room.connected[seat] = True

    def _free(self, room, seat):
        room.seats[seat] = None
        room.ready[seat] = False
        room.sitting_in[seat] = False
        room.stacks[seat] = None
        room.connected[seat] = False
        room.last_seen[seat] = None
        if room.host == seat:
            occupied = room.occupied()
            room.host = occupied[0] if occupied else None

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
            if seat is not None:
                self._seen(room, seat)
                return 200, {"state": self._view(room, seat, 0)}
            if room.phase == "match_over":
                return self._err(409, "match_over", "이미 끝난 매치입니다")
            if user["userId"] in room.left_users:
                return self._err(409, "left_match", "이 매치에서 나간 뒤에는 다시 앉을 수 없습니다")
            free = [i for i, value in enumerate(room.seats) if value is None]
            if not free:
                return self._err(409, "room_full", "방이 가득 찼습니다")
            if room.pending_result:
                # a buy-in must be ordered after the hand it follows, so wait until that hand is on record
                return self._err(409, "result_storage_pending", "직전 핸드 결과를 저장하는 중입니다. 잠시 뒤 다시 시도하세요")
            seat = free[0]
            if room.phase == "lobby":
                self._sit(room, seat, user)
                room.notice = "준비한 사람이 2명 이상이면 방장이 시작할 수 있고, 모두 준비하면 바로 시작합니다."
            else:
                # the match is running: the buy-in must be on record before the seat is taken
                if not self._record_seat_event(room, "buyin", user["dbId"], seat, BUY_IN, self._completed_hands(room), trace_id):
                    return self._err(503, "seat_storage_unknown", "자리 기록을 저장하지 못했습니다. 다시 시도하세요")
                self._sit(room, seat, user, BUY_IN)
                room.notice = f"{user['displayName']} 님이 앉았습니다. 준비하면 다음 핸드부터 참여합니다."
            self._bump(room, trace_id)
            return 200, {"state": self._view(room, seat, 0)}

    def leave(self, user, code, trace_id):
        room = self._room(code, trace_id)
        with self.guard, room.cond:
            seat = room.seat_of(user)
            if seat is None:
                return 200, {"left": True}
            if room.phase == "lobby":
                self._free(room, seat)
                room.notice = "한 명이 방을 나갔습니다."
                self._bump(room, trace_id)
                if not room.occupied():
                    self.rooms.pop(code, None)
                return 200, {"left": True}
            if room.phase == "playing" and room.in_hand(seat) and not room.hand.hand_over:
                return self._err(409, "match_in_progress", "참가 중인 핸드가 끝난 뒤에 나갈 수 있습니다. 창을 닫으면 차례마다 제한 시간 뒤 자동 처리됩니다",
                                 self._view(room, seat, 0))
            if room.pending_result:
                return self._err(409, "result_storage_pending", "결과 저장을 확인하는 중입니다. 잠시 뒤 다시 시도하세요", self._view(room, seat, 0))
            chips = room.stacks[seat] or 0
            if room.match_key is not None:
                if not self._record_seat_event(room, "leave", user["dbId"], seat, chips, self._completed_hands(room), trace_id):
                    return self._err(503, "seat_storage_unknown", "나가기 기록을 저장하지 못했습니다. 다시 시도하세요", self._view(room, seat, 0))
            room.left_users.add(user["userId"])
            self._free(room, seat)
            room.notice = f"{user['displayName']} 님이 칩 {chips:,}개를 가지고 나갔습니다."
            if room.phase in ("hand_over", "match_over"):
                self._check_match_over(room)
            self._bump(room, trace_id)
            return 200, {"left": True, "cashOut": chips}

    def set_ready(self, user, code, payload, trace_id):
        if (not isinstance(payload, dict) or set(payload) != {"ready", "hand_no"} or not isinstance(payload["ready"], bool)
                or not isinstance(payload["hand_no"], int) or isinstance(payload["hand_no"], bool)):
            return self._err(400, "invalid_ready_request", "ready(boolean) and hand_no(integer) are required")
        room = self._room(code, trace_id)
        with room.cond:
            seat = self._seat_or_stop(room, user)
            self._seen(room, seat)
            self._tick(room, trace_id)
            if room.phase == "match_over":
                return self._err(409, "match_over", "매치가 끝났습니다. 새 방을 만드세요", self._view(room, seat, 0))
            if room.phase == "playing" and room.in_hand(seat):
                return self._err(409, "hand_active", "핸드가 진행 중입니다", self._view(room, seat, 0))
            # hand_no pins the request to the hand it was made for
            if payload["hand_no"] != room.hand_no:
                return self._err(409, "stale_state", "이미 다음 상태로 넘어갔습니다", self._view(room, seat, 0))
            if room.phase != "lobby" and (room.stacks[seat] or 0) <= 0:
                return self._err(409, "busted", "칩이 없어 더 참여할 수 없습니다", self._view(room, seat, 0))
            changed = room.ready[seat] != payload["ready"]
            room.ready[seat] = payload["ready"]
            if room.phase != "lobby":
                changed = changed or room.sitting_in[seat] != payload["ready"]
                room.sitting_in[seat] = payload["ready"]
            if changed:
                self._bump(room, trace_id)
            error = self._advance(room, trace_id)
            if error:
                return self._err(error[0], error[1], error[2], self._view(room, seat, 0))
            return 200, {"state": self._view(room, seat, 0)}

    def host_start(self, user, code, payload, trace_id):
        if not isinstance(payload, dict) or set(payload) != {"hand_no"} or payload["hand_no"] != 0 or isinstance(payload["hand_no"], bool):
            return self._err(400, "invalid_start_request", "start accepts hand_no 0")
        room = self._room(code, trace_id)
        with room.cond:
            seat = self._seat_or_stop(room, user)
            self._seen(room, seat)
            if room.phase != "lobby":
                return self._err(409, "already_started", "이미 시작한 매치입니다", self._view(room, seat, 0))
            if seat != room.host:
                return self._err(403, "not_host", "방장만 시작할 수 있습니다", self._view(room, seat, 0))
            if sum(room.ready[i] for i in room.occupied()) < MIN_SEATS:
                return self._err(409, "not_enough_ready", "준비한 사람이 2명 이상이어야 합니다", self._view(room, seat, 0))
            error = self._start_match(room, trace_id)
            if error:
                return self._err(error[0], error[1], error[2], self._view(room, seat, 0))
            return 200, {"state": self._view(room, seat, 0)}

    def _seat_or_stop(self, room, user):
        seat = room.seat_of(user)
        if seat is None:
            # Knowing the room code is not enough: only the seat owner's token may act.
            raise _Stop(403, {"error": "not_seated", "message": "이 방의 좌석 소유자가 아닙니다"})
        return seat

    # ── transitions (always under room.cond) ─────────────────────────────────

    @staticmethod
    def _completed_hands(room):
        return room.hand_no - (1 if room.phase == "playing" else 0)

    def _candidates(self, room):
        return [i for i in room.occupied() if room.sitting_in[i] and (room.stacks[i] or 0) > 0 and room.connected[i]]

    def _advance(self, room, trace_id):
        """Start the match or the next hand when its conditions hold. Returns an error tuple or None."""
        if room.phase == "lobby":
            seated = room.occupied()
            if len(seated) >= MIN_SEATS and all(room.ready[i] for i in seated):
                return self._start_match(room, trace_id)
            return None
        if room.phase != "hand_over" or room.record_status not in ("confirmed", "not_saved") or room.pending_result:
            return None
        candidates = self._candidates(room)
        if len(candidates) < MIN_SEATS:
            return None
        timed = room.next_deadline is not None and self.clock() >= room.next_deadline
        if all(room.ready[i] for i in candidates) or timed:
            self._start_hand(room, candidates, trace_id)
        return None

    def _start_match(self, room, trace_id):
        match_key = match_key_for(room.code)
        players = [i for i in room.occupied() if room.ready[i]]
        sql = "INSERT INTO room_matches (match_key, room_code, capacity, host_user, blinds, rules_version) VALUES (?, ?, ?, ?, ?, ?)"
        values = [match_key, room.code, room.capacity, room.seats[room.host]["dbId"], f"{SMALL_BLIND}/{BIG_BLIND}", RULES_VERSION]
        _, trace = self.demo._insert_once(sql, values, "match_key", trace_id)
        ok = trace["outcome"] == "ok"
        room.match_key = match_key  # needed by the seat events below
        for seat in room.occupied():
            ok = ok and self._record_seat_event(room, "buyin", room.seats[seat]["dbId"], seat, BUY_IN, 0, trace_id)
        if not ok:
            # Seats are durable only once these rows exist, so the match does not start without them.
            room.match_key = None
            room.ready = [False] * room.capacity
            room.notice = "매치 기록을 저장하지 못해 시작하지 못했습니다. 다시 준비를 눌러 주세요."
            self._bump(room, trace_id)
            return (503, "match_storage_unknown", "매치 저장을 확인하지 못했습니다. 다시 준비를 눌러 주세요")
        for seat in room.occupied():
            room.stacks[seat] = BUY_IN
            room.sitting_in[seat] = seat in players
        room.record_status = "not_saved"
        self._start_hand(room, players, trace_id)  # ready players have just made a request, so they are connected
        return None

    def _start_hand(self, room, participants, trace_id):
        participants = sorted(participants)
        button = next_button(room.button, participants)
        hand = TableHand({s: room.stacks[s] for s in participants}, button, SMALL_BLIND, BIG_BLIND,
                         deck=self.deck_factory(), max_seats=room.capacity)
        room.hand = hand
        room.button = button
        room.hand_no += 1
        room.phase = "playing"
        room.ready = [False] * room.capacity
        room.record_status = "not_saved"
        room.next_deadline = None
        room.recovered = False
        room.action_replays = {}
        room.game_version += 1
        names = ", ".join(room.seats[s]["name"] for s in participants)
        room.notice = f"{room.hand_no}번째 핸드 · 블라인드 {SMALL_BLIND}/{BIG_BLIND} · 참가 {names}"
        running = self._table(room)
        for seat in participants:
            running["stacks"][seat] = hand.start_stacks[seat] - hand.blinds_posted.get(seat, 0)
            running["committed"][seat] = hand.blinds_posted.get(seat, 0)
        running["folded"] = set()
        self._event(room, "hand_start", running, button=button, sb=hand.sb, bb=hand.bb, participants=participants,
                    smallBlind=SMALL_BLIND, bigBlind=BIG_BLIND)
        self._after_step(room, [], 0, 0, running, trace_id)

    def _table(self, room):
        """Chips per seat right now: stacks in front and chips put in this hand."""
        stacks = [None if not room.seats[i] else room.stacks[i] for i in range(room.capacity)]
        committed = [0] * room.capacity
        hand = room.hand
        if hand is not None and not hand.hand_over:
            for seat in hand.seats:
                stacks[seat] = hand.stacks[seat]
                committed[seat] = hand.total_bets[seat]
        folded = set(hand.folded) if hand is not None else set()
        return {"stacks": stacks, "committed": committed, "folded": folded}

    def _event(self, room, kind, running=None, **fields):
        """Append one public event; `running` gives the chips right after it (no private cards ever)."""
        running = running or self._table(room)
        hand = room.hand
        live = [s for s in (hand.seats if hand else []) if s not in running["folded"]]
        contributions = {s: running["committed"][s] for s in (hand.seats if hand else [])}
        room.event_seq += 1
        event = {
            "seq": room.event_seq, "type": kind, "gameVersion": room.game_version, "handNo": room.hand_no,
            "board": list(hand.board) if hand else [],
            "pot": sum(running["committed"]), "stacks": list(running["stacks"]), "committed": list(running["committed"]),
            "pots": build_pots(contributions, live, {s for s in live if running["stacks"][s] == 0}) if contributions else [],
        }
        event.update(fields)
        room.events.append(event)
        del room.events[:-self.MAX_EVENTS]
        return event

    def _after_step(self, room, board_before, actions_before, returns_before, running, trace_id, auto=False):
        """Publish what the hand just did as ordered events (actions, returned chips, streets, payout)."""
        hand = room.hand
        board = list(hand.board)
        for action in hand.actions[actions_before:]:
            seat = action["seat"]
            paid = action.get("paid", 0)
            running["stacks"][seat] -= paid
            running["committed"][seat] += paid
            if action["action"] == "fold":
                running["folded"].add(seat)
            fields = {"seat": seat, "action": action["action"], "paid": paid, "allIn": bool(action.get("allIn")), "auto": auto}
            if "to" in action:
                fields["to"] = action["to"]
            event = self._event(room, "action", running, **fields)
            event["board"] = list(board_before)
        for item in hand.returns[returns_before:]:
            running["stacks"][item["seat"]] += item["amount"]
            running["committed"][item["seat"]] -= item["amount"]
            event = self._event(room, "returned", running, seat=item["seat"], amount=item["amount"])
            event["board"] = list(board_before)
        for street, size in STREET_SIZES:
            if len(board_before) < size <= len(board):
                event = self._event(room, "street", running, street=street)
                event["board"] = board[:size]
        if hand.hand_over:
            for seat in hand.seats:
                room.stacks[seat] = hand.stacks[seat]
            result = self._result(room)
            self._event(room, "hand_end", reason=result["reason"], potWon=result["pot"], pots=result["pots"],
                        winnerSeat=result["winnerSeat"], winnerSeats=result["winnerSeats"], payouts=result["payouts"])
            room.turn_deadline = None
            room.phase = "hand_over"
            room.notice = self._result_text(room)
            self._persist(room, trace_id)
            self._check_match_over(room)
        else:
            room.turn_deadline = self.clock() + self.TURN_SECONDS
        self._bump(room, trace_id)

    def _check_match_over(self, room):
        with_chips = [i for i in room.occupied() if (room.stacks[i] or 0) > 0]
        if len(with_chips) < MIN_SEATS and room.phase == "hand_over":
            room.phase = "match_over"
            room.notice += " · 칩이 남은 사람이 1명 이하라 매치가 끝났습니다."

    def _result(self, room):
        hand = room.hand
        raw = hand.result
        cap = room.capacity
        payouts = [0] * cap
        for seat, amount in raw["payouts"].items():
            payouts[seat] = amount
        hands = None
        if raw["hands"]:
            hands = [None] * cap
            for seat, label in raw["hands"].items():
                hands[seat] = label
        winners = sorted(s for s, a in raw["payouts"].items() if a > 0)
        pots = [{"amount": p["amount"], "eligible": p["eligible"], "winners": p["winners"],
                 "shares": [[s, a] for s, a in sorted(p["shares"].items())]} for p in raw["pots"]]
        return {"reason": raw["reason"], "pot": sum(p["amount"] for p in raw["pots"]), "pots": pots, "payouts": payouts,
                "winnerSeats": winners, "winnerSeat": winners[0] if len(winners) == 1 else None, "hands": hands}

    def _result_text(self, room):
        result = self._result(room)
        names = [room.seats[s]["name"] for s in result["winnerSeats"]]
        if result["reason"] == "fold":
            return f"{names[0]} 승리 (다른 사람 모두 폴드) · {result['pot']}칩"
        parts = []
        for index, pot in enumerate(result["pots"]):
            label = "메인팟" if index == 0 else f"사이드팟 {index}"
            who = ", ".join(room.seats[s]["name"] for s in pot["winners"])
            parts.append(f"{label} {pot['amount']} → {who}")
        return "쇼다운 · " + " / ".join(parts)

    def _record_seat_event(self, room, kind, user_db, seat, amount, after_hand, trace_id):
        fields = {"operation_key": f"{room.match_key}:seat:{user_db}:{kind}", "match_key": room.match_key, "kind": kind,
                  "user_db": user_db, "seat": seat, "amount": amount, "after_hand": after_hand}
        fields["payload_hash"] = hash_fields(fields)
        columns = [c for c in SEAT_COLUMNS if c != "id"]
        sql = f"INSERT INTO room_seat_events ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
        _, trace = self.demo._insert_once(sql, [fields[c] for c in columns], "operation_key", trace_id)
        return trace["outcome"] == "ok"

    def _make_result(self, room):
        hand = room.hand
        participants = [{"seat": s, "user": room.seats[s]["dbId"], "start": hand.start_stacks[s], "end": hand.stacks[s]}
                        for s in hand.seats]
        pots = self._result(room)["pots"]
        fields = {
            "operation_key": f"{room.match_key}:hand:{room.hand_no}:result", "schema_version": 2,
            "match_key": room.match_key, "hand_no": room.hand_no, "prev_result_id": room.last_result_id,
            "button": hand.button, "participants": compact(participants),
            "pots": compact([{"amount": p["amount"], "eligible": p["eligible"], "winners": p["winners"], "shares": p["shares"]} for p in pots]),
            "board": compact(hand.board),
            "public_actions": compact({"sb": hand.sb, "bb": hand.bb, "actions": hand.actions, "returns": hand.returns}),
            "reason": hand.result["reason"], "rules_version": RULES_VERSION,
        }
        fields["payload_hash"] = hash_fields(fields)
        columns = [c for c in HAND_COLUMNS if c != "id"]
        sql = f"INSERT INTO room_hand_results ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
        return {"sql": sql, "params": [fields[c] for c in columns]}

    def _persist(self, room, trace_id):
        """Append the completed hand once. Until it is confirmed, no next hand starts."""
        if room.storage_blocked:
            return False
        if room.pending_result is None:
            room.pending_result = self._make_result(room)
        room.record_status = "pending"
        saved, trace = self.demo._insert_once(room.pending_result["sql"], room.pending_result["params"], "operation_key", trace_id)
        now = self.clock()
        if trace["outcome"] == "ok":
            room.last_result_id = saved["result"]["insertedId"]
            room.pending_result = None
            room.record_status = "confirmed"
            room.next_deadline = now + self.NEXT_HAND_SECONDS
            return True
        if trace["outcome"] == "http_error" and trace.get("status") == 409:
            room.storage_blocked = True
            room.record_status = "blocked"
            return False
        room.record_status = "unknown"
        room.retry_at = now + self.STORAGE_RETRY_SECONDS
        room.notice += " · 결과 저장 확인 중(확인될 때까지 다음 핸드가 시작되지 않습니다)"
        return False

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
                return 200, {"state": self._view(room, seat, 0), "replayed": True}
            if room.phase != "playing":
                return self._err(409, "hand_not_active", "진행 중인 핸드가 없습니다", self._view(room, seat, 0))
            if payload["expected_version"] != room.game_version:
                return self._err(409, "stale_state", "상태가 이미 바뀌었습니다. 화면을 갱신했습니다", self._view(room, seat, 0))
            hand = room.hand
            if hand.turn != seat:
                return self._err(409, "not_your_turn", "다른 사람의 차례입니다", self._view(room, seat, 0))
            before = (list(hand.board), len(hand.actions), len(hand.returns))
            running = self._table(room)
            try:
                hand.act(seat, payload["action"], target)
            except RuleError as exc:
                return self._err(400, "illegal_action", str(exc), self._view(room, seat, 0))
            room.action_replays[replay_key] = digest
            room.game_version += 1
            self._after_step(room, *before, running, trace_id)
            return 200, {"state": self._view(room, seat, 0)}

    # ── time: presence, turn timeout, storage retry, next hand ──────────────

    def _seen(self, room, seat):
        room.last_seen[seat] = self.clock()

    def _tick(self, room, trace_id=None):
        now = self.clock()
        connected = [bool(room.seats[i]) and room.last_seen[i] is not None and now - room.last_seen[i] < self.PRESENCE_SECONDS
                     for i in range(room.capacity)]
        if connected != room.connected:
            room.connected = connected
            self._bump(room, trace_id)
        if room.phase == "playing" and room.turn_deadline is not None and now >= room.turn_deadline:
            self._timeout_turn(room, trace_id)
        if room.phase in ("hand_over", "match_over") and room.pending_result and not room.storage_blocked and now >= room.retry_at:
            room.notice = self._result_text(room)
            self._persist(room, trace_id)
            if room.phase == "match_over":
                room.notice += " · 칩이 남은 사람이 1명 이하라 매치가 끝났습니다."
            self._bump(room, trace_id)
        self._advance(room, trace_id)

    def _timeout_turn(self, room, trace_id):
        """Timeout rule, applied only by the server clock: check when free, otherwise fold."""
        hand = room.hand
        seat = hand.turn
        action = "check" if "check" in hand.legal_actions(seat) else "fold"
        before = (list(hand.board), len(hand.actions), len(hand.returns))
        running = self._table(room)
        hand.act(seat, action)
        room.game_version += 1
        self._after_step(room, *before, running, trace_id, auto=True)

    def tick(self, code):
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
        if not (0 <= wait <= 3600) or after < 0:
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
        """State for one seat owner: own hole cards only; others' only at a showdown they reached; never the deck."""
        hand = room.hand
        now = self.clock()
        playing = room.phase == "playing" and hand is not None and not hand.hand_over
        showdown = hand is not None and hand.street == "showdown"
        table = self._table(room)
        seats = []
        for index in range(room.capacity):
            info = room.seats[index]
            in_hand = room.in_hand(index)
            folded = in_hand and index in hand.folded
            stack = table["stacks"][index]
            entry = {
                "seat": index, "occupied": bool(info), "name": info["name"] if info else None,
                "isHost": room.host == index, "connected": room.connected[index], "ready": room.ready[index],
                "sittingIn": room.sitting_in[index], "stack": stack if stack is not None else 0,
                "committed": table["committed"][index],
                "streetBet": hand.street_bets[index] if playing and in_hand else 0,
                "isButton": bool(hand and hand.button == index), "isSmallBlind": bool(hand and hand.sb == index),
                "isBigBlind": bool(hand and hand.bb == index),
                "isTurn": bool(playing and hand.turn == index), "inHand": in_hand, "folded": folded,
                "allIn": bool(playing and in_hand and not folded and hand.stacks[index] == 0),
                "busted": bool(info and room.phase != "lobby" and (room.stacks[index] or 0) == 0 and not (playing and in_hand)),
                "cardCount": 2 if in_hand else 0, "cards": None,
            }
            if in_hand and (index == seat or (showdown and not folded)):
                entry["cards"] = list(hand.holes[index])
            seats.append(entry)
        my_turn = bool(playing and hand.turn == seat)
        remaining = max(0, int((room.turn_deadline - now) * 1000)) if playing and room.turn_deadline is not None else None
        next_in = max(0, int((room.next_deadline - now) * 1000)) if room.phase == "hand_over" and room.next_deadline is not None else None
        return {
            "code": room.code, "instance": room.instance, "capacity": room.capacity, "hostSeat": room.host,
            "version": room.version, "gameVersion": room.game_version, "phase": room.phase,
            "you": {"seat": seat, "name": room.seats[seat]["name"], "isHost": room.host == seat},
            "seats": seats, "handNo": room.hand_no,
            "street": hand.street if hand else None, "board": list(hand.board) if hand else [],
            "pot": sum(table["committed"]), "pots": hand.live_pots() if playing else [],
            "turnSeat": hand.turn if playing else None,
            "turnRemainingMs": remaining, "turnSeconds": self.TURN_SECONDS, "nextHandInMs": next_in,
            "legalActions": hand.legal_actions(seat) if my_turn else [],
            "toCall": hand.to_call(seat) if my_turn else 0,
            "minRaiseTo": hand.raise_bounds(seat)[0] if my_turn else None,
            "maxRaiseTo": hand.raise_bounds(seat)[1] if my_turn else None,
            "result": self._result(room) if hand is not None and hand.hand_over else None,
            "recordStatus": room.record_status, "notice": room.notice, "recovered": room.recovered,
            "readyCount": sum(room.ready[i] for i in room.occupied()),
            "canStart": room.phase == "lobby" and room.host == seat and sum(room.ready[i] for i in room.occupied()) >= MIN_SEATS,
            "lastEventSeq": room.event_seq,
            "events": [dict(event) for event in room.events if event["seq"] > after],
        }

    def _public(self, room):
        """What anyone holding the code may see (join preview). No cards except the shared board."""
        table = self._table(room)
        hand = room.hand
        return {
            "code": room.code, "capacity": room.capacity, "version": room.version, "phase": room.phase, "handNo": room.hand_no,
            "seats": [{"seat": i, "occupied": bool(info), "name": info["name"] if info else None, "isHost": room.host == i,
                       "connected": room.connected[i], "ready": room.ready[i],
                       "stack": table["stacks"][i] if table["stacks"][i] is not None else (BUY_IN if info else 0)}
                      for i, info in enumerate(room.seats)],
            "board": list(hand.board) if hand else [], "pot": sum(table["committed"]),
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
            self.redis_skip_until = time.monotonic() + self.REDIS_BACKOFF_SECONDS
            return False
        return True

    def _bump(self, room, trace_id=None):
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

    # ── stored records ────────────────────────────────────────────────────────

    def load_ledger(self, match_key, trace_id):
        """Seat events and hand results of one match, checked by replay_ledger. Returns (ledger|None, error|None)."""
        seat_rows, t1 = self.demo._sql("SELECT " + ", ".join(SEAT_COLUMNS) + " FROM room_seat_events WHERE match_key = ?", [match_key], trace_id)
        hand_rows, t2 = self.demo._sql("SELECT " + ", ".join(HAND_COLUMNS) + " FROM room_hand_results WHERE match_key = ?", [match_key], trace_id)
        if t1["outcome"] != "ok" or t2["outcome"] != "ok":
            return None, "unavailable"
        try:
            return replay_ledger(match_key, seat_rows["result"]["rows"], hand_rows["result"]["rows"]), None
        except (LedgerError, KeyError, TypeError, ValueError) as exc:
            return None, f"corrupt: {exc}"

    # ── recovery after a server restart ─────────────────────────────────────

    def _recover(self, code, trace_id):
        """Rebuild a started match: seats from buy-ins/cash-outs, chips from confirmed hand results.

        A hand in progress when the server stopped is void (its deck and bets lived only in memory);
        play resumes from the last confirmed hand. A lobby that never started is not stored.
        """
        match_key = match_key_for(code)
        payload, trace = self.demo._sql("SELECT id, match_key, room_code, capacity, host_user FROM room_matches WHERE match_key = ?", [match_key], trace_id)
        if trace["outcome"] != "ok":
            raise _Stop(503, {"error": "room_store_unavailable", "message": "Mini DBMS에 연결할 수 없어 방을 확인하지 못했습니다"})
        rows = payload.get("result", {}).get("rows", [])
        if not rows:
            return None
        if len(rows) != 1:
            raise _Stop(503, {"error": "room_recovery_failed", "message": "매치 기록이 올바르지 않습니다"})
        ledger, error = self.load_ledger(match_key, trace_id)
        if ledger is None:
            raise _Stop(503, {"error": "room_recovery_failed", "message": "기록을 확인하지 못해 방을 복구하지 않았습니다"})
        room = Room(code, rows[0]["capacity"])
        users = {}
        for seat, user_db in ledger["seats"].items():
            found, trace = self.demo._sql("SELECT id, user_id, display_name FROM guest_users WHERE id = ?", [user_db], trace_id)
            matches = found.get("result", {}).get("rows", []) if trace["outcome"] == "ok" else []
            if len(matches) != 1:
                raise _Stop(503, {"error": "room_recovery_failed", "message": "좌석 소유자 기록을 확인하지 못했습니다"})
            users[seat] = matches[0]
        for user_db in ledger["left"]:
            found, trace = self.demo._sql("SELECT user_id FROM guest_users WHERE id = ?", [user_db], trace_id)
            for row in (found.get("result", {}).get("rows", []) if trace["outcome"] == "ok" else []):
                room.left_users.add(row["user_id"])
        for seat, row in users.items():
            room.seats[seat] = {"userId": row["user_id"], "dbId": row["id"], "name": row["display_name"]}
            room.stacks[seat] = ledger["stacks"][row["id"]]
            room.sitting_in[seat] = room.stacks[seat] > 0
        host_db = rows[0]["host_user"]
        room.host = next((s for s, r in users.items() if r["id"] == host_db), min(users) if users else None)
        room.match_key = match_key
        room.hand_no = ledger["hand_no"]
        room.button = ledger["button"]
        room.last_result_id = ledger["last_id"]
        room.record_status = "confirmed" if ledger["hand_no"] else "not_saved"
        room.phase = "hand_over"
        with room.cond:
            self._check_match_over(room)
            room.recovered = True
            room.next_deadline = self.clock() + self.NEXT_HAND_SECONDS
            room.notice = "서버가 다시 시작되어, 진행 중이던 핸드는 무효 처리하고 마지막으로 저장된 칩에서 이어갑니다."
            self._event(room, "recovered")
            room.version += 1
        return room


class _Stop(Exception):
    def __init__(self, status, body):
        super().__init__(body.get("error"))
        self.status = status
        self.body = body
