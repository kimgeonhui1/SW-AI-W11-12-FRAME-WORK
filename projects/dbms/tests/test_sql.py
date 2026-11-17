# [test_sql.py] 토크나이저 · 파서 — SQL 글자가 올바른 구조가 되는지, 틀리면 위치가 맞는 오류가 나는지
#
# 실행: projects/dbms 에서  python -m unittest

import unittest

from mini_dbms.errors import SqlError
from mini_dbms.nodes import Condition, Insert, Select
from mini_dbms.parser import parse, parse_script
from mini_dbms.tokenizer import tokenize


def kinds(sql):
    return [(t.kind, t.value) for t in tokenize(sql)]


def error_of(fn, *args):
    """fn 이 던진 SqlError → (메시지, 줄, 칸)"""
    try:
        fn(*args)
    except SqlError as e:
        return e.message, e.line, e.col
    raise AssertionError("SqlError 가 나지 않았습니다")


class TokenizerTest(unittest.TestCase):
    def test_kinds_and_case(self):
        self.assertEqual(
            kinds("select Name FROM Users where AGE >= -5 and x <> 1.5;"),
            [("KEYWORD", "SELECT"), ("IDENT", "name"), ("KEYWORD", "FROM"), ("IDENT", "users"), ("KEYWORD", "WHERE"),
             ("IDENT", "age"), ("SYM", ">="), ("INT", -5), ("KEYWORD", "AND"), ("IDENT", "x"), ("SYM", "<>"), ("FLOAT", 1.5), ("SYM", ";")],
        )

    def test_strings_comments_and_positions(self):
        sql = "-- 주석\nSELECT 'O''Brien', '줄\n바꿈' /* 여러\n줄 */ ,'끝'"
        toks = list(tokenize(sql))
        self.assertEqual([(t.kind, t.value) for t in toks], [("KEYWORD", "SELECT"), ("STRING", "O'Brien"), ("SYM", ","), ("STRING", "줄\n바꿈"), ("SYM", ","), ("STRING", "끝")])
        self.assertEqual([(t.line, t.col) for t in toks], [(2, 1), (2, 8), (2, 18), (2, 20), (4, 6), (4, 7)])  # 문자열 · 주석 안의 줄바꿈도 센다

    def test_errors_with_position(self):
        self.assertEqual(error_of(list, tokenize("SELECT\n  'abc")), ("문자열이 닫히지 않았습니다 (끝의 ' 가 없음)", 2, 3))
        self.assertEqual(error_of(list, tokenize("SELECT /* 열림")), ("주석이 닫히지 않았습니다 (끝의 */ 가 없음)", 1, 8))
        self.assertEqual(error_of(list, tokenize("SELECT @")), ("알 수 없는 글자 '@'", 1, 8))
        self.assertIn("정수가 너무 큽니다", error_of(list, tokenize(str(2**63)))[0])
        self.assertEqual(kinds(str(2**63 - 1)), [("INT", 2**63 - 1)])  # 64비트 최댓값은 된다
        self.assertIn("소수가 너무 큽니다", error_of(list, tokenize("1" * 400 + ".0"))[0])
        self.assertIn("이름이 너무 깁니다", error_of(list, tokenize("a" * 65))[0])

    def test_lazy(self):
        # 앞의 토큰은 뒤쪽 오류와 상관없이 먼저 나온다 (문장 하나씩 실행하는 바탕)
        it = tokenize("SELECT @")
        self.assertEqual(next(it).value, "SELECT")


