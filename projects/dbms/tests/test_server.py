# [test_server.py] API 서버 기능 테스트 (Phase 3) — 실제 서버를 띄우고 외부 클라이언트처럼 HTTP로 요청한다

import contextlib
import http.client
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest

from minidb import server as server_module
from minidb.server import create_server, stop_server


def start(directory, **kwargs):
    server = create_server(directory, port=0, **kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def make_db():
    tmp = tempfile.TemporaryDirectory()
    with open(os.path.join(tmp.name, "schema.json"), "w", encoding="utf-8") as f:
        json.dump({"users": {"name": "TEXT", "age": "INT"}}, f)
    return tmp


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_timeout = server_module.Handler.timeout
        server_module.Handler.timeout = 0.5  # 본문을 덜 보낸 클라이언트 테스트를 빨리 끝내려고
        cls.tmp = make_db()
        cls.server = start(cls.tmp.name, workers=4, queue_size=64)
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        stop_server(cls.server)
        cls.tmp.cleanup()
        server_module.Handler.timeout = cls.original_timeout

    def request(self, method, path, body=None, raw=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            conn.request(method, path, body=data, headers=headers or {})
            res = conn.getresponse()
            text = res.read()
            return res.status, (json.loads(text) if text else None)
        finally:
            conn.close()

    def sql(self, sql):
        return self.request("POST", "/query", {"sql": sql})

    def raw(self, data):
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as c:
            c.sendall(data)
            c.shutdown(socket.SHUT_WR)
            out = b""
            while chunk := c.recv(65536):
                out += chunk
        head, _, body = out.partition(b"\r\n\r\n")
        return head, body

    # ── 정상 동작 ──

    def test_health(self):
        self.assertEqual(self.request("GET", "/health"), (200, {"status": "ok"}))

    def test_insert_and_select(self):
        status, body = self.sql("INSERT INTO users VALUES ('홍길동', 25); INSERT INTO users VALUES ('kim', 30);")
        self.assertEqual(status, 200)
        ids = [int(r["message"].split("id=")[1].rstrip(")")) for r in body["results"]]
        status, body = self.sql(f"SELECT name, age FROM users WHERE id = {ids[0]}")
        self.assertEqual((status, body["results"][0]["rows"], body["results"][0]["plan"]), (200, [["홍길동", 25]], "index"))
        status, body = self.sql("SELECT id FROM users WHERE name = 'kim'")
        self.assertEqual((body["results"][0]["rows"], body["results"][0]["plan"]), ([[ids[1]]], "scan"))
        self.assertEqual(body["results"][0]["columns"], ["id"])

    def test_concurrent_clients(self):
        # 클라이언트 40명이 동시에 10번씩 INSERT → 모두 200, id 400개가 겹치지 않는다 (스레드 풀 + 엔진의 락)
        before = len(self.sql("SELECT id FROM users")[1]["results"][0]["rows"])
        statuses, new_ids, lock = [], [], threading.Lock()

        def client(c):
            for i in range(10):
                status, body = self.sql(f"INSERT INTO users VALUES ('c{c}-{i}', {i})")
                with lock:
                    statuses.append(status)
                    if status == 200:
                        new_ids.append(body["results"][0]["message"])

        threads = [threading.Thread(target=client, args=(c,)) for c in range(40)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(set(statuses), {200})
        self.assertEqual(len(set(new_ids)), 400)
        rows = self.sql("SELECT id FROM users")[1]["results"][0]["rows"]
        self.assertEqual(len(rows), before + 400)
        self.assertEqual(len({r[0] for r in rows}), len(rows))

    # ── SQL 오류 ──

    def test_syntax_error_runs_nothing(self):
        before = len(self.sql("SELECT id FROM users")[1]["results"][0]["rows"])
        status, body = self.sql("INSERT INTO users VALUES ('a', 1);\nSELEC * FROM users")
        self.assertEqual(status, 400)
        self.assertIn("문법 오류", body["error"])
        self.assertIn("줄 2", body["error"])
        self.assertEqual(len(self.sql("SELECT id FROM users")[1]["results"][0]["rows"]), before)

    def test_execution_error_returns_earlier_results(self):
        status, body = self.sql("INSERT INTO users VALUES ('ok', 1); SELECT * FROM nope; INSERT INTO users VALUES ('never', 2)")
        self.assertEqual(status, 400)
        self.assertIn("2번째 문장", body["error"])
        self.assertIn("테이블이 없습니다", body["error"])
        self.assertEqual(len(body["results"]), 1)  # 앞 문장(INSERT)은 실행됐다
        self.assertEqual(self.sql("SELECT * FROM users WHERE name = 'never'")[1]["results"][0]["rows"], [])

    # ── 잘못된 요청 ──

    def test_bad_bodies(self):
        cases = [
            (b"not json", 400),
            (b"[1, 2]", 400),
            (b'{"query": "SELECT 1"}', 400),  # sql 없음
            (b'{"sql": 123}', 400),  # 문자열이 아님
            (b'{"sql": "SELECT * FROM users WHERE name = \'\\ud800\'"}', 400),  # 짝 없는 반쪽 문자: 파일에 쓸 수 없다
            (b"\xff\xfe", 400),  # UTF-8 아님
            (b"[" * 100000 + b"]" * 100000, 400),  # 너무 깊은 중첩
        ]
        for raw, expected in cases:
            status, body = self.request("POST", "/query", raw=raw)
            self.assertEqual(status, expected, raw[:30])
            self.assertIn("error", body, raw[:30])

    def test_bad_framing_headers(self):
        cases = [
            (b"POST /query HTTP/1.0\r\n\r\n", b" 400 "),  # Content-Length 없음
            # "+길이": 본문은 올바른 JSON이고 길이도 맞지만, Content-Length는 숫자만이라 거부해야 한다
            (b'POST /query HTTP/1.0\r\nContent-Length: +30\r\n\r\n{"sql": "SELECT * FROM users"}', b" 400 "),
            (b"POST /query HTTP/1.0\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}", b" 400 "),
            (b"POST /query HTTP/1.0\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n", b" 411 "),
            (b'POST /query HTTP/1.0\r\nContent-Length: 100\r\n\r\n{"sql": "SELECT * FROM users"}', b" 400 "),  # 잘린 본문
        ]
        for data, expected in cases:
            head, body = self.raw(data)
            self.assertIn(expected, head, data[:50])
            self.assertIn("error", json.loads(body), data[:50])

    def test_body_too_large(self):
        raw = json.dumps({"sql": "x" * (server_module.MAX_BODY + 1)}).encode()
        self.assertEqual(self.request("POST", "/query", raw=raw)[0], 413)

    def test_slow_client_gets_408(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as c:
            c.sendall(b'POST /query HTTP/1.0\r\nContent-Length: 50\r\n\r\n{"sql"')  # 덜 보내고 멈춤
            self.assertIn(b" 408 ", c.recv(4096))

    def test_client_reset_during_body_is_not_server_error(self):
        # 본문을 보내다 연결을 강제로 끊으면 500(서버 내부 오류)이 아니라 400으로 분류하고, 서버는 계속 정상 동작한다
        class ResetStream:
            def read(self, n):
                raise ConnectionResetError("클라이언트가 연결을 끊음")

        handler = server_module.Handler.__new__(server_module.Handler)  # 소켓 없이 핸들러만
        handler.headers = http.client.HTTPMessage()
        handler.headers["Content-Length"] = "100"
        handler.rfile = ResetStream()
        with self.assertRaises(server_module.ApiError) as ctx:
            handler._read_sql()
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(self.request("GET", "/health")[0], 200)

    def test_error_reply_arrives_even_with_unread_body(self):
        # 본문을 읽지 않고 답하는 요청(본문이 붙은 405 · 404)도 클라이언트가 응답을 받아야 한다.
        # 안 읽은 본문이 남은 채로 닫으면 Windows가 RST를 보내, 가끔 응답 대신 ConnectionAbortedError가 났다 (반복 실행에서 재현)
        for _ in range(40):
            self.assertEqual(self.request("POST", "/health", {"sql": "x" * 2000})[0], 405)
            self.assertEqual(self.request("POST", "/nope", {"sql": "x" * 2000})[0], 404)

    def test_wrong_paths_and_methods(self):
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("GET", "/query")[0], 405)
        self.assertEqual(self.request("DELETE", "/query")[0], 405)
        self.assertEqual(self.request("POST", "/health", {"sql": "x"})[0], 405)
        status, body = self.request("TRACE", "/query")  # do_*가 없는 메서드 → JSON 501
        self.assertEqual((status, "error" in body), (501, True))
        status, body = self.request("HEAD", "/query")  # HEAD는 본문 없이
        self.assertEqual((status, body), (501, None))


class BusyServerTest(unittest.TestCase):
    def test_full_queue_gets_503_right_away(self):
        # 작업자 1개 · 큐 1칸: 작업자는 느린 연결을 붙잡고 있고 큐도 찼다 → 다음 연결은 기다리지 않고 바로 503
        original = server_module.Handler.timeout
        server_module.Handler.timeout = 2
        tmp = make_db()
        server = start(tmp.name, workers=1, queue_size=1)
        port = server.server_address[1]
        slow = socket.create_connection(("127.0.0.1", port))
        try:
            slow.sendall(b"POST /query HTTP/1.0\r\n")  # 헤더를 다 보내지 않아 작업자가 기다린다
            time.sleep(0.3)
            queued = socket.create_connection(("127.0.0.1", port))  # 큐 1칸을 차지
            time.sleep(0.3)
            with socket.create_connection(("127.0.0.1", port), timeout=1) as extra:
                start_time = time.perf_counter()
                reply = extra.recv(4096)
                self.assertIn(b" 503 ", reply)
                self.assertLess(time.perf_counter() - start_time, 1)
            queued.close()
        finally:
            slow.close()
            server.shutdown()
            stop_server(server)
            tmp.cleanup()
            server_module.Handler.timeout = original


class MainTest(unittest.TestCase):
    def run_main(self, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            server_module.main(list(args))
        return cm.exception.code, err.getvalue()

    def test_bad_arguments(self):
        self.assertEqual(self.run_main("--port", "70000")[0], 2)
        with tempfile.TemporaryDirectory() as empty:
            code, err = self.run_main("--db", empty, "--port", "0")
            self.assertEqual(code, 1)
            self.assertIn("스키마", err)
            tmp = make_db()
            self.addCleanup(tmp.cleanup)
            code, err = self.run_main("--db", tmp.name, "--port", "0", "--workers", "0")
            self.assertEqual(code, 1)
            self.assertIn("workers", err)


if __name__ == "__main__":
    unittest.main()
