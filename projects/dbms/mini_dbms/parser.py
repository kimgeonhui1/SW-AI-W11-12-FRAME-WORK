# [parser.py] 토큰 → 문장 구조(Insert · Select). 재귀 하강 파서 (문법 규칙 하나 = 함수 하나)
#
# 지원 문법
#   문장들   := 문장 (";" 문장)* ";"?
#   INSERT   := INSERT INTO 테이블 [ "(" 열 ("," 열)* ")" ] VALUES 행 ("," 행)*
#   행       := "(" 값 ("," 값)* ")"
#   SELECT   := [EXPLAIN] SELECT ( "*" | 열 ("," 열)* ) FROM 테이블
#               [ WHERE 비교 (AND 비교)* ] [ ORDER BY 열 [ASC | DESC] ] [ LIMIT 정수 ]
#   비교     := 열 ( = | != | <> | < | <= | > | >= ) 값
#   값       := 정수 | 소수 | '문자열' | NULL
#
# ■ parse_script 는 문장을 "하나씩" 돌려주는 제너레이터다.
#   ";" 가 나올 때까지만 토큰을 모아 문장 하나를 만들고 넘긴다 → 실행기가 그 문장을 실행한 뒤 다음 문장을 읽는다.
#   100만 행 SQL 파일도 메모리에는 문장 하나(1,000행)의 토큰만 있다.
#   그리고 뒤쪽 문장에 문법 오류가 있어도 앞 문장들은 먼저 실행된다 (파일을 위에서부터 차례로 실행하는 것과 같다).
#
# ■ 틀리면 SqlError 에 "무엇이 와야 하는데 무엇이 있다" 와 그 토큰의 위치를 담는다.

from .errors import SqlError
from .nodes import Condition, Insert, Select
from .tokenizer import tokenize

