# [test_executor.py] 파싱된 문장이 스키마 검사를 거쳐 파일에 저장 · 조회되는지 (파서 + 실행기 + 저장소 연결)
# Phase 2: 자동 id, WHERE id = 값은 인덱스, 나머지는 전체 탐색

import json
import os
import tempfile
import unittest

from minidb.executor import ExecutionError, Executor
from minidb.parser import parse
from minidb.storage import Database


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with open(os.path.join(tmp.name, "schema.json"), "w", encoding="utf-8") as f:
            json.dump({"users": {"name": "TEXT", "age": "INT"}, "empty": {"x": "INT"}}, f)
        self.db = Database(tmp.name)
        self.addCleanup(self.db.close)  # 열어 둔 테이블 파일을 닫아야 임시 폴더를 지울 수 있다 (Windows)
        self.ex = Executor(self.db)

    def run_sql(self, sql, executor=None):
        return [(executor or self.ex).execute(stmt) for stmt in parse(sql)]

    def select(self, sql, executor=None):
        result = self.run_sql(sql, executor)[-1]
        return result.columns, result.rows

    def test_insert_then_select(self):
        self.run_sql("""
            INSERT INTO users (name, age) VALUES ('kim', 25);
            INSERT INTO users VALUES ('lee', 30);
            INSERT INTO users (age, name) VALUES (25, 'park');
        """)
        self.assertEqual(self.select("SELECT * FROM users"),
                         (["id", "name", "age"], [[1, "kim", 25], [2, "lee", 30], [3, "park", 25]]))  # id는 1부터 자동
        self.assertEqual(self.select("SELECT name FROM users WHERE age = 25"), (["name"], [["kim"], ["park"]]))
        self.assertEqual(self.select("SELECT age, name, age FROM users WHERE name = 'lee'"),
                         (["age", "name", "age"], [[30, "lee", 30]]))  # 순서 바꾸기, 같은 컬럼 두 번도 된다
        self.assertEqual(self.select("SELECT name, id FROM users WHERE id = 3"), (["name", "id"], [["park", 3]]))

    def test_column_order_in_file_follows_schema(self):
        self.run_sql("INSERT INTO users (age, name) VALUES (7, 'a')")
        with open(self.db.path("users"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '[1, "a", 7]\n')  # id가 맨 앞, 나머지는 스키마 순서

    def test_results_and_plans(self):
        insert, by_age, by_id, missing = self.run_sql(
            "INSERT INTO users VALUES ('a', 1); SELECT * FROM users WHERE age = 2;"
            "SELECT * FROM users WHERE id = 1; SELECT * FROM users WHERE id = 99")
        self.assertEqual((insert.message, insert.plan), ("1개 행을 추가했습니다 (id=1)", ""))
        self.assertEqual((by_age.rows, by_age.message, by_age.plan), ([], "0개 행 (전체 탐색)", "scan"))
        self.assertEqual((by_id.rows, by_id.plan, by_id.message), ([[1, "a", 1]], "index", "1개 행 (인덱스 사용)"))
        self.assertEqual((missing.rows, missing.plan), ([], "index"))  # 없는 id도 인덱스로 바로 "없음"

    def test_index_and_scan_give_same_rows(self):
        # 같은 질문을 인덱스로 · 전체 탐색으로 풀어도 답이 같아야 한다 (성능 비교의 전제)
        for i in range(1, 201):
            self.run_sql(f"INSERT INTO users VALUES ('user{i}', {i % 7})")
        scan = Executor(self.db, use_index=False)
        for row_id in (1, 2, 100, 199, 200, 201, 0, -5):
            sql = f"SELECT * FROM users WHERE id = {row_id}"
            with_index = self.run_sql(sql)[0]
            without = self.run_sql(sql, scan)[0]
            self.assertEqual(with_index.rows, without.rows, row_id)
            self.assertEqual((with_index.plan, without.plan), ("index", "scan"))

    def test_ids_continue_after_restart(self):
        self.run_sql("INSERT INTO users VALUES ('a', 1); INSERT INTO users VALUES ('b', 2)")
        self.db.close()
        reopened = Database(self.db.directory)  # 프로그램을 다시 켠 것과 같다 → 파일을 읽어 인덱스를 다시 만든다
        self.addCleanup(reopened.close)
        ex = Executor(reopened)
        self.assertEqual(self.run_sql("INSERT INTO users VALUES ('c', 3)", ex)[0].message, "1개 행을 추가했습니다 (id=3)")
        self.assertEqual(self.select("SELECT name FROM users WHERE id = 2", ex), (["name"], [["b"]]))
        self.assertEqual(self.select("SELECT name FROM users WHERE id = 3", ex), (["name"], [["c"]]))

    def test_select_from_table_never_inserted(self):
        self.assertEqual(self.select("SELECT * FROM empty"), (["id", "x"], []))
        self.assertEqual(self.select("SELECT * FROM empty WHERE id = 1"), (["id", "x"], []))

    def test_where_is_exact_and_case_sensitive(self):
        self.run_sql("INSERT INTO users VALUES ('Kim', 1); INSERT INTO users VALUES ('kim ', 2)")
        self.assertEqual(self.select("SELECT age FROM users WHERE name = 'kim'")[1], [])

    def test_errors(self):
        cases = [
            "INSERT INTO nope VALUES (1)",  # 없는 테이블
            "SELECT * FROM nope",
            "SELECT * FROM Users",  # 테이블 이름은 대소문자 구분
            "INSERT INTO users VALUES ('a')",  # 값 개수가 컬럼 수와 다름
            "INSERT INTO users VALUES ('a', 1, 2)",
            "INSERT INTO users VALUES (5, 'a', 1)",  # id 자리에 값을 넣으려 함 (값 개수가 맞지 않음)
            "INSERT INTO users (id, name, age) VALUES (5, 'a', 1)",  # id는 자동 부여
            "INSERT INTO users (name) VALUES ('a', 1)",
            "INSERT INTO users (name) VALUES ('a')",  # age 값 없음 (NULL 미지원)
            "INSERT INTO users (name, nope) VALUES ('a', 1)",  # 없는 컬럼
            "INSERT INTO users (name, name) VALUES ('a', 'b')",  # 같은 컬럼 두 번
            "INSERT INTO users VALUES (1, 1)",  # TEXT 칸에 정수
            "INSERT INTO users VALUES ('a', '1')",  # INT 칸에 문자열
            "SELECT nope FROM users",
            "SELECT * FROM users WHERE nope = 1",
            "SELECT * FROM users WHERE age = '25'",  # 타입이 달라 절대 같을 수 없는 비교
            "SELECT * FROM users WHERE name = 1",
            "SELECT * FROM users WHERE id = '1'",  # id는 INT
        ]
        for sql in cases:
            with self.assertRaises(ExecutionError, msg=sql):
                self.run_sql(sql)

    def test_insert_with_id_explains_auto_id(self):
        # "없는 컬럼"이 아니라 왜 안 되는지를 알려 준다
        with self.assertRaises(ExecutionError) as ctx:
            self.run_sql("INSERT INTO users (id, name, age) VALUES (5, 'a', 1)")
        self.assertIn("자동으로 부여", str(ctx.exception))

    def test_failed_insert_writes_nothing(self):
        for sql in ["INSERT INTO users VALUES ('a', 'x')", "INSERT INTO users (name) VALUES ('a')",
                    "INSERT INTO users (id, name, age) VALUES (1, 'a', 1)"]:
            with self.assertRaises(ExecutionError):
                self.run_sql(sql)
        self.assertFalse(os.path.exists(self.db.path("users")))  # 파일조차 만들지 않았다
        self.assertEqual(self.run_sql("INSERT INTO users VALUES ('a', 1)")[0].message, "1개 행을 추가했습니다 (id=1)")  # id도 안 썼다


if __name__ == "__main__":
    unittest.main()
