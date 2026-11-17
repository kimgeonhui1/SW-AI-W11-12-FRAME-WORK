# [test_engine.py] 저장 · 실행 · 엔진 — SQL 이 파일에 들어가고 다시 나오는지, 계획(인덱스 / 훑기)이 맞는지, 오류 · 엣지 케이스
#
#   카탈로그: 스키마 검사 · 데이터 파일: 저장 → 다시 열기 왕복 · 깨진 마지막 줄 · 쓰기 실패 되돌리기
#   실행: INSERT 열 · 타입 · 원자성 / SELECT 조건 · NULL · 정렬 · LIMIT · 계획 · 잘라 담기
#   읽기-쓰기 락: 읽기는 동시에, 쓰기는 혼자, 쓰기가 굶지 않음

import json
import os
import threading
import time
import unittest
from unittest import mock

from mini_dbms.engine import Engine
from mini_dbms.errors import DataError, SqlError
from mini_dbms.rwlock import RWLock
from tests.helpers import make_data_dir


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir(self)
        self.engine = Engine(self.dir)
        self.addCleanup(lambda: self.engine.close())

    def run_sql(self, sql, **kw):
        return self.engine.execute_all(sql, **kw)

    def rows(self, sql):
        return self.run_sql(sql)[-1]["rows"]

    def error(self, sql):
        with self.assertRaises(SqlError) as ctx:
            self.run_sql(sql)
        return ctx.exception

    def reopen(self):
        self.engine.close()
        self.engine = Engine(self.dir)


class StorageTest(EngineCase):
    def test_round_trip_special_values(self):
        values = ["O'Brien", "줄\n바꿈", "따옴표\"와 \\역슬래시", "이모지 🎹", "", "쉼표, 세미콜론;"]
        for v in values:
            self.run_sql("INSERT INTO users (name) VALUES ('" + v.replace("'", "''") + "')")
        self.reopen()  # 파일에서 다시 읽어도 같아야 한다
        self.assertEqual([r[1] for r in self.rows("SELECT * FROM users")], values)
        self.assertEqual(len((self.dir / "users.jsonl").read_bytes().splitlines()), len(values))  # 줄바꿈 값이 있어도 한 줄 = 한 행

    def test_ids_continue_after_reopen(self):
        self.run_sql("INSERT INTO users (name) VALUES ('a'), ('b')")
        self.reopen()
        r = self.run_sql("INSERT INTO users (name) VALUES ('c')")[0]
        self.assertEqual((r["first_id"], r["last_id"]), (3, 3))
        self.assertEqual(self.rows("SELECT name FROM users WHERE id = 3"), [["c"]])

    def test_partial_last_line_is_cut_with_warning(self):
        self.run_sql("INSERT INTO users (name) VALUES ('a'), ('b')")
        self.engine.close()
        with open(self.dir / "users.jsonl", "ab") as f:
            f.write('[3,"반쯤'.encode("utf-8"))  # 쓰다가 꺼진 줄
        self.engine = Engine(self.dir)
        self.assertEqual(len(self.engine.warnings), 1)
        self.assertEqual([r[0] for r in self.rows("SELECT * FROM users")], [1, 2])
        self.assertEqual(self.run_sql("INSERT INTO users (name) VALUES ('c')")[0]["first_id"], 3)  # 잘라 낸 자리부터 이어서

    def test_corrupt_middle_line_refuses_to_start(self):
        self.run_sql("INSERT INTO users (name) VALUES ('a'), ('b')")
        self.engine.close()
        path = self.dir / "users.jsonl"
        path.write_bytes(b"[1,\"a\",null,null]\nGARBAGE\n[2,\"b\",null,null]\n")
        with self.assertRaises(DataError):
            Engine(self.dir)
        path.write_bytes(b"[2,\"a\",null,null]\n[1,\"b\",null,null]\n")  # id 순서가 어긋남
        with self.assertRaises(DataError):
            Engine(self.dir)
        self.engine = Engine(make_data_dir(self))  # tearDown 이 닫을 엔진

    def test_write_failure_rolls_back(self):
        self.run_sql("INSERT INTO users (name) VALUES ('a')")
        size = os.path.getsize(self.dir / "users.jsonl")
        table = self.engine.tables["users"]
        with mock.patch.object(table._writer, "flush", side_effect=OSError("디스크 가득")):
            e = self.error("INSERT INTO users (name) VALUES ('b'), ('c')")
        self.assertIn("아무 행도 저장되지 않음", e.message)
        self.assertEqual(os.path.getsize(self.dir / "users.jsonl"), size)  # 파일은 쓰기 전 크기
        self.assertEqual((len(table), table.next_id), (1, 2))  # 인덱스 · 다음 id 도 그대로
        self.assertEqual(self.run_sql("INSERT INTO users (name) VALUES ('d')")[0]["first_id"], 2)
        self.reopen()
        self.assertEqual([r[1] for r in self.rows("SELECT * FROM users")], ["a", "d"])

    def test_lone_surrogate_is_rejected_before_writing(self):
        e = self.error("INSERT INTO users (name) VALUES ('\ud800')")
        self.assertIn("서로게이트", e.message)
        self.assertEqual(self.rows("SELECT * FROM users"), [])

    def test_bad_schemas(self):
        for columns, why in [
            ({"columns": [{"name": "name", "type": "TEXT"}]}, "첫 열은 id INT"),
            ({"columns": [{"name": "id", "type": "INT"}, {"name": "a", "type": "DATE"}]}, "열은"),
            ({"columns": [{"name": "id", "type": "INT"}, {"name": "../x", "type": "TEXT"}]}, "열 이름"),
            ({"columns": [{"name": "id", "type": "INT"}, {"name": "a", "type": "INT"}, {"name": "a", "type": "INT"}]}, "겹칩니다"),
            ([], "columns"),
        ]:
            d = make_data_dir(self, {})
            (d / "t.schema.json").write_text(json.dumps(columns), encoding="utf-8")
            with self.assertRaises(DataError) as ctx:
                Engine(d)
            self.assertIn(why, str(ctx.exception))
        d = make_data_dir(self, {})
        (d / "Bad-Name.schema.json").write_text('{"columns": [{"name": "id", "type": "INT"}]}', encoding="utf-8")
        self.assertRaises(DataError, Engine, d)
        self.assertRaises(DataError, Engine, d / "없는폴더")


