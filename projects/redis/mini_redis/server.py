# [server.py] Mini Redis HTTP JSON API — 외부 프로그램이 HTTP로 저장소를 사용
#
#   GET    /keys/{key}          값 조회        → 200 {"key", "value", "ttl"} / 404
#   PUT    /keys/{key}          값 저장        body {"value": ..., "ttl": 초(선택)} → 200 {"ok": true}
#   DELETE /keys/{key}          삭제(무효화)    → 200 {"deleted": true/false}
#   GET    /keys/{key}/ttl      남은 만료 시간  → 200 {"ttl": 초 | -1(만료 없음) | -2(키 없음)}
#   POST   /keys/{key}/expire   만료 시간 설정  body {"ttl": 초} → 200 {"ok": true} / 404
#   GET    /health              상태 확인      → 200 {"keys": 저장된 키 수}
#
# 키에 "/" 같은 특수문자가 있으면 URL 인코딩해서 보낸다 (예: "char:a/b" → /keys/char%3Aa%2Fb)
# 빈 문자열 키는 HTTP API에서 지원하지 않는다 (/keys/ 는 404). 저장소(MiniRedis) 자체는 빈 키도 받는다
# 에러 응답은 모두 {"error": "이유"} 모양이다 (400 잘못된 요청 / 404 없음 / 405 지원 안 하는 메서드 / 408 본문 수신 시간 초과 / 413 너무 큼 / 500 서버 오류)
#
# 실행: projects/redis 에서  python -m mini_redis.server --port 6380

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from .store import MiniRedis

MAX_BODY = 1024 * 1024  # 요청 본문 최대 1MB. 너무 큰 요청으로 서버 메모리를 다 쓰는 것을 막는다
REQUEST_TIMEOUT = 10  # 요청을 다 받을 때까지 기다리는 최대 시간(초). 본문을 덜 보내고 멈춘 클라이언트가 스레드를 영원히 붙잡지 못하게 한다
SWEEP_INTERVAL = 1.0  # 만료 키 정리(주기 삭제) 간격(초)


