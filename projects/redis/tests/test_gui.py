# [test_gui.py] 테스트 GUI 실행기(tests/gui.py) 테스트 — 실행: projects/redis 에서 python -m unittest
#
# 확인하는 것
#   - GET / · /gui 에서 gui.html 이 HTML 로 나온다 (캐시 안 함)
#   - 그 밖의 경로(/keys/... · /health)는 실제 Mini Redis 서버와 똑같이 동작한다 → 화면이 진짜 서버를 시험한다
#   - 화면이 기대하는 오류 문구가 서버 문구와 같다 (서버 문구를 바꾸고 화면을 안 고치는 일을 막는다)

import http.client
import json
import re
import threading
import unittest

from mini_redis.store import MiniRedis
from tests.gui import PAGE, create_gui_server


class GuiServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MiniRedis()
        cls.server = create_gui_server(cls.store, port=0)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body)
            res = conn.getresponse()
            return res.status, dict(res.getheaders()), res.read()
        finally:
            conn.close()

    def test_page_served_at_root(self):
        for path in ["/", "/gui", "/?x=1"]:
            status, headers, data = self.request("GET", path)
            self.assertEqual((status, headers["Content-Type"], headers["Cache-Control"]), (200, "text/html; charset=utf-8", "no-store"), path)
            self.assertEqual(data, PAGE.read_bytes())

    def test_api_still_works(self):
        # 화면과 같은 출처의 API 가 실제 서버와 똑같이 동작한다
        self.assertEqual(self.request("PUT", "/keys/a", b'{"value": 1, "ttl": 60}')[0], 200)
        status, _, data = self.request("GET", "/keys/a")
        self.assertEqual((status, json.loads(data)), (200, {"key": "a", "value": 1, "ttl": 60}))
        status, _, data = self.request("GET", "/health")
        self.assertEqual((status, json.loads(data)), (200, {"keys": 1}))
        status, _, data = self.request("POST", "/keys/a")
        self.assertEqual((status, json.loads(data)), (405, {"error": "GET / PUT / DELETE만 지원합니다"}))

    def test_page_messages_match_server(self):
        # 화면의 자동 시나리오가 기대하는 오류 문구가 서버 코드에 실제로 있어야 한다
        page = PAGE.read_text(encoding="utf-8")
        root = PAGE.parent.parent  # projects/redis
        server_src = (root / "mini_redis/server.py").read_text(encoding="utf-8") + (root / "mini_redis/store.py").read_text(encoding="utf-8")
        expected = set(re.findall(r'\{ error: "([^"]+)" \}', page))
        expected |= set(re.findall(r'\["[A-Z]+", "/[^"]*", "([^"]+)"\]', page))  # 405 표의 문구
        self.assertGreater(len(expected), 5)
        for message in expected:
            # store 의 ttl 문구는 f-string 이라 {MIN_TTL} 을 실제 값으로 바꿔 비교한다
            self.assertTrue(message in server_src or message.replace("0.001", "{MIN_TTL}") in server_src, message)


if __name__ == "__main__":
    unittest.main()
