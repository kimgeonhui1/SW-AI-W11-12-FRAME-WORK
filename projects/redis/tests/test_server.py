# [test_server.py] HTTP API 기능 테스트 — 실제 서버를 띄우고 외부 클라이언트처럼 요청한다

import json
import socket
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mini_redis import server as server_module
from mini_redis.server import create_server
from mini_redis.store import MiniRedis


class _ClosedSocketFile:
    def write(self, data):
        raise BrokenPipeError("클라이언트가 연결을 끊음")


def disconnected_handler(handler_class):
    """소켓 없이 핸들러 객체만 만든다. 응답을 쓰는 순간 BrokenPipeError가 나는 "이미 끊긴 클라이언트" 상황"""
    handler = handler_class.__new__(handler_class)
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET / HTTP/1.1"
    handler.wfile = _ClosedSocketFile()
    handler.close_connection = False
    return handler


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server_module.SWEEP_INTERVAL = 0.05  # 주기 삭제를 빨리 돌려서 테스트 시간을 줄인다
        server_module.REQUEST_TIMEOUT = 0.5  # 본문 수신 제한 시간도 짧게 (408 테스트용)
        cls.store = MiniRedis()
        cls.server = create_server(cls.store, port=0)  # 0 = 빈 포트 자동 선택
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, method, path, body=None, raw=None):
        """외부 클라이언트처럼 요청을 보내고 (상태 코드, JSON 응답)을 돌려준다"""
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urlopen(req) as res:
                return res.status, json.loads(res.read())
        except HTTPError as e:
            with e:  # 에러 응답도 닫아 준다 (안 닫으면 ResourceWarning)
                return e.code, json.loads(e.read())

    # ── 정상 동작 ──

    def test_put_get_delete(self):
        self.assertEqual(self.request("PUT", "/keys/user:1", {"value": {"name": "철수", "lv": 200}}), (200, {"ok": True}))
        self.assertEqual(self.request("GET", "/keys/user:1"), (200, {"key": "user:1", "value": {"name": "철수", "lv": 200}, "ttl": -1}))
        self.assertEqual(self.request("DELETE", "/keys/user:1"), (200, {"deleted": True}))
        self.assertEqual(self.request("GET", "/keys/user:1")[0], 404)
        self.assertEqual(self.request("DELETE", "/keys/user:1"), (200, {"deleted": False}))

    def test_value_types(self):
        # JSON이면 문자열·숫자·불리언·배열·객체 모두 그대로 돌아와야 한다
        for i, value in enumerate(["문자열", 0, 3.14, False, [1, "a"], {"a": [1, 2]}, ""]):
            self.request("PUT", f"/keys/type{i}", {"value": value})
            self.assertEqual(self.request("GET", f"/keys/type{i}")[1]["value"], value, repr(value))

    def test_ttl_and_expire(self):
        self.request("PUT", "/keys/t", {"value": 1, "ttl": 100})
        self.assertEqual(self.request("GET", "/keys/t/ttl"), (200, {"ttl": 100}))
        self.assertEqual(self.request("POST", "/keys/t/expire", {"ttl": 5}), (200, {"ok": True}))
        self.assertEqual(self.request("GET", "/keys/t/ttl"), (200, {"ttl": 5}))
        self.assertEqual(self.request("GET", f"/keys/{quote('없는키')}/ttl"), (200, {"ttl": -2}))
        self.assertEqual(self.request("POST", f"/keys/{quote('없는키')}/expire", {"ttl": 5})[0], 404)

    def test_expired_value_not_returned_and_swept(self):
        self.request("PUT", "/keys/short", {"value": "x", "ttl": 0.1})
        time.sleep(0.3)  # 만료 + 주기 삭제 스레드가 돌 시간
        self.assertFalse(self.store.exists("short"))  # 아무도 안 읽었는데 주기 삭제로 지워짐
        self.assertEqual(self.request("GET", "/keys/short")[0], 404)

    def test_special_characters_in_key(self):
        key = "char:메이플/2024-01-01 ?&#"
        self.request("PUT", "/keys/" + quote(key, safe=""), {"value": 1})
        self.assertEqual(self.request("GET", "/keys/" + quote(key, safe=""))[1]["key"], key)
        self.assertTrue(self.store.exists(key))

    def test_health(self):
        status, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIsInstance(body["keys"], int)

    def test_concurrent_clients(self):
        # 여러 클라이언트가 동시에 요청해도 전부 저장된다 (요청마다 스레드 + 저장소 락)
        def client(t):
            for i in range(20):
                self.request("PUT", f"/keys/c{t}:{i}", {"value": i})

        threads = [threading.Thread(target=client, args=(t,)) for t in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertTrue(all(self.store.get(f"c{t}:{i}") == i for t in range(5) for i in range(20)))

    # ── 잘못된 요청 ──

    def test_bad_bodies(self):
        cases = [
            (b"{not json", 400),  # JSON 아님
            (b"[1]", 400),  # 객체가 아님
            (json.dumps({"ttl": 5}).encode(), 400),  # value 없음
            (json.dumps({"value": None}).encode(), 400),  # null은 저장 불가
            (json.dumps({"value": 1, "ttl": -1}).encode(), 400),
            (json.dumps({"value": 1, "ttl": "5"}).encode(), 400),
            (json.dumps({"value": 1, "ttl": 0.0001}).encode(), 400),  # 최소 1ms 미만
            ("한글".encode("cp949"), 400),  # UTF-8이 아닌 본문
            (('{"value": ' + "[" * 100000 + "]" * 100000 + "}").encode(), 400),  # 너무 깊은 중첩 (500이던 것, 리뷰 반영)
            (b'{"value": "\\ud800"}', 400),  # 짝 없는 반쪽 문자 (저장되면 이후 GET이 응답 없이 끊기던 것, 리뷰 반영)
            # 자체 검토에서 찾은 것
            (('{"value": 1, "ttl": ' + "9" * 400 + "}").encode(), 400),  # float로 못 바꾸는 큰 정수 (500이던 것)
            (b'{"value": NaN}', 400),  # 표준 JSON이 아님 (저장 후 응답이 NaN으로 나가던 것)
            (b'{"value": [1, Infinity]}', 400),
            (b'{"value": 1, "ttl": -Infinity}', 400),
        ]
        for raw, status in cases:
            self.assertEqual(self.request("PUT", "/keys/bad", raw=raw)[0], status, raw)
        self.assertFalse(self.store.exists("bad"))
        self.assertEqual(self.request("POST", "/keys/bad/expire", {})[0], 400)  # ttl 없음

    def test_bad_paths_and_methods(self):
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("GET", "/keys/")[0], 404)  # 빈 키
        self.assertEqual(self.request("GET", "/keys/a/b/c")[0], 404)
        self.assertEqual(self.request("GET", "/keys/a/unknown")[0], 404)
        self.assertEqual(self.request("POST", "/keys/a")[0], 405)
        self.assertEqual(self.request("PUT", "/keys/a/ttl", {})[0], 405)
        self.assertEqual(self.request("GET", "/keys/a/expire")[0], 405)
        self.assertEqual(self.request("DELETE", "/health")[0], 405)
        # 표준 라이브러리 기본값이면 HTML 501이던 메서드도 JSON 405로 (자체 검토)
        for method in ["PATCH", "OPTIONS"]:
            status, body = self.request(method, "/keys/a")
            self.assertEqual((status, "error" in body), (405, True), method)

    def test_slow_client_gets_408_and_does_not_hang(self):
        # Content-Length보다 적게 보내고 멈춘 클라이언트 → 제한 시간 뒤 408로 끝나야 한다 (전에는 스레드가 영원히 대기)
        port = self.server.server_address[1]
        with socket.create_connection(("127.0.0.1", port)) as c:
            c.sendall(b"PUT /keys/slow HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{")
            c.settimeout(5)
            self.assertIn(b" 408 ", c.recv(200))

    def test_response_survives_unencodable_value(self):
        # 파이썬 코드로 저장소에 직접 넣은 반쪽 문자도, 응답은 끊기지 않고 \uXXXX 형태의 올바른 JSON으로 나가야 한다
        self.store.set("raw", "\ud800")
        self.assertEqual(self.request("GET", "/keys/raw"), (200, {"key": "raw", "value": "\ud800", "ttl": -1}))

    def test_second_server_on_same_port_fails(self):
        # Windows에서 같은 포트로 서버가 두 개 떠서 요청이 어디로 갈지 모르던 문제 → 두 번째는 OSError로 실패해야 한다
        port = self.server.server_address[1]
        with self.assertRaises(OSError):
            create_server(MiniRedis(), port=port)

    def test_send_to_disconnected_client_is_quiet(self):
        # 클라이언트가 응답 전에 끊어도 _send가 예외를 밖으로 던지지 않고 연결만 정리해야 한다 (리눅스에서 traceback이 찍히던 것)
        handler = disconnected_handler(server_module.make_handler(self.store))
        handler._send(200, {"ok": True})
        self.assertTrue(handler.close_connection)

    def test_body_too_large(self):
        raw = json.dumps({"value": "x" * (server_module.MAX_BODY + 1)}).encode()
        self.assertEqual(self.request("PUT", "/keys/big", raw=raw)[0], 413)


if __name__ == "__main__":
    unittest.main()
