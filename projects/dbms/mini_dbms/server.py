# [server.py] 미니 DBMS API 서버 (Phase 3) — 스레드 풀이 HTTP 요청을 나눠 처리하고, 안에서는 Engine 하나를 함께 쓴다
#
#   POST /query    {"sql": "SELECT …; INSERT …"}  → 200 {"results": [결과, …]}
#                  SQL 오류 → 400 {"error", "line", "col", "statement", "results": 오류 전 문장들의 결과}
#   GET  /tables   → 200 {"tables": [{"name", "columns", "rows"}, …]}
#   GET  /health   → 200 {"ok": true, "workers", "busy", "queued"}
#   그 밖: 404 없는 경로 · 405 메서드 · 408 본문을 제때 안 보냄 · 413 본문 1MB 초과 · 503 대기열 가득 · 500 — 모든 응답은 JSON
#   SELECT 결과는 최대 MAX_ROWS 행까지만 담는다. 넘으면 "truncated": true, "total": 전체 행 수 (응답이 수백 MB 가 되지 않게)
#
# ■ 스레드 풀
#   표준 ThreadingHTTPServer 는 요청마다 스레드를 새로 만든다 — 과제가 말하는 "스레드 풀" 이 아니다.
#   그래서 HTTPServer 의 process_request(연결 하나를 처리하는 곳)를 바꿔, 연결을 미리 만들어 둔 스레드 N 개
#   (concurrent.futures.ThreadPoolExecutor) 에 넘긴다:
#
#     메인 스레드: accept() → 대기열이 가득? ─예→ 503 보내고 닫기
#                                      └아니오→ pool.submit(연결)
#     작업 스레드 1..N: 요청 읽기 → Engine.run(sql) → JSON 응답 → 연결 닫기 → 다음 연결
#
# ■ 대기열 한도(백프레셔): 작업 중 + 기다리는 연결이 workers + queue_limit 을 넘으면 바로 503.
#   한도가 없으면 몰릴 때 기다리는 연결이 끝없이 쌓여 메모리 · 응답 시간이 끝없이 는다.
# ■ 응답마다 연결을 닫는다 (HTTP/1.0). 연결을 재사용(keep-alive)하면 쉬는 연결 하나가 작업자 하나를 붙잡고 있어서,
#   쉬는 클라이언트 N 명이 풀 전체를 막는다. 풀 크기가 정해진 서버에서는 닫는 쪽이 안전하다.
# ■ 동시성: 엔진의 테이블 락이 맡는다 (SELECT 는 동시에, INSERT 는 혼자). 서버는 락을 모른다.
# ■ GIL: 파이썬은 한 번에 한 스레드만 파이썬 코드를 실행한다. 그래도 소켓 · 파일을 기다리는 동안에는 다른 스레드가 돈다.
#   작업자 수별 처리량은 bench 에서 측정한다.
#
# 실행: projects/dbms 에서  python -m mini_dbms.server --port 8080 --workers 8

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer

from .cli import DEFAULT_DATA
from .engine import Engine
from .errors import DataError, SqlError

MAX_BODY = 1024 * 1024  #       요청 본문 최대 1MB
MAX_DISCARD = 16 * 1024 * 1024  # 413 전에 읽어서 버릴 최대 크기 (안 읽고 닫으면 클라이언트가 413 대신 Connection reset 을 본다)
REQUEST_TIMEOUT = 10  #         요청을 다 받을 때까지 기다리는 최대 초 — 보내다 멈춘 클라이언트가 작업자를 영원히 붙잡지 못하게
MAX_ROWS = 1000  #              SELECT 응답에 담는 최대 행 수
# 위 값들은 요청마다 다시 읽으므로 테스트가 모듈 값을 바꾸면 바로 적용된다


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(body)
        self.status = status
        self.body = body if isinstance(body, dict) else {"error": body}