class ApiError(Exception):
    """응답 상태 코드를 담은 에러. 핸들러 어디서 던져도 _dispatch가 {"error": ...} 응답으로 바꾼다"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def make_handler(store):
    # 요청 하나마다 Handler 객체가 새로 만들어진다 (ThreadingHTTPServer라서 요청마다 스레드도 하나씩)
    # → 저장소 store는 여러 스레드가 함께 쓰지만, store 안의 락이 명령을 하나씩만 실행되게 한다
    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT  # 소켓 읽기 제한 시간 (BaseHTTPRequestHandler가 연결 소켓에 적용한다)

        def do_GET(self):
            self._dispatch("GET")

        # 지원하지 않는 메서드도 기본 HTML 501 대신 JSON 405로 답한다 (모든 응답은 JSON이라는 약속)
        def do_PATCH(self):
            self._dispatch("PATCH")

        def do_OPTIONS(self):
            self._dispatch("OPTIONS")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            try:
                status, body = self._route(method)
            except ApiError as e:
                status, body = e.status, {"error": str(e)}
            except Exception:  # 예상 못한 오류도 서버가 죽지 않고 500으로 응답한다
                status, body = 500, {"error": "서버 내부 오류"}
            self._send(status, body)

        def _route(self, method):
            # 경로를 "/"로 먼저 나눈 뒤 조각마다 디코딩한다 → 키 안의 %2F("/")가 경로 구분자로 오해되지 않는다
            path = self.path.split("?", 1)[0]
            parts = [unquote(p) for p in path.strip("/").split("/")]

            if parts == ["health"]:
                if method != "GET":
                    raise ApiError(405, "GET만 지원합니다")
                return 200, {"keys": len(store)}
            if len(parts) not in (2, 3) or parts[0] != "keys" or parts[1] == "":
                raise ApiError(404, "없는 경로입니다")

            key = parts[1]
            action = parts[2] if len(parts) == 3 else None

            if action is None:
                if method == "GET":
                    # 값과 ttl을 락 하나 안에서 함께 읽는다 (따로 읽으면 그 사이에 끼어든 요청 때문에 둘이 어긋날 수 있다)
                    value, ttl = store.get_with_ttl(key)
                    if value is None:  # PUT에서 null 저장을 막아 두어서, None = "없거나 만료됨"이 확실하다
                        raise ApiError(404, "키가 없습니다")
                    return 200, {"key": key, "value": value, "ttl": ttl}
                if method == "PUT":
                    body = self._read_json()
                    if body.get("value") is None:
                        raise ApiError(400, "value가 필요합니다 (null은 저장할 수 없습니다)")
                    self._call(store.set, key, body["value"], body.get("ttl"))
                    return 200, {"ok": True}
                if method == "DELETE":
                    return 200, {"deleted": store.delete(key)}
                raise ApiError(405, "GET / PUT / DELETE만 지원합니다")

            if action == "ttl":
                if method != "GET":
                    raise ApiError(405, "GET만 지원합니다")
                return 200, {"ttl": store.ttl(key)}
            if action == "expire":
                if method != "POST":
                    raise ApiError(405, "POST만 지원합니다")
                body = self._read_json()
                if "ttl" not in body:
                    raise ApiError(400, "ttl이 필요합니다")
                if not self._call(store.expire, key, body["ttl"]):
                    raise ApiError(404, "키가 없습니다")
                return 200, {"ok": True}
            raise ApiError(404, "없는 경로입니다")

        # 저장소 명령 실행. 저장소가 잘못된 값(ttl 등)으로 ValueError를 내면 400으로 바꾼다 (검증 규칙은 store 한 곳에서만 관리)
        def _call(self, fn, *args):
            try:
                return fn(*args)
            except ValueError as e:
                raise ApiError(400, str(e))

        def _read_json(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ApiError(400, "Content-Length가 올바르지 않습니다")
            if length < 0:
                raise ApiError(400, "Content-Length가 올바르지 않습니다")
            if length > MAX_BODY:
                raise ApiError(413, "요청 본문이 너무 큽니다 (최대 1MB)")
            try:
                raw = self.rfile.read(length)
            except TimeoutError:
                raise ApiError(408, "요청 본문을 제한 시간 안에 다 받지 못했습니다")
            try:
                # parse_constant: 파이썬 json은 NaN / Infinity를 기본으로 받아들이는데, 표준 JSON이 아니라서
                # 저장 후 응답에 그대로 나가면 다른 언어의 클라이언트가 응답을 읽지 못한다 → 처음부터 거부
                body = json.loads(raw or b"{}", parse_constant=_reject_constant)
            except ValueError:  # JSONDecodeError, UnicodeDecodeError, _reject_constant 모두 ValueError 계열
                raise ApiError(400, "본문이 올바른 JSON이 아닙니다 (NaN / Infinity 불가)")
            except RecursionError:  # [[[[...]]]]처럼 너무 깊게 중첩되면 파서가 재귀 한도를 넘는다 → 서버 오류가 아니라 잘못된 요청
                raise ApiError(400, "JSON이 너무 깊게 중첩되어 있습니다")
            if not isinstance(body, dict):
                raise ApiError(400, "본문은 JSON 객체({...})여야 합니다")
            # "\ud800" 같은 짝 없는 반쪽 문자는 JSON 문법으로는 통과하지만 UTF-8로 바꿀 수 없어서, 저장하면 나중에 응답을 못 보낸다 → 처음부터 거부
            try:
                json.dumps(body, ensure_ascii=False).encode("utf-8")
            except UnicodeEncodeError:
                raise ApiError(400, "UTF-8로 표현할 수 없는 문자(짝 없는 서로게이트)가 들어 있습니다")
            return body

        def _send(self, status, body):
            try:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            except UnicodeEncodeError:
                # 파이썬 코드로 직접 저장된 반쪽 문자 등이 있어도 응답은 반드시 나가게: 모든 비ASCII를 \uXXXX로 적는 방식으로 다시 만든다
                data = json.dumps(body).encode("ascii")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            pass  # 요청마다 콘솔에 찍지 않는다 (성능 측정에 출력 비용이 섞이지 않게)

    return Handler


def _reject_constant(name):
    raise ValueError(f"{name}은(는) 표준 JSON 값이 아닙니다")


# 저장소를 감싼 HTTP 서버 객체 생성 (port=0이면 빈 포트를 자동으로 고른다 → 테스트용)
# 주기 삭제 스레드도 함께 시작하고, server_close() 때 같이 멈춘다
def create_server(store, host="127.0.0.1", port=6380):
    server = ThreadingHTTPServer((host, port), make_handler(store))
    stop = threading.Event()

    def sweeper():
        # wait()는 SWEEP_INTERVAL만큼 기다리다가, stop이 켜지면 바로 깨어나 반복을 끝낸다
        while not stop.wait(SWEEP_INTERVAL):
            store.sweep()

    threading.Thread(target=sweeper, daemon=True).start()
    original_close = server.server_close

    def server_close():
        stop.set()
        original_close()

    server.server_close = server_close
    return server


# 명령줄 실행 시작점
def main():
    parser = argparse.ArgumentParser(description="Mini Redis HTTP 서버")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6380)
    args = parser.parse_args()
    server = create_server(MiniRedis(), args.host, args.port)
    print(f"Mini Redis listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
