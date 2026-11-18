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
# 에러 응답은 모두 {"error": "이유"} 모양이다
#   (400 잘못된 요청 / 404 없음 / 405 지원 안 하는 메서드 / 408 본문 수신 시간 초과 / 411 Content-Length 없는 chunked 본문 / 413 너무 큼 / 417 모르는 Expect / 500 서버 오류 / 503 동시 연결 수 초과)
#
# 실행: projects/redis 에서  python -m mini_redis.server --port 6380
#       (기본으로 data/dump.json에 60초마다 스냅샷을 저장하고, 켤 때 복구한다. --snapshot "" 로 끌 수 있다)

import argparse
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from .persistence import SnapshotError, load_snapshot, start_periodic_snapshot
from .store import MiniRedis

MAX_BODY = 1024 * 1024  # 요청 본문 최대 1MB. 너무 큰 요청으로 서버 메모리를 다 쓰는 것을 막는다
DISCARD_LIMIT = 16 * 1024 * 1024  # 413 응답 전에 읽어서 버려 줄 최대 크기 (아래 _discard_body 참고)
REQUEST_TIMEOUT = 10  # 요청을 다 받을 때까지 기다리는 최대 시간(초). 본문을 덜 보내고 멈춘 클라이언트가 스레드를 영원히 붙잡지 못하게 한다
SWEEP_INTERVAL = 1.0  # 만료 키 정리(주기 삭제) 간격(초)
# 값의 중첩 깊이 상한 ([[[...]]] 또는 {"a": {"a": ...}}). 실제 RedisJSON의 기본 상한도 128이다.
# 상한이 없으면 깊이 1000 이상인 값도 저장되는데, 스냅샷 저장(json.dump)이 RecursionError로 매번 실패해
# 다른 키까지 디스크에 남지 않았다 (전체 점검에서 재현)
MAX_DEPTH = 128
MAX_CLIENTS = 256  # Mini Redis 서버의 동시 연결 상한 (아래 SafeThreadingHTTPServer.max_clients). 실제 Redis 기본값은 10000
_BUSY_BODY = json.dumps({"error": "연결이 너무 많습니다 (최대 연결 수 초과)"}, ensure_ascii=False).encode("utf-8")
_TOO_MANY_CLIENTS = (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json; charset=utf-8\r\n"
                     b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(_BUSY_BODY)) + _BUSY_BODY


