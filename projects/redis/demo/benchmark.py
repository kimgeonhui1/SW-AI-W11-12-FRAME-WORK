# [benchmark.py] Mini Redis 사용 / 미사용 성능 비교 — 같은 요청을 반복해 응답 시간 측정
#
# Mini Redis 서버와 데모 API 서버를 이 프로세스 안에서 빈 포트로 띄운 뒤, 외부 클라이언트처럼 HTTP로 요청한다.
#   - 캐시 미사용: GET /items/{id}?cache=off 를 n번 → 매번 느린 원본 조회
#   - 캐시 사용  : 먼저 한 번 조회해 캐시를 채운 뒤(MISS) GET /items/{id} 를 n번 → 모두 HIT
#
# 실행: projects/redis 에서  python -m demo.benchmark            (기본 50번, 원본 지연 0.2초)
#                            python -m demo.benchmark --n 100 --delay 0.05

import argparse
import json
import statistics
import threading
import time
from urllib.request import urlopen

from demo import api_server
from mini_redis.server import create_server
from mini_redis.store import MiniRedis


# 요청 n번의 응답 시간(ms) 통계 → {"avg", "p50", "p95", "min", "max", "cache"}
def measure(url, n):
    if n < 1:
        raise ValueError("n은 1 이상이어야 합니다")
    times = []
    caches = set()
    for _ in range(n):
        start = time.perf_counter()
        with urlopen(url, timeout=30) as res:
            body = json.loads(res.read())
        times.append((time.perf_counter() - start) * 1000)
        caches.add(body["cache"])
    times.sort()
    return {
        "avg": statistics.fmean(times),
        "p50": times[len(times) // 2],
        "p95": times[min(len(times) - 1, int(len(times) * 0.95))],  # 느린 쪽 5% 경계 (가끔 튀는 응답을 보여 준다)
        "min": times[0],
        "max": times[-1],
        "cache": "/".join(sorted(caches)),  # 측정 중 받은 캐시 상태 (전부 HIT여야 "캐시 사용" 측정이 맞다)
    }


# 두 서버를 띄우고 측정 → (캐시 미사용 결과, 캐시 사용 결과). 서버는 끝나면 닫는다
def run(n, delay, item_id=1):
    api_server.SLOW_DELAY = delay
    redis_server = create_server(MiniRedis(), port=0)
    demo_server = api_server.create_demo_server(f"http://127.0.0.1:{redis_server.server_address[1]}", port=0)
    for server in (redis_server, demo_server):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    # localhost가 아니라 127.0.0.1: Windows에서 localhost는 IPv6를 먼저 시도해 요청마다 약 0.2초가 더 붙는다
    base = f"http://127.0.0.1:{demo_server.server_address[1]}/items/{item_id}"
    try:
        without_cache = measure(base + "?cache=off", n)
        urlopen(base, timeout=30).close()  # 캐시 채우기 (MISS 한 번)
        with_cache = measure(base, n)
        return without_cache, with_cache
    finally:
        for server in (demo_server, redis_server):
            server.shutdown()
            server.server_close()


# 캐시 사용 / 미사용 결과를 표로 출력
def main():
    parser = argparse.ArgumentParser(description="Mini Redis 사용/미사용 성능 비교")
    parser.add_argument("--n", type=int, default=50, help="측정할 요청 수")
    parser.add_argument("--delay", type=float, default=0.2, help="원본 조회 지연(초)")
    args = parser.parse_args()

    without_cache, with_cache = run(args.n, args.delay)
    print(f"\n요청 {args.n}번, 원본 조회 지연 {args.delay}초 (단위: ms)\n")
    print(f"{'':14}{'평균':>9}{'p50':>9}{'p95':>9}{'최소':>9}{'최대':>9}   캐시 상태")
    for label, r in [("캐시 미사용", without_cache), ("캐시 사용", with_cache)]:
        print(f"{label:<12}{r['avg']:>9.1f}{r['p50']:>9.1f}{r['p95']:>9.1f}{r['min']:>9.1f}{r['max']:>9.1f}   {r['cache']}")
    print(f"\n→ 캐시 사용 시 평균 {without_cache['avg'] / with_cache['avg']:.1f}배 빠름")


if __name__ == "__main__":
    main()
