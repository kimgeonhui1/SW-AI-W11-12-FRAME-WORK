# [test_cli.py] Phase 1 기능 테스트 — 실제 명령(python -m mini_dbms)을 실행해 출력 · 종료 코드를 확인한다
#
# examples/phase1.sql 의 출력은 examples/phase1.expected 와 글자 하나까지 같아야 한다 (--no-timing 으로 시간은 숨김).

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests.helpers import make_data_dir

ROOT = Path(__file__).resolve().parent.parent  # projects/dbms


def cli(*args, stdin=None):
    p = subprocess.run([sys.executable, "-m", "mini_dbms", *args], cwd=ROOT, input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return p.returncode, p.stdout, p.stderr


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = make_data_dir(self, {})
        for schema in (ROOT / "data").glob("*.schema.json"):  # 저장소의 스키마를 임시 폴더로 (저장소 data/ 는 건드리지 않음)
            shutil.copy(schema, self.dir)

    def test_example_file_matches_expected_output(self):
        code, out, err = cli("--data", str(self.dir), "--no-timing", "examples/phase1.sql")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, (ROOT / "examples/phase1.expected").read_text(encoding="utf-8"))

    def test_execute_option_and_json_format(self):
        cli("--data", str(self.dir), "-e", "INSERT INTO users (name, age) VALUES ('kim', 25)")
        code, out, _ = cli("--data", str(self.dir), "--format", "json", "--no-timing", "-e", "SELECT name FROM users WHERE id = 1")
        self.assertEqual(code, 0)
        self.assertIn('"rows": [["kim"]]', out)
        self.assertIn('"plan": "index-eq (id = 1)"', out)

    def test_sql_error_exit_code_and_message(self):
        code, out, err = cli("--data", str(self.dir), "-e", "INSERT INTO users (name) VALUES ('a');\nSELECT * FROM users WHERE age = 'x'")
        self.assertEqual(code, 1)
        self.assertIn("INSERT users 1행", out)  # 앞 문장은 실행됨
        self.assertEqual(err.strip(), "오류 (2번째 문장) 2번째 줄 27칸: 열 'age'(INT) 을 문자열 값 'x' 과 비교할 수 없습니다")

    def test_file_and_data_problems_exit_2(self):
        self.assertEqual(cli("--data", str(self.dir), "없는파일.sql")[0], 2)
        self.assertEqual(cli("--data", str(self.dir / "없음"), "-e", "SELECT * FROM users")[0], 2)

    def test_repl(self):
        code, out, _ = cli("--data", str(self.dir), "--no-timing", stdin="INSERT INTO users (name)\nVALUES ('a');\nSELECT nope FROM users;\nSELECT name FROM users;\nexit\n")
        self.assertEqual(code, 0)
        self.assertIn("INSERT users 1행 (id 1)", out)
        self.assertIn("| a    |", out)  # 오류가 난 뒤에도 계속 받는다


if __name__ == "__main__":
    unittest.main()
