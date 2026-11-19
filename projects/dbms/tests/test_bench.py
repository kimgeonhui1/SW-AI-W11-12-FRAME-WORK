# [test_bench.py] 성능 비교 스크립트가 작은 규모에서 올바르게 동작하는지 (100만 행은 직접 실행: python -m minidb.bench)

import contextlib
import io
import os
import tempfile
import unittest

from minidb import bench


class BenchTest(unittest.TestCase):
    def test_small_run(self):
        lines = []
        result = bench.run(rows=2_500, queries=5, out=lines.append)  # BATCH(1만)보다 적은 행 · 여러 묶음 모두 확인하려고 아래에서 한 번 더
        self.assertTrue(result["correct"])  # 세 방법의 답이 같다
        plans = [r["plan"] for r in result["results"].values()]
        self.assertEqual(plans, ["index", "scan", "scan"])
        self.assertGreaterEqual(result["height"], 2)
        self.assertTrue(any("인덱스 다시 만들기" in line for line in lines))

    def test_multiple_batches_and_keep_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "bench_db")
            original = bench.BATCH
            bench.BATCH = 300  # 묶음 경계(마지막 묶음이 덜 찬 경우)를 작은 규모로 확인
            try:
                result = bench.run(rows=1_000, queries=3, directory=folder, out=lambda *_: None)
            finally:
                bench.BATCH = original
            self.assertTrue(result["correct"])
            with open(os.path.join(folder, "users.jsonl"), encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual((len(lines), lines[0], lines[-1]), (1000, '[1, "user1", 1]', '[1000, "user1000", 0]'))
            with self.assertRaises(ValueError):  # 이미 데이터가 있는 폴더는 받지 않는다 (덮어쓰거나 섞이지 않게)
                bench.run(rows=10, queries=1, directory=folder, out=lambda *_: None)

    def test_bad_arguments(self):
        for rows, queries in [(0, 1), (-5, 1), (True, 1), (1.5, 1), (10, 0), (10, 11), (10, False)]:
            with self.assertRaises(ValueError, msg=(rows, queries)):
                bench.run(rows=rows, queries=queries, out=lambda *_: None)

    def test_main_exit_codes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(bench.main(["--rows", "50", "--queries", "2"]), 0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            bench.main(["--rows", "0"])
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
