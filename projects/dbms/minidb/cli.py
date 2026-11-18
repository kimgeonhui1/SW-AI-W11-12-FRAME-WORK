# [cli.py] 명령줄(CLI)에서 SQL 파일을 실행한다 — 처리 흐름 전체를 잇는 곳
#
#   python -m minidb examples/demo.sql              (DB 폴더 기본값: data)
#   python -m minidb examples/demo.sql --db mydb
#
# ■ 순서: 파일 읽기 → 전체 파싱 → 문장을 하나씩 실행 → 결과 출력
#   - 파싱을 먼저 "전부" 끝낸다: 문법 오류가 하나라도 있으면 아무 문장도 실행하지 않는다 (반만 실행된 파일이 생기지 않게)
#   - 실행 중 오류(없는 테이블, 타입 불일치 등)가 나면 거기서 멈춘다. 앞 문장의 INSERT는 이미 저장된 상태다 (mysql 클라이언트와 같은 동작)
# ■ 종료 코드: 성공 0, 실패 1 → 다른 스크립트에서 성공 여부를 확인할 수 있다

import argparse
import sys
import unicodedata

from .executor import ExecutionError, Executor
from .parser import parse
from .storage import Database, SchemaError, StorageError
from .tokenizer import SqlSyntaxError


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m minidb", description="미니 DBMS SQL 처리기: SQL 파일을 읽어 실행합니다")
    parser.add_argument("sql_file", help="실행할 SQL 파일 (UTF-8)")
    parser.add_argument("--db", default="data", help="DB 폴더: schema.json과 테이블 파일이 있는 곳 (기본값: data)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # 출력을 파일로 돌리면 Windows 기본 인코딩(cp949)이 되어, 거기 없는 문자(이모지 등)를 찍다가 죽는다 → \U.. 로 바꿔 찍는다
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")

    try:
        with open(args.sql_file, encoding="utf-8-sig") as f:  # -sig: 메모장이 붙이는 BOM을 건너뛴다
            sql = f.read()
    except UnicodeDecodeError:
        return _error(f"SQL 파일이 UTF-8이 아닙니다: {args.sql_file}")
    except OSError as e:
        return _error(f"SQL 파일을 열 수 없습니다: {e}")

    try:
        statements = parse(sql)
    except SqlSyntaxError as e:
        return _error(f"문법 오류: {e}")

    try:
        executor = Executor(Database(args.db))
    except SchemaError as e:
        return _error(f"스키마 오류: {e}")

    for number, stmt in enumerate(statements, 1):
        try:
            result = executor.execute(stmt)
        except (ExecutionError, StorageError, OSError) as e:
            return _error(f"실행 오류 ({number}번째 문장, 줄 {stmt.line}): {e}")
        print(format_result(result))
    return 0


def _error(message):
    print(message, file=sys.stderr)
    return 1


# SELECT 결과를 표로, INSERT 결과는 메시지 한 줄로
#   +--------+-----+
#   | name   | age |
#   +--------+-----+
#   | 홍길동 | 25  |
#   +--------+-----+
#   1개 행
def format_result(result):
    if not result.columns:
        return result.message
    table = [[_cell(c) for c in result.columns]] + [[_cell(v) for v in row] for row in result.rows]
    widths = [max(_width(row[i]) for row in table) for i in range(len(result.columns))]
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def render(row):
        return "|" + "|".join(f" {text}{' ' * (w - _width(text))} " for text, w in zip(row, widths)) + "|"

    return "\n".join([line, render(table[0]), line, *map(render, table[1:]), line, result.message])


# 값 안의 줄바꿈·탭 같은 제어 문자는 \n 처럼 보이게 바꾼다 (그대로 찍으면 표가 깨진다)
def _cell(value):
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in str(value))


# 터미널에서 한글·한자 같은 전각 문자는 2칸을 차지한다. len()으로 맞추면 표 줄이 어긋난다
def _width(text):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)
