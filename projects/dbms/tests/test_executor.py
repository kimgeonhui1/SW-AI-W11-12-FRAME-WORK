# [test_executor.py] 파싱된 문장이 스키마 검사를 거쳐 파일에 저장 · 조회되는지 (파서 + 실행기 + 저장소 연결)

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
        self.ex = Executor(self.db)

    def run_sql(self, sql):
        return [self.ex.execute(stmt) for stmt in parse(sql)]

    def select(self, sql):
        result = self.run_sql(sql)[-1]
        return result.columns, result.rows

    def test_insert_then_select(self):
        self.run_sql("""
            INSERT INTO users (name, age) VALUES ('kim', 25);
            INSERT INTO users VALUES ('lee', 30);
            INSERT INTO users (age, name) VALUES (25, 'park');
        """)
        self.assertEqual(self.select("SELECT * FROM users"),
                         (["name", "age"], [["kim", 25], ["lee", 30], ["park", 25]]))  # 넣은 순서대로
        self.assertEqual(self.select("SELECT name FROM users WHERE age = 25"), (["name"], [["kim"], ["park"]]))
        self.assertEqual(self.select("SELECT age, name, age FROM users WHERE name = 'lee'"),
                         (["age", "name", "age"], [[30, "lee", 30]]))  # 순서 바꾸기, 같은 컬럼 두 번도 된다

    def test_column_order_in_file_follows_schema(self):
        self.run_sql("INSERT INTO users (age, name) VALUES (7, 'a')")
        with open(self.db.path("users"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '["a", 7]\n')

    def test_results(self):
        insert, select = self.run_sql("INSERT INTO users VALUES ('a', 1); SELECT * FROM users WHERE age = 2")
        self.assertEqual(insert.message, "1개 행을 추가했습니다")
        self.assertEqual((select.rows, select.message), ([], "0개 행"))

    def test_select_from_table_never_inserted(self):
        self.assertEqual(self.select("SELECT * FROM empty"), (["x"], []))

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
        ]
        for sql in cases:
            with self.assertRaises(ExecutionError, msg=sql):
                self.run_sql(sql)

    def test_failed_insert_writes_nothing(self):
        for sql in ["INSERT INTO users VALUES ('a', 'x')", "INSERT INTO users (name) VALUES ('a')"]:
            with self.assertRaises(ExecutionError):
                self.run_sql(sql)
        self.assertFalse(os.path.exists(self.db.path("users")))  # 파일조차 만들지 않았다


if __name__ == "__main__":
    unittest.main()
