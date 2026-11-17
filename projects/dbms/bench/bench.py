# [bench.py] Phase 2 성능 측정 — B+ 트리 인덱스(WHERE id = ?) vs 선형 탐색(WHERE name = ?)
#
#   python -m bench.bench                        (projects/dbms 에서) 1만 · 10만 · 100만 건
#   python -m bench.bench --sizes 10000,100000   크기 바꾸기
#   python -m bench.bench --server               + Phase 3 서버의 작업자 수별 처리량
#
# 하는 일 (크기마다 빈 임시 폴더에서 새로)
#   1) gen_sql 의 INSERT 문장을 Engine.run 으로 실행 — CLI 와 같은 SQL 처리기 경로 (파싱 → 검사 → 파일 → 인덱스)
#   2) 엔진을 껐다 켜서 인덱스 다시 만들기(파일 훑기 + 한꺼번에 쌓기) 시간
#   3) 같은 한 행을 id 로 · name 으로 찾는 시간 (앞 · 가운데 · 끝 · 없는 id) — SQL 파싱까지 포함한 사용자 기준 시간
#   4) id 범위 1,000행
#   5) B+ 트리만 따로: 100만 개를 순서대로 넣을 때 오른쪽 치우침 분할 켬 / 끔 → 잎 수 · 채움 · 시간
# 측정은 여러 번 해서 중앙값. 같은 파일을 반복해서 읽으므로 운영체제 파일 캐시가 데워진 상태의 값이다.

import argparse
import shutil
import statistics
import tempfile
import threading
import time
from pathlib import Path

from bench.gen_sql import users_sql
from mini_dbms.bptree import BPlusTree
from mini_dbms.engine import Engine

ROOT = Path(__file__).resolve().parent.parent


def timed(fn, reps):
    """fn 을 reps 번 → 중앙값(ms)"""
    samples = []
    for _ in range(reps):
        t = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t) * 1000)
    return statistics.median(samples)


def fresh_dir():
    d = Path(tempfile.mkdtemp(prefix="mini_dbms_bench_"))
    shutil.copy(ROOT / "data/users.schema.json", d)
    return d


def bench_size(n):
    d = fresh_dir()
    try:
        engine = Engine(d)
        t = time.perf_counter()
        for _ in engine.run("".join(users_sql(n))):
            pass
        insert_s = time.perf_counter() - t
        size_mb = (d / "users.jsonl").stat().st_size / 1e6
        engine.close()
        t = time.perf_counter()
        engine = Engine(d)  # 인덱스는 메모리에만 → 켤 때 파일을 훑어 다시 만든다
        reopen_s = time.perf_counter() - t
        run = lambda sql: engine.execute_all(sql)  # noqa: E731
        mid = n // 2
        check = run(f"SELECT * FROM users WHERE id = {mid}")[0]
        same = run(f"SELECT * FROM users WHERE name = 'user_{mid}'")[0]
        assert check["rows"] == same["rows"] and len(check["rows"]) == 1, "인덱스와 선형 탐색이 다른 행을 찾음"
        assert check["plan"].startswith("index-eq") and same["plan"] == "full-scan"
        row = {
            "n": n,
            "insert_s": insert_s,
            "file_mb": size_mb,
            "reopen_s": reopen_s,
            "id_first": timed(lambda: run("SELECT * FROM users WHERE id = 1"), 1000),
            "id_mid": timed(lambda: run(f"SELECT * FROM users WHERE id = {mid}"), 1000),
            "id_last": timed(lambda: run(f"SELECT * FROM users WHERE id = {n}"), 1000),
            "id_missing": timed(lambda: run(f"SELECT * FROM users WHERE id = {n + 1}"), 1000),
            "name_mid": timed(lambda: run(f"SELECT * FROM users WHERE name = 'user_{mid}'"), 5),
            "range_1000": timed(lambda: run(f"SELECT * FROM users WHERE id >= {mid} AND id < {mid + 1000}"), 50),
            "height": engine.tables["users"].index.height(),
        }
        engine.close()
        return row
    finally:
        shutil.rmtree(d, ignore_errors=True)


def bench_split(n):
    """순서대로 n 개 넣기 — 오른쪽 치우침 분할 켬 / 끔"""
    out = {}
    for flag in (True, False):
        tree = BPlusTree(64, append_split=flag)
        t = time.perf_counter()
        for k in range(1, n + 1):
            tree.insert(k, k)
        out[flag] = {"s": time.perf_counter() - t, **tree.stats()}
    return out