class InsertTest(EngineCase):
    def test_columns_and_defaults(self):
        r = self.run_sql("INSERT INTO users (email, name) VALUES ('a@x', 'a'); INSERT INTO users VALUES ('b', 20, 'b@x')")
        self.assertEqual([(x["count"], x["first_id"], x["last_id"]) for x in r], [(1, 1, 1), (1, 2, 2)])
        self.assertEqual(self.rows("SELECT * FROM users"), [[1, "a", None, "a@x"], [2, "b", 20, "b@x"]])

    def test_float_column_takes_ints(self):
        self.run_sql("INSERT INTO products VALUES ('a', 3), ('b', 2.5)")
        self.assertEqual(self.rows("SELECT price FROM products"), [[3.0], [2.5]])

    def test_errors(self):
        cases = [
            ("INSERT INTO nope VALUES (1)", "테이블 'nope' 이 없습니다 (있는 테이블: products, users)"),
            ("INSERT INTO users (nme) VALUES ('a')", "테이블 'users' 에 열 'nme' 이 없습니다 (있는 열: id, name, age, email)"),
            ("INSERT INTO users (id, name) VALUES (5, 'a')", "id 는 자동으로 붙는 열이라 직접 넣을 수 없습니다"),
            ("INSERT INTO users (name, name) VALUES ('a', 'b')", "열 'name' 이 두 번 나옵니다"),
            ("INSERT INTO users (name, age) VALUES ('a', 1), ('b')", "2번째 행: 값이 1개인데 열은 2개입니다"),
            ("INSERT INTO users (age) VALUES ('스물')", "1번째 행: 열 'age' 은 INT 인데 문자열 값 '스물' 이 왔습니다"),
            ("INSERT INTO users (age) VALUES (25.5)", "1번째 행: 열 'age' 은 INT 인데 소수 값 25.5 이 왔습니다"),
            ("INSERT INTO users (name) VALUES (1)", "1번째 행: 열 'name' 은 TEXT 인데 정수 값 1 이 왔습니다"),
        ]
        for sql, message in cases:
            self.assertEqual(self.error(sql).message, message, sql)
        self.assertEqual(self.rows("SELECT * FROM users"), [])

    def test_multi_row_insert_is_all_or_nothing(self):
        e = self.error("INSERT INTO users (name, age) VALUES ('a', 1), ('b', 2), ('c', 'x')")
        self.assertIn("3번째 행", e.message)
        self.assertEqual(self.rows("SELECT * FROM users"), [])  # 앞의 두 행도 들어가지 않았다

    def test_script_stops_at_failing_statement(self):
        e = self.error("INSERT INTO users (name) VALUES ('a'); SELECT * FROM nope; INSERT INTO users (name) VALUES ('b')")
        self.assertEqual(e.statement, 2)
        self.assertEqual(self.rows("SELECT name FROM users"), [["a"]])  # 1번째는 남고, 3번째는 실행되지 않음
        self.assertEqual(self.error("SELECT * FROM users; SELEC 1").statement, 2)  # 문법 오류도 몇 번째 문장인지


