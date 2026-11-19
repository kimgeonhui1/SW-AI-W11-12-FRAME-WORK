# [server.py] 미니 DBMS API 서버 (Phase 3) — 외부 클라이언트가 HTTP로 SQL을 보내면, 스레드 풀의 작업자가 엔진으로 실행한다
#
#   python -m minidb.server                                  (DB 폴더 data, 127.0.0.1:8080, 작업자 8개, 큐 64칸)
#   python -m minidb.server --db mydb --port 9000 --workers 16 --queue 128
#
#   POST /query   본문 {"sql": "SELECT * FROM users WHERE id = 3;"}
#     → 200 {"results": [{"columns": [...], "rows": [[...]], "message": "1개 행 (인덱스 사용)", "plan": "index"}]}
#     → 400 {"error": "문법 오류: ..."}                                   (아무 문장도 실행하지 않음)
#     → 400 {"error": "실행 오류 (2번째 문장, 줄 2): ...", "results": [앞 문장 결과]}   (앞 문장의 INSERT는 저장됨)
#   GET  /health  → 200 {"status": "ok"}
#   그 밖: 404 없는 경로 / 405 지원 안 하는 메서드 / 408 본문을 제때 안 보냄 / 411 chunked / 413 1MB 초과 /
#         500 파일 손상 등 서버 오류 / 501 모르는 메서드 / 503 작업 큐가 꽉 참. 오류는 모두 {"error": "이유"}
#
# ■ 구조
#   [접속 받는 스레드] accept → 스레드 풀에 "이 연결을 처리하라" 넣기 (꽉 찼으면 바로 503 후 닫기)
#   [작업자 스레드 N개] 큐에서 연결을 꺼내 → 요청 읽기 → 엔진.execute(sql) → JSON 응답 → 연결 닫기
#
# ■ 요청 하나마다 연결을 닫는다(HTTP/1.0). 연결을 유지(keep-alive)하면 쉬는 연결이 작업자를 붙잡아, 작업자 N개가
#   쉬는 연결 N개에 묶이면 서버가 멈춘다 (공부 6번). 연결이 끝나면 남은 본문도 함께 사라져 요청이 섞일 일도 없다

import argparse
import json
import os
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from .engine import Engine, StatementError
from .executor import ExecutionError
from .storage import SchemaError
from .threadpool import ThreadPool
from .tokenizer import SqlSyntaxError

MAX_BODY = 1024 * 1024  # 요청 본문 최대 1MB
REQUEST_TIMEOUT = 10  # 요청을 다 받을 때까지 기다리는 최대 시간(초). 보내다 멈춘 클라이언트가 작업자를 영원히 붙잡지 못하게
_BUSY = json.dumps({"error": "서버가 바쁩니다 (작업 큐가 꽉 참). 잠시 뒤 다시 시도하세요"}, ensure_ascii=False).encode("utf-8")
_BUSY_RESPONSE = (b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
                  b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(_BUSY)) + _BUSY


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class PooledHTTPServer(HTTPServer):
    """요청(연결)을 직접 처리하지 않고 스레드 풀에 넘기는 HTTP 서버"""

    request_queue_size = 128  # 아직 받지 못한 연결의 대기열 (기본 5면 동시 접속 수십 개에서 거부된다: Mini Redis에서 겪은 일)
    allow_reuse_address = os.name != "nt"  # Windows에서는 켜면 같은 포트에 서버 두 개가 떠 버린다 (Mini Redis에서 겪은 일)

    def __init__(self, address, engine, pool):
        self.engine = engine
        self.pool = pool
        super().__init__(address, Handler)

    # accept한 연결마다 불린다 (접속 받는 스레드). 원래는 여기서 바로 처리하지만, 작업자에게 넘긴다
    def process_request(self, request, client_address):
        if not self.pool.submit(self._handle, request, client_address):
            try:
                request.sendall(_BUSY_RESPONSE)  # 새 연결의 송신 버퍼에 들어가므로 접속 받는 스레드가 멈추지 않는다
            except OSError:
                pass
            self.shutdown_request(request)

    # 작업자 스레드에서 실행: 요청 하나를 처리하고 연결을 닫는다 (socketserver.ThreadingMixIn이 스레드 안에서 하는 일과 같다)
    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def handle_error(self, request, client_address):
        pass  # 응답 도중 클라이언트가 끊는 등은 서버 콘솔에 traceback을 찍지 않는다 (작업자는 계속 일한다)


