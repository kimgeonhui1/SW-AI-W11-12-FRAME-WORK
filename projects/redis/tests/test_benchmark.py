# [test_benchmark.py] 성능 비교 스크립트가 올바르게 측정하는지 확인 (숫자 자체가 아니라 측정 방식)

import unittest

from demo import api_server, benchmark


class BenchmarkTest(unittest.TestCase):
    def test_cache_is_faster_and_all_hits(self):
        without_cache, with_cache = benchmark.run(n=5, delay=0.05)
        # 측정 구간이 의도대로인지: 미사용은 전부 OFF, 사용은 전부 HIT여야 공정한 비교다
        self.assertEqual((without_cache["cache"], with_cache["cache"]), ("OFF", "HIT"))
        self.assertGreaterEqual(without_cache["avg"], 50)  # 원본 지연 50ms가 매번 들어감
        self.assertLess(with_cache["avg"], without_cache["avg"])
        for r in (without_cache, with_cache):
            self.assertTrue(r["min"] <= r["p50"] <= r["p95"] <= r["max"])

    def test_invalid_n(self):
        with self.assertRaises(ValueError):
            benchmark.measure("http://127.0.0.1:1", 0)

    def test_invalid_args_rejected_before_servers_start(self):
        for n, delay in [(0, 0.1), (True, 0.1), (1.5, 0.1), (1, -1), (1, float("nan")), (1, float("inf")), (1, True)]:
            with self.assertRaises(ValueError, msg=(n, delay)):
                benchmark.run(n, delay)

    def test_run_restores_slow_delay(self):
        # run이 바꾼 원본 지연 시간이 같은 프로세스의 다른 코드(데모 테스트 등)에 남지 않아야 한다
        before = api_server.SLOW_DELAY
        benchmark.run(n=1, delay=0.01)
        self.assertEqual(api_server.SLOW_DELAY, before)


if __name__ == "__main__":
    unittest.main()
