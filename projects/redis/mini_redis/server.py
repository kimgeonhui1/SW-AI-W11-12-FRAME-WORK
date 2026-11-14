# [server.py] Mini Redis HTTP JSON API — 외부 프로그램이 HTTP로 저장소를 사용
#
# 설계 문서: projects/redis/Docs/설계.md  8장
#
#   GET    /keys/{key}          값 조회         → 200 {"key": k, "value": v, "ttl": 초 | -1} / 404
#   PUT    /keys/{key}          값 저장         body {"value": ..., "ttl": 초(선택)} → 200 {"ok": true} / 400
#   DELETE /keys/{key}          삭제(무효화)     → 200 {"deleted": true/false}
#   GET    /keys/{key}/ttl      남은 만료 시간   → 200 {"ttl": 초 | -1(만료 없음) | -2(키 없음)}
#   POST   /keys/{key}/expire   만료 시간 설정   body {"ttl": 초} → 200 {"ok": true} / 404 키 없음 / 400
#   GET    /health              상태 확인       → 200 {"keys": 저장된 키 수}
#   그 밖의 경로 · 빈 키(/keys/)                → 404 {"error": "없는 경로입니다"}
#   경로는 맞는데 메서드가 다름 (PATCH · OPTIONS 포함) → 405 {"error": "GET만 지원합니다" 등}
#   오류 응답은 모두 {"error": "이유"} 모양이고, 문구는 dev 와 같은 한국어다
#
# ■ 계층에서의 위치: API Server
#   HTTP 요청 → 입력 검사 → MiniRedis 메서드 호출 → JSON 응답. 해시 테이블 · 만료 계산은 모른다.
#   이 파일은 신뢰 경계다: 밖에서 오는 요청은 무엇이든 올 수 있으므로 store 에 넘기기 전에 여기서 막는다.
#
# ■ 키에 "/" 같은 특수문자가 있으면 URL 인코딩해서 보낸다 (예: "char:a/b" → /keys/char%3Aa%2Fb)
#   경로를 "/" 로 먼저 나눈 뒤 조각마다 디코딩한다 → 키 안의 %2F 가 경로 구분자로 오해되지 않는다
#
# ■ 동시성: ThreadingHTTPServer → 요청마다 스레드가 따로 돈다. store 안의 락 하나가 명령을 한 번에 하나씩 실행한다.
#   주기 삭제(sweep) 스레드도 서버와 함께 시작하고, server_close() 때 함께 멈춘다.
#
# 실행: projects/redis 에서  python -m mini_redis.server --port 6380
#       (기본으로 data/dump.json 에 60초마다 + 끌 때 스냅샷을 저장하고, 켤 때 복구한다. --snapshot "" 로 끌 수 있다)

import argparse
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from .persistence import SnapshotError, load_snapshot, start_periodic_snapshot
from .store import MiniRedis

MAX_BODY = 1024 * 1024  #     요청 본문 최대 1MB — 큰 요청 하나로 서버 메모리를 다 쓰지 못하게
MAX_DISCARD = 16 * 1024 * 1024  # 413 을 보내기 전에 읽어서 버릴 최대 크기 (아래 _discard 참고)
REQUEST_TIMEOUT = 10  #       요청을 다 받을 때까지 기다리는 최대 시간(초) — 보내다 멈춘 클라이언트가 스레드를 영원히 붙잡지 못하게
SWEEP_INTERVAL = 1.0  #       주기 삭제 간격(초)
# 세 값 모두 요청 · 반복마다 다시 읽으므로, 테스트가 모듈 값을 바꾸면 바로 적용된다 (dev 테스트가 이렇게 쓴다)


