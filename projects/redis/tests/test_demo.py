# [test_demo.py] 기능 테스트 — 간단한 API의 응답을 Mini Redis에 캐시해서 활용하는지 확인 (과제 품질 항목)
# Mini Redis 서버와 데모 API 서버를 둘 다 실제로 띄우고, 외부 클라이언트처럼 요청한다

import json
import socket
import threading
import time
import unittest
from urllib.error import HTTPError
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, urlopen

from demo import api_server
from mini_redis.server import create_server
from mini_redis.store import MiniRedis


def start(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}"


class DemoApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_server.SLOW_DELAY = 0.05  # 원본 조회 지연을 줄여 테스트를 빠르게 (그래도 캐시와 차이는 분명하다)
        cls.store = MiniRedis()
        cls.redis_server = create_server(cls.store, port=0)
        redis_url = start(cls.redis_server)
        cls.demo_server = api_server.create_demo_server(redis_url, port=0)
        cls.base = start(cls.demo_server)

    @classmethod
    def tearDownClass(cls):
        for s in (cls.demo_server, cls.redis_server):
            s.shutdown()
            s.server_close()

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = Request(self.base + path, data=data, method=method)
        start_time = time.perf_counter()
        try:
            with urlopen(req) as res:
                status, payload = res.status, json.loads(res.read())
        except HTTPError as e:
            with e:
                status, payload = e.code, json.loads(e.read())
        return status, payload, time.perf_counter() - start_time

    def test_miss_then_hit(self):
        _, first, slow = self.request("GET", "/items/1")
        _, second, fast = self.request("GET", "/items/1")
        self.assertEqual((first["cache"], second["cache"]), ("MISS", "HIT"))
        self.assertEqual(first["item"], second["item"])
        self.assertTrue(self.store.exists("item:1:v1"))  # 응답 값이 실제로 Mini Redis에 (버전 키로) 저장됨
        self.assertLess(fast, slow)  # 캐시 응답이 더 빠르다

    def test_cache_off_always_reads_source(self):
        self.request("GET", "/items/2")  # 캐시에 넣어 두어도
        statuses = [self.request("GET", "/items/2?cache=off")[1]["cache"] for _ in range(2)]
        self.assertEqual(statuses, ["OFF", "OFF"])

    def test_cache_has_ttl(self):
        self.request("GET", "/items/3")
        self.assertGreater(self.store.ttl("item:3:v1"), 0)  # 옛 버전 키도 결국 만료되도록 TTL이 붙어 있다

    def test_update_invalidates_cache(self):
        self.request("GET", "/items/4")  # 캐시에 넣고
        status, body, _ = self.request("PUT", "/items/4", {"price": 9999})
        self.assertEqual((status, body["item"]["version"], body["old_cache_deleted"]), (200, 2, True))
        self.assertFalse(self.store.exists("item:4:v1"))  # 옛 버전 캐시는 메모리에서도 정리됨
        _, after, _ = self.request("GET", "/items/4")
        self.assertEqual((after["cache"], after["item"]["price"]), ("MISS", 9999))  # 옛 가격이 아니라 새 가격
        self.assertEqual(self.request("GET", "/items/4")[1]["cache"], "HIT")  # 새 버전으로 다시 캐시됨

    def test_update_during_slow_miss_does_not_cache_stale_value(self):
        # 경쟁 상태: 느린 조회가 옛 가격을 읽은 뒤 → 그사이 가격 수정 → 조회가 늦게 옛 가격을 캐시에 저장.
        # 버전 키라서 옛 가격은 옛 키(v1)에 들어가고, 이후 요청은 새 가격을 받아야 한다 (자체 검토에서 재현한 버그)
        api_server.SLOW_DELAY = 0.3
        try:
            slow_get = threading.Thread(target=self.request, args=("GET", "/items/10"))
            slow_get.start()
            time.sleep(0.1)  # 조회가 원본을 읽고 기다리는 중
            self.request("PUT", "/items/10", {"price": 5})
            slow_get.join()
            api_server.SLOW_DELAY = 0.05
            _, body, _ = self.request("GET", "/items/10")
            self.assertEqual(body["item"]["price"], 5)
            self.assertFalse(self.store.exists("item:10:v1"))  # 옛 버전 데이터는 캐시에 다시 저장되지도 않음 (리뷰 반영)
        finally:
            api_server.SLOW_DELAY = 0.05

    def test_missing_item_is_not_cached(self):
        before = len(self.store)
        status, _, _ = self.request("GET", "/items/99999")
        self.assertEqual((status, len(self.store)), (404, before))

    def test_bad_requests(self):
        self.assertEqual(self.request("GET", "/items/abc")[0], 404)
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("PUT", "/items/5", {"price": "비쌈"})[0], 400)
        self.assertEqual(self.request("PUT", "/items/5", {})[0], 400)
        self.assertEqual(self.request("PUT", "/items/5", raw=b'{"price": NaN}')[0], 400)  # 자체 검토: 원본에 NaN이 저장되던 것
        self.assertEqual(self.request("PUT", "/items/5", raw=b'{"price": ' + b"9" * 400 + b"}")[0], 400)
        self.assertEqual(self.request("PUT", "/items/99999", {"price": 1})[0], 404)
        # 객체가 아닌 본문, 너무 깊은 중첩 → 400 (리뷰 반영: 깊은 중첩은 500이던 것)
        for raw in [b"123", b'[{"price": 1}]', b'"price"', b"[" * 100000 + b"]" * 100000]:
            self.assertEqual(self.request("PUT", "/items/5", raw=raw)[0], 400, raw[:20])

    def test_non_ascii_digit_path_is_404(self):
        # 원시 바이트 0xB2는 서버가 "²"(위첨자 2)로 읽는다. isdigit은 True지만 int()가 실패해 500이던 것 (리뷰 반영)
        port = self.demo_server.server_address[1]
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(b"GET /items/\xb2 HTTP/1.0\r\n\r\n")
            c.settimeout(5)
            self.assertIn(b" 404 ", c.recv(100))

    def swap_redis(self, client):
        """api_server가 쓰는 Redis 클라이언트를 잠시 바꾸고, 테스트가 끝나면 되돌린다"""
        original = api_server.redis
        api_server.redis = client
        self.addCleanup(setattr, api_server, "redis", original)

    def test_cache_write_failure_still_answers(self):
        # 캐시 조회는 MISS로 성공했는데 저장만 실패 → 원본 값으로 BYPASS 응답 (리뷰 반영)
        class WriteFails(api_server.RedisClient):
            def get(self, key):
                return None

            def set(self, key, value, ttl):
                raise api_server.RedisUnavailable("저장 실패")

        self.swap_redis(WriteFails("http://unused"))
        status, body, _ = self.request("GET", "/items/7")
        self.assertEqual((status, body["cache"], body["item"]["id"]), (200, "BYPASS", 7))

    def test_broken_redis_response_falls_back(self):
        # Mini Redis 자리에서 JSON이 아니거나 약속과 다른 모양을 주는 서버 → 500이 아니라 BYPASS (리뷰 반영)
        for reply in [b"not json", b'{"no_value": 1}', b"[1, 2]"]:
            class Broken(BaseHTTPRequestHandler):
                def do_GET(self, reply=reply):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(reply)))
                    self.end_headers()
                    self.wfile.write(reply)

                def log_message(self, *args):
                    pass

            broken = HTTPServer(("127.0.0.1", 0), Broken)
            threading.Thread(target=broken.serve_forever, daemon=True).start()
            try:
                self.swap_redis(api_server.RedisClient(f"http://127.0.0.1:{broken.server_address[1]}"))
                status, body, _ = self.request("GET", "/items/8")
                self.assertEqual((status, body["cache"]), (200, "BYPASS"), reply)
            finally:
                broken.shutdown()
                broken.server_close()

    def test_redis_down_falls_back_to_source(self):
        # Mini Redis가 꺼져 있어도 API는 원본으로 응답해야 한다 (캐시 장애가 서비스 장애가 되지 않게)
        original, original_timeout = api_server.redis, api_server.REDIS_TIMEOUT
        api_server.redis = api_server.RedisClient("http://127.0.0.1:1")  # 아무도 없는 포트
        api_server.REDIS_TIMEOUT = 0.2  # Windows는 닫힌 포트 연결 실패를 제한 시간까지 기다려서, 테스트에서는 짧게
        try:
            status, body, _ = self.request("GET", "/items/6")
            self.assertEqual((status, body["cache"], body["item"]["id"]), (200, "BYPASS", 6))
            status, body, _ = self.request("PUT", "/items/6", {"price": 1})
            self.assertEqual((status, body["old_cache_deleted"]), (200, False))
        finally:
            api_server.redis, api_server.REDIS_TIMEOUT = original, original_timeout


if __name__ == "__main__":
    unittest.main()
