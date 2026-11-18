# [test_cli.py] 기능 테스트 — SQL 파일을 CLI로 실행했을 때 결과 · 저장 · 종료 코드 · 에러 메시지

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from unittest import mock

from minidb.cli import _width, main
from minidb.executor import Executor

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # projects/dbms


class CliTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.db = os.path.join(self.dir, "db")
        os.makedirs(self.db)
        with open(os.path.join(self.db, "schema.json"), "w", encoding="utf-8") as f:
            json.dump({"users": {"name": "TEXT", "age": "INT"}}, f)

    def sql_file(self, content, encoding="utf-8"):
        path = os.path.join(self.dir, "q.sql")
        with open(path, "w", encoding=encoding) as f:
            f.write(content)
        return path

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def rows_in_file(self):
        path = os.path.join(self.db, "users.jsonl")
        if not os.path.exists(path):
            return 0
        with open(path, encoding="utf-8") as f:
            return len(f.read().splitlines())

    def test_runs_file_and_persists(self):
        path = self.sql_file("INSERT INTO users VALUES ('kim', 25);\nSELECT * FROM users;\n")
        code, out, err = self.run_cli(path, "--db", self.db)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.splitlines(), [
            "1개 행을 추가했습니다",
            "+------+-----+",
            "| name | age |",
            "+------+-----+",
            "| kim  | 25  |",
            "+------+-----+",
            "1개 행",
        ])
        code, out, _ = self.run_cli(path, "--db", self.db)  # 다시 실행 = 프로그램을 껐다 켬
        self.assertEqual(code, 0)
        self.assertIn("2개 행", out)  # 파일에 남아 있던 첫 행 + 새 행

    def test_syntax_error_runs_nothing(self):
        # 3번째 문장에 문법 오류 → 앞의 INSERT 2개도 실행하지 않는다 (먼저 전부 파싱)
        path = self.sql_file("INSERT INTO users VALUES ('a', 1);\nINSERT INTO users VALUES ('b', 2);\nSELEC * FROM users;")
        code, out, err = self.run_cli(path, "--db", self.db)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("문법 오류", err)
        self.assertIn("줄 3, 칸 1", err)
        self.assertEqual(self.rows_in_file(), 0)

    def test_execution_error_stops_there(self):
        path = self.sql_file("INSERT INTO users VALUES ('a', 1);\n\nINSERT INTO users VALUES ('b', 'x');\nINSERT INTO users VALUES ('c', 3);")
        code, out, err = self.run_cli(path, "--db", self.db)
        self.assertEqual(code, 1)
        self.assertIn("2번째 문장, 줄 3", err)
        self.assertEqual(self.rows_in_file(), 1)  # 오류 앞의 문장만 저장, 뒤의 문장은 실행 안 함

    def test_file_problems(self):
        cases = {
            "열 수 없습니다": os.path.join(self.dir, "없는파일.sql"),
            "UTF-8이 아닙니다": self.sql_file("SELECT * FROM users WHERE name = '김'", encoding="cp949"),
        }
        for message, path in cases.items():
            code, _, err = self.run_cli(path, "--db", self.db)
            self.assertEqual(code, 1, message)
            self.assertIn(message, err)
        code, _, err = self.run_cli(self.dir, "--db", self.db)  # 파일 대신 폴더
        self.assertEqual(code, 1)

    def test_missing_schema(self):
        code, _, err = self.run_cli(self.sql_file("SELECT * FROM users"), "--db", self.dir)
        self.assertEqual(code, 1)
        self.assertIn("스키마 오류", err)

    def test_argument_errors_exit_with_1(self):
        # argparse 기본값(2) 대신 이 CLI의 약속대로 실패는 1, --help는 0 (GPT 리뷰)
        self.assertEqual(self.run_cli()[0], 1)
        self.assertEqual(self.run_cli("a.sql", "--nope")[0], 1)
        self.assertEqual(self.run_cli("--help")[0], 0)

    def test_table_aligns_decomposed_and_combining_text(self):
        # 맥에서 온 자모 분리 한글(NFD)과 결합 문자(악센트)가 있어도 표 줄이 맞는다 (Gemini 리뷰)
        nfd = unicodedata.normalize("NFD", "홍길동")
        accent = "q" + chr(0x0301) + "b"  # q́: NFC로도 한 글자로 합쳐지지 않는 조합 → 결합 문자 0칸 계산을 확인
        path = self.sql_file(f"INSERT INTO users VALUES ('{nfd}', 1);\nINSERT INTO users VALUES ('{accent}', 2);\nSELECT * FROM users;")
        _, out, _ = self.run_cli(path, "--db", self.db)
        table = [line for line in out.splitlines() if line[:1] in "+|"]

        def screen_width(text):  # 터미널에 보이는 폭 (모듈의 _width와 따로 계산해야 그 함수의 실수를 잡는다)
            return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)

        self.assertEqual(len({screen_width(unicodedata.normalize("NFC", line)) for line in table}), 1, out)

    def test_ctrl_c_is_reported_without_traceback(self):
        # 실행 중 Ctrl+C → traceback 없이 한 줄 안내와 종료 코드 130. 앞 문장의 INSERT는 저장된 상태로 남는다
        path = self.sql_file("INSERT INTO users VALUES ('a', 1);\nINSERT INTO users VALUES ('b', 2);")
        real = Executor.execute
        calls = []

        def interrupted(executor, stmt):
            calls.append(stmt)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real(executor, stmt)

        with mock.patch.object(Executor, "execute", interrupted):
            code, out, err = self.run_cli(path, "--db", self.db)
        self.assertEqual(code, 130)
        self.assertIn("중단했습니다", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.rows_in_file(), 1)

    def test_bom_file(self):
        path = self.sql_file(chr(0xFEFF) + "SELECT * FROM users")  # 메모장의 "UTF-8 (BOM)" 저장
        self.assertEqual(self.run_cli(path, "--db", self.db)[0], 0)

    def test_empty_file(self):
        self.assertEqual(self.run_cli(self.sql_file("-- 주석만\n"), "--db", self.db), (0, "", ""))

    def test_table_aligns_wide_and_control_characters(self):
        path = self.sql_file("INSERT INTO users VALUES ('홍길동', 1);\nINSERT INTO users VALUES ('a\nb', 22);\nSELECT * FROM users;")
        _, out, _ = self.run_cli(path, "--db", self.db)
        table = [line for line in out.splitlines() if line[:1] in "+|"]
        self.assertEqual(len(table), 6)  # 줄바꿈이 든 값도 표에서는 한 줄 (\n으로 보인다)
        self.assertIn(r"| a\nb   |", out)
        self.assertEqual(len({_width(line) for line in table}), 1)  # 한글이 있어도 모든 줄 너비가 같다

    def test_python_dash_m(self):
        # 실제 명령 "python -m minidb ..."가 동작하는지 (__main__.py 연결)
        path = self.sql_file("INSERT INTO users VALUES ('kim', 1); SELECT name FROM users")
        done = subprocess.run([sys.executable, "-m", "minidb", path, "--db", self.db], cwd=PROJECT,
                              capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("| kim  |", done.stdout)
        bad = subprocess.run([sys.executable, "-m", "minidb", path + ".none", "--db", self.db], cwd=PROJECT,
                             capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
        self.assertEqual(bad.returncode, 1)


if __name__ == "__main__":
    unittest.main()
