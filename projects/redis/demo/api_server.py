# [api_server.py] 기능 테스트용 간단한 API — 느린 데이터 조회 응답을 Mini Redis에 캐시해서 활용
#
#   GET /items/{id}            Mini Redis 캐시 사용 (없으면 느린 조회 후 저장)
#   GET /items/{id}?cache=off  캐시 없이 매번 느린 조회 (성능 비교용)
#   PUT /items/{id}            원본 데이터 수정 body {"price": 숫자} → 버전을 올려 캐시 무효화
#
# ■ 무효화 방식: 버전 키 (item:{id}:v{version})
#   단순히 "수정 후 캐시 삭제"만 하면 경쟁 상태가 생긴다:
#     ① GET이 원본에서 가격 100을 읽음(느림)  ② 그사이 PUT이 가격을 5로 바꾸고 캐시 삭제  ③ GET이 늦게 100을 캐시에 저장
#     → 이후 TTL 동안 옛 가격 100이 HIT로 나간다
#   캐시 키에 데이터의 버전을 넣으면, ③의 옛 데이터는 옛 버전 키(v1)에 저장되고 새 요청은 새 버전 키(v2)만 읽으므로 섞이지 않는다
#
# 응답: {"item": {...}, "cache": "HIT" | "MISS" | "OFF" | "BYPASS"}
#   HIT    : Mini Redis에 있어서 바로 응답
#   MISS   : 없어서 원본을 조회하고 Mini Redis에 저장
#   OFF    : ?cache=off 라서 캐시를 쓰지 않음
#   BYPASS : Mini Redis가 꺼져 있거나 응답이 없어서 원본만 조회 (캐시가 죽어도 API는 동작한다)
#
# 실행: projects/redis 에서  python -m demo.api_server --port 8000 --redis http://127.0.0.1:6380

import argparse
import http.client
import json
import math
import select
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote, urlsplit

from mini_redis.server import MAX_BODY, SafeThreadingHTTPServer, discard_body

SLOW_DELAY = 0.2  # 원본 조회에 걸리는 시간(초). 실제 DB 쿼리나 외부 API 호출을 흉내 낸다
CACHE_TTL = 60  # 캐시 보관 시간(초). 원본이 바뀌었는데 무효화를 놓쳐도 최대 60초 뒤에는 새 값이 보인다
REDIS_TIMEOUT = 1.0  # Mini Redis 요청 제한 시간. 캐시가 느려져도 API 전체가 같이 느려지지 않게
MAX_IDLE = 16  # Mini Redis 연결 풀에 남겨 둘 쉬는 연결 최대 수
ITEM_COUNT = 100
# 원본(DB)에 동시에 연결할 수 있는 수. 실제 DB도 연결 풀 크기만큼만 동시에 쿼리를 처리하고 나머지는 줄을 선다.
# 이 제한이 없으면 sleep이 무한히 병렬로 돌아, 동시 요청 벤치마크에서 "원본이 병목"이라는 현실이 드러나지 않는다
SOURCE_CONNECTIONS = 5
_source_pool = threading.BoundedSemaphore(SOURCE_CONNECTIONS)

# 원본 데이터(= DB 역할). 데모의 "느린 저장소"라서 파이썬 dict를 쓴다 (dict 금지는 Mini Redis 저장소 구현에 대한 제약)
_items = {i: {"id": i, "name": f"아이템 {i}", "price": i * 100, "version": 1} for i in range(1, ITEM_COUNT + 1)}
_items_lock = threading.Lock()


# 느린 원본 데이터 조회 (DB나 외부 API 호출을 흉내). 없는 id면 None
def fetch_item(item_id):
    with _items_lock:
        item = _items.get(item_id)
        item = dict(item) if item else None  # 복사본 (호출한 쪽이 고쳐도 원본이 바뀌지 않게)
    # 실제 DB처럼 "읽은 시점의 데이터가 나중에 도착"하게: 읽고 나서 기다린다
    # (그 사이 원본이 바뀌면 이 결과는 이미 옛 값이다 → 캐시에 옛 값을 넣는 경쟁 상태가 생길 수 있다)
    with _source_pool:  # 빈 연결이 없으면 앞 조회가 끝날 때까지 기다린다
        time.sleep(SLOW_DELAY)
    return item


