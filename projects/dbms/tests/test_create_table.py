# [test_create_table.py] CREATE TABLE (추가 기능): 문법 · 검사 · schema.json 저장 · 재시작 · 동시 실행

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from minidb import storage
from minidb.engine import Engine, StatementError
from minidb.executor import ExecutionError, Executor
from minidb.parser import CreateTable, parse
from minidb.storage import Database
from minidb.tokenizer import SqlSyntaxError


def make_dir(case, schema=None):
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    with open(os.path.join(tmp.name, "schema.json"), "w", encoding="utf-8") as f:
        json.dump(schema or {"users": {"name": "TEXT"}}, f)
    return tmp.name


def read_schema(directory):
    with open(os.path.join(directory, "schema.json"), encoding="utf-8") as f:
        return json.load(f)


class ParseCreateTableTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse("create table books (title text, Price INT);"),
                         [CreateTable("books", [("title", "TEXT"), ("Price", "INT")], 1)])

    def test_syntax_errors(self):
        for sql in ["CREATE books (a INT)",  # TABLE 없음
                    "CREATE TABLE books",  # 컬럼 목록 없음
                    "CREATE TABLE books ()",  # 컬럼 0개
                    "CREATE TABLE books (a)",  # 타입 없음
                    "CREATE TABLE books (a FLOAT)",  # 지원하지 않는 타입
                    "CREATE TABLE books (a INT,)",
                    "CREATE TABLE table (a INT)"]:  # 키워드는 이름으로 못 쓴다
            with self.assertRaises(SqlSyntaxError, msg=sql):
                parse(sql)

    def test_type_error_points_at_type(self):
        with self.assertRaises(SqlSyntaxError) as ctx:
            parse("CREATE TABLE books (a INT,\n  b FLOAT)")
        self.assertEqual((ctx.exception.line, ctx.exception.col), (2, 5))


class CreateTableTest(unittest.TestCase):
    def setUp(self):
        self.dir = make_dir(self)
        self.db = Database(self.dir)
        self.addCleanup(self.db.close)
        self.ex = Executor(self.db)

    def run_sql(self, sql):
        return [self.ex.execute(s) for s in parse(sql)]

    def test_create_then_insert_and_select_in_same_sql(self):
        results = self.run_sql("CREATE TABLE books (title TEXT, price INT); INSERT INTO books VALUES ('책', 100);"
                               "SELECT * FROM books WHERE id = 1")
        self.assertEqual(results[0].message, "테이블을 만들었습니다: books")
        self.assertEqual((results[2].columns, results[2].rows), (["id", "title", "price"], [[1, "책", 100]]))

    def test_saved_to_schema_and_survives_restart(self):
        self.run_sql("CREATE TABLE books (title TEXT, price INT); INSERT INTO books VALUES ('책', 100)")
        self.assertEqual(read_schema(self.dir), {"users": {"name": "TEXT"}, "books": {"title": "TEXT", "price": "INT"}})
        self.db.close()
        with Database(self.dir) as db:
            self.assertEqual(Executor(db).execute(parse("SELECT * FROM books")[0]).rows, [[1, "책", 100]])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "schema.json.tmp")))

    def test_rejected_definitions_change_nothing(self):
        cases = {
            "CREATE TABLE users (a INT)": "이미 있는 테이블",
            "CREATE TABLE Users (a INT)": "대소문자만 다른",
            "CREATE TABLE con (a INT)": "Windows 장치",
            "CREATE TABLE books (id INT)": "id는 자동",
            "CREATE TABLE books (a INT, a TEXT)": "같은 컬럼이 두 번",
            f"CREATE TABLE {'b' * 65} (a INT)": "이름이 올바르지 않습니다",
        }
        before = read_schema(self.dir)
        for sql, message in cases.items():
            with self.assertRaises(ExecutionError, msg=sql) as ctx:
                self.run_sql(sql)
            self.assertIn(message, str(ctx.exception), sql)
        self.assertEqual(read_schema(self.dir), before)
        self.assertEqual(list(self.db.tables), ["users"])

    def test_leftover_data_file_is_rejected(self):
        with open(os.path.join(self.dir, "books.jsonl"), "w", encoding="utf-8") as f:
            f.write('[1, "옛 데이터"]\n')
        with self.assertRaises(ExecutionError) as ctx:
            self.run_sql("CREATE TABLE books (title TEXT, price INT)")
        self.assertIn("books.jsonl 파일이 이미 있습니다", str(ctx.exception))
        self.assertNotIn("books", self.db.tables)

    def test_failed_save_keeps_old_schema_and_memory(self):
        # os.replace가 실패하면(다른 프로그램이 파일을 잡고 있음 등) 스키마 파일 · 메모리 모두 그대로, 임시 파일도 남지 않는다
        before = read_schema(self.dir)
        with mock.patch.object(storage.os, "replace", side_effect=PermissionError("잠김")):
            with self.assertRaises(ExecutionError) as ctx:
                self.run_sql("CREATE TABLE books (title TEXT)")
        self.assertIn("저장하지 못했습니다", str(ctx.exception))
        self.assertEqual(read_schema(self.dir), before)
        self.assertNotIn("books", self.db.tables)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "schema.json.tmp")))


