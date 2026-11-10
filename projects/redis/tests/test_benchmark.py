# [test_benchmark.py] 성능 비교 스크립트가 올바르게 측정하는지 확인 (숫자 자체가 아니라 측정 방식)

import unittest

from demo import benchmark


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


if __name__ == "__main__":
    unittest.main()