class SafeThreadingHTTPServer(ThreadingHTTPServer):
    """요청마다 스레드를 쓰는 HTTP 서버. Windows에서만 SO_REUSEADDR를 끈다.
    Windows의 SO_REUSEADDR는 "이미 다른 서버가 쓰는 포트에도 또 묶기"를 허용해서, 같은 포트로 서버를 두 번 켜면
    에러 없이 둘 다 떠 버린다(요청이 어느 쪽으로 갈지 모름). 끄면 두 번째 서버는 "포트 사용 중" 에러로 멈춘다.
    리눅스·맥에서는 SO_REUSEADDR가 "방금 끈 서버의 포트를 바로 다시 쓰기"만 허용하므로 그대로 둔다."""

    allow_reuse_address = os.name != "nt"
    # 아직 accept하지 못한 연결을 줄 세워 둘 수 있는 수 (listen backlog). 기본값 5면 클라이언트 수십 명이 동시에 연결할 때
    # 대기열이 넘쳐 운영체제가 연결을 거부한다 (동시 50명 벤치마크에서 WinError 10061로 재현). 실제 Redis 기본값(tcp-backlog)은 511
    request_queue_size = 128
    # 동시에 열어 둘 수 있는 연결 수 상한 (None = 제한 없음). 연결마다 스레드 하나라서, 연결을 열어 두기만 하는 클라이언트가
    # 많으면 스레드가 끝없이 늘어난다. 넘치면 503으로 바로 거절한다 (실제 Redis의 maxclients와 같은 역할)
    max_clients = None

    def __init__(self, *args, **kwargs):
        self._clients = set()  # 지금 처리 중인 연결 (요청 소켓)
        self._clients_lock = threading.Lock()
        super().__init__(*args, **kwargs)

    # accept한 연결마다 불린다 (accept 스레드). 상한을 넘으면 스레드를 만들지 않고 503 응답 후 닫는다
    def process_request(self, request, client_address):
        if self.max_clients is not None:
            with self._clients_lock:
                full = len(self._clients) >= self.max_clients
                if not full:
                    self._clients.add(request)
            if full:
                try:
                    request.sendall(_TOO_MANY_CLIENTS)  # 새 연결의 송신 버퍼에 들어가므로 accept 스레드가 멈추지 않는다
                except OSError:
                    pass
                self.shutdown_request(request)
                return
        try:
            super().process_request(request, client_address)
        except BaseException as e:
            # 스레드 시작 실패. Exception이면 socketserver가 shutdown_request를 불러 주지만, BaseException(KeyboardInterrupt 등)은
            # 그대로 올라가 자리와 소켓이 남았다 (Gemini 리뷰로 재현) → 여기서 돌려준다 (두 번 불려도 안전하다)
            if not isinstance(e, Exception):
                self.shutdown_request(request)
            raise

    # 연결 처리가 끝나면(요청 스레드) 불린다 → 자리를 돌려준다
    def shutdown_request(self, request):
        with self._clients_lock:
            self._clients.discard(request)
        super().shutdown_request(request)

    # 서버를 닫을 때 열려 있는 연결도 끊는다. 듣는 소켓만 닫으면, 다음 요청을 기다리던 연결의 스레드가
    # REQUEST_TIMEOUT(10초)까지 남아 있었다 (Gemini 리뷰로 재현). 끊으면 그 스레드는 "요청 없음"을 받고 바로 끝난다
    def server_close(self):
        super().server_close()
        with self._clients_lock:
            clients = list(self._clients)
        for request in clients:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class ApiError(Exception):
    """응답 상태 코드를 담은 에러. 핸들러 어디서 던져도 _dispatch가 {"error": ...} 응답으로 바꾼다"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def make_handler(store):
    # 요청 하나마다 Handler 객체가 새로 만들어진다 (ThreadingHTTPServer라서 요청마다 스레드도 하나씩)
    # → 저장소 store는 여러 스레드가 함께 쓰지만, store 안의 락이 명령을 하나씩만 실행되게 한다
    class Handler(BaseHTTPRequestHandler):
        # 소켓 읽기 제한 시간 (BaseHTTPRequestHandler가 연결 소켓에 적용한다).
        # 연결을 재사용하므로 "다음 요청을 기다리는 시간"에도 걸린다 → 쉬는 연결은 이 시간 뒤 서버가 닫아 스레드를 돌려받는다
        timeout = REQUEST_TIMEOUT
        # HTTP/1.1 = 연결 재사용(keep-alive). 기본값 HTTP/1.0이면 응답마다 연결을 끊어서, 요청마다
        # TCP 연결 + 스레드 생성 + 정리를 다시 했다 (이 PC에서 요청당 약 3.5ms 중 2.4ms가 그 비용, 재사용하면 약 1.0ms).
        # 실제 Redis도 클라이언트와 연결을 계속 유지한다. 클라이언트가 Connection: close를 보내면(urlopen) 예전처럼 끊는다
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            # 응답을 헤더와 본문 두 번에 나눠 쓴다. Nagle 알고리즘은 앞 조각의 ACK가 올 때까지 뒤 조각을 붙잡고,
            # 클라이언트는 응답이 다 와야 ACK를 보내서(지연 ACK) 연결을 재사용하면 요청마다 수십 ms씩 멈출 수 있다 → 작은 조각도 바로 보낸다
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        # 다음 요청을 기다리던 연결을 클라이언트가 강제로 끊으면(RST: 응답을 다 안 읽고 닫거나 프로세스가 죽음) 표준 라이브러리는
        # ConnectionResetError를 그대로 올려 서버 콘솔에 traceback이 찍혔다 (연결 재사용을 넣으며 생긴 일, 자체 점검에서 재현).
        # "더 이상 요청이 없다"와 같으므로 조용히 연결을 닫는다
        def handle_one_request(self):
            try:
                super().handle_one_request()
            except ConnectionError:
                self.close_connection = True

        # 표준 라이브러리는 Expect: 100-continue가 오면 경로 · 메서드 · 길이를 보기도 전에 100 Continue부터 보냈다.
        # 그래서 405 · 413처럼 거절할 요청에도 클라이언트가 본문(최대 1MB 이상)을 다 보낸 뒤에야 거절을 받았다 (Gemini 리뷰로 재현)
        # → 여기서는 보내지 않고, _read_json이 검사를 통과한 뒤에 보낸다
        def handle_expect_100(self):
            return True

        # Connection 헤더의 쉼표로 나뉜 토큰("keep-alive, close")이나 여러 줄에서 close를 찾는다. 표준 라이브러리는 값 전체가
        # 정확히 "close"일 때만 닫아서, 닫아 달라는 클라이언트의 연결을 유지했다 (GPT 리뷰로 재현)
        def parse_request(self):
            if not super().parse_request():
                return False
            tokens = {t.strip().lower() for value in (self.headers.get_all("Connection") or []) for t in value.split(",")}
            if "close" in tokens:
                self.close_connection = True
            return True

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
            self._body_read = False  # _read_json이 본문을 끝까지 읽으면 True
            self._length = 0  # 검사를 통과한 Content-Length 값
            try:
                self._check_framing()
                status, body = self._route(method)
            except ApiError as e:
                status, body = e.status, {"error": str(e)}
            except Exception:  # 예상 못한 오류도 서버가 죽지 않고 500으로 응답한다
                status, body = 500, {"error": "서버 내부 오류"}
            # 본문이 있는 요청인데 읽지 않고 답하면(404 · 405 · 잘못된 Content-Length · 411 등) 남은 본문이 같은 연결의
            # "다음 요청"으로 읽혀 엉뚱한 응답이 나간다 → 이 응답을 끝으로 연결을 닫는다 (연결을 재사용하면서 생긴 규칙)
            # (Content-Length 형식이 잘못됐으면 _check_framing이 이미 연결을 닫기로 정했다)
            if not self._body_read and ("Transfer-Encoding" in self.headers or self._length > 0):
                self.close_connection = True
            self._send(status, body)

        # 본문 경계와 관련된 헤더를 경로 · 메서드와 상관없이 먼저 검사한다. 하나라도 이상하면 본문이 어디서 끝나는지 믿을 수 없으므로
        # 거절하면서 연결도 닫는다 (안 닫으면 남은 바이트에 숨긴 요청이 다음 요청으로 실행된다)
        def _check_framing(self):
            # "Content-Length : 43"처럼 형식이 틀린 헤더 줄을 표준 라이브러리는 에러 없이 버리고 defects에만 기록한다.
            # 그래서 본문이 없다고 보고 연결을 유지해 숨긴 요청이 실행됐다 (자체 점검으로 재현). RFC 9112도 이런 요청은 400으로 거절하라고 한다
            if self.headers.defects:
                self.close_connection = True
                raise ApiError(400, "헤더 형식이 올바르지 않습니다")
            lengths = self.headers.get_all("Content-Length") or []
            # Content-Length 두 개: headers.get은 첫 번째만 본다. 첫 값이 0이면 거절 응답 뒤에도 연결을 유지해 숨긴 DELETE가 실행됐다
            # (GPT 리뷰로 재현. 그 전에는 서로 다른 두 길이로 같은 문제) → 값과 상관없이 거부 + 닫기
            if len(lengths) > 1:
                self.close_connection = True
                raise ApiError(400, "Content-Length 헤더가 여러 개입니다")
            # HTTP 규칙상 0~9 숫자만. int()는 "+12" · "1_2" · 전각 숫자를 받아 주고, 빈 값을 0으로 보면 스머글링이 됐다 (리뷰로 재현).
            # 본문을 읽지 않는 경로(GET 등)에도 같은 규칙을 적용한다 (GPT 리뷰)
            if lengths:
                raw = lengths[0].strip()
                if not (raw.isascii() and raw.isdigit()) or len(raw) > 4000:  # 4000: 파이썬 int 자릿수 제한(4300)보다 작게
                    self.close_connection = True
                    raise ApiError(400, "Content-Length가 올바르지 않습니다")
                self._length = int(raw)
            # Transfer-Encoding은 값이 비어 있어도 "있다"로 본다. 빈 값을 없는 것으로 봐서 숨긴 요청이 실행됐다 (Gemini 리뷰로 재현)
            if "Transfer-Encoding" in self.headers:
                self.close_connection = True
            # Expect는 100-continue만 안다. 모르는 값이면 417 (RFC 9110). 전에는 본문을 기다리다 408이 됐다 (GPT 리뷰로 재현)
            expects = [v.strip().lower() for value in (self.headers.get_all("Expect") or []) for v in value.split(",")]
            if any(v != "100-continue" for v in expects):
                self.close_connection = True
                raise ApiError(417, "지원하지 않는 Expect 헤더입니다 (100-continue만 지원)")

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
            # chunked 전송은 Content-Length가 없어 본문을 0바이트로 읽고 "value가 필요합니다"라는 엉뚱한 400을 주던 것 → 원인대로 411
            if "Transfer-Encoding" in self.headers:  # 값이 빈 헤더도 (위 _check_framing)
                self.close_connection = True  # 읽지 않은 본문이 연결에 남으므로 닫는다
                raise ApiError(411, "Content-Length로 본문 길이를 알려 주세요 (chunked 전송은 지원하지 않습니다)")
            length = self._length  # 형식은 _check_framing이 검사했다 (헤더가 없으면 0)
            expects_continue = "Expect" in self.headers  # _check_framing을 지났으면 값은 100-continue뿐이다
            if length > MAX_BODY:
                if expects_continue:
                    self.close_connection = True  # 클라이언트는 100을 기다리며 본문을 아직 안 보냈다 → 버릴 본문 없이 바로 거절
                else:
                    self._discard_body(length)
                raise ApiError(413, "요청 본문이 너무 큽니다 (최대 1MB)")
            # 본문이 0바이트면 보낼 것이 없으니 100도 보내지 않는다 (Gemini 리뷰)
            if expects_continue and length > 0 and self.request_version >= "HTTP/1.1":
                # 검사를 모두 통과했을 때만 "본문을 보내도 된다"(100 Continue)고 알린다 (아래 handle_expect_100 참고)
                self.send_response_only(100)
                self.end_headers()
            try:
                raw = self.rfile.read(length)
            except (TimeoutError, socket.timeout):  # 파이썬 3.9(맥 기본 python3)까지는 socket.timeout이 TimeoutError가 아니라서 둘 다 잡는다
                raise ApiError(408, "요청 본문을 제한 시간 안에 다 받지 못했습니다")
            # 클라이언트가 Content-Length보다 덜 보내고 연결을 닫으면 read는 에러 없이 받은 만큼만 돌려준다.
            # 잘린 본문이 우연히 올바른 JSON이면 그대로 저장되므로, 길이가 다르면 거부한다
            if len(raw) != length:
                self.close_connection = True
                raise ApiError(400, "본문이 Content-Length보다 짧습니다")
            self._body_read = True  # 여기부터는 에러가 나도 본문을 다 읽었으므로 연결을 계속 쓸 수 있다
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
            if _nesting_exceeds(body, MAX_DEPTH + 1):  # +1: 본문 객체 {...} 자체가 한 단계
                raise ApiError(400, f"JSON 중첩은 {MAX_DEPTH}단계까지입니다")
            # "\ud800" 같은 짝 없는 반쪽 문자는 JSON 문법으로는 통과하지만 UTF-8로 바꿀 수 없어서, 저장하면 나중에 응답을 못 보낸다 → 처음부터 거부
            try:
                json.dumps(body, ensure_ascii=False).encode("utf-8")
            except UnicodeEncodeError:
                raise ApiError(400, "UTF-8로 표현할 수 없는 문자(짝 없는 서로게이트)가 들어 있습니다")
            return body

        # 너무 큰 본문을 "읽어서 버린다" (메모리에 모으지 않고 64KB씩). 안 읽고 바로 413을 보내고 연결을 닫으면,
        # 아직 본문을 보내던 클라이언트 쪽 연결이 끊겨(Windows에서 자주) 413 응답을 못 받는 경우가 생긴다.
        # 버리는 양은 DISCARD_LIMIT까지만: 그보다 크면 끝까지 읽어 주지 않고 연결을 닫는다 (거대한 요청에 시간을 쓰지 않게)
        def _discard_body(self, length):
            self.close_connection = True
            discard_body(self.rfile, length)

        def _send(self, status, body):
            try:
                data = _encode(body)
            except (TypeError, ValueError, RecursionError):
                # 파이썬 코드로 JSON으로 못 바꾸는 값({1, 2} 등)을 직접 저장했으면, 응답 없이 연결이 끊기고 traceback이 찍히던 것 → JSON 500
                status, data = 500, _encode({"error": "저장된 값을 JSON으로 바꿀 수 없습니다 (파이썬 코드로 직접 넣은 값)"})
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))  # 연결이 안 끊기므로 클라이언트는 이 길이로 응답 끝을 안다
                if self.close_connection:
                    self.send_header("Connection", "close")  # 알려야 클라이언트가 닫힐 연결에 다음 요청을 보내지 않는다
                self.end_headers()
                if self.command != "HEAD":  # HEAD 응답은 헤더만 보낸다 (HTTP 규약: 본문을 보내면 클라이언트가 다음 응답으로 착각한다)
                    self.wfile.write(data)
            except ConnectionError:
                # 클라이언트가 응답을 다 받기 전에 연결을 끊었다 (BrokenPipe / ConnectionReset / ConnectionAborted).
                # 보낼 곳이 없으니 조용히 연결만 정리한다 (에러로 취급해 로그를 남기거나 다시 응답하려 하지 않는다)
                self.close_connection = True

        # HEAD · TRACE · CONNECT처럼 do_* 메서드가 없는 요청이나 깨진 요청 줄은 기본 동작이 HTML 에러 페이지라서, 여기서 JSON으로 바꾼다.
        # 501(서버가 아예 모르는 메서드)과 405(아는 메서드지만 이 경로에서 안 됨, _route에서 처리)는 그대로 구분한다
        def send_error(self, code, message=None, explain=None):
            self.close_connection = True
            if code == 501:
                message = f"지원하지 않는 메서드입니다: {self.command}"
            self._send(code, {"error": message or "잘못된 요청입니다"})

        def log_message(self, format, *args):
            pass  # 요청마다 콘솔에 찍지 않는다 (성능 측정에 출력 비용이 섞이지 않게)

    return Handler


def _reject_constant(name):
    raise ValueError(f"{name}은(는) 표준 JSON 값이 아닙니다")


# 요청 본문을 DISCARD_LIMIT까지 64KB씩 읽어서 버린다 (데모 API의 413 응답도 같은 방식을 쓴다)
def discard_body(rfile, length):
    remaining = min(length, DISCARD_LIMIT)
    try:
        while remaining > 0:
            chunk = rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
    except (TimeoutError, OSError):
        pass


# 응답 JSON 바이트. 파이썬 코드로 직접 저장된 반쪽 문자 등이 있어도 응답은 반드시 나가게:
# UTF-8로 못 바꾸면 모든 비ASCII를 \uXXXX로 적는 방식으로 다시 만든다
def _encode(body):
    try:
        return json.dumps(body, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(body).encode("ascii")


# value의 중첩 깊이가 limit을 넘는지. 재귀 대신 스택으로 훑어서 아주 깊은 값에서도 RecursionError가 나지 않는다
def _nesting_exceeds(value, limit):
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, (list, dict)):
            if depth > limit:
                return True
            stack.extend((child, depth + 1) for child in (item.values() if isinstance(item, dict) else item))
    return False


# 저장소를 감싼 HTTP 서버 객체 생성 (port=0이면 빈 포트를 자동으로 고른다 → 테스트용)
# 주기 삭제 스레드도 함께 시작하고, server_close() 때 같이 멈춘다
def create_server(store, host="127.0.0.1", port=6380):
    server = SafeThreadingHTTPServer((host, port), make_handler(store))
    server.max_clients = MAX_CLIENTS  # 만들 때 읽는다 (테스트가 모듈 값을 바꿔 작은 상한으로 확인한다)
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
    parser.add_argument("--snapshot", default="data/dump.json", help="스냅샷 파일 경로 (빈 문자열이면 저장 안 함)")
    parser.add_argument("--snapshot-interval", type=float, default=60, help="스냅샷 저장 주기(초)")
    args = parser.parse_args()
    # 범위 밖 포트는 bind가 OSError가 아닌 OverflowError를 내서 traceback으로 나오던 것 → 사용법 에러로
    if not 0 <= args.port <= 65535:
        parser.error("--port는 0~65535 사이여야 합니다")
    # 상한 threading.TIMEOUT_MAX(Windows 약 49.7일): 넘으면 주기 저장 스레드가 OverflowError로 바로 죽는다. NaN도 이 비교에서 걸러진다
    if args.snapshot and not 0 < args.snapshot_interval <= threading.TIMEOUT_MAX:
        parser.error(f"--snapshot-interval은 0보다 크고 {threading.TIMEOUT_MAX:g}초 이하여야 합니다")

    store = MiniRedis()
    if args.snapshot:
        try:
            loaded = load_snapshot(store, args.snapshot)
        except SnapshotError as e:
            # 손상된 파일로 빈 서버를 띄우면 다음 저장 때 그 파일을 덮어써 데이터가 영영 사라진다 → 시작하지 않는다
            raise SystemExit(f"[snapshot] {e}\n파일을 확인하거나 다른 경로(--snapshot)를 지정하세요.")
        print(f"[snapshot] {args.snapshot}에서 키 {loaded}개 복구")

    # 서버(포트)를 먼저 연다. 포트가 이미 쓰이는 중이면 여기서 끝나고, 스냅샷 스레드는 아직 켜지지 않는다
    try:
        server = create_server(store, args.host, args.port)
    except OSError as e:
        raise SystemExit(f"{args.host}:{args.port}에서 서버를 열 수 없습니다: {e}")
    stop_snapshot = start_periodic_snapshot(store, args.snapshot, args.snapshot_interval) if args.snapshot else None

    print(f"Mini Redis listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if stop_snapshot:
            try:
                stop_snapshot()  # 종료 직전 상태까지 저장
                print(f"[snapshot] 종료 전 저장 완료: {args.snapshot}")
            except Exception as e:  # 저장에 실패해도 마지막 주기 저장 파일은 남아 있다
                print(f"[snapshot] 종료 전 저장 실패 (마지막 주기 저장본은 그대로): {e}")


if __name__ == "__main__":
    main()
