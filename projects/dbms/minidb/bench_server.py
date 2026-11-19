# [bench_server.py] Phase 3 서버 동시성 벤치마크 — 클라이언트 여러 명이 동시에 요청할 때 처리량 · 응답 시간 · 거절
#
#   python -m minidb.bench_server                       (기본: 5만 행, 클라이언트 1 · 4 · 16명, 한 명당 50번)
#   python -m minidb.bench_server --rows 20000 --requests 30 --clients 1,8,32
#
# ■ 무엇을 재나
#   ① id SELECT (인덱스): 클라이언트 수를 늘릴 때 처리량(요청/초)과 p50 · p95
#   ② INSERT: 같은 방식. INSERT는 테이블의 쓰기 락을 혼자 잡으므로 한 번에 하나씩만 실행된다
#   ③ 작업자 수: 같은 부하(클라이언트 16명의 id SELECT)를 작업자 1개 서버와 8개 서버에 보내 비교
#   ④ 과부하: 작업자 2개 · 큐 4칸 서버에 느린 요청(전체 탐색)을 몰아 넣어, 감당 못 하는 요청을 503으로 바로 거절하는지
#
# ■ 측정 방법 (Mini Redis 벤치마크와 같은 원칙)
#   - 클라이언트 스레드가 모두 준비된 뒤 출발선(Barrier)에서 한꺼번에 출발한다. 출발 시각은 Barrier의 action에서 잰다
#   - 처리량 = 요청 수 ÷ (모두 출발한 순간부터 마지막 응답까지의 시간)
#   - 요청마다 새 HTTP 연결 (서버가 응답마다 연결을 닫으므로)
#   - 서버와 클라이언트가 같은 프로세스 · 같은 컴퓨터에 있다. 파이썬 GIL 때문에 CPU 작업(파싱 · JSON · 트리 탐색)은 한 번에
#     하나만 실행되므로, 작업자를 늘려도 처리량이 그만큼 늘지는 않는다 (네트워크 · 파일 대기만 겹친다)

import argparse
import http.client
import json
import math
import os
import random
import statistics
import sys
import tempfile
import threading
import time
from collections import Counter

from .bench import _name, load_users
from .server import create_server, stop_server


def _post(port, sql):
    """SQL 한 번 → (상태 코드 또는 "error", 걸린 ms)"""
    start = time.perf_counter()
    # 연결은 제한 시간 없이 맺고, 연결된 뒤에만 읽기 제한 시간을 건다: Windows에서 제한 시간을 건 connect는 localhost에서도
    # 약 40%가 15ms 이상 걸려 측정을 흔들었다 (Mini Redis 벤치마크에서 찾은 원인). 클라이언트 수는 대기열(128) 이하라 연결이 멈추지 않는다
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.connect()
        conn.sock.settimeout(60)
        conn.request("POST", "/query", body=json.dumps({"sql": sql}).encode(), headers={"Content-Type": "application/json"})
        res = conn.getresponse()
        res.read()
        status = res.status
    except OSError as e:  # 연결 거부 · 끊김 (서버 대기열이 넘친 경우 등). 종류를 남겨 원인을 알 수 있게
        status = f"error:{type(e).__name__}"
    finally:
        conn.close()
    return status, (time.perf_counter() - start) * 1000


# clients명이 동시에 per_client번씩 요청 → {"rps", "p50_ms", "p95_ms", "statuses"}. make_sql(client, i)가 보낼 SQL을 만든다
def _load(port, clients, per_client, make_sql):
    clock, samples, lock = {}, [], threading.Lock()
    ready = threading.Barrier(clients + 1, action=lambda: clock.setdefault("start", time.perf_counter()), timeout=30)

    def client(c):
        ready.wait()
        mine = [_post(port, make_sql(c, i)) for i in range(per_client)]
        with lock:
            samples.extend(mine)

    threads = [threading.Thread(target=client, args=(c,)) for c in range(clients)]
    for t in threads:
        t.start()
    ready.wait()  # 모두 준비되면 한꺼번에 출발
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - clock["start"]
    ok = sorted(ms for status, ms in samples if status == 200)
    return {
        "clients": clients,
        "requests": len(samples),
        "rps": len(samples) / elapsed,
        "p50_ms": statistics.median(ok) if ok else None,
        "p95_ms": ok[math.ceil(0.95 * len(ok)) - 1] if ok else None,  # nearest-rank
        "statuses": Counter(samples_status for samples_status, _ in samples),
    }


