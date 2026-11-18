# [test_tokenizer.py] SQL 문자열 → 토큰 목록이 맞게 잘리는지, 잘못된 입력을 위치와 함께 알려 주는지

import time
import unittest

from minidb.tokenizer import INT_MAX, INT_MIN, SqlSyntaxError, tokenize


def kinds_values(sql):
    return [(t.kind, t.value) for t in tokenize(sql)]


class TokenizerTest(unittest.TestCase):
    def test_basic_select(self):
        self.assertEqual(kinds_values("SELECT name FROM users WHERE age = 25;"), [
            ("KEYWORD", "SELECT"), ("NAME", "name"), ("KEYWORD", "FROM"), ("NAME", "users"),
            ("KEYWORD", "WHERE"), ("NAME", "age"), ("SYMBOL", "="), ("INT", 25), ("SYMBOL", ";"), ("EOF", None)])

    def test_keywords_ignore_case_names_keep_case(self):
        self.assertEqual(kinds_values("select Users")[:2], [("KEYWORD", "SELECT"), ("NAME", "Users")])

    def test_strings(self):
        cases = {
            "'it''s'": "it's",  # 따옴표 두 번 = 따옴표 하나
            "''": "",  # 빈 문자열
            "''''": "'",
            "'a, b; -- c'": "a, b; -- c",  # 문자열 안의 쉼표·세미콜론·주석 기호는 그냥 글자
            "'줄\n바꿈'": "줄\n바꿈",
            "'홍길동'": "홍길동",
        }
        for sql, expected in cases.items():
            self.assertEqual(kinds_values(sql)[0], ("STRING", expected), sql)

    def test_comments_and_whitespace_are_skipped(self):
        sql = "-- 맨 앞 주석\nSELECT\t*\u3000FROM t -- 끝 주석 (줄바꿈 없이 파일 끝)"
        self.assertEqual([v for _, v in kinds_values(sql)], ["SELECT", "*", "FROM", "t", None])

    def test_integers(self):
        self.assertEqual(kinds_values("-5 0 007")[:3], [("INT", -5), ("INT", 0), ("INT", 7)])
        self.assertEqual(tokenize(str(INT_MAX))[0].value, INT_MAX)
        self.assertEqual(tokenize(str(INT_MIN))[0].value, INT_MIN)
        self.assertEqual(tokenize("0" * 30 + "1")[0].value, 1)  # 앞의 0은 자릿수에 넣지 않는다

    def test_long_strings_are_fast(self):
        # 글자마다 선택지를 고르던 예전 정규식은 10MB 문자열에 약 10초 걸렸다 (자체 점검). 닫히지 않은 긴 문자열도 빨리 거절해야 한다
        start = time.perf_counter()
        self.assertEqual(len(tokenize("'" + "a''" * 300_000 + "'")[0].value), 600_000)
        for unclosed in ["'" + "a" * 1_000_000, "'a" + "''" * 300_000, "'" * 300_001]:
            with self.assertRaises(SqlSyntaxError):
                tokenize(unclosed)
        self.assertLess(time.perf_counter() - start, 1.0)

    def test_double_dash_is_comment_not_negative(self):
        self.assertEqual(kinds_values("--5"), [("EOF", None)])

    def test_empty_input(self):
        self.assertEqual(kinds_values(""), [("EOF", None)])
        self.assertEqual(kinds_values("  \n -- 주석만\n"), [("EOF", None)])

    def test_line_and_column(self):
        tokens = tokenize("SELECT\n  'a\nb' x")
        self.assertEqual((tokens[1].line, tokens[1].col), (2, 3))  # 문자열은 시작 위치
        self.assertEqual((tokens[2].line, tokens[2].col), (3, 4))  # 여러 줄 문자열 안의 줄바꿈도 센다

    def test_crlf_line_numbers(self):
        # 파일은 텍스트 모드로 읽어 \r\n이 \n이 되지만, 문자열로 직접 받아도(Phase 3 API) \r은 공백으로 넘어간다
        x = tokenize("SELECT\r\nx")[1]
        self.assertEqual((x.value, x.line, x.col), ("x", 2, 1))

    def test_errors_with_position(self):
        cases = {
            "SELECT\n  @": (2, 3),  # 알 수 없는 문자
            'SELECT "name"': (1, 8),  # 큰따옴표는 지원 안 함
            "SELECT 'abc": (1, 8),  # 닫히지 않은 문자열 → 여는 따옴표 위치
            "SELECT 'abc''": (1, 8),  # 마지막 ''는 따옴표 글자 → 결국 안 닫힘. 위치는 여는 따옴표 (전에는 칸 13, Gemini 리뷰)
            "SELECT 'a\nb''c": (1, 8),  # 여러 줄 문자열도 시작 위치
            "VALUES ('kim', 25abc)": (1, 16),  # 숫자에 붙은 글자: 숫자 시작 위치에서 "잘못된 숫자" (전에는 abc 위치의 엉뚱한 에러)
            "WHERE a = 0x10": (1, 11),
            "WHERE a = 1e5": (1, 11),
            "WHERE a = 1.2.3": (1, 11),
            "VALUES (3.5)": (1, 9),  # 소수
            "VALUES (1.)": (1, 9),
            f"VALUES ({INT_MAX + 1})": (1, 9),  # 64비트 범위 밖
            f"VALUES ({INT_MIN - 1})": (1, 9),
            "VALUES (" + "9" * 5000 + ")": (1, 9),  # int()의 4300자리 제한에 걸리기 전에 범위 오류로
            "VALUES (\uff11)": (1, 9),  # 전각 숫자 \uff11은 숫자로 보지 않는다
            "- 5": (1, 1),
        }
        for sql, (line, col) in cases.items():
            with self.assertRaises(SqlSyntaxError, msg=sql[:40]) as ctx:
                tokenize(sql)
            self.assertEqual((ctx.exception.line, ctx.exception.col), (line, col), sql[:40])
            self.assertIn(f"줄 {line}, 칸 {col}", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
