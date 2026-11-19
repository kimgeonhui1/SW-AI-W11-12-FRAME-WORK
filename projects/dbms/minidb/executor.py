# [executor.py] 파싱된 문장을 실제로 실행한다 — 처리 흐름의 3단계 (파서와 저장소 사이)
#
# ■ 하는 일
#   1) 스키마와 맞춰 보며 검사: 없는 테이블·컬럼, 값 개수, 타입(INT 칸에 문자열 등)
#   2) INSERT: 값을 스키마의 컬럼 순서로 맞춰 저장소에 한 줄 추가 (id는 저장소가 자동으로 부여)
#      SELECT: WHERE에 맞는 행만 골라 요청한 컬럼만 돌려준다
#
# ■ 실행 계획 (가장 단순한 옵티마이저, Phase 2)
#   WHERE id = 값  → B+ 트리 인덱스로 offset을 찾아 한 줄만 읽는다 (O(log n))
#   그 밖의 경우   → 파일을 처음부터 끝까지 읽는다 (전체 탐색, O(n))
#   어느 쪽을 썼는지 Result.plan에 남긴다 ("index" / "scan"). 성능 비교용으로 인덱스를 끈 Executor도 만들 수 있다
#
# ■ 검사를 저장 "전에" 모두 끝낸다 → 잘못된 INSERT가 파일에 반쯤 들어가는 일이 없다

from typing import NamedTuple

from .parser import CreateTable, Delete, Insert
from .storage import ID, SchemaError

_LABELS = {"index": "인덱스 사용", "scan": "전체 탐색"}


class ExecutionError(ValueError):
    """문법은 맞지만 스키마와 맞지 않는 문장 (없는 테이블, 타입 불일치 등)"""


class Result(NamedTuple):
    columns: list  # SELECT 결과의 컬럼 이름 (INSERT는 빈 목록)
    rows: list  # SELECT 결과 행들
    message: str
    plan: str = ""  # SELECT를 어떻게 찾았나: "index" 또는 "scan" (INSERT는 "")


class Executor:
    def __init__(self, db, use_index=True):
        self.db = db
        self.use_index = use_index  # False면 WHERE id도 전체 탐색 (인덱스 사용 · 미사용 속도 비교용)

    def execute(self, stmt):
        if isinstance(stmt, Insert):
            return self._insert(stmt)
        if isinstance(stmt, CreateTable):
            return self._create_table(stmt)
        if isinstance(stmt, Delete):
            return self._delete(stmt)
        return self._select(stmt)

    def _create_table(self, stmt):
        try:
            self.db.create_table(stmt.table, stmt.columns)
        except SchemaError as e:  # 이미 있는 테이블 · 잘못된 이름 등도 다른 실행 오류와 같은 종류로 알린다
            raise ExecutionError(str(e)) from None
        return Result([], [], f"테이블을 만들었습니다: {stmt.table}")

    def _check_table(self, table):
        if table not in self.db.tables:
            raise ExecutionError(f"테이블이 없습니다: {table}")

    def _insert(self, stmt):
        self._check_table(stmt.table)
        schema = self.db.tables[stmt.table]  # id를 뺀, 사용자가 값을 넣는 열들
        names = [name for name, _ in schema]
        if stmt.columns is not None and ID in stmt.columns:
            raise ExecutionError("id는 자동으로 부여되므로 값을 넣을 수 없습니다")
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
        row_id = self.db.append(stmt.table, [given[name] for name in names])  # 파일에는 항상 스키마 순서로
        return Result([], [], f"1개 행을 추가했습니다 (id={row_id})")

    def _select(self, stmt):
        self._check_table(stmt.table)
        schema = self.db.columns(stmt.table)  # id + 스키마의 열
        position = {name: i for i, (name, _) in enumerate(schema)}
        columns = list(position) if stmt.columns is None else stmt.columns
        for column in columns:
            if column not in position:
                raise ExecutionError(f"{stmt.table}에 없는 컬럼입니다: {column}")
        picks = [position[c] for c in columns]
        found, plan = self._find(stmt.table, stmt.where)
        rows = [[row[i] for i in picks] for row in found]
        return Result(columns, rows, f"{len(rows)}개 행 ({_LABELS[plan]})", plan)

    # DELETE: 지울 행을 SELECT와 같은 방법(인덱스 또는 전체 탐색)으로 찾은 뒤 저장소에 지우게 한다
    def _delete(self, stmt):
        self._check_table(stmt.table)
        found, plan = self._find(stmt.table, stmt.where)
        ids = [row[0] for row in found]  # 파일을 고치기 "전에" 다 찾아 둔다 (읽는 도중에 같은 파일을 덮어쓰지 않게)
        count = self.db.delete(stmt.table, ids)
        return Result([], [], f"{count}개 행을 삭제했습니다 ({_LABELS[plan]})", plan)

    # WHERE에 맞는 행 찾기 → (행들, "index" 또는 "scan"). where는 (컬럼, 값) 또는 None
    def _find(self, table, where):
        schema = self.db.columns(table)
        position = {name: i for i, (name, _) in enumerate(schema)}
        if where is not None:
            column, value = where
            if column not in position:
                raise ExecutionError(f"{table}에 없는 컬럼입니다: {column}")
            # WHERE age = '25'처럼 타입이 다르면 어떤 행과도 같을 수 없다 → 조용히 0개 대신 실수를 알려 준다
            _check_type(table, column, schema[position[column]][1], value)
            where = (position[column], value)

        if where is not None and where[0] == 0 and self.use_index:  # WHERE id = 값 → 인덱스
            row = self.db.get(table, where[1])
            return ([] if row is None else [row]), "index"
        # 전체 탐색: 모든 행을 하나씩 비교
        return (row for row in self.db.scan(table) if where is None or row[where[0]] == where[1]), "scan"


def _check_type(table, column, kind, value):
    ok = type(value) is int if kind == "INT" else type(value) is str
    if not ok:
        got = "INT" if type(value) is int else "TEXT"
        raise ExecutionError(f"{table}.{column}은(는) {kind}인데 {got} 값 {value!r}이(가) 왔습니다")
