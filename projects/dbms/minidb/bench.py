# [bench.py] Phase 2 성능 비교 — 대량 INSERT 후 "id로 찾기(B+ 트리)" vs "다른 열로 찾기(전체 탐색)"
#
#   python -m minidb.bench                      (기본: 100만 행, 검색 10번씩)
#   python -m minidb.bench --rows 200000 --queries 20
#   python -m minidb.bench --keep data_bench    (만든 DB 폴더를 지우지 않고 남긴다)
#
# ■ 데이터 만들기: INSERT 문을 1만 줄씩 문자열로 만들어 Phase 1 SQL 처리기(파서 → 실행기 → 저장소)에 그대로 넣는다
#   (과제 조건: Phase 1 처리기를 그대로 사용). 파일 하나에 100만 줄을 쓰면 파싱 결과를 한꺼번에 메모리에 들고 있게 돼서 나눠 넣는다
#
# ■ 무엇을 비교하나 (같은 질문을 세 가지로 풀어 시간을 잰다)
#   ① WHERE id = 값,   인덱스 사용 : B+ 트리에서 offset을 찾아 한 줄만 읽음       → O(log n)
#   ② WHERE id = 값,   인덱스 끔   : 같은 질문을 처음부터 끝까지 읽어서 찾음       → O(n)  (인덱스만의 효과를 보려고)
#   ③ WHERE name = 값, 인덱스 없음 : 과제가 말한 "다른 필드 기준 SELECT(선형 탐색)" → O(n)
#   세 방법의 결과 행이 같은지도 확인한다 (빠르기만 하고 틀리면 의미가 없다)
#
# ■ 재시작: 다 넣은 뒤 DB를 닫고 다시 열어, 파일을 읽어 인덱스를 다시 만드는 시간도 잰다 (메모리 기반 인덱스의 비용)

import argparse
import json
import os
import random
import statistics
import sys
import tempfile
import time

from .executor import Executor
from .parser import parse
from .storage import Database

BATCH = 10_000  # 한 번에 파싱하는 INSERT 문 수


def _name(i):
    return f"user{i}"


# rows개 행을 넣고 세 가지 검색을 queries번씩 재서 결과 dict를 돌려준다. out에 진행 상황과 표를 출력한다
def run(rows=1_000_000, queries=10, directory=None, out=print, seed=0):
    if isinstance(rows, bool) or not isinstance(rows, int) or rows < 1:
        raise ValueError("rows는 1 이상의 정수여야 합니다")
    if isinstance(queries, bool) or not isinstance(queries, int) or not 1 <= queries <= rows:
        raise ValueError("queries는 1 이상, rows 이하의 정수여야 합니다")
    tmp = None
    if directory is None:
        tmp = tempfile.TemporaryDirectory()
        directory = tmp.name
    elif os.path.exists(os.path.join(directory, "users.jsonl")):
        raise ValueError(f"{directory}에 이미 users.jsonl이 있습니다 (빈 폴더를 주세요)")
    os.makedirs(directory, exist_ok=True)
    try:
        with open(os.path.join(directory, "schema.json"), "w", encoding="utf-8") as f:
            json.dump({"users": {"name": "TEXT", "age": "INT"}}, f)
        return _measure(rows, queries, directory, out, random.Random(seed))
    finally:
        if tmp is not None:
            tmp.cleanup()


# schema.json(users: name, age)이 있는 빈 DB 폴더에 users 행을 rows개 넣는다 (Phase 1 SQL 처리기를 그대로 거친다) → 걸린 초
# 서버 동시성 벤치마크(bench_server.py)도 같은 데이터를 쓴다
def load_users(directory, rows, out=print):
    start = time.perf_counter()
    # 대량 적재: INSERT마다 flush하지 않고 끝날 때 한 번에 (행마다 약 9µs 아낌). 실제 DB의 대량 적재(LOAD DATA, COPY)도 같은 생각이다
    with Database(directory, autoflush=False) as db:
        ex = Executor(db)
        for first in range(1, rows + 1, BATCH):
            last = min(first + BATCH - 1, rows)
            sql = "".join(f"INSERT INTO users (name, age) VALUES ('{_name(i)}', {i % 100});\n" for i in range(first, last + 1))
            for stmt in parse(sql):
                ex.execute(stmt)
            if last % 100_000 == 0 or last == rows:
                out(f"  INSERT {last:,} / {rows:,}  ({time.perf_counter() - start:.1f}초)")
    return time.perf_counter() - start


