# [test_server.py] HTTP API 기능 테스트 — 실제 서버를 띄우고 외부 클라이언트처럼 요청한다

import contextlib
import functools
import http.client
import io
import json
import os
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mini_redis import server as server_module
from mini_redis.persistence import load_snapshot, save_snapshot
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

    def raw_request(self, data):
        """소켓으로 바이트를 그대로 보내고(쓰기 쪽은 닫음) 응답 전체를 받는다"""
        with socket.create_connection(("127.0.0.1", self.server.server_address[1])) as c:
            c.sendall(data)
            c.shutdown(socket.SHUT_WR)
            c.settimeout(5)
            out = b""
            while chunk := c.recv(65536):
                out += chunk
        head, _, body = out.partition(b"\r\n\r\n")
        return head, body

    def test_truncated_body_is_rejected(self):
        # Content-Length 100인데 12바이트만 보내고 연결을 닫음 → 잘린 본문이 우연히 올바른 JSON이어도 저장하면 안 된다 (Gemini 리뷰)
        head, body = self.raw_request(b'PUT /keys/cut HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{"value": 1}')
        self.assertIn(b" 400 ", head)
        self.assertIn("error", json.loads(body))
        self.assertFalse(self.store.exists("cut"))

    def test_unknown_methods_get_json_501(self):
        # do_* 가 없는 메서드는 표준 라이브러리 기본값이면 HTML 501 → JSON 501 (아는 메서드의 잘못된 경로는 405로 구분)
        for method in [b"TRACE", b"CONNECT", b"FOO"]:
            head, body = self.raw_request(method + b" /keys/a HTTP/1.1\r\nHost: x\r\n\r\n")
            self.assertIn(b" 501 ", head, method)
            self.assertIn("error", json.loads(body), method)
        # HEAD는 HTTP 규약상 본문 없이 헤더만
        head, body = self.raw_request(b"HEAD /keys/a HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertIn(b" 501 ", head)
        self.assertEqual(body, b"")

    def test_bad_content_length_headers(self):
        # 헤더가 없거나(본문 없음 → value 없음) 숫자가 아니거나 음수인 Content-Length → 모두 400, 저장 안 됨
        for header in [b"", b"Content-Length: abc\r\n", b"Content-Length: -5\r\n", b"Content-Length: 0\r\n"]:
            head, body = self.raw_request(b"PUT /keys/cl HTTP/1.1\r\nHost: x\r\n" + header + b"\r\n")
            self.assertIn(b" 400 ", head, header)
            self.assertIn("error", json.loads(body), header)
        self.assertFalse(self.store.exists("cl"))

    def test_encoded_slash_and_double_encoding_are_different_keys(self):
        # %2F는 "a/b", %252F는 "a%2Fb" — 디코딩을 정확히 한 번만 해서 서로 다른 키가 되어야 한다
        self.request("PUT", "/keys/a%2Fb", {"value": "slash"})
        self.request("PUT", "/keys/a%252Fb", {"value": "percent"})
        self.assertEqual((self.store.get("a/b"), self.store.get("a%2Fb")), ("slash", "percent"))

    def test_too_long_url_gets_json_414(self):
        # 요청 줄이 64KB를 넘는 아주 긴 키 → 표준 라이브러리가 거부(414). 그 응답도 HTML이 아니라 JSON이어야 한다
        head, body = self.raw_request(b"GET /keys/" + b"k" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertIn(b" 414 ", head)
        self.assertIn("error", json.loads(body))

    def test_body_too_large(self):
        raw = json.dumps({"value": "x" * (server_module.MAX_BODY + 1)}).encode()
        self.assertEqual(self.request("PUT", "/keys/big", raw=raw)[0], 413)

    # ── 전체 점검에서 재현한 문제 (수정 전 코드에서 실패 확인) ──

    def test_nesting_depth_limit_keeps_snapshot_working(self):
        # 깊이 1000 이상의 [[[...]]]도 200으로 저장되던 것 → 스냅샷 저장(json.dump)이 RecursionError로 매번 실패해
        # 다른 키까지 디스크에 남지 않았다. 실제 RedisJSON처럼 중첩 깊이에 상한을 둔다
        limit = server_module.MAX_DEPTH
        ok = json.loads("[" * limit + "]" * limit)
        self.assertEqual(self.request("PUT", "/keys/deep_ok", {"value": ok})[0], 200)
        for depth in [limit + 1, 3000]:
            raw = ('{"value": ' + "[" * depth + "]" * depth + "}").encode()
            self.assertEqual(self.request("PUT", "/keys/deep_bad", raw=raw)[0], 400, depth)
        nested_dict = functools.reduce(lambda inner, _: {"a": inner}, range(limit + 1), 1)  # 객체 중첩도 같은 규칙
        self.assertEqual(self.request("PUT", "/keys/deep_bad", {"value": nested_dict})[0], 400)
        self.assertEqual(self.request("PUT", "/keys/deep_bad", {"value": 1, "ttl": 5, "x": nested_dict})[0], 400)
        self.assertFalse(self.store.exists("deep_bad"))
        # 상한 깊이의 값이 있어도 스냅샷 저장 · 복구가 된다
        snapshot_store = MiniRedis()
        snapshot_store.set("deep_ok", self.store.get("deep_ok"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dump.json")
            save_snapshot(snapshot_store, path)
            restored = MiniRedis()
            load_snapshot(restored, path)
        self.assertEqual(restored.get("deep_ok"), ok)

    def test_chunked_body_gets_411(self):
        # Transfer-Encoding: chunked는 Content-Length가 없어 본문을 안 읽고 "value가 필요합니다" 400을 주던 것 → 원인대로 411
        head, body = self.raw_request(b"PUT /keys/chunked HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: chunked\r\n\r\n"
                                      b'f\r\n{"value": 12345}\r\n0\r\n\r\n')
        self.assertIn(b" 411 ", head)
        self.assertIn("Content-Length", json.loads(body)["error"])
        self.assertFalse(self.store.exists("chunked"))

    def test_unserializable_value_gets_json_500(self):
        # 파이썬 코드로 JSON으로 못 바꾸는 값을 직접 넣으면 GET이 응답 없이 끊기고 서버에 traceback이 찍히던 것 → JSON 500
        self.store.set("pyset", {1, 2})
        self.addCleanup(self.store.delete, "pyset")
        status, body = self.request("GET", "/keys/pyset")
        self.assertEqual(status, 500)
        self.assertIn("error", body)

    def test_main_rejects_bad_port(self):
        # --port 70000 → bind의 OverflowError(OSError가 아님)가 traceback으로 나오던 것 → 사용법 에러
        for port in ["70000", "-1", "65536"]:
            err = io.StringIO()
            with mock.patch("sys.argv", ["server", "--port", port, "--snapshot="]), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as cm:
                    server_module.main()
            self.assertEqual(cm.exception.code, 2, port)
            self.assertIn("--port", err.getvalue())

    # ── 연결 재사용 (HTTP/1.1 keep-alive) ──

    def test_keep_alive_reuses_one_connection(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(conn.close)
        conn.request("PUT", "/keys/ka", body=b'{"value": 1}')
        first = conn.getresponse()
        first.read()
        sock = conn.sock
        for _ in range(3):
            conn.request("GET", "/keys/ka")
            res = conn.getresponse()
            self.assertEqual((res.status, json.loads(res.read())["value"]), (200, 1))
        self.assertIs(conn.sock, sock)  # 새로 연결하지 않고 같은 소켓으로 계속 주고받았다
        self.assertFalse(first.will_close)

    def test_keep_alive_does_not_stall(self):
        # TCP_NODELAY가 없으면 Nagle + 지연 ACK 때문에 연결을 재사용하는 요청마다 수십~200ms씩 멈출 수 있다 (주로 Linux).
        # Windows localhost에서는 옵션을 꺼도 멈춤이 재현되지 않아서, 이 테스트는 "멈추지 않는다"만 확인한다
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        self.addCleanup(conn.close)
        start = time.perf_counter()
        for _ in range(30):
            conn.request("GET", "/health")
            conn.getresponse().read()
        self.assertLess(time.perf_counter() - start, 1.5)

    def test_unread_body_closes_connection(self):
        # 본문을 읽지 않고 답한 요청(405 · 404 등)의 본문이 같은 연결의 "다음 요청"으로 읽히면 안 된다.
        # 본문 자리에 요청처럼 생긴 바이트를 넣어도 응답은 하나여야 하고, 서버는 연결을 닫는다
        smuggled = b"DELETE /keys/victim HTTP/1.1\r\nHost: x\r\n\r\n"
        self.store.set("victim", 1)
        self.addCleanup(self.store.delete, "victim")
        cases = [
            b"POST /keys/victim HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n" % len(smuggled),  # 405
            b"GET /nope HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n" % len(smuggled),  # 404
            b"GET /keys/victim HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\n\r\n" % len(smuggled),  # GET에 붙은 본문
        ]
        for head in cases:
            out_head, out_body = self.raw_request(head + smuggled)
            self.assertEqual((out_head + out_body).count(b"HTTP/1.1 "), 1, head)
            self.assertIn(b"Connection: close", out_head, head)
        self.assertTrue(self.store.exists("victim"))  # 숨겨 보낸 DELETE가 실행되지 않았다

    def test_duplicate_content_length_is_rejected(self):
        # Content-Length가 두 개면 첫 번째만 보고 본문을 읽어, 남은 바이트에 숨긴 DELETE가 다음 요청으로 실행됐다 (GPT · Gemini 리뷰로 재현)
        body = b'{"value": "x"}'
        smuggled = b"DELETE /keys/victim HTTP/1.1\r\nHost: x\r\n\r\n"
        self.store.set("victim", 1)
        self.addCleanup(self.store.delete, "victim")
        for second in (len(body) + len(smuggled), len(body)):  # 다른 값 · 같은 값 모두 거부
            head, out = self.raw_request(b"PUT /keys/dup HTTP/1.1\r\nHost: x\r\nContent-Length: %d\r\nContent-Length: %d\r\n\r\n"
                                         % (len(body), second) + body + smuggled)
            self.assertIn(b" 400 ", head)
            self.assertIn(b"Connection: close", head)
            self.assertEqual((head + out).count(b"HTTP/1.1 "), 1)
        self.assertTrue(self.store.exists("victim"))
        self.assertFalse(self.store.exists("dup"))

    def test_idle_connection_is_closed_after_timeout(self):
        # 쉬는 연결이 스레드를 영원히 붙잡지 않는다: REQUEST_TIMEOUT(테스트에서 0.5초) 뒤 서버가 닫는다
        with socket.create_connection(("127.0.0.1", self.server.server_address[1])) as c:
            c.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
            c.settimeout(5)
            data = b""
            while not data.endswith(b"}"):  # 헤더와 본문이 따로 도착할 수 있다 (TCP_NODELAY) → 본문 끝까지 받는다
                data += c.recv(4096)
            self.assertIn(b" 200 ", data)
            start = time.perf_counter()
            self.assertEqual(c.recv(4096), b"")  # 서버가 연결을 닫았다
            self.assertLess(time.perf_counter() - start, 3)

    def test_client_connection_close_is_respected(self):
        # urlopen처럼 Connection: close를 보내면 예전처럼 응답 하나로 끊는다
        head, _ = self.raw_request(b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        self.assertIn(b"Connection: close", head)

    def test_content_length_must_be_plain_digits(self):
        # int()가 받아 주던 "+12" · "1_2" 등이 200으로 저장되던 것 (Gemini 리뷰로 재현) → 숫자만, 아니면 400 + 연결 닫기
        body = b'{"value": 7}'
        for raw in [b"+12", b"1_2", "１２".encode(), b"-0", b"0x0c", b"12.0", b"9" * 5000, b"", b"   "]:  # 빈 값도 거부
            head, _ = self.raw_request(b"PUT /keys/strict HTTP/1.1\r\nHost: x\r\nContent-Length: " + raw + b"\r\n\r\n" + body)
            self.assertIn(b" 400 ", head, raw[:10])
            self.assertIn(b"Connection: close", head, raw[:10])
        self.assertFalse(self.store.exists("strict"))
        head, _ = self.raw_request(b"PUT /keys/strict HTTP/1.1\r\nHost: x\r\nContent-Length:  12 \r\n\r\n" + body)
        self.assertIn(b" 200 ", head)  # 앞뒤 공백은 HTTP 규칙상 허용
        self.store.delete("strict")

    def test_framing_headers_never_smuggle(self):
        # 숨긴 DELETE가 실행되던 두 경로 (리뷰로 재현): 중복 Content-Length의 첫 값이 0 (GPT), 값이 빈 Transfer-Encoding (Gemini)
        smuggled = b"DELETE /keys/victim3 HTTP/1.1\r\nHost: x\r\n\r\n"
        self.store.set("victim3", 1)
        self.addCleanup(self.store.delete, "victim3")
        heads = [
            b"PUT /keys/d HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\nContent-Length: %d\r\n\r\n" % len(smuggled),
            b"PUT /keys/d HTTP/1.1\r\nHost: x\r\nTransfer-Encoding:\r\n\r\n",
            b"GET /keys/d HTTP/1.1\r\nHost: x\r\nTransfer-Encoding: \r\n\r\n",
            # 이름과 콜론 사이 공백: 표준 라이브러리가 "Content-Length "라는 다른 헤더로 저장한다 (자체 점검으로 재현)
            b"PUT /keys/d HTTP/1.1\r\nHost: x\r\nContent-Length : %d\r\n\r\n" % len(smuggled),
            b"GET /keys/d HTTP/1.1\r\nHost: x\r\nContent-Length\t: %d\r\n\r\n" % len(smuggled),
            b"PUT /keys/d HTTP/1.1\r\nHost: x\r\nTransfer-Encoding : chunked\r\n\r\n",
        ]
        for head in heads:
            out_head, out_body = self.raw_request(head + smuggled)
            self.assertEqual((out_head + out_body).count(b"HTTP/1.1 "), 1, head)
            self.assertIn(b"Connection: close", out_head, head)
        self.assertTrue(self.store.exists("victim3"))

    def test_content_length_checked_on_every_route(self):
        # 본문을 읽지 않는 경로(GET)도 같은 규칙: "+1"이면 400 (전에는 200, GPT 리뷰)
        head, _ = self.raw_request(b"GET /health HTTP/1.1\r\nHost: x\r\nContent-Length: +1\r\n\r\n")
        self.assertIn(b" 400 ", head)
        self.assertIn(b"Connection: close", head)

    def test_expect_header_rules(self):
        port = self.server.server_address[1]
        # 모르는 Expect 값 → 본문을 기다리지 않고 바로 417 (전에는 408까지 기다림, GPT 리뷰)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
            c.sendall(b"PUT /keys/e HTTP/1.1\r\nHost: x\r\nExpect: 100-continue, foo\r\nContent-Length: 14\r\n\r\n")
            start = time.perf_counter()
            out = b""
            while chunk := c.recv(4096):
                out += chunk
        self.assertIn(b" 417 ", out)
        self.assertLess(time.perf_counter() - start, 0.4)  # 제한 시간(0.5초)을 기다리지 않았다
        # 본문 0바이트면 100 없이 바로 최종 응답 (Gemini 리뷰)
        head, body = self.raw_request(b"PUT /keys/e HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nContent-Length: 0\r\n\r\n")
        self.assertNotIn(b" 100 ", head + body)
        self.assertIn(b" 400 ", head)

    def test_connection_close_token_in_list(self):
        # "Connection: keep-alive, close"나 헤더 두 줄에 든 close도 닫아 달라는 뜻이다 (표준 라이브러리는 값 전체가 close일 때만, GPT 리뷰)
        port = self.server.server_address[1]
        for headers in [b"Connection: keep-alive, close\r\n", b"Connection: keep-alive\r\nConnection: close\r\n"]:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
                c.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n" + headers + b"\r\n")
                start = time.perf_counter()
                out = b""
                while chunk := c.recv(4096):
                    out += chunk
            self.assertIn(b"Connection: close", out, headers)
            self.assertLess(time.perf_counter() - start, 0.4, headers)  # 쉬는 연결 제한 시간이 아니라 바로 닫혔다

    def test_empty_content_length_does_not_smuggle(self):
        # "Content-Length:"(빈 값)을 "본문 없음"으로 보고 연결을 유지해, 뒤에 숨긴 DELETE가 실행되던 것 (Gemini 리뷰로 재현)
        self.store.set("victim2", 1)
        self.addCleanup(self.store.delete, "victim2")
        for request_line in [b"PUT /keys/a", b"GET /keys/a", b"GET /nope"]:  # 본문을 읽는 경로 · 읽지 않는 경로 모두
            head, body = self.raw_request(request_line + b" HTTP/1.1\r\nHost: x\r\nContent-Length:\r\n\r\n"
                                          b"DELETE /keys/victim2 HTTP/1.1\r\nHost: x\r\n\r\n")
            self.assertEqual((head + body).count(b"HTTP/1.1 "), 1, request_line)
            self.assertIn(b"Connection: close", head, request_line)
        self.assertTrue(self.store.exists("victim2"))

    def test_expect_continue_only_after_checks(self):
        # Expect: 100-continue: 거절할 요청에는 100을 보내지 않고 바로 거절, 받을 요청에만 100 → 본문 → 200 (Gemini 리뷰로 재현)
        port = self.server.server_address[1]
        for head in [b"POST /keys/a HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nContent-Length: 10\r\n\r\n",  # 405
                     b"PUT /keys/a HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nContent-Length: 2000000\r\n\r\n"]:  # 413
            with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
                c.sendall(head)  # 본문은 보내지 않고 기다린다 (curl 등이 하는 방식)
                out = b""
                while chunk := c.recv(4096):
                    out += chunk
            self.assertNotIn(b" 100 ", out, head[:20])
            self.assertEqual(out.count(b"HTTP/1.1 "), 1, head[:20])
        body = b'{"value": 5}'
        with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
            c.sendall(b"PUT /keys/expect HTTP/1.1\r\nHost: x\r\nExpect: 100-continue\r\nContent-Length: %d\r\n\r\n" % len(body))
            self.assertTrue(c.recv(4096).startswith(b"HTTP/1.1 100"))
            c.sendall(body)
            self.assertIn(b" 200 ", c.recv(4096))
        self.assertEqual(self.store.get("expect"), 5)
        self.store.delete("expect")

    def test_server_close_ends_idle_connections(self):
        # 서버를 닫으면 다음 요청을 기다리던 연결도 끊어 그 스레드가 바로 끝난다 (전에는 REQUEST_TIMEOUT까지 남음, Gemini 리뷰로 재현)
        original = server_module.REQUEST_TIMEOUT
        server_module.REQUEST_TIMEOUT = 5  # 제한 시간에 걸려 우연히 끊기지 않게 길게
        try:
            other = create_server(MiniRedis(), port=0)
        finally:
            server_module.REQUEST_TIMEOUT = original
        threading.Thread(target=other.serve_forever, daemon=True).start()
        with socket.create_connection(("127.0.0.1", other.server_address[1]), timeout=5) as c:
            c.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
            data = b""
            while not data.endswith(b"}"):
                data += c.recv(4096)
            other.shutdown()
            other.server_close()
            start = time.perf_counter()
            self.assertEqual(c.recv(4096), b"")  # 서버가 끊었다
            self.assertLess(time.perf_counter() - start, 2)  # 제한 시간(5초)을 기다리지 않았다

    def test_thread_start_base_exception_releases_slot(self):
        # 스레드 시작이 BaseException(KeyboardInterrupt 등)으로 실패하면 자리와 소켓이 남던 것 (Gemini 리뷰로 재현)
        class Boom(BaseException):
            pass

        a, b = socket.socketpair()
        self.addCleanup(b.close)
        with mock.patch.object(threading.Thread, "start", side_effect=Boom), self.assertRaises(Boom):
            self.server.process_request(a, ("127.0.0.1", 1))
        self.assertNotIn(a, self.server._clients)
        self.assertEqual(a.fileno(), -1)  # 소켓도 닫혔다

    def test_client_reset_on_idle_connection_is_quiet(self):
        # 쉬는 keep-alive 연결을 클라이언트가 강제로 끊어도(RST) 서버 콘솔에 traceback이 찍히지 않는다
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            c = socket.create_connection(("127.0.0.1", self.server.server_address[1]))
            c.sendall(b"GET /health HTTP/1.1\r\nHost: x\r\n\r\n")
            time.sleep(0.1)  # 응답이 도착했지만 읽지 않는다
            c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))  # 닫을 때 RST
            c.close()
            time.sleep(0.3)  # 서버 스레드가 끊김을 알아챌 시간
        self.assertNotIn("Traceback", err.getvalue())

    def test_max_clients_rejects_extra_connections(self):
        # 연결을 열어 두기만 하는 클라이언트가 많아도 스레드가 끝없이 늘지 않는다: 상한을 넘는 연결은 503으로 바로 거절
        original = server_module.MAX_CLIENTS
        server_module.MAX_CLIENTS = 3
        try:
            small = create_server(MiniRedis(), port=0)
        finally:
            server_module.MAX_CLIENTS = original
        threading.Thread(target=small.serve_forever, daemon=True).start()
        self.addCleanup(small.server_close)
        self.addCleanup(small.shutdown)
        port = small.server_address[1]
        held = []
        for _ in range(3):  # 자리를 모두 차지하고 쉬는 연결 3개
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            self.assertEqual(conn.getresponse().status, 200)
            held.append(conn)
        with socket.create_connection(("127.0.0.1", port), timeout=5) as c:
            data = b""
            while chunk := c.recv(4096):  # 서버가 503을 보내고 닫는다
                data += chunk
        self.assertIn(b" 503 ", data)
        self.assertIn("error", json.loads(data.partition(b"\r\n\r\n")[2]))
        held.pop().close()  # 하나가 나가면 자리가 생긴다
        deadline = time.monotonic() + 3
        while True:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/health")
            status = conn.getresponse().status
            conn.close()
            if status == 200 or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        self.assertEqual(status, 200)
        for conn in held:
            conn.close()


if __name__ == "__main__":
    unittest.main()
