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

from .executor import Executor
from .parser import Insert, parse
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

    def close(self):
        self.db.close()

    # SQL(문장 여러 개 가능) → 문장마다 Result 목록
    # 문법 오류는 SqlSyntaxError(아무것도 실행 안 함), 실행 중 오류는 StatementError(앞 문장까지는 실행됨)
    def execute(self, sql):
        statements = parse(sql)  # 전부 먼저 파싱 → 문법 오류가 있으면 아무것도 실행하지 않는다 (CLI와 같은 규칙)
        results = []
        for number, stmt in enumerate(statements, 1):
            lock = self._locks.get(stmt.table)
            try:
                if lock is None:  # 없는 테이블: 실행기가 "테이블이 없습니다"를 낸다 (잠글 대상이 없음)
                    results.append(self._executor.execute(stmt))
                    continue
                with lock.write() if isinstance(stmt, Insert) else lock.read():
                    results.append(self._executor.execute(stmt))
            except Exception as e:
                raise StatementError(number, stmt.line, e, results) from e
        return results
