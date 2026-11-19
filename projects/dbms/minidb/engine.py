# [engine.py] 내부 DB 엔진 (Phase 3) — Phase 1 SQL 처리기 + Phase 2 인덱스를 여러 스레드가 함께 쓰게 감싼다
#
#   API 서버(작업자 스레드 N개) ──execute(sql)──▶ 엔진: 파싱 → 테이블 락 → 실행기 → 저장소(파일 + B+ 트리)
#
# ■ 엔진은 HTTP를 모른다. SQL 문자열을 받아 결과를 돌려줄 뿐이라, CLI · API 서버 · 테스트가 같은 엔진을 쓴다
#   (Mini Redis에서 저장소와 HTTP 서버를 나눈 것과 같은 구조)
#
# ■ 동시성 (공부 5번)
#   - 파싱은 락 밖에서 한다: 공유 데이터를 건드리지 않으므로 여러 스레드가 동시에 해도 된다
#   - 실행은 테이블마다 읽기-쓰기 락 안에서: SELECT끼리는 동시에, INSERT는 혼자
#     → 두 INSERT가 같은 next_id를 받거나, 파일에 두 줄이 섞이거나, B+ 트리가 나뉘는 도중 다른 스레드가 읽는 일을 막는다
#   - 문장 하나는 테이블 하나만 쓰므로 락을 두 개 잡는 일이 없다 → 교착 상태(deadlock)가 생기지 않는다
#   - 파이썬 GIL이 있어도 락은 필요하다: GIL은 "next_id 읽기 → +1 → 쓰기" 같은 여러 단계를 한 덩어리로 묶어 주지 않는다

import threading

from .executor import ExecutionError, Executor
from .parser import CreateTable, Delete, Insert, parse
from .rwlock import RWLock
from .storage import Database


class StatementError(Exception):
    """n번째 문장을 실행하다 실패. 그 앞 문장들의 결과(results)를 함께 담는다 (앞의 INSERT는 이미 저장된 상태)"""

    def __init__(self, number, line, cause, results):
        super().__init__(f"{number}번째 문장 (줄 {line}): {cause}")
        self.cause = cause
        self.results = results


class Engine:
    def __init__(self, directory):
        self.db = Database(directory)
        self._executor = Executor(self.db)
        self._locks = {table: RWLock() for table in self.db.tables}
        # CREATE TABLE끼리만 잡는다: "이미 있나 확인 → schema.json 저장"을 한 덩어리로 (같은 이름을 두 요청이 동시에 만들지 않게).
        # SELECT · INSERT는 잡지 않는다 (아래 실행 순서로 안전)
        self._schema_lock = threading.Lock()

    def close(self):
        self.db.close()

    # SQL(문장 여러 개 가능) → 문장마다 Result 목록
    # 문법 오류는 SqlSyntaxError(아무것도 실행 안 함), 실행 중 오류는 StatementError(앞 문장까지는 실행됨)
    def execute(self, sql):
        statements = parse(sql)  # 전부 먼저 파싱 → 문법 오류가 있으면 아무것도 실행하지 않는다 (CLI와 같은 규칙)
        results = []
        for number, stmt in enumerate(statements, 1):
            try:
                if isinstance(stmt, CreateTable):
                    with self._schema_lock:
                        # 테이블 락을 테이블보다 "먼저" 등록한다: 다른 스레드에 새 테이블이 보이는 순간 그 락도 이미 있어야 한다
                        # (반대 순서면 "테이블은 있는데 락은 없는" 틈에 INSERT가 락 없이 실행된다 — Gemini 설계 검토에서 지적)
                        self._locks.setdefault(stmt.table, RWLock())
                        try:
                            results.append(self._executor.execute(stmt))
                        except Exception:
                            # 만들지 못했으면 방금 등록한 락을 치운다: 잘못된 이름으로 CREATE를 반복하면 락이 끝없이 쌓였다 (자체 점검)
                            if stmt.table not in self.db.tables:
                                self._locks.pop(stmt.table, None)
                            raise
                    continue
                lock = self._locks.get(stmt.table)
                if lock is None:
                    # 실행기에 넘기지 않고 여기서 끝낸다: 넘긴 사이에 CREATE가 끝나면 그 테이블에 락 없이 쓰게 된다
                    raise ExecutionError(f"테이블이 없습니다: {stmt.table}")
                # 파일 · 인덱스를 바꾸는 INSERT · DELETE는 쓰기 락(혼자), SELECT는 읽기 락(여럿이 함께)
                with lock.write() if isinstance(stmt, (Insert, Delete)) else lock.read():
                    results.append(self._executor.execute(stmt))
            except Exception as e:
                raise StatementError(number, stmt.line, e, results) from e
        return results