class Handler(BaseHTTPRequestHandler):
    # protocol_version 기본값 HTTP/1.0 → 응답 하나 뒤 연결을 닫는다 (위 설명)

    def setup(self):
        self.timeout = REQUEST_TIMEOUT
        super().setup()

    def _handle(self):
        try:
            status, body = self._route(self.command, self.path.split("?", 1)[0])
        except ApiError as e:
            status, body = e.status, e.body
        except Exception:  # 예상 못 한 오류도 이 요청만 500 으로 끝나고 서버는 계속 돈다
            status, body = 500, {"error": "서버 내부 오류"}
        self._send(status, body)

    # 표준 라이브러리는 "do_" + 메서드 이름 함수를 부른다 → 모두 _handle 로. PUT 등도 받아 HTML 501 대신 JSON 405 로 답한다
    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _handle

    def _route(self, method, path):
        server = self.server
        routes = {"/query": "POST", "/tables": "GET", "/health": "GET"}
        if path not in routes:
            raise ApiError(404, "없는 경로입니다")
        if method != routes[path]:
            raise ApiError(405, f"{routes[path]}만 지원합니다")
        if path == "/health":
            return 200, {"ok": True, **server.pool_status()}
        if path == "/tables":
            return 200, {"tables": server.engine.describe_tables()}
        sql = self._read_sql()
        results = []
        try:
            for result in server.engine.run(sql, max_rows=MAX_ROWS):
                results.append(result)
        except SqlError as e:
            raise ApiError(400, {**e.to_dict(), "results": results})
        return 200, {"results": results}

    def _read_sql(self):
        """본문 {"sql": "…"} 을 읽어 SQL 글자를 돌려준다. 잘못되면 ApiError"""
        length = self.headers.get("Content-Length", "")
        if not (length.isascii() and length.isdigit()):
            raise ApiError(400, "Content-Length가 올바르지 않습니다")
        length = int(length)
        if length > MAX_BODY:
            self._discard(length)
            raise ApiError(413, "요청 본문이 너무 큽니다 (최대 1MB)")
        try:
            raw = self.rfile.read(length)
        except TimeoutError:
            raise ApiError(408, "요청 본문을 제한 시간 안에 다 받지 못했습니다")
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError):
            raise ApiError(400, "본문이 올바른 JSON이 아닙니다")
        if not isinstance(body, dict) or not isinstance(body.get("sql"), str) or not body["sql"].strip():
            raise ApiError(400, '본문은 {"sql": "SQL 문장"} 이어야 합니다')
        return body["sql"]

    def _discard(self, length):
        left = min(length, MAX_DISCARD)
        try:
            while left > 0 and (chunk := self.rfile.read(min(left, 64 * 1024))):
                left -= len(chunk)
        except TimeoutError:
            pass

    def _send(self, status, body):
        try:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError:  # 짝 없는 반쪽 문자가 든 값 → 모든 비ASCII 를 \uXXXX 로 적어 응답은 반드시 나가게
            data = json.dumps(body).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass  # 요청마다 콘솔에 찍지 않는다 (처리량 측정에 출력 비용이 섞이지 않게)


class PoolHTTPServer(HTTPServer):
    """연결을 스레드 풀에 넘기는 HTTP 서버"""

    request_queue_size = 128  # 운영체제 연결 대기열 (기본 5 면 동시 접속이 몰릴 때 연결이 끊긴다 — Mini Redis 에서 겪은 문제)

    def __init__(self, engine, address, workers=8, queue_limit=None):
        super().__init__(address, Handler)
        self.engine = engine
        self.workers = workers
        self.queue_limit = workers * 4 if queue_limit is None else queue_limit
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dbms-worker")
        self._count_lock = threading.Lock()
        self._pending = 0  # 풀에 넘긴 뒤 아직 끝나지 않은 연결 (작업 중 + 기다리는 중)
        self._busy = 0  #    지금 작업 스레드가 처리 중인 연결

    def pool_status(self):
        with self._count_lock:
            return {"workers": self.workers, "busy": self._busy, "queued": self._pending - self._busy}

    def process_request(self, request, client_address):
        """메인 스레드가 accept 한 연결 하나 → 풀에 넘기거나, 가득 찼으면 503"""
        with self._count_lock:
            full = self._pending >= self.workers + self.queue_limit
            if not full:
                self._pending += 1
        if full:
            self._reject(request)
            return
        self.pool.submit(self._work, request, client_address)

    def _work(self, request, client_address):
        with self._count_lock:
            self._busy += 1
        try:
            self.finish_request(request, client_address)  # Handler 를 만들어 요청 하나를 처리
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)
            with self._count_lock:
                self._busy -= 1
                self._pending -= 1

    def _reject(self, request):
        """대기열 가득 → 503 을 바로 보내고 닫는다 (메인 스레드에서, 짧게)"""
        body = json.dumps({"error": "서버가 바쁩니다. 잠시 뒤 다시 시도하세요"}, ensure_ascii=False).encode("utf-8")
        head = f"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {len(body)}\r\n\r\n"
        try:
            request.settimeout(0.5)
            request.recv(64 * 1024)  # 이미 온 요청을 읽어 둔다 — 안 읽고 닫으면 클라이언트가 응답 대신 Connection reset 을 본다
            request.sendall(head.encode("ascii") + body)
        except OSError:
            pass
        self.shutdown_request(request)

    def server_close(self):
        super().server_close()
        self.pool.shutdown(wait=True)  # 진행 중인 요청은 끝까지 처리한다


def create_server(engine, host="127.0.0.1", port=8080, workers=8, queue_limit=None):
    """port=0 이면 빈 포트를 고른다 (테스트용)"""
    return PoolHTTPServer(engine, (host, port), workers, queue_limit)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m mini_dbms.server", description="미니 DBMS API 서버")
    parser.add_argument("--host", default="127.0.0.1", help="기본은 이 컴퓨터에서만 접속 (인증이 없으므로)")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--workers", type=int, default=8, help="스레드 풀 크기")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers 는 1 이상이어야 합니다")
    try:
        engine = Engine(args.data)
    except DataError as e:
        raise SystemExit(f"데이터를 열 수 없습니다: {e}")
    for warning in engine.warnings:
        print(f"경고: {warning}")
    try:
        server = create_server(engine, args.host, args.port, args.workers)
    except OSError as e:
        engine.close()
        raise SystemExit(f"{args.host}:{args.port} 에서 서버를 열 수 없습니다: {e}")
    print(f"미니 DBMS API: http://{args.host}:{args.port}  (작업자 {args.workers}개 · 테이블 {', '.join(engine.tables)})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()


if __name__ == "__main__":
    main()
