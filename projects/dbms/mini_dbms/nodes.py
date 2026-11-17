# [nodes.py] 파서가 만드는 문장 구조 (AST) — 실행기는 SQL 글자가 아니라 이 객체만 본다
#
#   "INSERT INTO users (name, age) VALUES ('kim', 25), ('lee', NULL)"
#     → Insert(table="users", columns=["name", "age"], rows=[["kim", 25], ["lee", None]])
#   "SELECT name FROM users WHERE id >= 10 AND age < 30 ORDER BY age DESC LIMIT 5"
#     → Select(table="users", columns=["name"], where=[Condition("id", ">=", 10), Condition("age", "<", 30)],
#              order_by=("age", True), limit=5)
#
# line · col = 그 문장(조건)이 시작한 위치 — 실행 중 오류("없는 열")에도 위치를 붙이려고 들고 다닌다.

from dataclasses import dataclass, field


@dataclass
class Condition:
    column: str
    op: str  # "=" "!=" "<" "<=" ">" ">="  ("<>" 는 파서가 "!=" 로 바꿔 둔다)
    value: object  # int · float · str · None(NULL)
    line: int = 0
    col: int = 0


@dataclass
class Insert:
    table: str
    columns: list  # None 이면 열 목록 생략 → 스키마 순서(id 제외)
    rows: list  # [[값, …], …]
    line: int = 0
    col: int = 0


@dataclass
class Select:
    table: str
    columns: list  # None 이면 *
    where: list = field(default_factory=list)  # Condition 들, 모두 AND
    order_by: tuple = None  # (열, 내림차순인가) 또는 None
    limit: int = None
    explain: bool = False  # EXPLAIN SELECT … → 실행하지 않고 계획만
    line: int = 0
    col: int = 0