# 지금 원본의 버전 (없는 아이템이면 None).
# shortcut: 버전 확인은 가벼운 조회라고 가정해 지연을 넣지 않았다. 실제 서비스면 버전을 캐시(Redis)에 따로 두는 방식을 쓴다
def current_version(item_id):
    with _items_lock:
        item = _items.get(item_id)
        return item["version"] if item else None


# 원본 수정 + 버전 올리기 → (수정된 아이템 복사본, 이전 버전). 캐시 정리는 호출한 쪽(PUT 처리)이 맡는다
def update_item(item_id, price):
    with _items_lock:
        if item_id not in _items:
            return None, None
        item = _items[item_id]
        old_version = item["version"]
        item["price"] = price
        item["version"] = old_version + 1
        return dict(item), old_version


class RedisClient:
    """Mini Redis HTTP API를 부르는 작은 클라이언트. 연결 실패·시간 초과는 RedisUnavailable로 통일한다

    연결을 재사용한다(연결 풀): 요청이 끝난 연결을 _idle에 돌려놓고 다음 요청이 꺼내 쓴다.
    urlopen은 요청마다 새 TCP 연결을 맺고 끊어서, 캐시 HIT 한 번의 대부분이 연결 비용이었다.
    데모 API는 요청마다 스레드가 따로 돌기 때문에 스레드별 연결이 아니라 함께 쓰는 풀로 둔다 (실제 Redis 클라이언트도 연결 풀을 쓴다)"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        url = urlsplit(self.base_url)
        # https 주소면 TLS 연결 (urlopen을 쓰던 때와 같은 동작). 포트가 없으면 각 방식의 기본 포트(80 / 443)
        self._conn_class = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
        self._host, self._port, self._prefix = url.hostname, url.port, url.path
        self._idle = []
        self._lock = threading.Lock()
        # 풀 세대 번호. close()가 올린다. 요청 도중에 close()가 불리면 그 요청의 연결은 끝난 뒤 옛 세대라서 풀에 넣지 않고 닫는다
        # (번호 없이는 닫은 풀에 연결이 다시 쌓였다: 자체 점검)
        self._generation = 0

    def get(self, key):
        """값 또는 None(없음)"""
        status, body = self._request("GET", key)
        if status == 404:
            return None
        if not isinstance(body, dict) or "value" not in body:  # 약속과 다른 모양의 응답 → 믿을 수 없는 캐시로 보고 쓰지 않는다
            raise RedisUnavailable("Mini Redis 응답 형식이 올바르지 않습니다")
        return body["value"]

    def set(self, key, value, ttl):
        self._request("PUT", key, {"value": value, "ttl": ttl})

    def delete(self, key):
        self._request("DELETE", key)

    # 쉬는 연결들을 닫는다 (서버를 바꿔 끼우거나 끝낼 때)
    def close(self):
        with self._lock:
            idle, self._idle = self._idle, []
            self._generation += 1
        for conn in idle:
            conn.close()

    def _request(self, method, key, body=None):
        data = json.dumps(body).encode() if body is not None else None
        path = f"{self._prefix}/keys/{quote(key, safe='')}"
        headers = {"Content-Type": "application/json"} if data is not None else {}
        for fresh in (False, True):
            conn, reused = self._take(fresh)
            try:
                conn.request(method, path, body=data, headers=headers)
                res = conn.getresponse()
                raw = res.read()
            except (ConnectionError, http.client.HTTPException) as e:
                conn.close()
                # 재사용한 연결이 끊겼거나 응답이 깨졌으면(이상한 상태 줄 · 중간에 잘린 응답) 새 연결로 한 번만 다시 보낸다.
                # (HTTPException은 ConnectionError가 아니라서 전에는 재사용 GET도 바로 BYPASS였다: Gemini 리뷰로 재현) 단 GET(읽기)만:
                # 서버가 PUT · DELETE를 이미 실행하고 응답만 잃었을 수도 있어서, 다시 보내면 그사이 다른 요청이 쓴 값을
                # 옛 값으로 덮거나 지울 수 있다 (GPT 리뷰, PUT이 두 번 실행되는 것 재현). 쓰기 실패는 캐시를 못 쓴 것일 뿐이라 BYPASS로 충분하다
                if reused and method == "GET":
                    continue
                raise RedisUnavailable(str(e))
            except OSError as e:  # TimeoutError 포함
                # 연결 실패·시간 초과 → "캐시 사용 불가"로 통일
                # → 호출한 쪽은 원본으로 응답(BYPASS)하면 되고, 캐시 문제로 500이 나지 않는다
                conn.close()
                raise RedisUnavailable(str(e))
            with self._lock:
                # 서버가 Connection: close로 답했으면 다시 못 쓴다. 풀이 꽉 찼으면 닫는다: 요청이 몰렸다 빠진 뒤
                # 쓰지 않는 연결 수백 개를 계속 쥐고 있지 않게 (GPT · Gemini 리뷰)
                keep = not res.will_close and len(self._idle) < MAX_IDLE and conn.pool_generation == self._generation
                if keep:
                    self._idle.append(conn)
            if not keep:
                conn.close()
            if res.status == 404:  # 404는 "키 없음"이라는 정상 응답
                return 404, None
            if res.status >= 400:
                raise RedisUnavailable(f"Mini Redis 오류 응답 {res.status}")
            try:
                return res.status, json.loads(raw)
            except ValueError as e:  # JSON이 아닌 응답
                raise RedisUnavailable(str(e))

    # 쉬는 연결을 꺼내거나 새로 만든다 → (연결, 재사용 여부). fresh=True면 무조건 새 연결 (재시도용: 남은 연결도 다 끊겼을 수 있다)
    def _take(self, fresh):
        while not fresh:
            with self._lock:
                if not self._idle:
                    break
                conn = self._idle.pop()
            if not _dropped(conn):
                return conn, True
            conn.close()  # 쉬는 동안 서버가 닫은 연결(REQUEST_TIMEOUT) → 버리고 다음 연결을 본다
        conn = self._conn_class(self._host, self._port, timeout=REDIS_TIMEOUT)
        with self._lock:
            conn.pool_generation = self._generation  # 이 연결이 속한 풀 세대
        return conn, False


# 쉬는 연결이 이미 끊겼는지 보내기 전에 확인한다. 응답을 기다리지 않는 연결에서 "읽을 것이 있다" = 서버가 닫았다(FIN)는 뜻.
# 이렇게 미리 버려야 PUT · DELETE도 재시도 없이 성공한다 (재시도는 GET만 하므로)
def _dropped(conn):
    sock = conn.sock
    if sock is None:  # 이미 닫힌 연결 (select에 None을 주면 TypeError)
        return True
    if isinstance(sock, ssl.SSLSocket):
        # TLS는 서버가 응답 없이도 레코드(TLS 1.3 세션 티켓 등)를 보내서 "읽을 것이 있다"가 끊김을 뜻하지 않는다 (Gemini 리뷰).
        # 확인하지 않고 쓴다. 끊겼으면 GET은 새 연결로 다시 보내고, 쓰기는 BYPASS가 된다
        return False
    try:
        if hasattr(select, "poll"):
            # 리눅스·맥: select()는 소켓 번호 1024 이상을 다루지 못해(ValueError) 모든 연결을 끊긴 것으로 보던 것 → poll은 번호 제한이 없다
            poller = select.poll()
            poller.register(sock, select.POLLIN)
            return bool(poller.poll(0))
        return bool(select.select([sock], [], [], 0)[0])  # Windows: poll이 없고, select에 번호 제한도 없다
    except (OSError, ValueError):  # 이미 닫힌 소켓
        return True


class RedisUnavailable(Exception):
    pass


def cache_key(item_id, version):
    return f"item:{item_id}:v{version}"


# 데모 API가 쓰는 Mini Redis 클라이언트 (create_demo_server가 주소를 정해 바꿔 끼운다)
redis = RedisClient("http://127.0.0.1:6380")


# 캐시를 먼저 보고, 없으면 원본 조회 후 Mini Redis에 저장 (Cache-Aside 패턴) → (아이템, 캐시 상태)
def get_item_cached(item_id):
    version = current_version(item_id)
    if version is None:  # 없는 아이템은 캐시하지 않는다 (null은 Mini Redis에 저장할 수도 없다)
        return fetch_item(item_id), "MISS"
    try:
        cached = redis.get(cache_key(item_id, version))  # 지금 버전의 키만 읽는다
        if cached is not None:
            return cached, "HIT"
    except RedisUnavailable:
        return fetch_item(item_id), "BYPASS"  # 캐시가 죽어도 원본으로 응답한다

    item = fetch_item(item_id)
    # 조회하는 사이 수정되어 이미 옛 버전이 된 데이터는 저장하지 않는다 (옛 키를 다시 만들어 메모리를 차지하지 않게)
    # 이 확인과 저장 사이에 또 수정돼도 버전 키라서 옛 값이 새 요청에 보이지는 않는다
    if item is not None and item["version"] == current_version(item_id):
        try:
            # "읽어 온 데이터의" 버전 키에 저장한다. 조회 도중 수정됐다면 옛 버전 키에 들어가서 새 요청에 안 보인다
            redis.set(cache_key(item_id, item["version"]), item, CACHE_TTL)
        except RedisUnavailable:
            return item, "BYPASS"
    return item, "MISS"


def make_handler():
    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def do_GET(self):
            self._handle("GET")

        def do_PUT(self):
            self._handle("PUT")

        def _handle(self, method):
            try:
                self._route(method)
            except Exception:  # 예상 못한 오류도 연결을 끊지 않고 JSON 500으로 응답한다
                self._send(500, {"error": "서버 내부 오류"})

        def _route(self, method):
            url = urlsplit(self.path)
            parts = url.path.strip("/").split("/")
            # isascii: "²"(위첨자 2)처럼 isdigit은 True인데 int()로 못 바꾸는 유니코드 숫자를 막는다
            if len(parts) != 2 or parts[0] != "items" or not (parts[1].isascii() and parts[1].isdigit()):
                return self._send(404, {"error": "없는 경로입니다 (/items/{숫자 id})"})
            try:
                item_id = int(parts[1])
            except ValueError:  # 4300자리를 넘는 숫자는 int() 자릿수 제한에 걸린다 (500이던 것) → 그런 아이템은 없다
                return self._send(404, {"error": "없는 아이템입니다"})

            if method == "GET":
                if parse_qs(url.query).get("cache") == ["off"]:
                    item, cache = fetch_item(item_id), "OFF"
                else:
                    item, cache = get_item_cached(item_id)
                if item is None:
                    return self._send(404, {"error": "없는 아이템입니다", "cache": cache})
                return self._send(200, {"item": item, "cache": cache})

            # PUT: 원본을 고치고 버전을 올린다(무효화). 다음 GET은 새 버전 키를 찾다가 MISS가 되어 새 값을 가져간다
            # Mini Redis 서버와 같은 규칙: chunked는 411, 1MB 초과는 413 (전에는 둘 다 "price" 400으로 원인을 알 수 없었다)
            if "Transfer-Encoding" in self.headers:  # 값이 빈 헤더도 "있다"로 본다 (Mini Redis 서버와 같은 규칙)
                self.close_connection = True  # 읽지 않은 본문이 연결에 남으므로 닫는다
                return self._send(411, {"error": "Content-Length로 본문 길이를 알려 주세요 (chunked 전송은 지원하지 않습니다)"})
            # Mini Redis 서버와 같은 규칙: Content-Length는 0~9 숫자 하나만 ("+12" · "1_2" · 빈 값 · 두 개는 400, Gemini 리뷰)
            raw_length = self.headers.get("Content-Length", "0").strip()
            if (len(self.headers.get_all("Content-Length") or []) > 1 or not (raw_length.isascii() and raw_length.isdigit())
                    or len(raw_length) > 4000):
                self.close_connection = True
                return self._send(400, {"error": "Content-Length가 올바르지 않습니다"})
            try:
                length = int(raw_length)
                if length > MAX_BODY:
                    self.close_connection = True
                    discard_body(self.rfile, length)  # 읽어서 버린 뒤 응답해야 Windows에서 클라이언트가 413을 받는다
                    return self._send(413, {"error": "요청 본문이 너무 큽니다 (최대 1MB)"})
                if length < 0:
                    raise ValueError
                try:
                    raw = self.rfile.read(length)
                except (TimeoutError, socket.timeout):  # 본문을 덜 보내고 멈춘 클라이언트 → 500이 아니라 408
                    self.close_connection = True
                    return self._send(408, {"error": "요청 본문을 제한 시간 안에 다 받지 못했습니다"})
                if len(raw) != length:  # 덜 보내고 연결을 닫은 요청: 잘린 본문이 우연히 올바른 JSON이어도 받지 않는다
                    raise ValueError
                # NaN / Infinity는 표준 JSON이 아니라서 거부 (Mini Redis도 저장을 거부한다)
                body = json.loads(raw or b"{}", parse_constant=_reject_constant)
                if not isinstance(body, dict):
                    raise ValueError
                price = body["price"]
                if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price):
                    raise ValueError
            except (ValueError, KeyError, TypeError, OverflowError, RecursionError):  # RecursionError: 너무 깊게 중첩된 JSON
                return self._send(400, {"error": 'body는 {"price": 유한한 숫자} 여야 합니다'})
            item, old_version = update_item(item_id, price)
            if item is None:
                return self._send(404, {"error": "없는 아이템입니다"})
            # 버전이 올라갔으므로 이미 옛 캐시는 읽히지 않는다(무효화 완료). 옛 키 삭제는 메모리 정리용
            try:
                redis.delete(cache_key(item_id, old_version))
                old_cache_deleted = True
            except RedisUnavailable:
                old_cache_deleted = False  # 지우지 못해도 옛 키는 읽히지 않고 CACHE_TTL 뒤 만료된다
            return self._send(200, {"item": item, "old_cache_deleted": old_cache_deleted})

        def _send(self, status, body):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":  # HEAD 응답은 헤더만 보낸다 (HTTP 규약)
                    self.wfile.write(data)
            except ConnectionError:
                # 클라이언트가 응답을 다 받기 전에 연결을 끊었다. 보낼 곳이 없으니 조용히 정리한다
                # (예전에는 이 에러를 500으로 다시 응답하려다 끊긴 연결에 또 써서 두 번째 에러가 났다)
                self.close_connection = True

        # do_*가 없는 메서드(DELETE · POST · HEAD 등)나 깨진 요청 줄은 기본 동작이 HTML 에러 페이지라서,
        # Mini Redis 서버(server.py)와 같은 방식으로 JSON으로 바꾼다 (Gemini 리뷰: JSON을 기대하는 클라이언트가 파싱 에러)
        def send_error(self, code, message=None, explain=None):
            self.close_connection = True
            if code == 501:
                message = f"지원하지 않는 메서드입니다: {self.command}"
            self._send(code, {"error": message or "잘못된 요청입니다"})

        def log_message(self, format, *args):
            pass

    return Handler


def _reject_constant(name):
    raise ValueError(f"{name}은(는) 표준 JSON 값이 아닙니다")


# 데모 API 서버 객체 생성 (port=0이면 빈 포트 자동 선택 → 테스트용)
def create_demo_server(redis_url, host="127.0.0.1", port=8000):
    global redis
    redis.close()  # 바꿔 끼우기 전 클라이언트가 쥐고 있던 쉬는 연결을 닫는다
    redis = RedisClient(redis_url)
    return SafeThreadingHTTPServer((host, port), make_handler())


# 명령줄 실행 시작점
def main():
    parser = argparse.ArgumentParser(description="Mini Redis 캐시 데모 API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--redis", default="http://127.0.0.1:6380", help="Mini Redis 주소")
    args = parser.parse_args()
    # Mini Redis 서버 main과 같은 처리: 범위 밖 포트(OverflowError)와 이미 쓰이는 포트(OSError)가 traceback으로 나오던 것
    if not 0 <= args.port <= 65535:
        parser.error("--port는 0~65535 사이여야 합니다")
    try:
        server = create_demo_server(args.redis, args.host, args.port)
    except OSError as e:
        raise SystemExit(f"{args.host}:{args.port}에서 서버를 열 수 없습니다: {e}")
    print(f"Demo API listening on http://{args.host}:{args.port} (Mini Redis: {args.redis})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        redis.close()  # Mini Redis 연결 풀도 닫는다


if __name__ == "__main__":
    main()