class ApiError(Exception):
    """응답 상태 코드를 담은 오류. 처리 중 어디서 던져도 _handle 이 {"error": ...} 응답으로 바꾼다"""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Handler(BaseHTTPRequestHandler):
    # 연결 하나마다 Handler 객체가 새로 만들어진다. 저장소는 self.server.store 로 함께 쓴다
    #
    # HTTP/1.1 = 연결 재사용(keep-alive): 클라이언트가 연결을 닫지 않으면 같은 연결로 다음 요청을 계속 받는다.
    #   HTTP/1.0(표준 라이브러리 기본값)이면 요청마다 TCP 연결 + 스레드를 새로 만들어, 요청 한 번(약 170µs)의 대부분이 그 비용이었다.
    #   연결을 재사용하는 클라이언트(http.client · requests.Session · 브라우저 fetch)는 그 비용이 사라진다.
    #   urlopen 처럼 "Connection: close" 를 보내는 클라이언트는 예전처럼 요청마다 끊긴다.
    #   쉬는 연결은 REQUEST_TIMEOUT 동안 다음 요청이 없으면 서버가 닫는다 (연결마다 스레드 하나를 쥐고 있으므로).
    protocol_version = "HTTP/1.1"

    # 연결마다 소켓 읽기 제한 시간을 정한다. 클래스 속성(timeout = ...)으로 두면 import 때 한 번만 읽혀서
    # 나중에 REQUEST_TIMEOUT 을 바꿔도 적용되지 않는다 → 연결이 올 때마다 모듈 값을 읽는다
    def setup(self):
        self.timeout = REQUEST_TIMEOUT
        super().setup()
        # 응답은 헤더 · 본문을 두 번에 나눠 쓴다. Nagle 알고리즘은 앞 조각의 ACK 가 올 때까지 뒤 조각을 붙잡고,
        # 클라이언트는 응답이 다 와야 ACK 를 보내므로(지연 ACK) 연결을 재사용하면 요청마다 최대 40ms 씩 멈출 수 있다 (Linux).
        # → 작은 조각도 바로 보낸다. 실제 Redis 도 연결마다 TCP_NODELAY 를 켠다
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # 모든 응답을 여기서 한 번에 보낸다 — 예상한 오류(ApiError)도, 예상 못 한 오류(500)도 JSON 으로
    # 메서드 이름(GET · PUT …)은 표준 라이브러리가 요청 줄에서 읽어 self.command 에 넣어 둔다
    def _handle(self):
        self._body_read = False  # _read_json 이 본문을 끝까지 읽으면 True
        try:
            status, body = self._route(self.command)
        except ApiError as e:
            status, body = e.status, {"error": str(e)}
        except Exception:  # 예상 못 한 오류에도 이 요청의 스레드만 500 으로 끝나고 서버는 계속 돈다
            status, body = 500, {"error": "서버 내부 오류"}
        # 본문이 있는 요청인데 읽지 않고 답하면(405 · 404 · Content-Length 오류 · 408 · chunked …) 남은 본문이
        # 같은 연결의 "다음 요청" 으로 읽혀 엉뚱한 응답이 나간다 → 이 응답을 끝으로 연결을 닫는다 (HTTP/1.1 이라 생긴 일)
        if not self._body_read and (self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0").strip() != "0"):
            self.close_connection = True
        self._send(status, body)

    # 표준 라이브러리는 "do_" + 메서드 이름 함수를 부른다 → 모두 _handle 한 곳으로.
    # PATCH · OPTIONS 도 받는 이유: 기본값이면 HTML 501 로 답하는데, 모든 응답은 JSON 이라는 약속을 지켜 405 JSON 으로 답하려고
    do_GET = do_PUT = do_DELETE = do_POST = do_PATCH = do_OPTIONS = _handle

    # 경로 · 메서드 → 저장소 명령. (상태 코드, 응답 본문) 을 돌려준다
    def _route(self, method):
        path = self.path.split("?", 1)[0]  # ?뒤 쿼리는 쓰지 않는다
        parts = [unquote(p) for p in path.split("/")[1:]]  # "/keys/a%2Fb/ttl" → ["keys", "a/b", "ttl"]
        store = self.server.store

        # 경로는 맞는데 메서드가 다르면 405. 문구는 허용 메서드를 이은 것 ("GET / PUT / DELETE만 지원합니다" — dev 와 같은 문구)
        def allow(*methods):
            if method not in methods:
                raise ApiError(405, f"{' / '.join(methods)}만 지원합니다")

        if parts == ["health"]:  # 상태 확인 — 저장된 키 수 (아직 sweep 안 된 만료 키 포함)
            allow("GET")
            return 200, {"keys": len(store)}
        # 경로는 /keys/{key} · /keys/{key}/ttl · /keys/{key}/expire 셋뿐.
        # /keys/ 처럼 빈 키도 없는 경로로 본다 (dev 와 같음). 저장소 자체는 빈 키도 받는다
        if len(parts) not in (2, 3) or parts[0] != "keys" or parts[1] == "" or parts[2:] not in ([], ["ttl"], ["expire"]):
            raise ApiError(404, "없는 경로입니다")
        key = parts[1]

        if len(parts) == 2:  # /keys/{key}
            allow("GET", "PUT", "DELETE")
            if method == "GET":
                # 값과 ttl 을 락 하나 안에서 함께 읽는다 (따로 읽으면 사이에 끼어든 요청 때문에 둘이 어긋날 수 있다)
                value, ttl = store.get_with_ttl(key)
                if value is None:  # PUT 에서 null 을 막아 두었으므로 None = "없거나 만료됨" 이 확실하다
                    raise ApiError(404, "키가 없습니다")
                return 200, {"key": key, "value": value, "ttl": ttl}
            if method == "PUT":
                body = self._read_json()
                if body.get("value") is None:
                    raise ApiError(400, "value가 필요합니다 (null은 저장할 수 없습니다)")
                self._call(store.set, key, body["value"], body.get("ttl"))
                return 200, {"ok": True}
            return 200, {"deleted": store.delete(key)}  # DELETE (allow 를 지났으므로 남은 것은 이것뿐)
        if parts[2] == "ttl":  # /keys/{key}/ttl
            allow("GET")
            return 200, {"ttl": store.ttl(key)}
        allow("POST")  # /keys/{key}/expire
        body = self._read_json()
        if "ttl" not in body:
            raise ApiError(400, "ttl이 필요합니다")
        if not self._call(store.expire, key, body["ttl"]):
            raise ApiError(404, "키가 없습니다")
        return 200, {"ok": True}

    # 저장소 명령 실행. 잘못된 ttl 로 ValueError 가 나면 400 (ttl 규칙은 store 한 곳에서만 관리한다)
    def _call(self, fn, *args):
        try:
            return fn(*args)
        except ValueError as e:
            raise ApiError(400, str(e))

    # 요청 본문을 읽어 JSON 객체(dict)로 돌려준다. 잘못되면 ApiError
    def _read_json(self):
        length = self.headers.get("Content-Length", "")
        # 없거나 숫자가 아님(음수 포함). isascii: "²" 처럼 isdigit() 은 True 인데 int() 는 실패하는 글자를 막는다
        if not (length.isascii() and length.isdigit()):
            raise ApiError(400, "Content-Length가 올바르지 않습니다")
        length = int(length)
        if length > MAX_BODY:
            self._discard(length)
            self.close_connection = True  # 남은 본문이 다음 요청으로 읽히지 않게 연결을 닫는다
            raise ApiError(413, "요청 본문이 너무 큽니다 (최대 1MB)")
        try:
            raw = self.rfile.read(length)
        except TimeoutError:
            raise ApiError(408, "요청 본문을 제한 시간 안에 다 받지 못했습니다")
        self._body_read = True  # 여기부터 오류가 나도 본문은 다 읽었으므로 연결을 계속 쓸 수 있다
        try:
            # NaN · Infinity 는 파이썬 json 이 받아 주지만 표준 JSON 이 아니라 다른 언어 클라이언트가 응답을 못 읽는다 → 거부
            body = json.loads(raw, parse_constant=_reject_constant)
            if not isinstance(body, dict):
                raise ApiError(400, "본문은 JSON 객체({...})여야 합니다")  # ApiError 는 아래 except 들에 걸리지 않고 그대로 나간다
            # 응답으로 다시 쓸 수 없는 값은 저장 전에 거부한다 (저장은 됐는데 조회 때 500 · 끊김이 되지 않게) — 지금 한 번 써 본다
            json.dumps(body, ensure_ascii=False).encode("utf-8")
        except RecursionError:  # 아주 깊게 중첩된 값([[[[...]]]]) — 파이썬 버전에 따라 읽을 때, 또는 다시 쓸 때(3.14) 이 오류
            raise ApiError(400, "JSON이 너무 깊게 중첩되어 있습니다")
        except UnicodeEncodeError:  # 짝 없는 반쪽 문자("\ud800") — JSON 문법으로는 통과하지만 UTF-8 로 못 바꾼다 (ValueError 의 한 종류라 그보다 먼저)
            raise ApiError(400, "UTF-8로 표현할 수 없는 문자(짝 없는 서로게이트)가 들어 있습니다")
        except ValueError:  # JSONDecodeError · UnicodeDecodeError · _reject_constant 모두 ValueError 계열
            raise ApiError(400, "본문이 올바른 JSON이 아닙니다 (NaN / Infinity 불가)")
        return body

    # 너무 큰 본문을 응답 전에 읽어서 버린다 (최대 MAX_DISCARD).
    # 읽지 않은 데이터가 남은 채로 연결을 닫으면 운영체제가 RST(강제 끊김)를 보내, 아직 본문을 보내던 클라이언트는
    # 413 응답을 받기도 전에 "Connection reset" 오류를 본다 (dev 코드 · 테스트에서도 나던 문제).
    # shortcut: MAX_DISCARD(16MB) 보다 큰 본문은 다 버리지 못하고 끊긴다 → 그런 클라이언트가 실제로 있으면 응답 후 소켓 shutdown 방식으로 바꾼다
    def _discard(self, length):
        left = min(length, MAX_DISCARD)
        try:
            # 64KB 씩 읽는다 (한 번에 16MB 를 읽으면 그만큼 메모리를 잡는다). 빈 조각 = 클라이언트가 보내기를 멈추고 연결을 닫음
            while left > 0 and (chunk := self.rfile.read(min(left, 64 * 1024))):
                left -= len(chunk)
        except TimeoutError:  # 보내다 멈춘 클라이언트 — 기다리지 않고 바로 413
            pass

    def _send(self, status, body):
        try:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")  # 한글을 \uXXXX 가 아닌 글자 그대로 보낸다
        except UnicodeEncodeError:
            # 짝 없는 반쪽 문자("\ud800")가 든 값은 UTF-8 로 못 바꾼다 → 모든 비ASCII 를 \uXXXX 로 적어 응답은 반드시 나가게
            data = json.dumps(body).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))  # HTTP/1.1 에서 클라이언트가 응답 끝을 아는 방법 (연결이 안 끊기므로 필수)
        if self.close_connection:
            self.send_header("Connection", "close")  # 이 응답 뒤 닫는다고 알려야 클라이언트가 이 연결로 다음 요청을 보내지 않는다
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass  # 요청마다 콘솔에 찍지 않는다 (성능 측정에 출력 비용이 섞이지 않게)


