# [executor.py] 문장 구조 → 실제 동작. INSERT 는 값 검사 후 행 만들기, SELECT 는 계획 고르기 → 행 모으기
#
# ■ SELECT 의 계획 고르기 — WHERE 에 id 조건이 있으면 B+ 트리를 쓴다
#   | WHERE                          | 계획        | 하는 일                                   | 비용          |
#   | id = 5                         | index-eq    | 트리에서 한 점 찾기 → 그 줄만 읽기        | O(log n)      |
#   | id >= 10 AND id < 20           | index-range | lo 를 찾고 잎 연결을 따라 hi 까지         | O(log n + k)  |
#   | id = 5 AND age > 20            | index-eq    | 인덱스로 후보를 줄인 뒤 나머지 조건 검사  | O(log n)      |
#   | name = 'kim' · 없음 · id != 5  | full-scan   | 파일 처음부터 끝까지 한 줄씩              | O(n)          |
#   어느 계획이든 결과의 "plan" 에 적어 돌려준다 → CLI · API · 테스트에서 인덱스를 실제로 썼는지 확인할 수 있다.
#   인덱스로 고른 행에도 WHERE 의 모든 조건을 다시 검사한다 (id 조건 포함) — 계획이 틀려도 결과는 틀리지 않게.
#
# ■ 비교 규칙
#   - 숫자 열(INT · FLOAT)은 숫자와, TEXT 열은 문자열과만 비교한다. 섞으면(age = 'x') 실행 전에 SqlError
#     (조용히 "없음" 을 돌려주면 오타를 찾기 어렵다)
#   - NULL 이 끼면 결과는 항상 거짓 — SQL 과 같다 (age = NULL 도 거짓)
#   - 문자열은 유니코드 순서로 비교
# ■ 결과 순서: ORDER BY 가 없으면 id 오름차순 (인덱스 범위 · 훑기 모두 원래 id 순서라 정렬 비용이 없다)
#   ORDER BY 다른 열은 정렬하며, NULL 은 오름차순 · 내림차순 모두 맨 뒤.

import operator
from itertools import islice

from .catalog import kind_of
from .errors import SqlError

_OPS = {"=": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge}
_NUMERIC = ("INT", "FLOAT")


# ── INSERT ────────────────────────────────────────────────────────────


def prepare_insert(stmt, schema):
    """INSERT 의 모든 행을 검사해 저장할 행(id 를 뺀 스키마 순서 값) 목록으로 만든다.
    하나라도 틀리면 SqlError — 아직 아무것도 쓰지 않았으므로 1,000행 중 한 행이 틀려도 0행이 들어간다."""
    names = schema.names[1:] if stmt.columns is None else stmt.columns
    targets = []
    for name in names:
        if name == "id":
            raise SqlError("id 는 자동으로 붙는 열이라 직접 넣을 수 없습니다", stmt.line, stmt.col)
        i = schema.column(name, stmt.line, stmt.col)
        if i in targets:
            raise SqlError(f"열 '{name}' 이 두 번 나옵니다", stmt.line, stmt.col)
        targets.append(i)
    width = len(schema.names) - 1
    rows = []
    for row_no, values in enumerate(stmt.rows, 1):
        if len(values) != len(targets):
            raise SqlError(f"{row_no}번째 행: 값이 {len(values)}개인데 열은 {len(targets)}개입니다", stmt.line, stmt.col)
        row = [None] * width  # 적지 않은 열은 NULL
        for i, value in zip(targets, values):
            row[i - 1] = schema.check_value(i, value, stmt.line, stmt.col, row_no)
        rows.append(row)
    return rows


# ── SELECT ────────────────────────────────────────────────────────────


def check_select(stmt, schema):
    """실행 전 검사: 열이 있는지, 비교 타입이 맞는지 → (출력 열 위치, [(열 위치, 비교 함수, 값)])"""
    if stmt.columns is None:
        out = list(range(len(schema.names)))
    else:
        out = [schema.column(c, stmt.line, stmt.col) for c in stmt.columns]
    conds = []
    for c in stmt.where:
        i = schema.column(c.column, c.line, c.col)
        v = c.value
        if v is not None:
            t = schema.types[i]
            ok = (t in _NUMERIC and type(v) in (int, float)) or (t == "TEXT" and type(v) is str)
            if not ok:
                raise SqlError(f"열 '{c.column}'({t}) 을 {kind_of(v)} 값 {v!r} 과 비교할 수 없습니다", c.line, c.col)
        conds.append((i, _OPS[c.op], v))
    if stmt.order_by is not None:
        schema.column(stmt.order_by[0], stmt.line, stmt.col)
    return out, conds


