# [benchmark.py] Mini Redis 사용 / 미사용 성능 비교 — 같은 요청을 반복해 평균 응답 시간 측정
#
# 설계 문서: projects/redis/Docs/설계.md  11장
#
# 실행: projects/redis 에서  python -m demo.benchmark
#   --api 를 주지 않으면 Mini Redis 서버와 데모 API 서버를 이 프로그램 안에서 빈 포트로 직접 띄운다 → 명령 하나로 끝
#   이미 띄워 둔 서버로 재려면:  python -m demo.benchmark --api http://127.0.0.1:8000
#
# 같은 아이템을 n번 요청한다
#   캐시 미사용 (?cache=off) : 매번 느린 원본 조회 → 약 200ms × n
#   캐시 사용               : 첫 요청만 MISS(약 200ms), 나머지는 HIT(수 ms)

import argparse
import threading
import time
from urllib.request import urlopen

from demo import api_server
from mini_redis.server import create_server as create_redis_server
from mini_redis.store import MiniRedis


# 요청 n번의 평균 응답 시간(ms) 측정
# 응답 본문까지 다 읽은 시간을 잰다 (헤더만 받고 끝내면 서버가 덜 일한 것처럼 보인다)
def measure(url, n):
    total = 0.0
    for _ in range(n):
        start = time.perf_counter()  # perf_counter: 짧은 시간 재기에 가장 정밀한 시계
        with urlopen(url, timeout=10) as res:
            res.read()
        total += time.perf_counter() - start
    return total / n * 1000


# 캐시 사용 / 미사용 결과를 표로 출력
def main():
    parser = argparse.ArgumentParser(description="Mini Redis 캐시 사용 / 미사용 성능 비교")
    parser.add_argument("--api", help="데모 API 주소 (없으면 이 안에서 서버를 직접 띄운다)")
    parser.add_argument("--n", type=int, default=20, help="요청 횟수")
    parser.add_argument("--id", type=int, default=1, help="요청할 아이템 id (1~100)")
    args = parser.parse_args()

    servers = [] if args.api else _start_servers()
    api = args.api.rstrip("/") if args.api else f"http://127.0.0.1:{servers[1].server_address[1]}"
    try:
        off = measure(f"{api}/items/{args.id}?cache=off", args.n)
        on = measure(f"{api}/items/{args.id}", args.n)
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()

    print(f"아이템 {args.id} 을 {args.n}번 요청한 평균 응답 시간")
    print(f"| 방식        | 평균 (ms) |")
    print(f"|-------------|-----------|")
    print(f"| 캐시 미사용 | {off:9.2f} |")
    print(f"| 캐시 사용   | {on:9.2f} |")
    print(f"→ 캐시를 쓰면 약 {off / on:.1f}배 빠름 (캐시 사용의 첫 요청은 MISS 라 원본 조회 시간이 포함됨)")


# Mini Redis 서버 + 데모 API 서버를 빈 포트에 띄운다 → [redis 서버, api 서버]
def _start_servers():
    redis = create_redis_server(MiniRedis(), port=0)
    api = api_server.create_demo_server(f"http://127.0.0.1:{redis.server_address[1]}", port=0)
    for server in (redis, api):
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return [redis, api]


if __name__ == "__main__":
    main()
