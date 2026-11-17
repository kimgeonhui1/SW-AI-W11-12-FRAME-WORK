# [test_server.py] Phase 3 기능 테스트 — 실제 서버를 빈 포트에 띄우고 HTTP 로 요청한다
#
#   API: /query 성공 · SQL 오류(위치 · 오류 전 결과) · /tables · /health · 404 · 405 · 잘못된 본문 · 413 · 408 · 결과 잘라 담기
#   스레드 풀: 클라이언트 20개가 동시에 INSERT → id 빠짐 · 겹침 없음, 풀이 가득 차면 503

import http.client
import json
import socket
import threading
import time
import unittest

from mini_dbms import server as server_module
from mini_dbms.engine import Engine
from mini_dbms.server import create_server
from tests.helpers import make_data_dir


class ServerCase(unittest.TestCase):
    workers, queue_limit = 4, None

    def setUp(self):
        self.dir = make_data_dir(self)
        self.engine = Engine(self.dir)
        self.server = create_server(self.engine, port=0, workers=self.workers, queue_limit=self.queue_limit)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.engine.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = json.dumps(body).encode() if isinstance(body, dict) else body
            conn.request(method, path, body=data, headers=headers or {})
            res = conn.getresponse()
            self.assertEqual(res.getheader("Content-Type"), "application/json; charset=utf-8")
            return res.status, json.loads(res.read())
        finally:
            conn.close()

    def query(self, sql):
        return self.request("POST", "/query", {"sql": sql})


class ApiTest(ServerCase):
    # 대기열을 넉넉히: 클라이언트 20개가 응답을 받자마자 다음 요청을 보내면, 서버가 앞 연결을 정리하기 전이라
    # 기본 한도(작업자 4 + 대기 16 = 20)를 순간적으로 넘겨 503 이 날 수 있다 — 그건 BackpressureTest 가 따로 본다
    queue_limit = 64

    def test_query_round_trip(self):
        status, body = self.query("INSERT INTO users (name, age) VALUES ('김준우', 25), ('lee', 30); SELECT name FROM users WHERE id = 2")
        self.assertEqual(status, 200)
        insert, select = body["results"]
        self.assertEqual((insert["count"], insert["first_id"], insert["last_id"]), (2, 1, 2))
        self.assertEqual((select["rows"], select["plan"]), ([["lee"]], "index-eq (id = 2)"))

    def test_sql_error_has_position_and_earlier_results(self):
        status, body = self.query("INSERT INTO users (name) VALUES ('a');\nSELECT * FROM users WHERE age = 'x'")
        self.assertEqual(status, 400)
        self.assertEqual((body["statement"], body["line"], body["col"]), (2, 2, 27))
        self.assertIn("비교할 수 없습니다", body["error"])
        self.assertEqual(body["results"][0]["count"], 1)

    def test_tables_and_health(self):
        self.query("INSERT INTO products VALUES ('a', 1)")
        status, body = self.request("GET", "/tables")
        self.assertEqual(status, 200)
        self.assertEqual({t["name"]: t["rows"] for t in body["tables"]}, {"products": 1, "users": 0})
        status, body = self.request("GET", "/health")
        self.assertEqual((status, body["ok"], body["workers"]), (200, True, 4))

    def test_routes_and_bad_bodies(self):
        self.assertEqual(self.request("GET", "/nope"), (404, {"error": "없는 경로입니다"}))
        self.assertEqual(self.request("GET", "/query"), (405, {"error": "POST만 지원합니다"}))
        self.assertEqual(self.request("DELETE", "/tables"), (405, {"error": "GET만 지원합니다"}))
        for raw, message in [
            (b"{", "본문이 올바른 JSON이 아닙니다"),
            (b"[]", '본문은 {"sql": "SQL 문장"} 이어야 합니다'),
            (b'{"sql": 1}', '본문은 {"sql": "SQL 문장"} 이어야 합니다'),
            (b'{"sql": "  "}', '본문은 {"sql": "SQL 문장"} 이어야 합니다'),
        ]:
            self.assertEqual(self.request("POST", "/query", raw), (400, {"error": message}), raw)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", "/query")
        conn.endheaders()  # Content-Length 없음
        res = conn.getresponse()
        self.assertEqual((res.status, json.loads(res.read())), (400, {"error": "Content-Length가 올바르지 않습니다"}))
        conn.close()

    def test_body_too_large(self):
        big = json.dumps({"sql": "SELECT * FROM users -- " + "x" * server_module.MAX_BODY}).encode()
        self.assertEqual(self.request("POST", "/query", big), (413, {"error": "요청 본문이 너무 큽니다 (최대 1MB)"}))

    def test_slow_client_gets_408(self):
        original = server_module.REQUEST_TIMEOUT
        server_module.REQUEST_TIMEOUT = 0.3
        self.addCleanup(setattr, server_module, "REQUEST_TIMEOUT", original)
        with socket.create_connection(("127.0.0.1", self.port)) as c:
            c.sendall(b"POST /query HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{")
            c.settimeout(5)
            self.assertIn(b" 408 ", c.recv(200))

    def test_large_select_is_truncated(self):
        values = ", ".join(f"('u{i}')" for i in range(server_module.MAX_ROWS + 5))
        self.query(f"INSERT INTO users (name) VALUES {values}")
        status, body = self.query("SELECT id FROM users")
        r = body["results"][0]
        self.assertEqual((status, r["count"], r["total"], r["truncated"]), (200, server_module.MAX_ROWS, server_module.MAX_ROWS + 5, True))

    def test_concurrent_inserts_through_pool(self):
        errors = []

        def client(t):
            for i in range(25):
                status, body = self.query(f"INSERT INTO users (name) VALUES ('t{t}-{i}')")
                if status != 200:
                    errors.append(body)

        threads = [threading.Thread(target=client, args=(t,)) for t in range(20)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        status, body = self.query("SELECT id FROM users ORDER BY id")
        self.assertEqual(body["results"][0]["total"], 500)
        self.assertEqual([r[0] for r in self.engine.execute_all("SELECT id FROM users")[0]["rows"]], list(range(1, 501)))  # 빠짐 · 겹침 없음
        self.assertEqual(len((self.dir / "users.jsonl").read_bytes().splitlines()), 500)


class BackpressureTest(ServerCase):
    workers, queue_limit = 1, 0  # 작업자 1개 · 기다리는 자리 0 → 작업자가 바쁘면 바로 503

    def test_full_pool_returns_503(self):
        original = server_module.REQUEST_TIMEOUT
        server_module.REQUEST_TIMEOUT = 1.5
        self.addCleanup(setattr, server_module, "REQUEST_TIMEOUT", original)
        slow = socket.create_connection(("127.0.0.1", self.port))  # 아무것도 안 보내는 클라이언트가 작업자 하나를 붙잡는다
        self.addCleanup(slow.close)
        deadline = time.monotonic() + 2
        while self.server.pool_status()["busy"] == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.request("GET", "/health")[0], 503)
        time.sleep(1.6)  # 느린 클라이언트가 408 로 끝나면 작업자가 풀린다
        self.assertEqual(self.request("GET", "/health")[0], 200)


if __name__ == "__main__":
    unittest.main()