class ParserTest(unittest.TestCase):
    def test_insert_forms(self):
        (a, b) = parse("INSERT INTO users (name, age) VALUES ('kim', 25), ('lee', NULL); insert into products values ('x', 1.5)")
        self.assertEqual((a.table, a.columns, a.rows), ("users", ["name", "age"], [["kim", 25], ["lee", None]]))
        self.assertEqual((b.table, b.columns, b.rows), ("products", None, [["x", 1.5]]))
        self.assertIsInstance(a, Insert)

    def test_select_forms(self):
        s = parse("SELECT name, age FROM users WHERE id >= 10 AND age <> 3 AND name = 'k' ORDER BY age DESC LIMIT 5")[0]
        self.assertIsInstance(s, Select)
        self.assertEqual((s.table, s.columns, s.order_by, s.limit, s.explain), ("users", ["name", "age"], ("age", True), 5, False))
        self.assertEqual([(c.column, c.op, c.value) for c in s.where], [("id", ">=", 10), ("age", "!=", 3), ("name", "=", "k")])
        star = parse("EXPLAIN SELECT * FROM users ORDER BY id ASC")[0]
        self.assertEqual((star.columns, star.where, star.order_by, star.explain), (None, [], ("id", False), True))

    def test_statements_and_empty(self):
        self.assertEqual(parse(""), [])
        self.assertEqual(parse(";;  -- 주석만\n/* */;"), [])
        self.assertEqual(len(parse("SELECT * FROM a; SELECT * FROM b")), 2)  # 마지막 ; 는 없어도 된다
        self.assertEqual(parse("SELECT * FROM a;")[0].where, [])

    def test_statement_position(self):
        s = parse("\n\n   SELECT * FROM t WHERE x = 1")[0]
        self.assertEqual((s.line, s.col), (3, 4))
        self.assertEqual(s.where[0], Condition("x", "=", 1, 3, 26))  # "   SELECT * FROM t WHERE " 25글자 뒤

    def test_errors(self):
        cases = [
            ("UPDATE users SET a = 1", "'update' 로 시작하는 문장은 지원하지 않습니다 (INSERT · SELECT 만)", 1, 1),
            ("SELECT FROM users", "'FROM' 는 예약어라 이름으로 쓸 수 없습니다", 1, 8),
            ("SELECT * users", "'FROM' 가 와야 하는데 'users' 이(가) 있습니다", 1, 10),
            ("SELECT * FROM", "이름이 와야 하는데 문장 끝 이(가) 있습니다", 1, 10),
            ("SELECT * FROM t WHERE a 1", "비교 연산자(= != <> < <= > >=)가 와야 하는데 1 이(가) 있습니다", 1, 25),
            ("SELECT * FROM t WHERE a = b", "값(숫자 · '문자열' · NULL)이 와야 하는데 'b' 이(가) 있습니다", 1, 27),
            ("SELECT * FROM t LIMIT -1", "LIMIT 은 0 이상이어야 합니다", 1, 23),
            ("SELECT * FROM t LIMIT 'a'", "정수가 와야 하는데 문자열 'a' 이(가) 있습니다", 1, 23),
            ("INSERT INTO t VALUES ()", "값(숫자 · '문자열' · NULL)이 와야 하는데 ')' 이(가) 있습니다", 1, 23),
            ("INSERT INTO t VALUES (1, 2", "')' 가 와야 하는데 문장 끝 이(가) 있습니다", 1, 26),
            ("INSERT INTO t (a VALUES (1)", "')' 가 와야 하는데 VALUES 이(가) 있습니다", 1, 18),
            ("SELECT * FROM t\nINSERT INTO t VALUES (1)", "문장이 끝나야 하는데 INSERT 이(가) 있습니다 (';' 를 빠뜨렸나요?)", 2, 1),
        ]
        for sql, message, line, col in cases:
            self.assertEqual(error_of(parse, sql), (message, line, col), sql)

    def test_later_error_after_earlier_statement(self):
        # 문장을 하나씩 만든다 → 앞 문장은 뒤 문장의 오류와 상관없이 먼저 나온다
        it = parse_script("SELECT * FROM a; SELEC * FROM b")
        self.assertEqual(next(it).table, "a")
        self.assertRaises(SqlError, next, it)


if __name__ == "__main__":
    unittest.main()