def _measure(rows, queries, directory, out, rng):
    out(f"[미니 DBMS 인덱스 벤치마크] {rows:,}행, 검색 {queries}번씩")
    insert_s = load_users(directory, rows, out)
    size = os.path.getsize(os.path.join(directory, "users.jsonl"))

    with Database(directory) as db:  # 다시 켠 것과 같다 → 첫 사용 때 파일을 읽어 인덱스를 다시 만든다
        start = time.perf_counter()
        height = db.index_height("users")  # 첫 사용 = 인덱스 재구성만 일어난다 (검색 시간이 섞이지 않게, Gemini 리뷰)
        rebuild_s = time.perf_counter() - start

        targets = rng.sample(range(1, rows + 1), queries)
        modes = [
            ("① id, 인덱스 사용", Executor(db), "id"),
            ("② id, 인덱스 끔 (전체 탐색)", Executor(db, use_index=False), "id"),
            ("③ name, 전체 탐색", Executor(db), "name"),
        ]
        results, answers = {}, {}
        for label, executor, column in modes:
            times, plans = [], set()
            for row_id in targets:
                value = row_id if column == "id" else f"'{_name(row_id)}'"
                stmt = parse(f"SELECT * FROM users WHERE {column} = {value};")[0]
                t = time.perf_counter()
                result = executor.execute(stmt)
                times.append((time.perf_counter() - t) * 1000)
                plans.add(result.plan)
                answers.setdefault(row_id, []).append(result.rows)
            results[label] = {"avg_ms": statistics.fmean(times), "p50_ms": statistics.median(times),
                              "min_ms": min(times), "max_ms": max(times), "plan": "/".join(sorted(plans))}
    # 세 방법이 같은 답을 냈는가 (각 id마다 행 하나, 그 행의 id가 맞는가)
    correct = all(len({json.dumps(a) for a in ans}) == 1 and ans[0] and ans[0][0][0] == row_id
                  for row_id, ans in answers.items())

    out("")
    out(f"INSERT {rows:,}행: {insert_s:.1f}초 (초당 {rows / insert_s:,.0f}행), 파일 {size / 1024 / 1024:.1f}MB")
    out(f"재시작 후 인덱스 다시 만들기: {rebuild_s:.2f}초, B+ 트리 높이 {height}")
    out("")
    out(f"{'검색 방법':<26}{'평균(ms)':>12}{'p50(ms)':>12}{'최소':>10}{'최대':>10}   계획")
    for label, r in results.items():
        out(f"{label:<26}{r['avg_ms']:>12.3f}{r['p50_ms']:>12.3f}{r['min_ms']:>10.3f}{r['max_ms']:>10.3f}   {r['plan']}")
    fast = results["① id, 인덱스 사용"]["p50_ms"]
    out("")
    for label in ("② id, 인덱스 끔 (전체 탐색)", "③ name, 전체 탐색"):
        out(f"→ {label}은(는) 인덱스보다 p50 기준 약 {results[label]['p50_ms'] / fast:,.0f}배 느림")
    out(f"세 방법의 결과가 모두 같은가: {'예' if correct else '아니오 (확인 필요)'}")
    return {"rows": rows, "insert_s": insert_s, "file_bytes": size, "rebuild_s": rebuild_s, "height": height,
            "results": results, "correct": correct}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m minidb.bench", description="B+ 트리 인덱스 사용 · 미사용 검색 속도 비교")
    parser.add_argument("--rows", type=int, default=1_000_000, help="넣을 행 수 (기본 100만)")
    parser.add_argument("--queries", type=int, default=10, help="검색 방법마다 몇 번 잴지 (기본 10)")
    parser.add_argument("--keep", metavar="폴더", help="DB를 이 폴더에 만들고 지우지 않는다 (빈 폴더)")
    args = parser.parse_args(argv)
    try:
        result = run(args.rows, args.queries, args.keep)
    except ValueError as e:
        parser.exit(1, f"오류: {e}\n")
    except KeyboardInterrupt:
        parser.exit(130, "\n중단했습니다 (Ctrl+C)\n")
    return 0 if result["correct"] else 1


if __name__ == "__main__":
    sys.exit(main())
