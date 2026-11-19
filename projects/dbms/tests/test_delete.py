# [test_delete.py] DELETE (추가 기능): 지운 행이 안 보이는지, 남은 행 · 인덱스 · 파일이 맞는지, 다시 켠 뒤와 동시 실행

import json
import os
import tempfile
import unittest
from unittest import mock

from minidb.engine import Engine
from minidb.executor import ExecutionError, Executor
from minidb.parser import Delete, parse
from minidb.storage import Database, StorageError


def make_dir(case):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    with open(os.path.join(tmp.name, "schema.json"), "w", encoding="utf-8") as f:
        json.dump({"users": {"name": "TEXT", "age": "INT"}}, f)
    return tmp.name


class DeleteTest(unittest.TestCase):
    def setUp(self):
        self.dir = make_dir(self)
        self.open()
        self.run_sql("INSERT INTO users VALUES ('kim', 20); INSERT INTO users VALUES ('lee', 30);"
                     "INSERT INTO users VALUES ('kim', 40); INSERT INTO users VALUES ('park', 50)")

    def open(self, **kwargs):
        self.db = Database(self.dir, **kwargs)
        self.addCleanup(self.db.close)
        self.ex = Executor(self.db)

    def reopen(self):
        self.db.close()
        self.open()

    def run_sql(self, sql):
        return [self.ex.execute(s) for s in parse(sql)]

    def rows(self):
        return self.run_sql("SELECT * FROM users")[0].rows

    def file_bytes(self):
        with open(os.path.join(self.dir, "users.jsonl"), "rb") as f:
            return f.read()

    def test_parse(self):
        self.assertEqual(parse("delete from users where id = 3; DELETE FROM users"),
                         [Delete("users", ("id", 3), 1), Delete("users", None, 1)])

    def test_delete_by_id_uses_index_and_keeps_other_rows(self):
        result = self.run_sql("DELETE FROM users WHERE id = 2")[0]
        self.assertEqual((result.message, result.plan), ("1개 행을 삭제했습니다 (인덱스 사용)", "index"))
        self.assertEqual(self.rows(), [[1, "kim", 20], [3, "kim", 40], [4, "park", 50]])
        # 남은 행의 offset은 그대로라 인덱스로 찾아도 맞다
        for row_id, name in [(1, "kim"), (3, "kim"), (4, "park")]:
            self.assertEqual(self.run_sql(f"SELECT name FROM users WHERE id = {row_id}")[0].rows, [[name]])
        self.assertEqual(self.run_sql("SELECT * FROM users WHERE id = 2")[0].rows, [])

    def test_delete_by_other_column_removes_all_matches(self):
        result = self.run_sql("DELETE FROM users WHERE name = 'kim'")[0]
        self.assertEqual((result.message, result.plan), ("2개 행을 삭제했습니다 (전체 탐색)", "scan"))
        self.assertEqual(self.rows(), [[2, "lee", 30], [4, "park", 50]])
        self.assertEqual(self.run_sql("DELETE FROM users WHERE name = 'kim'")[0].message, "0개 행을 삭제했습니다 (전체 탐색)")

    def test_delete_all_then_insert_continues_ids(self):
        self.assertEqual(self.run_sql("DELETE FROM users")[0].message, "4개 행을 삭제했습니다 (전체 탐색)")
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.run_sql("INSERT INTO users VALUES ('new', 1)")[0].message, "1개 행을 추가했습니다 (id=5)")

    def test_file_keeps_line_lengths_and_marks_deleted_rows(self):
        before = self.file_bytes()
        self.run_sql("DELETE FROM users WHERE id = 2")
        after = self.file_bytes()
        self.assertEqual(len(after), len(before))  # 뒤 행들의 offset이 그대로
        old_line, new_line = before.splitlines(keepends=True)[1], after.splitlines(keepends=True)[1]
        self.assertEqual(len(new_line), len(old_line))
        self.assertEqual(new_line.rstrip(), b"[2]")
        self.assertTrue(new_line.endswith(b"\n"))

    def test_restart_skips_deleted_rows_and_never_reuses_their_ids(self):
        self.run_sql("DELETE FROM users WHERE id = 1; DELETE FROM users WHERE id = 4")  # 맨 끝 행(가장 큰 id)도 지운다
        self.reopen()
        self.assertEqual(self.rows(), [[2, "lee", 30], [3, "kim", 40]])
        self.assertEqual(self.run_sql("SELECT name FROM users WHERE id = 3")[0].rows, [["kim"]])
        self.assertEqual(self.run_sql("SELECT * FROM users WHERE id = 4")[0].rows, [])
        self.assertEqual(self.run_sql("INSERT INTO users VALUES ('new', 1)")[0].message, "1개 행을 추가했습니다 (id=5)")

    def test_errors_delete_nothing(self):
        before = self.file_bytes()
        for sql, message in [("DELETE FROM nope", "테이블이 없습니다"),
                             ("DELETE FROM users WHERE nope = 1", "없는 컬럼"),
                             ("DELETE FROM users WHERE age = 'x'", "INT인데 TEXT")]:
            with self.assertRaises(ExecutionError, msg=sql) as ctx:
                self.run_sql(sql)
            self.assertIn(message, str(ctx.exception), sql)
        self.assertEqual(self.file_bytes(), before)

    def test_rows_still_in_write_buffer_can_be_deleted(self):
        # 대량 적재 모드(autoflush=False): 방금 넣어 아직 버퍼에만 있는 행도 지울 수 있어야 한다
        self.db.close()
        self.open(autoflush=False)
        self.run_sql("INSERT INTO users VALUES ('buffered', 60); DELETE FROM users WHERE id = 5")
        self.assertEqual([r[0] for r in self.rows()], [1, 2, 3, 4])
        self.reopen()
        self.assertEqual([r[0] for r in self.rows()], [1, 2, 3, 4])

    def test_storage_delete_flushes_before_overwriting(self):
        # 실행기는 지울 행을 찾을 때(get · scan) 이미 flush하지만, 저장소의 delete를 바로 불러도 버퍼의 행을 지울 수 있어야 한다
        self.db.close()
        self.open(autoflush=False)
        row_id = self.db.append("users", ["buffered", 60])
        self.assertEqual(self.db.delete("users", [row_id]), 1)
        self.reopen()
        self.assertEqual([r[0] for r in self.rows()], [1, 2, 3, 4])

    def test_crlf_line_keeps_its_line_ending(self):
        self.db.close()
        with open(os.path.join(self.dir, "users.jsonl"), "wb") as f:
            f.write(b'[1, "a", 1]\r\n[2, "b", 2]\r\n')
        self.open()
        self.run_sql("DELETE FROM users WHERE id = 1")
        self.assertEqual(self.file_bytes(), b"[1]        \r\n" + b'[2, "b", 2]\r\n')
        self.reopen()
        self.assertEqual(self.rows(), [[2, "b", 2]])

    def test_torn_delete_mark_is_reported_on_restart(self):
        # 한계 확인: 덮어쓰다 꺼져 줄이 반쯤 바뀌면, 조용히 건너뛰지 않고 켤 때 손상으로 알린다
        self.db.close()
        path = os.path.join(self.dir, "users.jsonl")
        with open(path, "r+b") as f:
            f.write(b"[1]  ")  # 줄 앞부분만 덮어쓴 상태: '[1]  "kim", 20]'
        self.open()
        with self.assertRaises(StorageError):
            self.rows()


class EngineDeleteTest(unittest.TestCase):
    def test_delete_runs_under_the_table_write_lock(self):
        engine = Engine(make_dir(self))
        self.addCleanup(engine.close)
        engine.execute("INSERT INTO users VALUES ('a', 1); INSERT INTO users VALUES ('b', 2)")
        held = []
        real_delete = Database.delete

        def delete(db, table, row_ids):
            held.append(engine._locks[table]._writing)
            return real_delete(db, table, row_ids)

        with mock.patch.object(Database, "delete", delete):
            engine.execute("DELETE FROM users WHERE id = 1; DELETE FROM users WHERE name = 'b'")
        self.assertEqual(held, [True, True])
        self.assertEqual(engine.execute("SELECT * FROM users")[0].rows, [])


if __name__ == "__main__":
    unittest.main()
