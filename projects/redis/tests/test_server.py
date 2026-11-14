# [test_server.py] HTTP JSON API 기능 테스트 — 실행: projects/redis 에서 python -m unittest
#
# 설계 문서 8 · 10장의 계획대로 확인한다
#   경로 표   : GET · PUT · DELETE /keys/{key}, GET /keys/{key}/ttl, POST /keys/{key}/expire 의 성공 · 실패 상태 코드
#   입력 검사 : 잘못된 JSON · NaN · 너무 깊은 중첩 · 짝 없는 반쪽 문자 · 객체가 아닌 본문 · null 값 · 잘못된 ttl · Content-Length 없음 · 1MB 초과 · 보내다 멈춘 클라이언트(408)
#   키        : 한글 · "/" 가 든 키(URL 인코딩), 빈 키
#   그 밖     : GET 응답의 ttl · 소수 ttl, /health, 405(PATCH · OPTIONS 포함) · 404 경로, 500 뒤에도 서버가 계속 동작, 주기 삭제, 여러 스레드 동시 요청
#   연결      : HTTP/1.1 연결 재사용(keep-alive), 본문을 읽지 않은 응답 뒤에는 연결을 닫음
#
# 실제 서버를 빈 포트(port=0)에 띄우고 http.client 로 요청한다 (헤더 · 본문을 마음대로 만들 수 있게)

import http.client
import json
import socket
import threading
import time
import unittest
from unittest import mock
from urllib.parse import quote