class SelectTest(EngineCase):
    def setUp(self):
        super().setUp()
        self.run_sql(
            "INSERT INTO users (name, age, email) VALUES ('kim', 25, 'k@x'), ('lee', NULL, 'l@x'), ('park', 31, NULL),"
            " ('choi', 25, 'c@x'), ('jung', 40, 'j@x')"
        )

    def ids(self, where):
        return [r[0] for r in self.rows(f"SELECT * FROM users WHERE {where}")]

    def test_where_operators_and_and(self):
        self.assertEqual(self.ids("age = 25"), [1, 4])
        self.assertEqual(self.ids("age != 25"), [3, 5])  # NULL(2번)은 != 에도 안 걸린다
        self.assertEqual(self.ids("age <> 25"), [3, 5])
        self.assertEqual(self.ids("age > 25 AND age <= 40"), [3, 5])
        self.assertEqual(self.ids("name >= 'kim'"), [1, 2, 3])  # 문자열은 유니코드 순서 (kim · lee · park)
        self.assertEqual(self.ids("age = 25 AND name = 'choi'"), [4])
        self.assertEqual(self.ids("age = 25.0"), [1, 4])  # INT 열을 소수와 비교

    def test_null_comparisons_are_false(self):
        self.assertEqual(self.ids("age = NULL"), [])
        self.assertEqual(self.ids("age != NULL"), [])
        self.assertEqual(self.ids("email = 'nope'"), [])

    def test_type_mismatch_is_error(self):
        e = self.error("SELECT * FROM users WHERE age = 'x'")
        self.assertEqual((e.message, e.line, e.col), ("열 'age'(INT) 을 문자열 값 'x' 과 비교할 수 없습니다", 1, 27))
        self.assertIn("비교할 수 없습니다", self.error("SELECT * FROM users WHERE name = 1").message)
        self.assertIn("열 'nope' 이 없습니다", self.error("SELECT * FROM users WHERE nope = 1").message)
        self.assertIn("열 'nope' 이 없습니다", self.error("SELECT * FROM users ORDER BY nope").message)

    def test_projection_order_limit(self):
        self.assertEqual(self.rows("SELECT name FROM users WHERE id = 3"), [["park"]])
        self.assertEqual(self.rows("SELECT age, name FROM users ORDER BY age")[0:2], [[25, "kim"], [25, "choi"]])  # 같으면 id 순서 유지
        self.assertEqual([r[0] for r in self.rows("SELECT age FROM users ORDER BY age DESC")], [40, 31, 25, 25, None])  # NULL 은 맨 뒤
        self.assertEqual([r[0] for r in self.rows("SELECT age FROM users ORDER BY age ASC")], [25, 25, 31, 40, None])
        self.assertEqual([r[0] for r in self.rows("SELECT id FROM users ORDER BY id DESC LIMIT 2")], [5, 4])
        self.assertEqual([r[0] for r in self.rows("SELECT id FROM users LIMIT 2")], [1, 2])
        self.assertEqual(self.rows("SELECT id FROM users LIMIT 0"), [])

    def test_plan_choice(self):
        def plan(where):
            r = self.run_sql(f"SELECT * FROM users WHERE {where}")[0]
            return r["plan"], r["scanned"], [row[0] for row in r["rows"]]

        self.assertEqual(plan("id = 3"), ("index-eq (id = 3)", 1, [3]))  # 한 행만 읽음
        self.assertEqual(plan("id = 99"), ("index-eq (id = 99)", 0, []))
        self.assertEqual(plan("id >= 2 AND id < 4"), ("index-range (id >= 2 AND id < 4)", 2, [2, 3]))
        self.assertEqual(plan("id > 1 AND id > 3"), ("index-range (id > 3)", 2, [4, 5]))  # 더 좁은 경계
        self.assertEqual(plan("id <= 2 AND age = 25"), ("index-range (id <= 2)", 2, [1]))  # 인덱스로 줄인 뒤 나머지 조건
        self.assertEqual(plan("id = 1 AND id = 2"), ("index-eq (id = 1)", 1, []))  # 모순 → 빈 결과
        self.assertEqual(plan("id != 3"), ("full-scan", 5, [1, 2, 4, 5]))
        self.assertEqual(plan("name = 'park'"), ("full-scan", 5, [3]))
        self.assertEqual(self.run_sql("EXPLAIN SELECT * FROM users WHERE id = 2")[0], {"type": "explain", "table": "users", "plan": "index-eq (id = 2)", "ms": mock.ANY})

    def test_max_rows_truncates_but_counts(self):
        r = self.run_sql("SELECT id FROM users", max_rows=2)[0]
        self.assertEqual((r["rows"], r["count"], r["total"], r["truncated"]), ([[1], [2]], 2, 5, True))
        r = self.run_sql("SELECT id FROM users ORDER BY age", max_rows=2)[0]
        self.assertEqual((r["count"], r["total"], r["truncated"]), (2, 5, True))
        self.assertFalse(self.run_sql("SELECT id FROM users", max_rows=10)[0]["truncated"])

    def test_empty_table(self):
        r = self.run_sql("SELECT * FROM products")[0]
        self.assertEqual((r["columns"], r["rows"], r["count"]), (["id", "name", "price"], [], 0))


