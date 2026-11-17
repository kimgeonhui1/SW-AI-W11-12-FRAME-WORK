# [gen_sql.py] 대량 INSERT SQL 만들기 — Phase 2 의 100만 건을 "SQL 처리기 그대로" 넣기 위한 입력
#
#   python -m bench.gen_sql --rows 1000000 > /tmp/users_1m.sql        (projects/dbms 에서)
#   python -m mini_dbms --data /tmp/bench_data /tmp/users_1m.sql
#
# ■ INSERT 한 문장에 1,000행씩 (VALUES (…), (…), …) → 문장 1,000개. 행마다 문장 하나면 파싱 · 락 · 쓰기가 100만 번이라 느리다.
# ■ 고정 씨앗(seed) 난수 → 누가 언제 돌려도 같은 데이터 · 같은 결과.
# ■ n 번째 행의 name 은 'user_n' (겹치지 않음) → "WHERE id = n" 과 "WHERE name = 'user_n'" 이 정확히 같은 한 행을 찾는다
#   (인덱스 / 선형 탐색을 공정하게 비교하려고). 빈 테이블에 넣으면 id 도 n 이 된다.

import argparse
import random
import sys


def users_sql(rows, batch=1000, seed=42):
    """users 테이블용 INSERT 문장을 하나씩 (문자열)"""
    rnd = random.Random(seed)
    for start in range(1, rows + 1, batch):
        values = ", ".join(f"('user_{n}', {rnd.randint(18, 80)}, 'user{n}@example.com')" for n in range(start, min(rows, start + batch - 1) + 1))
        yield f"INSERT INTO users (name, age, email) VALUES {values};\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="users 테이블 대량 INSERT SQL 생성")
    parser.add_argument("--rows", type=int, default=1_000_000)
    parser.add_argument("--batch", type=int, default=1000, help="INSERT 한 문장의 행 수")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    if args.rows < 0 or args.batch < 1:
        parser.error("--rows 는 0 이상, --batch 는 1 이상")
    for stmt in users_sql(args.rows, args.batch, args.seed):
        sys.stdout.write(stmt)


if __name__ == "__main__":
    main()