class Handler(BaseHTTPRequestHandler):
    timeout = REQUEST_TIMEOUT  # 소켓 읽기 제한 시간 (요청 줄 · 헤더 · 본문 모두)
    server_version = "MiniDBMS/1.0"

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    # 아는 메서드지만 경로에 맞지 않으면 405 (do_*가 없는 메서드는 send_error의 501)
    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def _dispatch(self, method):
        try:
            status, body = self._route(method)
        except ApiError as e:
            status, body = e.status, {"error": str(e)}
        except Exception:  # 예상 못 한 오류도 서버는 죽지 않고 이 요청만 500
            status, body = 500, {"error": "서버 내부 오류"}
        self._send(status, body)

    def _route(self, method):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            if method != "GET":
                raise ApiError(405, "GET만 지원합니다")
            return 200, {"status": "ok"}
        if path != "/query":
            raise ApiError(404, "없는 경로입니다 (POST /query 또는 GET /health)")
        if method != "POST":
            raise ApiError(405, "POST만 지원합니다")
        sql = self._read_sql()
        try:
            results = self.server.engine.execute(sql)
        except SqlSyntaxError as e:
            raise ApiError(400, f"문법 오류: {e}")
        except StatementError as e:
            done = [_result_json(r) for r in e.results]
            if isinstance(e.cause, ExecutionError):  # 요청이 잘못됨 (없는 테이블, 타입 불일치 등)
                return 400, {"error": f"실행 오류: {e}", "results": done}
            return 500, {"error": f"서버 오류: {e}", "results": done}  # 파일 손상 · 디스크 오류 등 서버 쪽 문제
        return 200, {"results": [_result_json(r) for r in results]}

    # 본문 {"sql": "..."}에서 SQL 문자열을 꺼낸다. 여기가 신뢰 경계: 밖에서 오는 것은 무엇이든 올 수 있다
    def _read_sql(self):
        if "Transfer-Encoding" in self.headers:
            raise ApiError(411, "Content-Length로 본문 길이를 알려 주세요 (chunked 전송은 지원하지 않습니다)")
        lengths = self.headers.get_all("Content-Length") or []
        raw_length = lengths[0].strip() if len(lengths) == 1 else ""
        # 숫자 하나만: "+12" · "1_2" · 빈 값 · 헤더 두 개는 거부 (Mini Redis 리뷰에서 배운 규칙)
        if not (raw_length.isascii() and raw_length.isdigit()) or len(raw_length) > 12:
            raise ApiError(400, "Content-Length가 올바르지 않습니다 (숫자 하나)")
        length = int(raw_length)
        if length > MAX_BODY:
            _discard(self.rfile, length)  # 안 읽고 바로 닫으면 Windows에서 클라이언트가 413을 못 받고 "연결 끊김"을 본다
            raise ApiError(413, "요청 본문이 너무 큽니다 (최대 1MB)")
        try:
            raw = self.rfile.read(length)
        except (TimeoutError, socket.timeout):  # 파이썬 3.9까지는 socket.timeout이 TimeoutError가 아니다
            raise ApiError(408, "요청 본문을 제한 시간 안에 다 받지 못했습니다")
        if len(raw) != length:  # 덜 보내고 연결을 닫은 요청: 잘린 본문이 우연히 올바른 JSON이어도 받지 않는다
            raise ApiError(400, "본문이 Content-Length보다 짧습니다")
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError):  # JSON이 아님, UTF-8이 아님, 너무 깊은 중첩
            raise ApiError(400, '본문은 JSON {"sql": "..."} 이어야 합니다')
        if not isinstance(body, dict) or not isinstance(body.get("sql"), str):
            raise ApiError(400, '본문은 JSON {"sql": "..."} 이어야 합니다 (sql은 문자열)')
        try:
            # "\ud800"(짝 없는 반쪽 문자)은 JSON으로는 통과하지만 파일(UTF-8)에 쓸 수 없다 → 처음부터 거부 (Mini Redis에서 배운 것)
            body["sql"].encode("utf-8")
        except UnicodeEncodeError:
            raise ApiError(400, "UTF-8로 표현할 수 없는 문자(짝 없는 서로게이트)가 들어 있습니다")
        return body["sql"]

    def _send(self, status, body):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except ConnectionError:
            pass  # 클라이언트가 응답 전에 끊었다. 보낼 곳이 없으니 조용히 끝낸다

    # HEAD · TRACE처럼 do_*가 없는 메서드, 깨진 요청 줄, 너무 긴 주소: 기본은 HTML 에러 페이지 → JSON으로
    def send_error(self, code, message=None, explain=None):
        if code == 501:
            message = f"지원하지 않는 메서드입니다: {self.command}"
        self._send(code, {"error": message or "잘못된 요청입니다"})

    def log_message(self, format, *args):
        pass  # 요청마다 콘솔에 찍지 않는다