from mini_redis import server as server_module
from mini_redis.server import create_server
from mini_redis.store import MiniRedis


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = MiniRedis()
        cls.server = create_server(cls.store, port=0)  # 0 = 빈 포트 자동 선택
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def raw(self, method, path, body=None, headers=None):
        """요청을 보내고 (상태 코드, 응답 본문 dict) 를 돌려준다. body 는 bytes 그대로 보낸다"""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            res = conn.getresponse()
            self.assertEqual(res.getheader("Content-Type"), "application/json; charset=utf-8")
            return res.status, json.loads(res.read())  # 모든 응답(오류 포함)이 올바른 JSON 이어야 한다
        finally:
            conn.close()

    def request(self, method, key_path, body=None):
        """key_path 는 "/keys/" 뒤 부분. body 가 있으면 JSON 으로 보낸다"""
        data = None if body is None else json.dumps(body).encode()
        return self.raw(method, "/keys/" + key_path, data)

    # ── 경로 표 ──────────────────────────────────────────────────────

    def test_put_get_delete(self):
        self.assertEqual(self.request("PUT", "user:1", {"value": {"name": "철수", "lv": 200}}), (200, {"ok": True}))
        self.assertEqual(self.request("GET", "user:1"), (200, {"key": "user:1", "value": {"name": "철수", "lv": 200}, "ttl": -1}))
        self.assertEqual(self.request("DELETE", "user:1"), (200, {"deleted": True}))
        self.assertEqual(self.request("DELETE", "user:1"), (200, {"deleted": False}))
        self.assertEqual(self.request("GET", "user:1"), (404, {"error": "키가 없습니다"}))

    def test_value_types(self):
        for i, value in enumerate(["글자", 0, -1.5, True, False, [], [1, "a"], {}, {"a": [None]}]):
            self.assertEqual(self.request("PUT", f"type{i}", {"value": value})[0], 200, repr(value))
            self.assertEqual(self.request("GET", f"type{i}"), (200, {"key": f"type{i}", "value": value, "ttl": -1}))

    def test_ttl_and_expire(self):
        self.request("PUT", "t", {"value": 1, "ttl": 100})
        self.assertEqual(self.request("GET", "t/ttl"), (200, {"ttl": 100}))
        self.assertEqual(self.request("POST", "t/expire", {"ttl": 5}), (200, {"ok": True}))
        self.assertEqual(self.request("GET", "t/ttl"), (200, {"ttl": 5}))
        self.request("PUT", "forever", {"value": 1})
        self.assertEqual(self.request("GET", "forever/ttl"), (200, {"ttl": -1}))
        self.assertEqual(self.request("GET", quote("없는키") + "/ttl"), (200, {"ttl": -2}))
        self.assertEqual(self.request("POST", quote("없는키") + "/expire", {"ttl": 5}), (404, {"error": "키가 없습니다"}))

    def test_get_includes_ttl_and_fractional_ttl(self):
        # GET 응답에 남은 ttl 이 함께 온다. 소수 ttl 도 받는다 (남은 시간은 올림)
        self.request("PUT", "f", {"value": "x", "ttl": 2.5})
        self.assertEqual(self.request("GET", "f"), (200, {"key": "f", "value": "x", "ttl": 3}))
        self.assertEqual(self.request("POST", "f/expire", {"ttl": 0.5}), (200, {"ok": True}))
        self.assertEqual(self.request("GET", "f/ttl"), (200, {"ttl": 1}))

    def test_health(self):
        status, body = self.raw("GET", "/health")
        self.assertEqual((status, body["keys"]), (200, len(self.store)))
        self.assertEqual(self.raw("PUT", "/health", b"{}", {"Content-Length": "2"}), (405, {"error": "GET만 지원합니다"}))

    def test_put_without_ttl_clears_expire(self):
        self.request("PUT", "c", {"value": 1, "ttl": 100})
        self.request("PUT", "c", {"value": 2})
        self.assertEqual(self.request("GET", "c/ttl"), (200, {"ttl": -1}))

    # ── 키 ───────────────────────────────────────────────────────────

    def test_special_characters_in_key(self):
        for key in ["메이플", "char:a/b", "a b?c#d", "%2F", "😀"]:
            path = quote(key, safe="")  # "/" 까지 %2F 로 인코딩해야 키의 일부로 전해진다
            self.assertEqual(self.request("PUT", path, {"value": key})[0], 200, key)
            self.assertEqual(self.request("GET", path), (200, {"key": key, "value": key, "ttl": -1}))
            self.assertTrue(self.store.exists(key))

    def test_empty_key_is_unknown_path(self):
        # 빈 키는 없는 경로로 본다 (dev 와 같음)
        for path in ["/keys/", "/keys//ttl"]:
            self.assertEqual(self.raw("GET", path), (404, {"error": "없는 경로입니다"}), path)

    # ── 잘못된 경로 · 메서드 ────────────────────────────────────────

    def test_unknown_path(self):
        for path in ["/", "/keys", "/nokeys/a", "/keys/a/unknown", "/keys/a/ttl/more", "/keys/a/"]:
            self.assertEqual(self.raw("GET", path), (404, {"error": "없는 경로입니다"}), path)

    def test_method_not_allowed(self):
        # 문구는 경로마다 그 경로가 받는 메서드를 알려 준다 (dev 와 같음)
        cases = [
            ("POST", "/keys/a", "GET / PUT / DELETE만 지원합니다"),
            ("PUT", "/keys/a/ttl", "GET만 지원합니다"),
            ("DELETE", "/keys/a/ttl", "GET만 지원합니다"),
            ("GET", "/keys/a/expire", "POST만 지원합니다"),
        ]
        for method, path, message in cases:
            self.assertEqual(self.raw(method, path, b"{}", {"Content-Length": "2"}), (405, {"error": message}), (method, path))
        # 표준 라이브러리 기본값이면 HTML 501 로 답하는 메서드도 JSON 405
        for method in ["PATCH", "OPTIONS"]:
            self.assertEqual(self.raw(method, "/keys/a"), (405, {"error": "GET / PUT / DELETE만 지원합니다"}), method)

    def test_query_string_ignored(self):
        self.request("PUT", "q", {"value": 1})
        self.assertEqual(self.raw("GET", "/keys/q?x=1"), (200, {"key": "q", "value": 1, "ttl": -1}))

    # ── 입력 검사 (신뢰 경계) ───────────────────────────────────────

    def test_bad_bodies(self):
        cases = [
            b"not json",
            b"[1, 2]",  # 객체가 아님
            b'"text"',
            b"",  # 빈 본문
            b"\xff\xfe",  # UTF-8 이 아님
            json.dumps({"ttl": 5}).encode(),  # value 없음
            json.dumps({"value": None}).encode(),  # null 은 "없음" 과 구별이 안 되므로 거부
            b'{"value": NaN}',
            b'{"value": 1, "ttl": Infinity}',
            b'{"value": ' + b"[" * 100000 + b"]" * 100000 + b"}",  # 너무 깊은 중첩 → 응답으로 다시 못 씀
            b'{"value": "\\ud800"}',  # 짝 없는 반쪽 문자 → UTF-8 로 응답을 못 씀
            b'{"value": ["ok", "\\udfff"]}',
        ]
        for ttl in [0, -1, 0.0001, True, "5", None, [], 10**400]:
            if ttl is not None:
                cases.append(json.dumps({"value": 1, "ttl": ttl}).encode())
        for body in cases:
            status, res = self.raw("PUT", "/keys/bad", body)
            self.assertEqual(status, 400, body[:60])
            self.assertIn("error", res)
        self.assertFalse(self.store.exists("bad"))  # 거부된 요청은 아무것도 저장하지 않는다

    def test_bad_body_messages(self):
        # 400 의 이유를 한국어로 알려 준다 (문구는 dev 와 같음)
        cases = [
            (b"{not json", "본문이 올바른 JSON이 아닙니다 (NaN / Infinity 불가)"),
            (b'{"value": NaN}', "본문이 올바른 JSON이 아닙니다 (NaN / Infinity 불가)"),
            (b"[1]", "본문은 JSON 객체({...})여야 합니다"),
            (b'{"value": ' + b"[" * 100000 + b"]" * 100000 + b"}", "JSON이 너무 깊게 중첩되어 있습니다"),
            (b'{"value": "\\ud800"}', "UTF-8로 표현할 수 없는 문자(짝 없는 서로게이트)가 들어 있습니다"),
            (b'{"ttl": 5}', "value가 필요합니다 (null은 저장할 수 없습니다)"),
            (b'{"value": 1, "ttl": 0}', "ttl은 0.001초 이상의 유한한 숫자여야 합니다"),
        ]
        for raw, message in cases:
            self.assertEqual(self.raw("PUT", "/keys/msg", raw), (400, {"error": message}), raw[:30])
        self.assertEqual(self.raw("POST", "/keys/msg/expire", b"{}"), (400, {"error": "ttl이 필요합니다"}))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("PUT", "/keys/msg")
        conn.endheaders()  # Content-Length 없음
        res = conn.getresponse()
        self.assertEqual((res.status, json.loads(res.read())), (400, {"error": "Content-Length가 올바르지 않습니다"}))
        conn.close()

    def test_bad_expire_bodies(self):
        self.request("PUT", "e", {"value": 1})
        for body in [{}, {"ttl": 0}, {"ttl": "5"}, {"ttl": 0.0001}, {"ttl": True}]:
            self.assertEqual(self.request("POST", "e/expire", body)[0], 400, body)
        self.assertEqual(self.request("GET", "e/ttl"), (200, {"ttl": -1}))  # 만료가 잘못 걸리지 않았다

    def test_content_length_required(self):
        for headers in [{}, {"Content-Length": "abc"}, {"Content-Length": "-1"}, {"Content-Length": "²"}]:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.putrequest("PUT", "/keys/cl")
            for name, value in headers.items():
                conn.putheader(name, value)
            conn.endheaders()
            res = conn.getresponse()
            self.assertEqual(res.status, 400, headers)
            conn.close()

    def test_body_too_large(self):
        # 1MB 를 넘는 본문을 실제로 다 보낸다 → 서버가 본문을 읽어서 버린 뒤 413 (연결이 강제로 끊기지 않고 응답이 온다)
        raw = json.dumps({"value": "x" * (server_module.MAX_BODY + 1)}).encode()
        self.assertEqual(self.raw("PUT", "/keys/big", raw), (413, {"error": "요청 본문이 너무 큽니다 (최대 1MB)"}))
        self.assertFalse(self.store.exists("big"))

    def test_slow_client_gets_408(self):
        # Content-Length 보다 적게 보내고 멈춘 클라이언트 → 제한 시간 뒤 408. REQUEST_TIMEOUT 을 연결마다 다시 읽는지도 확인
        original = server_module.REQUEST_TIMEOUT
        server_module.REQUEST_TIMEOUT = 0.3
        self.addCleanup(setattr, server_module, "REQUEST_TIMEOUT", original)
        with socket.create_connection(("127.0.0.1", self.port)) as c:
            c.sendall(b"PUT /keys/slow HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{")
            c.settimeout(5)
            self.assertIn(b" 408 ", c.recv(200))
        self.assertFalse(self.store.exists("slow"))

    def test_lone_surrogate_stored_directly_still_returns_valid_json(self):
        # HTTP 로는 거부되지만(위 test_bad_bodies), 파이썬 코드로 저장소에 직접 넣은 반쪽 문자도 응답은 \uXXXX 로 적혀 반드시 나간다
        self.store.set("surrogate", "\ud800")
        self.assertEqual(self.raw("GET", "/keys/surrogate"), (200, {"key": "surrogate", "value": "\ud800", "ttl": -1}))

    def test_internal_error_returns_500_and_server_survives(self):
        with mock.patch.object(self.store, "get_with_ttl", side_effect=RuntimeError("터짐")):
            self.assertEqual(self.request("GET", "x"), (500, {"error": "서버 내부 오류"}))
        self.request("PUT", "after", {"value": 1})
        self.assertEqual(self.request("GET", "after"), (200, {"key": "after", "value": 1, "ttl": -1}))

    # ── 만료 · 동시성 ─────────────────────────────────────────────────

    def test_expired_value_not_returned_and_swept(self):
        # 실제 시간으로 확인: ttl 1초 → 1초 뒤 아무도 안 읽어도 주기 삭제(1초 간격)가 메모리에서 지운다
        self.request("PUT", "short", {"value": "x", "ttl": 1})
        deadline = time.monotonic() + 4
        while "short" in self.store._data and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertNotIn("short", self.store._data)  # 지연 삭제가 아니라 sweep 이 지웠다 (exists 를 부르지 않음)
        self.assertEqual(self.request("GET", "short")[0], 404)

    def test_concurrent_requests(self):
        def worker(t):
            for i in range(20):
                self.request("PUT", f"c{t}:{i}", {"value": i})

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertTrue(all(self.store.get(f"c{t}:{i}") == i for t in range(5) for i in range(20)))

    def test_many_simultaneous_connections(self):
        # 클라이언트 50개가 "동시에" 접속해도 끊기지 않아야 한다 (listen backlog 가 기본값 5 이면 넘친 연결이 reset 됨)
        barrier = threading.Barrier(50)
        errors = []

        def client(t):
            barrier.wait()  # 50개가 같은 순간에 접속하도록 맞춘다
            try:
                self.assertEqual(self.request("PUT", f"burst{t}", {"value": t})[0], 200)
            except Exception as e:  # 스레드 안의 실패는 테스트로 전해지지 않으므로 모아 둔다
                errors.append(repr(e))

        threads = [threading.Thread(target=client, args=(t,)) for t in range(50)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertTrue(all(self.store.get(f"burst{t}") == t for t in range(50)))

    # ── 연결 재사용 (HTTP/1.1 keep-alive) ─────────────────────────────

    def test_keep_alive_reuses_one_connection(self):
        # 연결 하나로 저장 · 조회 · 오류 · 삭제를 이어서 보낸다 → 매번 같은 소켓, 서버가 닫지 않음
        # 본문을 끝까지 읽은 뒤의 오류(잘못된 JSON → 400)도 연결을 끊지 않는다
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        steps = [
            ("PUT", "/keys/ka", b'{"value": 1}', 200),
            ("GET", "/keys/ka", None, 200),
            ("PUT", "/keys/ka", b"{", 400),
            ("GET", "/keys/ka/ttl", None, 200),
            ("DELETE", "/keys/ka", None, 200),
            ("GET", "/keys/ka", None, 404),
        ]
        sock = None
        for method, path, body, status in steps:
            conn.request(method, path, body=body)
            res = conn.getresponse()
            res.read()
            self.assertEqual((res.status, res.will_close), (status, False), (method, path))
            sock = sock or conn.sock
            self.assertIs(conn.sock, sock, "같은 연결을 다시 써야 한다")

    def test_unread_body_closes_connection(self):
        # 본문(hello)을 읽지 않고 405 로 답한 뒤 연결을 닫는다. 닫지 않으면 "hello" 가 뒤에 붙여 보낸 GET 과 합쳐져
        # "helloGET /health …" 라는 엉뚱한 요청으로 읽혀 응답이 하나 더 나간다
        with socket.create_connection(("127.0.0.1", self.port)) as c:
            c.settimeout(5)
            c.sendall(b"POST /keys/a HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\nhello" + b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
            data = b""
            while chunk := c.recv(4096):  # 서버가 닫을 때까지 전부 받는다
                data += chunk
        self.assertEqual(data.count(b"HTTP/1.1 "), 1, data)
        self.assertIn(b" 405 ", data)
        self.assertIn(b"Connection: close", data)


if __name__ == "__main__":
    unittest.main()
