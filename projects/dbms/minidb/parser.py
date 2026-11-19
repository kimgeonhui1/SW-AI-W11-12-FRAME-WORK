# [parser.py] 토큰 목록을 "실행할 수 있는 구조(문장 객체)"로 바꾼다 — 처리 흐름의 2단계
#
# ■ 지원 문법
#   INSERT INTO 테이블 [(컬럼, ...)] VALUES (값, ...);
#   SELECT * | 컬럼, ... FROM 테이블 [WHERE 컬럼 = 값];
#   CREATE TABLE 테이블 (컬럼 타입, ...);   ← 타입은 INT 또는 TEXT. id 열은 자동으로 붙으므로 적지 않는다
#   DELETE FROM 테이블 [WHERE 컬럼 = 값];   ← WHERE가 없으면 모든 행
#   값은 정수 또는 '문자열'. 문장은 ;로 나누고, 마지막 문장은 ;를 빼도 된다
#
# ■ 방식: 재귀 하강(recursive descent) 파서
#   문법을 앞에서부터 그대로 따라가며 "다음 토큰은 반드시 이것이어야 한다(expect)"를 확인한다.
#   예: INSERT 다음엔 INTO, 그다음엔 테이블 이름... 기대와 다르면 그 토큰의 줄·칸으로 문법 오류를 낸다.
#
# ■ 파서는 문법만 본다. "users 테이블이 있나", "age가 정수 컬럼인가"는 스키마를 아는 실행기(executor)가 검사한다

from typing import NamedTuple, Optional

from .storage import TYPES
from .tokenizer import SqlSyntaxError, tokenize


class Insert(NamedTuple):
    table: str
    columns: Optional[list]  # None이면 스키마의 모든 컬럼을 순서대로
    values: list
    line: int  # 문장이 시작한 줄 (실행 오류 위치 안내용)


class Select(NamedTuple):
    table: str
    columns: Optional[list]  # None이면 * (모든 컬럼)
    where: Optional[tuple]  # (컬럼, 값) 또는 None
    line: int


class Delete(NamedTuple):
    table: str
    where: Optional[tuple]  # (컬럼, 값) 또는 None(모든 행)
    line: int


class CreateTable(NamedTuple):
    table: str
    columns: list  # [(컬럼, 타입)] 적힌 순서대로
    line: int


# SQL 전체(여러 문장) → 문장 목록
def parse(sql):
    p = _Parser(tokenize(sql))
    statements = []
    while True:
        while p.accept("SYMBOL", ";"):  # 빈 문장(;;)은 건너뛴다
            pass
        if p.peek().kind == "EOF":
            return statements
        statements.append(p.statement())
        if not p.accept("SYMBOL", ";") and p.peek().kind != "EOF":
            p.fail("문장 끝에 ';'가 필요합니다")


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    # 다음 토큰이 원하는 종류(와 값)이면 꺼내서 돌려주고, 아니면 None (꺼내지 않음)
    def accept(self, kind, value=None):
        tok = self.tokens[self.pos]
        if tok.kind == kind and (value is None or tok.value == value):
            self.pos += 1
            return tok
        return None

    # accept와 같지만, 없으면 문법 오류
    def expect(self, kind, value=None, what=None):
        tok = self.accept(kind, value)
        if tok is None:
            self.fail(f"{what or repr(value)}이(가) 필요합니다")
        return tok

    def fail(self, message):
        tok = self.peek()
        raise SqlSyntaxError(f"{message}. 실제: {_describe(tok)}", tok.line, tok.col)

    def statement(self):
        tok = self.peek()
        if tok.kind == "KEYWORD" and tok.value == "INSERT":
            return self.insert()
        if tok.kind == "KEYWORD" and tok.value == "SELECT":
            return self.select()
        if tok.kind == "KEYWORD" and tok.value == "CREATE":
            return self.create_table()
        if tok.kind == "KEYWORD" and tok.value == "DELETE":
            return self.delete()
        self.fail("INSERT, SELECT, DELETE 또는 CREATE TABLE 문장이어야 합니다")

    def insert(self):
        start = self.expect("KEYWORD", "INSERT")
        self.expect("KEYWORD", "INTO")
        table = self.expect("NAME", what="테이블 이름").value
        columns = None
        if self.accept("SYMBOL", "("):  # VALUES 앞의 괄호 = 컬럼 목록
            columns = self.names("컬럼 이름")
            self.expect("SYMBOL", ")")
        self.expect("KEYWORD", "VALUES")
        self.expect("SYMBOL", "(")
        values = [self.literal()]
        while self.accept("SYMBOL", ","):
            values.append(self.literal())
        self.expect("SYMBOL", ")")
        return Insert(table, columns, values, start.line)

    def select(self):
        start = self.expect("KEYWORD", "SELECT")
        columns = None if self.accept("SYMBOL", "*") else self.names("컬럼 이름 또는 *")
        self.expect("KEYWORD", "FROM")
        table = self.expect("NAME", what="테이블 이름").value
        return Select(table, columns, self.where(), start.line)

    def delete(self):
        start = self.expect("KEYWORD", "DELETE")
        self.expect("KEYWORD", "FROM")
        table = self.expect("NAME", what="테이블 이름").value
        return Delete(table, self.where(), start.line)

    # [WHERE 컬럼 = 값] → (컬럼, 값) 또는 None. SELECT와 DELETE가 같은 규칙을 쓴다
    def where(self):
        if not self.accept("KEYWORD", "WHERE"):
            return None
        column = self.expect("NAME", what="컬럼 이름").value
        self.expect("SYMBOL", "=")
        return column, self.literal()

    def create_table(self):
        start = self.expect("KEYWORD", "CREATE")
        self.expect("KEYWORD", "TABLE")
        table = self.expect("NAME", what="테이블 이름").value
        self.expect("SYMBOL", "(")
        columns = [self.column_def()]
        while self.accept("SYMBOL", ","):
            columns.append(self.column_def())
        self.expect("SYMBOL", ")")
        return CreateTable(table, columns, start.line)

    # "컬럼 타입" 하나. 타입은 키워드가 아니라 이름 토큰으로 온다 (INT · TEXT를 열 이름으로 쓰는 기존 스키마를 깨지 않으려고)
    def column_def(self):
        name = self.expect("NAME", what="컬럼 이름").value
        kind = self.peek()
        if kind.kind != "NAME" or kind.value.upper() not in TYPES:
            self.fail("타입(INT 또는 TEXT)이 필요합니다")
        self.pos += 1
        return name, kind.value.upper()

    # 쉼표로 이어진 이름 목록 (최소 1개)
    def names(self, what):
        result = [self.expect("NAME", what=what).value]
        while self.accept("SYMBOL", ","):
            result.append(self.expect("NAME", what=what).value)
        return result

    def literal(self):
        tok = self.accept("INT") or self.accept("STRING")
        if tok is None:
            self.fail("값(정수 또는 '문자열')이 필요합니다")
        return tok.value


def _describe(tok):
    if tok.kind == "EOF":
        return "파일 끝"
    if tok.kind == "STRING":
        return f"문자열 '{tok.value}'"
    return f"{tok.value!r}"
