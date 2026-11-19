# [test_parser.py] 토큰 → 문장 객체(Insert/Select)로 바르게 구조화하는지, 문법 오류를 위치와 함께 알려 주는지

import unittest

from minidb.parser import Insert, Select, parse
from minidb.tokenizer import SqlSyntaxError


class ParserTest(unittest.TestCase):
    def test_insert(self):
        self.assertEqual(parse("INSERT INTO users (name, age) VALUES ('kim', 25);"),
                         [Insert("users", ["name", "age"], ["kim", 25], 1)])
        self.assertEqual(parse("INSERT INTO users VALUES ('kim', -1)"), [Insert("users", None, ["kim", -1], 1)])

    def test_select(self):
        self.assertEqual(parse("SELECT * FROM users"), [Select("users", None, None, 1)])
        self.assertEqual(parse("SELECT name, age FROM users WHERE name = 'kim'"),
                         [Select("users", ["name", "age"], ("name", "kim"), 1)])

    def test_multiple_statements(self):
        sql = """
            INSERT INTO t VALUES (1);;
            ;
            SELECT * FROM t;
            SELECT a FROM t
        """
        result = parse(sql)
        self.assertEqual([type(s).__name__ for s in result], ["Insert", "Select", "Select"])
        self.assertEqual([s.line for s in result], [2, 4, 5])  # 각 문장이 시작한 줄

    def test_empty_script(self):
        self.assertEqual(parse(""), [])
        self.assertEqual(parse(";; -- 주석만"), [])

    def test_syntax_errors(self):
        cases = {
            "SELECT * FROM a SELECT * FROM b": (1, 17),  # 문장 사이 ; 없음
            "DROP TABLE users": (1, 1),  # 지원하지 않는 문장
            "SELECT * users": (1, 10),  # FROM 없음
            "SELECT FROM users": (1, 8),  # 컬럼 없음
            "SELECT name, FROM users": (1, 14),  # 쉼표 뒤 컬럼 없음
            "SELECT * FROM": (1, 14),  # 테이블 없음 → 파일 끝
            "SELECT * FROM from": (1, 15),  # 키워드는 이름으로 못 씀
            "SELECT * FROM users WHERE": (1, 26),
            "SELECT * FROM users WHERE age 25": (1, 31),  # = 없음
            "SELECT * FROM users WHERE age = name": (1, 33),  # 값 자리에 이름
            "SELECT * FROM users extra": (1, 21),  # 뒤에 남은 토큰
            "INSERT users VALUES (1)": (1, 8),  # INTO 없음
            "INSERT INTO users VALUES ()": (1, 27),  # 빈 값 목록
            "INSERT INTO users () VALUES (1)": (1, 20),  # 빈 컬럼 목록
            "INSERT INTO users VALUES (1, )": (1, 30),
            "INSERT INTO users VALUES (1": (1, 28),  # 닫는 괄호 없음
            "INSERT INTO users (a VALUES (1)": (1, 22),
            "INSERT INTO users VALUES 1": (1, 26),
            "SELECT *\nFROM t\nWHERE x = 1 y": (3, 13),
        }
        for sql, (line, col) in cases.items():
            with self.assertRaises(SqlSyntaxError, msg=sql) as ctx:
                parse(sql)
            self.assertEqual((ctx.exception.line, ctx.exception.col), (line, col), sql)

    def test_error_message_names_what_was_found(self):
        with self.assertRaises(SqlSyntaxError) as ctx:
            parse("SELECT * FROM")
        self.assertIn("파일 끝", str(ctx.exception))
        with self.assertRaises(SqlSyntaxError) as ctx:
            parse("DROP TABLE users")
        self.assertIn("DROP", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
