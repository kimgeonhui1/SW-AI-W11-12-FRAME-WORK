# [test_bench_server.py] 서버 동시성 벤치마크가 작은 규모에서 올바르게 동작하는지 (기본 규모는 직접 실행: python -m minidb.bench_server)

import contextlib
import io
import unittest

from minidb import bench_server


class BenchServerTest(unittest.TestCase):
    def test_small_run(self):
        lines = []
        report = bench_server.run(rows=300, per_client=5, clients_list=[1, 3], out=lines.append)
        for key in ("select", "insert"):
            self.assertEqual([r["clients"] for r in report[key]], [1, 3])
            for r in report[key]:
                self.assertEqual(r["statuses"], {200: r["clients"] * 5})  # 모든 요청 성공 (빠지거나 중복 없음)
                self.assertGreater(r["rps"], 0)
                self.assertLessEqual(r["p50_ms"], r["p95_ms"])
        self.assertEqual(set(report["workers"]), {1, 8})
        overload = report["overload"]["statuses"]
        self.assertEqual(sum(overload.values()), 90)  # 30명 × 3번, 응답 없이 사라진 요청 없음
        self.assertEqual(set(overload) - {200, 503}, set())  # 성공 아니면 바로 거절. 연결 끊김 · 서버 오류는 없다
        self.assertTrue(any("과부하" in line for line in lines))

    def test_bad_arguments(self):
        for rows, per, clients in [(0, 5, [1]), (10, 0, [1]), (10, 5, []), (10, 5, [0]), (10, 5, [101]), (10, 5, [True])]:
            with self.assertRaises(ValueError, msg=(rows, per, clients)):
                bench_server.run(rows, per, clients, out=lambda *_: None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            bench_server.main(["--clients", "a,b"])
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
