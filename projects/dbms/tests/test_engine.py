# [test_engine.py] 내부 엔진 (Phase 3): 여러 스레드가 동시에 INSERT · SELECT해도 데이터가 맞는지

import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from minidb.engine import Engine, StatementError
from minidb.executor import ExecutionError, Executor
from minidb.tokenizer import SqlSyntaxError


class EngineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "schema.json"), "w", encoding="utf-8") as f:
            json.dump({"users": {"name": "TEXT", "age": "INT"}, "logs": {"msg": "TEXT"}}, f)
        self.engine = Engine(tmp.name)
        self.addCleanup(self.engine.close)

    def test_runs_statements_in_order(self):
        results = self.engine.execute("INSERT INTO users VALUES ('a', 1); INSERT INTO users VALUES ('b', 2);"
                                      "SELECT name FROM users WHERE id = 2")
        self.assertEqual([r.message for r in results[:2]], ["1개 행을 추가했습니다 (id=1)", "1개 행을 추가했습니다 (id=2)"])
        self.assertEqual((results[2].rows, results[2].plan), ([["b"]], "index"))

    def test_syntax_error_runs_nothing(self):
        with self.assertRaises(SqlSyntaxError):
            self.engine.execute("INSERT INTO users VALUES ('a', 1); SELEC")
        self.assertEqual(self.engine.execute("SELECT * FROM users")[0].rows, [])

    def test_execution_error_keeps_earlier_results(self):
        with self.assertRaises(StatementError) as ctx:
            self.engine.execute("INSERT INTO users VALUES ('a', 1);\nINSERT INTO nope VALUES (1);\nINSERT INTO users VALUES ('c', 3)")
        error = ctx.exception
        self.assertIn("2번째 문장 (줄 2)", str(error))
        self.assertIsInstance(error.cause, ExecutionError)
        self.assertEqual(len(error.results), 1)  # 앞 문장 결과
        self.assertEqual(len(self.engine.execute("SELECT * FROM users")[0].rows), 1)  # 뒤 문장은 실행 안 함

    def test_concurrent_inserts_get_unique_ids(self):
        # 스레드 16개가 동시에 50번씩 INSERT → id 800개가 1~800으로 겹치지 않고, 파일 줄도 800개 (락이 없으면 id가 겹치거나 줄이 섞인다)
        errors = []

        def insert(worker):
            try:
                for i in range(50):
                    self.engine.execute(f"INSERT INTO users VALUES ('w{worker}-{i}', {i})")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=insert, args=(w,)) for w in range(16)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        rows = self.engine.execute("SELECT id, name FROM users")[0].rows
        self.assertEqual(sorted(r[0] for r in rows), list(range(1, 801)))
        self.assertEqual(len({r[1] for r in rows}), 800)
        self.engine.close()
        reopened = Engine(self.engine.db.directory)  # 파일에서 다시 읽어도 800개, 다음 id는 801
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.execute("INSERT INTO users VALUES ('x', 0)")[0].message, "1개 행을 추가했습니다 (id=801)")

    def test_concurrent_reads_and_writes_stay_consistent(self):
        # 읽는 스레드 8개는 id로 찾은 행이 항상 그 id의 행인지 확인하고, 쓰는 스레드 2개는 그동안 계속 INSERT한다
        # (id 검색용 파일 하나를 여러 스레드가 쓰므로, seek와 readline 사이에 끼어들면 남의 줄을 읽는다)
        for i in range(1, 301):
            self.engine.execute(f"INSERT INTO users VALUES ('u{i}', {i})")
        errors, stop = [], threading.Event()

        def reader(seed):
            try:
                for n in range(400):
                    row_id = (seed * 37 + n * 11) % 300 + 1
                    rows = self.engine.execute(f"SELECT id, name FROM users WHERE id = {row_id}")[0].rows
                    if rows != [[row_id, f"u{row_id}"]]:
                        errors.append((row_id, rows))
            except Exception as e:
                errors.append(e)

        def writer(w):
            i = 0
            while not stop.is_set():
                self.engine.execute(f"INSERT INTO logs VALUES ('w{w}-{i}')")
                self.engine.execute(f"INSERT INTO users VALUES ('extra{w}-{i}', 0)")
                i += 1

        readers = [threading.Thread(target=reader, args=(s,)) for s in range(8)]
        writers = [threading.Thread(target=writer, args=(w,)) for w in range(2)]
        [t.start() for t in readers + writers]
        [t.join() for t in readers]
        stop.set()
        [t.join() for t in writers]
        self.assertEqual(errors, [])

    def test_selects_run_at_the_same_time(self):
        # 같은 테이블의 SELECT 두 개가 동시에 실행 중일 수 있다 (락 하나였다면 하나가 끝날 때까지 기다린다)
        both_inside = threading.Barrier(2, timeout=2)
        real = Executor.execute

        def slow(executor, stmt):
            both_inside.wait()  # 두 SELECT가 동시에 여기 있어야 통과
            return real(executor, stmt)

        with mock.patch.object(Executor, "execute", slow):
            threads = [threading.Thread(target=self.engine.execute, args=("SELECT * FROM users",)) for _ in range(2)]
            [t.start() for t in threads]
            [t.join(3) for t in threads]
        self.assertFalse(both_inside.broken)


if __name__ == "__main__":
    unittest.main()