# 너무 큰 본문을 최대 16MB까지 64KB씩 읽어서 버린다 (그보다 크면 더 기다리지 않고 닫는다)
def _discard(rfile, length):
    remaining = min(length, 16 * 1024 * 1024)
    try:
        while remaining > 0:
            chunk = rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
    except OSError:  # 시간 초과 · 끊김 (TimeoutError도 OSError)
        pass


def _result_json(result):
    return {"columns": result.columns, "rows": result.rows, "message": result.message, "plan": result.plan}


# 엔진 · 스레드 풀 · 서버를 만든다 (port=0이면 빈 포트 → 테스트용). 끌 때는 stop_server(server)
def create_server(directory, host="127.0.0.1", port=8080, workers=8, queue_size=64):
    engine = Engine(directory)
    try:
        pool = ThreadPool(workers, queue_size)
    except ValueError:
        engine.close()
        raise
    try:
        return PooledHTTPServer((host, port), engine, pool)
    except BaseException:
        pool.stop()
        engine.close()
        raise


# 끄는 순서: 새 연결 받기 중단 → 큐에 쌓인 요청까지 처리하고 작업자 멈춤 → 테이블 파일 닫기
def stop_server(server):
    server.server_close()
    server.pool.stop()
    server.engine.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m minidb.server", description="미니 DBMS API 서버 (스레드 풀)")
    parser.add_argument("--db", default="data", help="DB 폴더 (기본값: data)")
    parser.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1: 같은 컴퓨터에서만 접속된다")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--workers", type=int, default=8, help="작업자 스레드 수 (기본 8)")
    parser.add_argument("--queue", type=int, default=64, help="작업 큐 크기 (기본 64, 꽉 차면 503)")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:  # 범위 밖이면 bind가 OSError가 아닌 OverflowError를 낸다
        parser.error("--port는 0~65535 사이여야 합니다")
    try:
        server = create_server(args.db, args.host, args.port, args.workers, args.queue)
    except (SchemaError, ValueError) as e:
        parser.exit(1, f"오류: {e}\n")
    except OSError as e:
        parser.exit(1, f"{args.host}:{args.port}에서 서버를 열 수 없습니다: {e}\n")
    print(f"미니 DBMS API 서버: http://{args.host}:{server.server_address[1]}  (작업자 {args.workers}개, 큐 {args.queue}칸)")
    print(f"예) curl -X POST http://127.0.0.1:{server.server_address[1]}/query -d '{{\"sql\": \"SELECT * FROM users\"}}'")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다 (Ctrl+C)", file=sys.stderr)
    finally:
        stop_server(server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