def bench_server(n=100_000, seconds=3.0):
    """Phase 3: 작업자 수별 처리량 — 클라이언트 16개가 seconds 초 동안 id 로 찾기 / 10만 건 선형 탐색"""
    import http.client
    import json
    import random
    import socket
    import struct

    from mini_dbms.server import create_server

    d = fresh_dir()
    engine = Engine(d)
    for _ in engine.run("".join(users_sql(n))):
        pass
    results = []
    try:
        for workers in (1, 4, 8, 16):
            server = create_server(engine, port=0, workers=workers, queue_limit=64)
            port = server.server_address[1]
            threading.Thread(target=server.serve_forever, daemon=True).start()
            for label, make_sql in [("id 찾기", lambda r: f"SELECT * FROM users WHERE id = {r.randint(1, n)}"), ("선형 탐색", lambda r: f"SELECT id FROM users WHERE name = 'user_{r.randint(1, n)}'")]:
                count, stop = [0], time.monotonic() + seconds

                def client(seed):
                    r = random.Random(seed)
                    while time.monotonic() < stop:
                        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                        conn.connect()
                        # 측정 클라이언트 전용: 닫을 때 TIME_WAIT 를 남기지 않는다. 요청마다 새 연결을 초당 수천 번 열면
                        # 맥의 임시 포트(약 1.6만 개)가 TIME_WAIT 로 다 차서 "Can't assign requested address" 가 난다
                        # (응답을 다 읽으면 http.client 가 소켓을 닫아 버리므로 연결 직후에 설정한다)
                        conn.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                        conn.request("POST", "/query", body=json.dumps({"sql": make_sql(r)}))
                        res = conn.getresponse()
                        res.read()
                        conn.close()
                        if res.status == 200:
                            count[0] += 1

                threads = [threading.Thread(target=client, args=(i,)) for i in range(16)]
                for th in threads:
                    th.start()
                for th in threads:
                    th.join()
                results.append((workers, label, count[0] / seconds))
            server.shutdown()
            server.server_close()
    finally:
        engine.close()
        shutil.rmtree(d, ignore_errors=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="미니 DBMS 성능 측정")
    parser.add_argument("--sizes", default="10000,100000,1000000")
    parser.add_argument("--server", action="store_true", help="Phase 3 작업자 수별 처리량도 잰다")
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",")]

    print("| 행 수 | INSERT 전체 | 파일 | 다시 열기(인덱스 재구성) | 높이 | id = 1 | id = 가운데 | id = 끝 | 없는 id | name = 가운데 (선형) | 배 | id 범위 1,000행 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n in sizes:
        r = bench_size(n)
        print(
            f"| {n:,} | {r['insert_s']:.1f}초 | {r['file_mb']:.0f}MB | {r['reopen_s']:.2f}초 | {r['height']} | {r['id_first']:.3f}ms | {r['id_mid']:.3f}ms | {r['id_last']:.3f}ms"
            f" | {r['id_missing']:.3f}ms | {r['name_mid']:.1f}ms | {r['name_mid'] / r['id_mid']:,.0f} | {r['range_1000']:.1f}ms |",
            flush=True,
        )

    n = max(sizes)
    s = bench_split(n)
    print(f"\nB+ 트리에 {n:,}개를 순서대로 넣기 (order 64)")
    print("| 분할 | 시간 | 높이 | 잎 수 | 안쪽 노드 | 잎 채움 |")
    print("|---|---|---|---|---|---|")
    for flag, label in ((True, "오른쪽 치우침 (기본)"), (False, "반반 (보통)")):
        x = s[flag]
        print(f"| {label} | {x['s']:.2f}초 | {x['height']} | {x['leaves']:,} | {x['inner']:,} | {x['leaf_fill'] * 100:.0f}% |")

    if args.server:
        print("\nPhase 3 — 작업자 수별 처리량 (10만 건, 클라이언트 16개, 3초씩)")
        print("| 작업자 | 쿼리 | 요청/초 |")
        print("|---|---|---|")
        for workers, label, qps in bench_server():
            print(f"| {workers} | {label} | {qps:,.0f} |", flush=True)


if __name__ == "__main__":
    main()