class EngineCreateTableTest(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(make_dir(self))
        self.addCleanup(self.engine.close)

    def test_same_create_at_once_only_one_succeeds(self):
        outcomes, barrier = [], threading.Barrier(16)

        def create():
            barrier.wait()
            try:
                self.engine.execute("CREATE TABLE books (title TEXT)")
                outcomes.append("ok")
            except StatementError as e:
                outcomes.append(str(e.cause))

        threads = [threading.Thread(target=create) for _ in range(16)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(outcomes.count("ok"), 1)
        self.assertTrue(all("이미 있는 테이블" in o for o in outcomes if o != "ok"))

    def test_failed_create_leaves_no_lock_behind(self):
        for i in range(50):
            with self.assertRaises(StatementError):
                self.engine.execute(f"CREATE TABLE {'x' * 70}{i} (a INT)")  # 이름이 너무 김
        with self.assertRaises(StatementError):
            self.engine.execute("CREATE TABLE users (a INT)")  # 이미 있음: 기존 락은 그대로
        self.assertEqual(set(self.engine._locks), {"users"})

    def test_inserts_racing_create_never_run_without_lock(self):
        # CREATE와 동시에 그 테이블에 INSERT를 퍼부어도, 실행기는 언제나 그 테이블의 쓰기 락을 잡은 상태에서만 불린다.
        # id가 실제로 겹치는 일은 GIL 때문에 드물고 CREATE의 fsync가 길어 틈을 시간으로 노리기 어렵다(변이 시험 0/10) →
        # 실행기가 테이블을 확인하는 순간 락이 잡혀 있었는지를 직접 기록한다 (락 없이 넘기면 CREATE 전에도 바로 드러난다)
        unlocked = []
        real_check = Executor._check_table

        def check(executor, table):
            lock = self.engine._locks.get(table)
            if lock is None or not lock._writing:
                unlocked.append(table)
            return real_check(executor, table)

        self.enterContext(mock.patch.object(Executor, "_check_table", check))
        # 테이블(과 락)이 없을 때의 INSERT는 실행기까지 가지 않아야 한다. 스레드 경쟁은 출발 직후 CREATE가 락을 바로 등록해
        # 이 상태를 거의 만들지 못하므로 먼저 확정적으로 한 번 확인한다
        with self.assertRaises(StatementError):
            self.engine.execute("INSERT INTO books VALUES ('x')")
        self.assertEqual(unlocked, [])
        ids, lock, start = [], threading.Lock(), threading.Barrier(9)

        def insert():
            start.wait()
            done = 0
            while done < 30:  # 테이블이 생기기 전(실패)부터 생긴 뒤(성공 30번)까지 계속 보낸다
                try:
                    message = self.engine.execute("INSERT INTO books VALUES ('x')")[0].message
                except StatementError as e:
                    self.assertIn("테이블이 없습니다", str(e.cause))
                    continue
                done += 1
                with lock:
                    ids.append(int(message.split("id=")[1].rstrip(")")))

        threads = [threading.Thread(target=insert) for _ in range(8)]
        [t.start() for t in threads]
        start.wait()
        self.engine.execute("CREATE TABLE books (title TEXT)")
        [t.join() for t in threads]
        self.assertEqual(unlocked, [])
        self.assertGreater(len(ids), 0)
        self.assertEqual(sorted(ids), list(range(1, len(ids) + 1)))
        rows = self.engine.execute("SELECT id FROM books")[0].rows
        self.assertEqual(sorted(r[0] for r in rows), sorted(ids))


if __name__ == "__main__":
    unittest.main()
