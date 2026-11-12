# [test_demo.py] 데모 API(캐시 활용) 기능 테스트 — 실행: projects/redis 에서 python -m unittest
#
# 설계 문서 6 · 10 · 11장의 계획대로 확인한다
#   Cache-Aside : 첫 요청 MISS → 다음 HIT, HIT 가 MISS 보다 빠름, Mini Redis 에 ttl 60초로 저장됨
#   무효화      : PUT 으로 가격을 바꾸면 버전이 올라 다음 GET 이 새 가격, 느린 읽기 도중 수정돼도 옛 값이 캐시에 남지 않음 (버전 키)
#   그 밖       : ?cache=off 는 저장하지 않음, 없는 아이템은 404 · 캐시 안 함, 잘못된 요청 400,
#                 Mini Redis 가 꺼져 있어도 원본으로 응답(BYPASS), 벤치마크 measure
# demo/api_server.py 는 dev 파일을 그대로 쓴다 (create_demo_server · RedisClient · old_cache_deleted 응답)
#
# 실제 Mini Redis 서버와 데모 API 서버를 빈 포트(port=0)에 띄워 HTTP 로 요청한다

import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from demo import api_server
from demo.benchmark import measure
from mini_redis.server import create_server as create_redis_server
from mini_redis.store import MiniRedis


class DemoApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MiniRedis()
        cls.redis = create_redis_server(cls.store, port=0)
        cls.api = api_server.create_demo_server(f"http://127.0.0.1:{cls.redis.server_address[1]}", port=0)
        cls.base = f"http://127.0.0.1:{cls.api.server_address[1]}"
        for server in (cls.redis, cls.api):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.api, cls.redis):
            server.shutdown()
            server.server_close()

    def call(self, method, path, body=None, raw=None):
        """(상태 코드, 응답 JSON, 걸린 초) 를 돌려준다"""
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        start = time.perf_counter()
        try:
            with urlopen(Request(self.base + path, data=data, method=method), timeout=5) as res:
                status, text = res.status, res.read()
        except HTTPError as e:
            with e:  # 오류 응답도 닫는다 (안 닫으면 ResourceWarning)
                status, text = e.code, e.read()
        return status, json.loads(text), time.perf_counter() - start

    # ── Cache-Aside ─────────────────────────────────────────────────

    def test_miss_then_hit_and_hit_is_faster(self):
        status1, body1, miss_time = self.call("GET", "/items/1")
        status2, body2, hit_time = self.call("GET", "/items/1")
        self.assertEqual((status1, body1["cache"], status2, body2["cache"]), (200, "MISS", 200, "HIT"))
        self.assertEqual(body1["item"], body2["item"])
        self.assertGreaterEqual(miss_time, api_server.SLOW_DELAY)  # MISS 는 느린 원본을 거친다
        self.assertLess(hit_time, api_server.SLOW_DELAY)  #          HIT 는 원본을 거치지 않는다

    def test_cached_in_mini_redis_with_ttl(self):
        self.call("GET", "/items/2")
        self.assertEqual(self.store.get("item:2:v1"), {"id": 2, "name": "아이템 2", "price": 200, "version": 1})
        self.assertTrue(0 < self.store.ttl("item:2:v1") <= api_server.CACHE_TTL)

    def test_cache_off_does_not_store(self):
        status, body, _ = self.call("GET", "/items/3?cache=off")
        self.assertEqual((status, body["cache"], body["item"]["id"]), (200, "OFF", 3))
        self.assertFalse(self.store.exists("item:3:v1"))

    # ── 무효화 ──────────────────────────────────────────────────────

    def test_update_invalidates_cache(self):
        self.call("GET", "/items/4")
        self.assertEqual(self.call("GET", "/items/4")[1]["cache"], "HIT")
        status, body, _ = self.call("PUT", "/items/4", {"price": 5})
        self.assertEqual((status, body["item"]["price"], body["item"]["version"], body["old_cache_deleted"]), (200, 5, 2, True))
        self.assertFalse(self.store.exists("item:4:v1"))  # 옛 버전 키는 메모리에서도 정리됨
        _, body, _ = self.call("GET", "/items/4")
        self.assertEqual((body["cache"], body["item"]["price"]), ("MISS", 5))  # 옛 가격 400 이 아니라 새 가격
        self.assertEqual(self.call("GET", "/items/4")[1]["item"]["price"], 5)  # 다시 채워진 캐시(v2)도 새 가격
        self.assertTrue(self.store.exists("item:4:v2"))

    def test_update_during_slow_read_does_not_cache_old_value(self):
        # 버전 키가 막는 경쟁 상태: ① GET 이 원본을 읽고 느리게 도착하는 사이 ② PUT 이 가격을 바꾸면
        # ③ GET 의 옛 데이터는 캐시에 저장되지 않고, 다음 GET 은 새 가격을 받아야 한다
        slow = threading.Thread(target=self.call, args=("GET", "/items/8"))
        slow.start()
        time.sleep(api_server.SLOW_DELAY / 4)  # ① 이 원본을 읽고 기다리는 중
        self.assertEqual(self.call("PUT", "/items/8", {"price": 1})[0], 200)  # ②
        slow.join()  # ③
        self.assertFalse(self.store.exists("item:8:v1"))  # 옛 값(800)은 어떤 키로도 저장되지 않았다
        _, body, _ = self.call("GET", "/items/8")
        self.assertEqual((body["cache"], body["item"]["price"]), ("MISS", 1))
        self.assertEqual(self.call("GET", "/items/8")[1], {"item": body["item"], "cache": "HIT"})

    # ── 잘못된 요청 · 없는 아이템 ───────────────────────────────────

    def test_missing_item_is_404_and_not_cached(self):
        for path in ["/items/999", "/items/999?cache=off"]:
            self.assertEqual(self.call("GET", path)[0], 404, path)
        self.assertEqual(self.call("PUT", "/items/999", {"price": 1})[0], 404)
        self.assertFalse(any(k.startswith("item:999") for k in self.store._data.keys()))

    def test_bad_paths(self):
        for path in ["/", "/items", "/items/abc", "/items/-1", "/items/1/more", "/items/%D9%A1", "/items/%31"]:
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_bad_update_bodies(self):
        # 가격은 유한한 숫자 (dev 와 같음 — 소수 · 음수도 받는다). NaN · 문자열 · 불리언 · 객체가 아닌 본문은 400
        for raw in [b"not json", b"[]", b'"x"', b"{}", b'{"price": NaN}', b'{"price": "5"}', b'{"price": true}', b'{"price": ' + b"9" * 400 + b"}"]:
            self.assertEqual(self.call("PUT", "/items/5", raw=raw)[0], 400, raw)
        self.assertEqual(self.call("GET", "/items/5?cache=off")[1]["item"]["price"], 500)  # 원본은 그대로

    # ── Mini Redis 장애 ─────────────────────────────────────────────

    def test_redis_down_falls_back_to_source(self):
        original = api_server.redis
        api_server.redis = api_server.RedisClient("http://127.0.0.1:1")  # 아무도 듣지 않는 포트 → 연결 실패
        self.addCleanup(setattr, api_server, "redis", original)
        status, body, _ = self.call("GET", "/items/6")
        self.assertEqual((status, body["cache"], body["item"]["id"]), (200, "BYPASS", 6))
        status, body, _ = self.call("PUT", "/items/6", {"price": 7})  # 캐시를 못 지워도 수정은 된다
        self.assertEqual((status, body["old_cache_deleted"]), (200, False))

    # ── 벤치마크 ────────────────────────────────────────────────────

    def test_benchmark_measure(self):
        self.call("GET", "/items/7")  # 캐시를 채워 둔다
        hit_ms = measure(f"{self.base}/items/7", 3)
        off_ms = measure(f"{self.base}/items/7?cache=off", 2)
        self.assertGreater(hit_ms, 0)
        self.assertGreaterEqual(off_ms, api_server.SLOW_DELAY * 1000)
        self.assertLess(hit_ms, off_ms)


if __name__ == "__main__":
    unittest.main()
