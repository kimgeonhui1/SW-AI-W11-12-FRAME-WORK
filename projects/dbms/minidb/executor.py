# [executor.py] 파싱된 문장을 실제로 실행한다 — 처리 흐름의 3단계 (파서와 저장소 사이)
#
# ■ 하는 일
#   1) 스키마와 맞춰 보며 검사: 없는 테이블·컬럼, 값 개수, 타입(INT 칸에 문자열 등)
#   2) INSERT: 값을 스키마의 컬럼 순서로 맞춰 저장소에 한 줄 추가
#      SELECT: 저장소의 모든 행을 처음부터 읽으며(선형 탐색) WHERE에 맞는 행만 골라, 요청한 컬럼만 돌려준다
#
# ■ 검사를 저장 "전에" 모두 끝낸다 → 잘못된 INSERT가 파일에 반쯤 들어가는 일이 없다

from typing import NamedTuple

from .parser import Insert


class ExecutionError(ValueError):
    """문법은 맞지만 스키마와 맞지 않는 문장 (없는 테이블, 타입 불일치 등)"""


class Result(NamedTuple):
    columns: list  # SELECT 결과의 컬럼 이름 (INSERT는 빈 목록)
    rows: list  # SELECT 결과 행들
    message: str


class Executor:
    def __init__(self, db):
        self.db = db

    def execute(self, stmt):
        if isinstance(stmt, Insert):
            return self._insert(stmt)
        return self._select(stmt)

    def _schema(self, table):
        schema = self.db.tables.get(table)
        if schema is None:
            raise ExecutionError(f"테이블이 없습니다: {table}")
        return schema

    def _insert(self, stmt):
        schema = self._schema(stmt.table)
        names = [name for name, _ in schema]
        columns = names if stmt.columns is None else stmt.columns
        if len(columns) != len(stmt.values):
            raise ExecutionError(f"컬럼은 {len(columns)}개인데 값은 {len(stmt.values)}개입니다")
        for i, column in enumerate(columns):
            if column not in names:
                raise ExecutionError(f"{stmt.table}에 없는 컬럼입니다: {column}")
            if column in columns[:i]:
                raise ExecutionError(f"같은 컬럼을 두 번 적었습니다: {column}")
        missing = [name for name in names if name not in columns]
        if missing:  # NULL을 지원하지 않으므로 모든 컬럼에 값이 있어야 한다
            raise ExecutionError(f"값이 없는 컬럼이 있습니다: {', '.join(missing)}")

        given = dict(zip(columns, stmt.values))
        for name, kind in schema:
            _check_type(stmt.table, name, kind, given[name])
        self.db.append(stmt.table, [given[name] for name in names])  # 파일에는 항상 스키마 순서로
        return Result([], [], "1개 행을 추가했습니다")

    def _select(self, stmt):
        schema = self._schema(stmt.table)
        position = {name: i for i, (name, _) in enumerate(schema)}
        columns = list(position) if stmt.columns is None else stmt.columns
        for column in columns:
            if column not in position:
                raise ExecutionError(f"{stmt.table}에 없는 컬럼입니다: {column}")
        picks = [position[c] for c in columns]

        where = None
        if stmt.where is not None:
            column, value = stmt.where
            if column not in position:
                raise ExecutionError(f"{stmt.table}에 없는 컬럼입니다: {column}")
            # WHERE age = '25'처럼 타입이 다르면 어떤 행과도 같을 수 없다 → 조용히 0개 대신 실수를 알려 준다
            _check_type(stmt.table, column, schema[position[column]][1], value)
            where = (position[column], value)

        rows = []
        for row in self.db.scan(stmt.table):  # 선형 탐색: 모든 행을 하나씩 비교 (Phase 2에서 id는 B+ 트리로 바꾼다)
            if where is None or row[where[0]] == where[1]:
                rows.append([row[i] for i in picks])
        return Result(columns, rows, f"{len(rows)}개 행")


def _check_type(table, column, kind, value):
    ok = type(value) is int if kind == "INT" else type(value) is str
    if not ok:
        got = "INT" if type(value) is int else "TEXT"
        raise ExecutionError(f"{table}.{column}은(는) {kind}인데 {got} 값 {value!r}이(가) 왔습니다")