COMPARE_OPS = {"=": "=", "!=": "!=", "<>": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


def parse_script(text):
    """SQL 글자(문장 여러 개) → 문장 구조를 하나씩. 빈 문장(;;)과 주석만 있는 부분은 건너뛴다"""
    tokens = []
    for tok in tokenize(text):
        if tok.kind == "SYM" and tok.value == ";":
            if tokens:
                yield _Parser(tokens).statement()
                tokens = []
        else:
            tokens.append(tok)
    if tokens:  # 마지막 문장은 ; 없이 끝나도 된다
        yield _Parser(tokens).statement()


def parse(text):
    """문장 목록을 한꺼번에 (테스트 · 작은 입력용)"""
    return list(parse_script(text))


def _describe(tok):
    """오류 문구에 넣을 토큰 설명"""
    if tok is None:
        return "문장 끝"
    if tok.kind == "KEYWORD":
        return tok.value
    if tok.kind == "STRING":
        return f"문자열 '{tok.value}'"
    if tok.kind == "SYM":
        return f"'{tok.value}'"
    return f"'{tok.value}'" if tok.kind == "IDENT" else str(tok.value)


class _Parser:
    """문장 하나의 토큰 목록을 앞에서부터 읽는다 (i = 지금 볼 토큰 번호)"""

    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    # ── 토큰 다루기 ──────────────────────────────────────────────────

    def _peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _fail(self, expected, tok=None):
        tok = tok if tok is not None else self._peek()
        at = tok if tok is not None else self.tokens[-1]  # 문장이 끝나 버렸으면 마지막 토큰 위치
        raise SqlError(f"{expected} 와야 하는데 {_describe(tok)} 이(가) 있습니다", at.line, at.col)

    def _accept(self, kind, value=None):
        """다음 토큰이 맞으면 먹고 돌려준다. 아니면 None (선택 문법용)"""
        tok = self._peek()
        if tok is not None and tok.kind == kind and (value is None or tok.value == value):
            self.i += 1
            return tok
        return None

    def _expect(self, kind, value=None):
        """다음 토큰이 반드시 이것이어야 한다 (필수 문법)"""
        tok = self._accept(kind, value)
        if tok is None:
            self._fail(f"'{value}' 가" if value else {"IDENT": "이름이", "INT": "정수가"}.get(kind, f"{kind} 가"))
        return tok

    def _name(self):
        """테이블 · 열 이름. 예약어를 이름으로 쓰면 그 이유를 알려 준다"""
        tok = self._peek()
        if tok is not None and tok.kind == "KEYWORD":
            raise SqlError(f"'{tok.value}' 는 예약어라 이름으로 쓸 수 없습니다", tok.line, tok.col)
        return self._expect("IDENT").value

    def _value(self):
        tok = self._peek()
        if tok is not None and tok.kind in ("INT", "FLOAT", "STRING"):
            self.i += 1
            return tok.value
        if self._accept("KEYWORD", "NULL"):
            return None
        self._fail("값(숫자 · '문자열' · NULL)이")

    # ── 문법 규칙 ────────────────────────────────────────────────────

    def statement(self):
        first = self.tokens[0]
        if self._accept("KEYWORD", "EXPLAIN"):
            stmt = self._select()
            stmt.explain = True
        elif first.kind == "KEYWORD" and first.value == "SELECT":
            stmt = self._select()
        elif first.kind == "KEYWORD" and first.value == "INSERT":
            stmt = self._insert()
        else:
            raise SqlError(f"{_describe(first)} 로 시작하는 문장은 지원하지 않습니다 (INSERT · SELECT 만)", first.line, first.col)
        stmt.line, stmt.col = first.line, first.col
        extra = self._peek()
        if extra is not None:  # 예: 문장 사이에 ; 를 빠뜨림 → "SELECT … FROM users INSERT …"
            raise SqlError(f"문장이 끝나야 하는데 {_describe(extra)} 이(가) 있습니다 (';' 를 빠뜨렸나요?)", extra.line, extra.col)
        return stmt

    def _select(self):
        self._expect("KEYWORD", "SELECT")
        if self._accept("SYM", "*"):
            columns = None
        else:
            columns = [self._name()]
            while self._accept("SYM", ","):
                columns.append(self._name())
        self._expect("KEYWORD", "FROM")
        stmt = Select(table=self._name(), columns=columns)
        if self._accept("KEYWORD", "WHERE"):
            stmt.where.append(self._condition())
            while self._accept("KEYWORD", "AND"):
                stmt.where.append(self._condition())
        if self._accept("KEYWORD", "ORDER"):
            self._expect("KEYWORD", "BY")
            column = self._name()
            desc = bool(self._accept("KEYWORD", "DESC"))
            if not desc:
                self._accept("KEYWORD", "ASC")
            stmt.order_by = (column, desc)
        if self._accept("KEYWORD", "LIMIT"):
            tok = self._expect("INT")
            if tok.value < 0:
                raise SqlError("LIMIT 은 0 이상이어야 합니다", tok.line, tok.col)
            stmt.limit = tok.value
        return stmt

    def _condition(self):
        start = self._peek()
        column = self._name()
        tok = self._peek()
        if tok is None or tok.kind != "SYM" or tok.value not in COMPARE_OPS:
            self._fail("비교 연산자(= != <> < <= > >=)가")
        self.i += 1
        return Condition(column, COMPARE_OPS[tok.value], self._value(), start.line, start.col)

    def _insert(self):
        self._expect("KEYWORD", "INSERT")
        self._expect("KEYWORD", "INTO")
        table = self._name()
        columns = None
        if self._accept("SYM", "("):
            columns = [self._name()]
            while self._accept("SYM", ","):
                columns.append(self._name())
            self._expect("SYM", ")")
        self._expect("KEYWORD", "VALUES")
        rows = [self._row()]
        while self._accept("SYM", ","):
            rows.append(self._row())
        return Insert(table=table, columns=columns, rows=rows)

    def _row(self):
        self._expect("SYM", "(")
        values = [self._value()]
        while self._accept("SYM", ","):
            values.append(self._value())
        self._expect("SYM", ")")
        return values
