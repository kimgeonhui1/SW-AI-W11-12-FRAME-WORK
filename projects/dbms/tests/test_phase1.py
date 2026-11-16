import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mini_dbms import Database, SQLParseError
from mini_dbms.executor import IdempotencyConflict
from mini_dbms.parser import split_script
from mini_dbms.storage import StorageError

PLAYER = "INSERT INTO players (display_name, created_at) VALUES ('Ada', '2026-11-12')"

class Phase1Tests(unittest.TestCase):
    def setUp(self): self.tmp = tempfile.TemporaryDirectory(); self.db = Database(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_insert_select_and_restart(self):
        self.assertEqual(self.db.execute(PLAYER), {"insertedId": 1})
        self.assertEqual(self.db.execute("SELECT id, display_name FROM players WHERE id = 1"), {"rows": [{"id": 1, "display_name": "Ada"}]})
        self.db = Database(self.tmp.name)
        self.assertEqual(self.db.execute("SELECT * FROM players")["rows"][0]["created_at"], "2026-11-12")
    def test_durable_batch_insert_and_restart(self):
        sql = "INSERT INTO bench_rows (lookup_code, payload) VALUES (?, ?)"
        result = self.db.execute_many(sql, ((f"k{i}", f"v{i}") for i in range(20)))
        self.assertEqual(result["insertedIds"], list(range(1, 21)))
        self.db = Database(self.tmp.name)
        self.assertEqual(self.db.execute("SELECT payload FROM bench_rows WHERE id = 20")["rows"], [{"payload": "v19"}])
    def test_insert_once_reuses_exact_row_and_rejects_key_reuse(self):
        sql = "INSERT INTO guest_users (user_id, token_hash, display_name, created_at) VALUES (?, ?, ?, ?)"
        params = ["guest-a", "hash-a", "Ada", "today"]
        first = self.db.execute_insert_once(sql, params, "token_hash")
        retry = self.db.execute_insert_once(sql, params, "token_hash")
        self.assertEqual(first, {"insertedId": 1, "created": True})
        self.assertEqual(retry, {"insertedId": 1, "created": False})
        with self.assertRaises(IdempotencyConflict):
            self.db.execute_insert_once(sql, ["guest-b", "hash-a", "Grace", "today"], "token_hash")
        self.assertEqual(len(self.db.execute("SELECT * FROM guest_users")["rows"]), 1)
        self.db = Database(self.tmp.name)
        self.assertEqual(self.db.execute("SELECT * FROM guest_users WHERE id = 1")["rows"][0]["user_id"], "guest-a")
    def test_script_semicolon_inside_string(self):
        self.assertEqual(len(split_script("INSERT INTO players (display_name, created_at) VALUES ('A;B', 'today'); SELECT * FROM players;")), 2)
    def test_bad_sql_and_types(self):
        for sql in ("DELETE FROM players", "SELECT nope FROM players", "SELECT * FROM players; SELECT * FROM players", "INSERT INTO players (display_name) VALUES ('x')"):
            with self.assertRaises((SQLParseError, ValueError)): self.db.execute(sql)
        with self.assertRaises(ValueError): self.db.execute("INSERT INTO players (display_name, created_at) VALUES (7, 'today')")
    def test_corrupt_file_stops_startup(self):
        (Path(self.tmp.name) / "players.rows").write_bytes(b'{"broken":true}\\n')
        with self.assertRaises(StorageError): Database(self.tmp.name)
    def test_uncertain_append_disables_table_until_reopen(self):
        with patch("mini_dbms.storage.os.fsync", side_effect=OSError("simulated fsync failure")):
            with self.assertRaises(StorageError): self.db.execute(PLAYER)
        with self.assertRaises(StorageError): self.db.execute("SELECT * FROM players")

if __name__ == "__main__": unittest.main()
