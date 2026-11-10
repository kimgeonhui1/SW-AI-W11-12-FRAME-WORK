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
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

from mini_redis.server import SafeThreadingHTTPServer

SLOW_DELAY = 0.2  # 원본 조회에 걸리는 시간(초). 실제 DB 쿼리나 외부 API 호출을 흉내 낸다
CACHE_TTL = 60  # 캐시 보관 시간(초). 원본이 바뀌었는데 무효화를 놓쳐도 최대 60초 뒤에는 새 값이 보인다
REDIS_TIMEOUT = 1.0  # Mini Redis 요청 제한 시간. 캐시가 느려져도 API 전체가 같이 느려지지 않게
ITEM_COUNT = 100

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
    """Mini Redis HTTP API를 부르는 작은 클라이언트. 연결 실패·시간 초과는 RedisUnavailable로 통일한다"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

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

    def _request(self, method, key, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = Request(f"{self.base_url}/keys/{quote(key, safe='')}", data=data, method=method)
        try:
            with urlopen(req, timeout=REDIS_TIMEOUT) as res:
                return res.status, json.loads(res.read())
        except HTTPError as e:
            with e:
                if e.code == 404:  # 404는 "키 없음"이라는 정상 응답
                    return 404, None
                raise RedisUnavailable(f"Mini Redis 오류 응답 {e.code}")
        except (URLError, TimeoutError, OSError, http.client.HTTPException, ValueError) as e:
            # 연결 실패·시간 초과·중간에 끊긴 응답(HTTPException)·JSON이 아닌 응답(ValueError)을 모두 "캐시 사용 불가"로 통일
            # → 호출한 쪽은 원본으로 응답(BYPASS)하면 되고, 캐시 문제로 500이 나지 않는다
            raise RedisUnavailable(str(e))


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
            item_id = int(parts[1])

            if method == "GET":
                if parse_qs(url.query).get("cache") == ["off"]:
                    item, cache = fetch_item(item_id), "OFF"
                else:
                    item, cache = get_item_cached(item_id)
                if item is None:
                    return self._send(404, {"error": "없는 아이템입니다", "cache": cache})
                return self._send(200, {"item": item, "cache": cache})

            # PUT: 원본을 고치고 버전을 올린다(무효화). 다음 GET은 새 버전 키를 찾다가 MISS가 되어 새 값을 가져간다
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= 1024 * 1024:
                    raise ValueError
                # NaN / Infinity는 표준 JSON이 아니라서 거부 (Mini Redis도 저장을 거부한다)
                body = json.loads(self.rfile.read(length) or b"{}", parse_constant=_reject_constant)
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
                self.wfile.write(data)
            except ConnectionError:
                # 클라이언트가 응답을 다 받기 전에 연결을 끊었다. 보낼 곳이 없으니 조용히 정리한다
                # (예전에는 이 에러를 500으로 다시 응답하려다 끊긴 연결에 또 써서 두 번째 에러가 났다)
                self.close_connection = True

        def log_message(self, format, *args):
            pass

    return Handler


def _reject_constant(name):
    raise ValueError(f"{name}은(는) 표준 JSON 값이 아닙니다")


# 데모 API 서버 객체 생성 (port=0이면 빈 포트 자동 선택 → 테스트용)
def create_demo_server(redis_url, host="127.0.0.1", port=8000):
    global redis
    redis = RedisClient(redis_url)
    return SafeThreadingHTTPServer((host, port), make_handler())


# 명령줄 실행 시작점
def main():
    parser = argparse.ArgumentParser(description="Mini Redis 캐시 데모 API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--redis", default="http://127.0.0.1:6380", help="Mini Redis 주소")
    args = parser.parse_args()
    server = create_demo_server(args.redis, args.host, args.port)
    print(f"Demo API listening on http://{args.host}:{args.port} (Mini Redis: {args.redis})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
