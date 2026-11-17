# [engine.py] DB 엔진 — CLI(Phase 1) 와 API 서버(Phase 3) 가 부르는 유일한 입구
#
#   engine = Engine("data")                      켤 때: 스키마 읽기 → 테이블마다 파일을 훑어 B+ 트리 다시 만들기
#   for result in engine.run(sql): …              문장마다: 파싱 → 락 → 실행 → 결과 dict (하나씩 돌려준다)
#   engine.close()
#
# ■ 계층: Engine 은 문장을 순서대로 실행하고 락만 책임진다.
#   문법은 parser, 계획 · 조건은 executor, 파일 · 인덱스는 table 이 맡는다 → 서버는 Engine 만 알면 된다.
#
# ■ 락: 테이블마다 읽기-쓰기 락 하나 (rwlock.py)
#   SELECT = 읽기 락 (여럿 동시), INSERT = 쓰기 락 (혼자) — 락은 문장 하나 동안만 잡는다.
#   INSERT 의 값 검사(prepare_insert)는 락 밖에서 먼저 한다 → 쓰기 락을 잡는 시간이 짧다.
#   SELECT 는 결과를 다 모을 때까지 읽기 락 안에 있다 (모으는 도중 행이 늘어나지 않게).
#
# ■ 여러 문장 중 하나가 틀리면 거기서 멈춘다. 앞 문장의 결과는 이미 돌려줬고(되돌리지 않음 — 트랜잭션 없음),
#   오류에는 몇 번째 문장인지(statement)가 붙는다.

import time

from . import executor
from .catalog import Catalog
from .errors import SqlError
from .nodes import Insert
from .parser import parse_script
from .rwlock import RWLock
from .table import Table


class Engine:
    def __init__(self, data_dir, order=64, sync=False):
        self.catalog = Catalog(data_dir)
        self.tables = {}
        self.locks = {}
        self.warnings = []
        try:
            for name, schema in self.catalog.tables.items():
                table = Table(schema, self.catalog.data_path(name), order=order, sync=sync)
                self.tables[name] = table
                self.locks[name] = RWLock()
                self.warnings.extend(table.warnings)
        except Exception:
            self.close()  # 앞에서 연 테이블의 파일을 닫고 오류를 그대로 올린다
            raise

    def close(self):
        for table in self.tables.values():
            table.close()
        self.tables = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def run(self, sql, max_rows=None):
        """SQL(문장 여러 개)을 위에서부터 실행하며 결과 dict 를 하나씩. 틀린 문장에서 SqlError(statement = 몇 번째)"""
        statements = parse_script(sql)
        n = 0
        while True:
            n += 1
            try:
                stmt = next(statements)  # 이 문장을 읽다가 난 문법 오류도 n 번째 문장의 오류
            except StopIteration:
                return
            except SqlError as e:
                e.statement = n
                raise
            try:
                result = self.execute(stmt, max_rows)
            except SqlError as e:
                e.statement = n
                raise
            yield result

    def execute_all(self, sql, max_rows=None):
        """run 의 결과를 목록으로 (테스트 · 서버용)"""
        return list(self.run(sql, max_rows))

    def execute(self, stmt, max_rows=None):
        """문장 하나 실행 → 결과 dict (+ 실행 시간 ms)"""
        started = time.perf_counter()
        schema = self.catalog.get(stmt.table, stmt.line, stmt.col)
        table, lock = self.tables[stmt.table], self.locks[stmt.table]
        if isinstance(stmt, Insert):
            rows = executor.prepare_insert(stmt, schema)  # 검사는 락 밖에서
            with lock.write():
                first, last = table.insert_rows(rows)
            result = {"type": "insert", "table": schema.name, "count": len(rows), "first_id": first, "last_id": last}
        elif stmt.explain:
            result = executor.explain(stmt, schema)
        else:
            with lock.read():
                result = executor.run_select(stmt, schema, table, max_rows)
        result["ms"] = round((time.perf_counter() - started) * 1000, 3)
        return result

    def describe_tables(self):
        """테이블 목록 · 열 · 행 수 (API 의 GET /tables)"""
        out = []
        for name, table in self.tables.items():
            with self.locks[name].read():
                rows = len(table)
            out.append({"name": name, "columns": [{"name": n, "type": t} for n, t in table.schema.columns], "rows": rows})
        return out