def _with_server(directory, workers, queue_size, fn):
    server = create_server(directory, port=0, workers=workers, queue_size=queue_size)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    # 데우기: 테이블을 처음 쓰는 요청은 파일을 읽어 인덱스를 다시 만든다(메모리 기반). 그 시간이 측정에 섞이지 않게 미리 한 번
    _post(port, "SELECT id FROM users WHERE id = 1")
    try:
        return fn(port)
    finally:
        server.shutdown()
        stop_server(server)


def run(rows=50_000, per_client=50, clients_list=(1, 4, 16), out=print, seed=0):
    for name, value in (("rows", rows), ("per_client", per_client)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name}은(는) 1 이상의 정수여야 합니다")
    clients_list = list(clients_list)
    if not clients_list or any(isinstance(c, bool) or not isinstance(c, int) or not 1 <= c <= 100 for c in clients_list):
        raise ValueError("clients는 1~100 사이 정수 목록이어야 합니다 (서버 연결 대기열 128을 넘지 않게)")
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory() as directory:
        with open(os.path.join(directory, "schema.json"), "w", encoding="utf-8") as f:
            json.dump({"users": {"name": "TEXT", "age": "INT"}}, f)
        out(f"[미니 DBMS 서버 동시성 벤치마크] {rows:,}행, 클라이언트 {clients_list}명, 한 명당 {per_client}번")
        load_users(directory, rows, out=lambda *_: None)
        ids = [rng.randint(1, rows) for _ in range(10_000)]

        def select_by_id(c, i):
            return f"SELECT * FROM users WHERE id = {ids[(c * per_client + i) % len(ids)]}"

        def insert(c, i):
            return f"INSERT INTO users (name, age) VALUES ('bench{c}-{i}', {i})"

        report = {}
        report["select"] = _with_server(directory, 8, 256, lambda port: [_load(port, c, per_client, select_by_id) for c in clients_list])
        report["insert"] = _with_server(directory, 8, 256, lambda port: [_load(port, c, per_client, insert) for c in clients_list])
        busiest = max(clients_list)
        report["workers"] = {w: _with_server(directory, w, 256, lambda port: _load(port, busiest, per_client, select_by_id))
                             for w in (1, 8)}
        # 과부하: 느린 요청(전체 탐색) 3번씩 × 30명을 작업자 2개 · 큐 4칸 서버에 → 처리 중 2 + 대기 4를 넘는 요청은 바로 503
        slow = lambda c, i: f"SELECT id FROM users WHERE name = '{_name(rows - c)}'"  # noqa: E731
        report["overload"] = _with_server(directory, 2, 4, lambda port: _load(port, 30, 3, slow))

    _print(report, out)
    return report


def _fmt(ms):
    return "-" if ms is None else f"{ms:.1f}"


def _print(report, out):
    for key, title in (("select", "① id SELECT (인덱스), 작업자 8개"), ("insert", "② INSERT, 작업자 8개")):
        out("")
        out(title)
        out(f"{'클라이언트':>10}{'요청/초':>12}{'p50(ms)':>10}{'p95(ms)':>10}   상태")
        for r in report[key]:
            out(f"{r['clients']:>10}{r['rps']:>12.0f}{_fmt(r['p50_ms']):>10}{_fmt(r['p95_ms']):>10}   {dict(r['statuses'])}")
    out("")
    out("③ 작업자 수 (같은 부하: 가장 많은 클라이언트의 id SELECT)")
    for workers, r in report["workers"].items():
        out(f"  작업자 {workers}개: {r['rps']:.0f} 요청/초, p50 {_fmt(r['p50_ms'])}ms, p95 {_fmt(r['p95_ms'])}ms")
    o = report["overload"]
    out("")
    out("④ 과부하 (작업자 2개 · 큐 4칸, 느린 전체 탐색 30명 × 3번)")
    out(f"  상태: {dict(o['statuses'])}  → 503은 큐가 꽉 차 바로 거절된 요청 (서버는 무너지지 않고 받은 요청은 끝까지 처리)")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m minidb.bench_server", description="API 서버 동시성 벤치마크")
    parser.add_argument("--rows", type=int, default=50_000)
    parser.add_argument("--requests", type=int, default=50, help="클라이언트 한 명당 요청 수")
    parser.add_argument("--clients", default="1,4,16", help="쉼표로 구분한 동시 클라이언트 수 (예: 1,4,16)")
    args = parser.parse_args(argv)
    try:
        clients = [int(c) for c in args.clients.split(",")]
        run(args.rows, args.requests, clients)
    except ValueError as e:
        parser.exit(1, f"오류: {e}\n")
    except KeyboardInterrupt:
        parser.exit(130, "\n중단했습니다 (Ctrl+C)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