def _reject_constant(name):
    raise ValueError(f"{name}은(는) 표준 JSON 값이 아닙니다")


class MiniRedisServer(ThreadingHTTPServer):
    """저장소와 주기 삭제 스레드를 함께 가진 HTTP 서버"""

    # 아직 받지 못한 연결을 운영체제가 줄 세워 두는 개수 (listen backlog). 표준 라이브러리 기본값은 5 라서,
    # 클라이언트 20개가 한꺼번에 접속하면 넘친 연결이 "Connection reset" 으로 끊겼다 (검증 중 부하 검사에서 발견)
    request_queue_size = 128

    def __init__(self, store, address):
        super().__init__(address, Handler)
        self.store = store
        self._stop = threading.Event()
        threading.Thread(target=self._sweep_loop, daemon=True).start()

    # wait() 는 SWEEP_INTERVAL 만큼 기다리다가 stop 이 켜지면 바로 깨어나 반복을 끝낸다
    def _sweep_loop(self):
        while not self._stop.wait(SWEEP_INTERVAL):
            self.store.sweep()

    def server_close(self):
        self._stop.set()
        super().server_close()


# 저장소를 감싼 HTTP 서버 객체 생성 (port=0 이면 빈 포트를 자동으로 고른다 → 테스트용)
def create_server(store, host="127.0.0.1", port=6380):
    return MiniRedisServer(store, (host, port))


# 명령줄 실행 시작점. 기본 127.0.0.1 — 같은 컴퓨터에서만 접속된다 (외부에 열려면 --host 0.0.0.0)
# 스냅샷(영속성): 켤 때 --snapshot 파일에서 복구하고, --snapshot-interval 초마다 + 끌 때 저장한다 (김건희 님 브랜치와 같음)
#   --snapshot "" 이면 저장 · 복구를 하지 않는다 (예전처럼 끄면 데이터가 사라지는 서버)
def main():
    parser = argparse.ArgumentParser(description="Mini Redis HTTP 서버")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=6380)
    parser.add_argument("--snapshot", default="data/dump.json", help="스냅샷 파일 경로 (빈 문자열이면 저장 안 함)")
    parser.add_argument("--snapshot-interval", type=float, default=60, help="스냅샷 저장 주기(초)")
    args = parser.parse_args()
    if args.snapshot and not 0 < args.snapshot_interval < float("inf"):  # NaN 도 이 비교에서 걸러진다
        parser.error("--snapshot-interval은 0보다 큰 유한한 숫자여야 합니다")

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
