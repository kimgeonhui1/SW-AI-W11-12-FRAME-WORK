# [errors.py] 미니 DBMS 의 오류 두 가지
#
#   SqlError  : 사용자가 보낸 SQL 이 틀렸거나 실행할 수 없음 (문법 · 없는 테이블 · 타입 · 쓰기 실패 …)
#               → CLI 는 종료 코드 1, API 서버는 400. "몇 번째 문장 · 몇 번째 줄 · 몇 번째 칸" 을 함께 담는다.
#   DataError : 스키마 파일 · 데이터 파일 자체가 잘못됨 (손상 · 형식 오류)
#               → 엔진을 시작하지 않는다 (CLI 종료 코드 2, 서버는 켜지지 않음).
#               손상된 파일 위에서 계속 쓰면 데이터를 더 망가뜨릴 수 있어서, 조용히 넘어가지 않고 멈춘다.


class SqlError(Exception):
    """SQL 처리 중 오류. 위치(line · col)는 1부터 센다. 위치를 모르면 None"""

    def __init__(self, message, line=None, col=None):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.statement = None  # 스크립트에서 몇 번째 문장인지 (1부터) — Engine.run 이 채운다

    def __str__(self):
        where = f"{self.line}번째 줄 {self.col}칸: " if self.line is not None else ""
        return where + self.message

    # API 응답 · JSON 출력용
    def to_dict(self):
        return {"error": self.message, "line": self.line, "col": self.col, "statement": self.statement}


class DataError(Exception):
    """스키마 · 데이터 파일이 잘못됨 — 엔진이 시작하지 않는다"""