def choose_plan(stmt):
    """WHERE 의 id 조건으로 계획을 고른다 → ("eq", 값) · ("range", lo, lo 포함?, hi, hi 포함?) · ("scan",)"""
    eq = lo = hi = None
    lo_inc = hi_inc = True
    for c in stmt.where:
        if c.column != "id" or c.value is None:
            continue
        v = c.value
        if c.op == "=":
            eq = v if eq is None else eq  # id = 1 AND id = 2 는 첫 값으로 찾고, 행 검사에서 두 번째 조건이 걸러 낸다
        elif c.op in (">", ">="):
            inc = c.op == ">="
            if lo is None or v > lo or (v == lo and not inc):  # 더 좁은 아래 경계를 고른다
                lo, lo_inc = v, inc
        elif c.op in ("<", "<="):
            inc = c.op == "<="
            if hi is None or v < hi or (v == hi and not inc):
                hi, hi_inc = v, inc
        # "!=" 는 인덱스로 줄일 수 없다 (거의 모든 행이 해당)
    if eq is not None:
        return ("eq", eq)
    if lo is not None or hi is not None:
        return ("range", lo, lo_inc, hi, hi_inc)
    return ("scan",)


def describe_plan(plan):
    """계획 → 사람이 읽는 글자 (결과의 plan 필드)"""
    if plan[0] == "eq":
        return f"index-eq (id = {plan[1]})"
    if plan[0] == "range":
        _, lo, lo_inc, hi, hi_inc = plan
        parts = []
        if lo is not None:
            parts.append(f"id {'>=' if lo_inc else '>'} {lo}")
        if hi is not None:
            parts.append(f"id {'<=' if hi_inc else '<'} {hi}")
        return f"index-range ({' AND '.join(parts)})"
    return "full-scan"


def run_select(stmt, schema, table, max_rows=None):
    """SELECT 실행 → 결과 dict. max_rows 를 주면(API 서버) 그만큼만 담고 나머지는 세기만 한다
    결과: columns · rows · count(담은 행) · total(조건에 맞은 행, LIMIT 적용 후) · truncated · plan · scanned(읽은 행)"""
    out, conds = check_select(stmt, schema)
    plan = choose_plan(stmt)
    if plan[0] == "eq":
        row = table.get(plan[1])
        source = [] if row is None else [row]
    elif plan[0] == "range":
        source = table.range_rows(plan[1], plan[3], plan[2], plan[4])
    else:
        source = table.scan()

    scanned = 0

    def matched():
        nonlocal scanned
        for row in source:
            scanned += 1
            if all(v is not None and row[i] is not None and op(row[i], v) for i, op, v in conds):
                yield row

    order = stmt.order_by
    if order is None or order == ("id", False):  # 이미 id 오름차순 → 정렬 없이, LIMIT 이면 일찍 멈춘다
        it = matched() if stmt.limit is None else islice(matched(), stmt.limit)
        rows, total = [], 0
        for row in it:
            total += 1
            if max_rows is None or len(rows) < max_rows:
                rows.append(row)
    else:
        col, desc = order
        i = schema.position[col]
        everything = list(matched())
        known = sorted((r for r in everything if r[i] is not None), key=lambda r: r[i], reverse=desc)
        everything = known + [r for r in everything if r[i] is None]  # NULL 은 항상 맨 뒤
        if stmt.limit is not None:
            everything = everything[: stmt.limit]
        total = len(everything)
        rows = everything if max_rows is None else everything[:max_rows]
    return {
        "type": "select",
        "table": schema.name,
        "columns": [schema.names[i] for i in out],
        "rows": [[r[i] for i in out] for r in rows],
        "count": len(rows),
        "total": total,
        "truncated": len(rows) < total,
        "plan": describe_plan(plan),
        "scanned": scanned,
    }


def explain(stmt, schema):
    """EXPLAIN SELECT … → 실행하지 않고 계획만 (열 · 타입 검사는 한다)"""
    check_select(stmt, schema)
    return {"type": "explain", "table": schema.name, "plan": describe_plan(choose_plan(stmt))}
