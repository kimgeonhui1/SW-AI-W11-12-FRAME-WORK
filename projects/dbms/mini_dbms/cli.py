# [cli.py] 명령줄 SQL 처리기 (Phase 1 의 입구)
#
#   python -m mini_dbms examples/phase1.sql            SQL 파일의 문장을 위에서부터 실행
#   python -m mini_dbms -e "SELECT * FROM users"       한 줄 SQL
#   python -m mini_dbms                                대화형 (mini_dbms> — ; 로 끝나는 줄에서 실행, exit 로 끝)
#   옵션: --data 폴더 (기본 projects/dbms/data) · --format table|json · --no-timing (시간 숨김 — 기대 출력 비교 테스트용)
#
# 출력 (표)
#   +----+--------+-----+
#   | id | name   | age |
#   +----+--------+-----+
#   |  1 | 김준우 |  25 |
#   +----+--------+-----+
#   1행 · 0.12 ms · index-eq (id = 1)
#
# 종료 코드: 0 = 모두 성공 · 1 = SQL 오류 (그 문장에서 멈춤) · 2 = 파일 · 데이터 폴더 문제

import argparse
import json
import sys
import unicodedata
from pathlib import Path

from .engine import Engine
from .errors import DataError, SqlError

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data"


def _width(text):
    """화면에서 차지하는 칸 수 — 한글 · 한자 같은 넓은 글자는 2칸 (표가 어긋나지 않게)"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _cell(value):
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return value.replace("\n", "\\n")  # 값 안의 줄바꿈은 표가 깨지지 않게 \n 으로 보여 준다
    return str(value)


def render_table(columns, rows):
    """결과 표 글자. 숫자는 오른쪽, 글자는 왼쪽 정렬"""
    cells = [[_cell(v) for v in row] for row in rows]
    widths = [max([_width(c)] + [_width(r[i]) for r in cells]) for i, c in enumerate(columns)]
    numeric = [bool(rows) and all(isinstance(r[i], (int, float)) or r[i] is None for r in rows) for i in range(len(columns))]

    def line(values, right):
        parts = []
        for v, w, r in zip(values, widths, right):
            pad = " " * (w - _width(v))
            parts.append(pad + v if r else v + pad)
        return "| " + " | ".join(parts) + " |"

    border = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [border, line(columns, [False] * len(columns)), border]
    out += [line(r, numeric) for r in cells]
    out.append(border)
    return "\n".join(out)


def format_result(result, timing=True):
    """결과 dict → 사람이 읽는 글자"""
    ms = f" · {result['ms']:.2f} ms" if timing else ""
    if result["type"] == "insert":
        ids = f"id {result['first_id']}" if result["count"] == 1 else f"id {result['first_id']} ~ {result['last_id']}"
        return f"INSERT {result['table']} {result['count']}행 ({ids}){ms}"
    if result["type"] == "explain":
        return f"계획: {result['plan']}"
    return f"{render_table(result['columns'], result['rows'])}\n{result['count']}행{ms} · {result['plan']} · 읽은 행 {result['scanned']}"


def run_sql(engine, sql, fmt, timing):
    """SQL 실행 + 출력. 성공 0, SQL 오류 1"""
    try:
        for result in engine.run(sql):
            if fmt == "json":
                if not timing:
                    result.pop("ms", None)
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(format_result(result, timing))
    except SqlError as e:
        print(f"오류 ({e.statement}번째 문장) {e}", file=sys.stderr)
        return 1
    return 0


def repl(engine, fmt, timing):
    """대화형: ; 로 끝나는 줄이 오면 모아 둔 줄들을 실행한다. 오류가 나도 계속 받는다"""
    print("미니 DBMS — SQL 을 입력하세요 (; 로 끝내면 실행, exit 로 종료)")
    buf = []
    while True:
        try:
            line = input("mini_dbms> " if not buf else "      ...> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:  # Ctrl+C: 쓰던 문장만 버린다
            print()
            buf = []
            continue
        if not buf and line.strip().lower() in ("exit", "quit"):
            return 0
        buf.append(line)
        if line.rstrip().endswith(";"):
            run_sql(engine, "\n".join(buf), fmt, timing)
            buf = []


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m mini_dbms", description="미니 DBMS — SQL 처리기 (INSERT · SELECT)")
    parser.add_argument("file", nargs="?", help="실행할 SQL 파일 (없으면 대화형)")
    parser.add_argument("-e", "--execute", help="파일 대신 이 SQL 을 실행")
    parser.add_argument("--data", default=str(DEFAULT_DATA), help="데이터 폴더 (스키마 · 데이터 파일)")
    parser.add_argument("--format", choices=("table", "json"), default="table")
    parser.add_argument("--no-timing", action="store_true", help="실행 시간을 출력하지 않음")
    args = parser.parse_args(argv)

    if args.execute is not None:
        sql = args.execute
    elif args.file is not None:
        try:
            sql = Path(args.file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"SQL 파일을 읽을 수 없습니다: {e}", file=sys.stderr)
            return 2
    else:
        sql = None

    try:
        engine = Engine(args.data)
    except DataError as e:
        print(f"데이터를 열 수 없습니다: {e}", file=sys.stderr)
        return 2
    try:
        for warning in engine.warnings:
            print(f"경고: {warning}", file=sys.stderr)
        if sql is None:
            return repl(engine, args.format, not args.no_timing)
        return run_sql(engine, sql, args.format, not args.no_timing)
    finally:
        engine.close()