class ConcurrencyTest(EngineCase):
    def test_concurrent_inserts_get_unique_ids(self):
        def worker(t):
            for i in range(50):
                self.run_sql(f"INSERT INTO users (name) VALUES ('t{t}-{i}')")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        ids = [r[0] for r in self.rows("SELECT id FROM users")]
        self.assertEqual(ids, list(range(1, 401)))  # 빠짐 · 겹침 없음
        self.assertEqual(len((self.dir / "users.jsonl").read_bytes().splitlines()), 400)
        self.engine.tables["users"].index.check()

    def test_reads_during_writes_see_whole_rows(self):
        stop, errors = threading.Event(), []

        def reader():
            while not stop.is_set():
                try:
                    for row in self.rows("SELECT * FROM users"):
                        assert len(row) == 4 and row[1].startswith("w"), row
                except Exception as e:  # noqa: BLE001 — 스레드 안 실패는 모아서 본다
                    errors.append(repr(e))

        readers = [threading.Thread(target=reader) for _ in range(4)]
        for th in readers:
            th.start()
        for i in range(200):
            self.run_sql(f"INSERT INTO users (name) VALUES ('w{i}'), ('w{i}b')")
        stop.set()
        for th in readers:
            th.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.rows("SELECT id FROM users")), 400)


class RWLockTest(unittest.TestCase):
    def test_readers_overlap(self):
        lock, inside, both = RWLock(), [], threading.Barrier(2, timeout=2)

        def reader():
            with lock.read():
                inside.append(1)
                both.wait()  # 두 읽기가 동시에 안에 있어야 통과 (아니면 BrokenBarrierError)

        threads = [threading.Thread(target=reader) for _ in range(2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(inside), 2)

    def test_writer_is_exclusive_and_not_starved(self):
        lock, log = RWLock(), []
        writer_waiting = threading.Event()

        def writer():
            writer_waiting.set()
            with lock.write():
                log.append("W")

        def late_reader():
            with lock.read():
                log.append("R2")

        with lock.read():  # 읽기 하나가 들어가 있는 동안
            w = threading.Thread(target=writer)
            w.start()
            writer_waiting.wait()
            time.sleep(0.05)  # 쓰기가 기다리기 시작할 시간
            r2 = threading.Thread(target=late_reader)
            r2.start()
            time.sleep(0.05)
            self.assertEqual(log, [])  # 쓰기는 읽기가 끝나길, 늦게 온 읽기는 쓰기가 끝나길 기다린다
        w.join()
        r2.join()
        self.assertEqual(log, ["W", "R2"])  # 쓰기 먼저 (쓰기 우선 — 굶지 않음)


if __name__ == "__main__":
    unittest.main()
