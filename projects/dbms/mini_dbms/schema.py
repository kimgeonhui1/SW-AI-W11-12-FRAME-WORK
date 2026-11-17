"""Fixed schemas; table names and columns are allow-listed here."""
SCHEMAS = {
    "players": {"display_name": "TEXT", "created_at": "TEXT"},
    "guest_users": {"user_id": "TEXT", "token_hash": "TEXT", "display_name": "TEXT", "created_at": "TEXT"},
    "matches": {"match_key": "TEXT", "player_a": "INTEGER", "player_b": "INTEGER", "initial_a": "INTEGER", "initial_b": "INTEGER", "blinds": "TEXT", "rules_version": "TEXT"},
    "hand_results": {"operation_key": "TEXT", "payload_hash": "TEXT", "schema_version": "INTEGER", "match_key": "TEXT", "hand_no": "INTEGER", "prev_result_id": "INTEGER", "start_a": "INTEGER", "start_b": "INTEGER", "end_a": "INTEGER", "end_b": "INTEGER", "winner": "TEXT", "reason": "TEXT", "board": "TEXT", "public_actions": "TEXT", "rules_version": "TEXT"},
    "bench_rows": {"lookup_code": "TEXT", "payload": "TEXT"},
    # 2-4 seat rooms (additive: the tables above and their files are unchanged).
    "room_matches": {"match_key": "TEXT", "room_code": "TEXT", "capacity": "INTEGER", "host_user": "INTEGER", "blinds": "TEXT", "rules_version": "TEXT"},
    "room_seat_events": {"operation_key": "TEXT", "payload_hash": "TEXT", "match_key": "TEXT", "kind": "TEXT", "user_db": "INTEGER", "seat": "INTEGER", "amount": "INTEGER", "after_hand": "INTEGER"},
    "room_hand_results": {"operation_key": "TEXT", "payload_hash": "TEXT", "schema_version": "INTEGER", "match_key": "TEXT", "hand_no": "INTEGER", "prev_result_id": "INTEGER", "button": "INTEGER", "participants": "TEXT", "pots": "TEXT", "board": "TEXT", "public_actions": "TEXT", "reason": "TEXT", "rules_version": "TEXT"},
}
MAX_RECORD_BYTES = 1_048_576
