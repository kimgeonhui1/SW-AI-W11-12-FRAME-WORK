# [tokenizer.py] SQL 문자열을 토큰(의미 있는 가장 작은 조각) 목록으로 자른다 — 처리 흐름의 1단계
#
# ■ 예: "SELECT name FROM users WHERE age = 25;"
#   → KEYWORD(SELECT) NAME(name) KEYWORD(FROM) NAME(users) KEYWORD(WHERE) NAME(age) SYMBOL(=) INT(25) SYMBOL(;) EOF
#
# ■ 왜 따로 자르나: 파서가 "문자 하나하나"가 아니라 "단어 단위"로 문법을 보게 하려고.
#   공백·줄바꿈·주석·따옴표 같은 지저분한 처리는 여기서 끝내고, 파서는 토큰의 순서(문법)만 본다.
#   (컴파일러의 어휘 분석 → 구문 분석과 같은 나눔)
#
# ■ 규칙
#   - 키워드는 대소문자를 구분하지 않는다 (select = SELECT). 이름(테이블·컬럼)은 적힌 그대로 비교한다
#   - 문자열은 작은따옴표. 안에 작은따옴표를 넣으려면 두 번 쓴다: 'it''s' → it's (표준 SQL 방식)
#   - 숫자는 정수만, 범위는 64비트 (실제 DB의 BIGINT와 같다)
#   - -- 부터 줄 끝까지는 주석
#   - 토큰마다 줄·칸 번호를 남겨, 에러가 나면 위치를 알려 준다

import re
from typing import NamedTuple

KEYWORDS = {"INSERT", "INTO", "VALUES", "SELECT", "FROM", "WHERE"}
INT_MIN, INT_MAX = -(2**63), 2**63 - 1

# 위에서부터 순서대로 맞춰 본다. 정규식 하나로 자르면 문자를 하나씩 보는 파이썬 반복문보다 훨씬 빠르다
# (Phase 2에서 INSERT 수십만 줄을 처리할 때 차이가 난다)
_TOKEN_RE = re.compile(
    r"""
      (?P<SPACE>[^\S\n]+)                 # 줄바꿈을 뺀 공백 (탭, 전각 공백 등 포함)
    | (?P<NEWLINE>\n)
    | (?P<COMMENT>--[^\n]*)
    | (?P<STRING>'[^']*(?:''[^']*)*'(?!'))  # '' 는 따옴표 하나. 줄바꿈도 문자열 안에 들어갈 수 있다
    #   따옴표가 아닌 글자는 [^']*로 한꺼번에 먹는다. 글자마다 "[^'] 또는 ''"를 고르던 예전 식은 10MB 문자열에 약 10초 걸렸다
    #   (자체 점검). [^']+를 *로 감싸는 식은 닫히지 않은 문자열에서 되돌아가기가 폭발하므로 이 모양(펼친 반복)을 쓴다
    #   (?!'): 닫는 따옴표 바로 뒤에 따옴표가 오면 그것은 ''(따옴표 글자)다. 이게 없으면 'abc'' 를 'abc' + ' 로 잘라
    #   "닫히지 않음" 위치를 문자열 시작이 아니라 끝의 따옴표로 알렸다 (Gemini 리뷰로 재현)
    | (?P<UNCLOSED>')                     # 위 STRING이 실패한 따옴표 = 닫히지 않은 문자열
    | (?P<NUMBER>-?[0-9][A-Za-z0-9_.]*)   # 숫자로 시작해 붙어 있는 글자까지 한 덩어리로 잡는다 → _to_int가 정수인지 검사
    #   (25abc · 0x10 · 1e5를 25 + abc처럼 둘로 잘라, 엉뚱한 위치에서 엉뚱한 에러가 나던 것: Gemini 리뷰로 재현)
    | (?P<NAME>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<SYMBOL>[(),;*=])
    """,
    re.VERBOSE,
)


class SqlSyntaxError(ValueError):
    """SQL 문법 오류. 메시지에 줄·칸 번호가 붙는다"""

    def __init__(self, message, line, col):
        super().__init__(f"{message} (줄 {line}, 칸 {col})")
        self.line = line
        self.col = col


class Token(NamedTuple):
    kind: str  # KEYWORD, NAME, INT, STRING, SYMBOL, EOF
    value: object  # KEYWORD는 대문자로 맞춘 단어, INT는 int, STRING은 따옴표를 벗긴 str
    line: int
    col: int


def tokenize(sql):
    tokens = []
    pos, line, line_start = 0, 1, 0
    while pos < len(sql):
        m = _TOKEN_RE.match(sql, pos)
        col = pos - line_start + 1
        if m is None:
            raise SqlSyntaxError(f"알 수 없는 문자입니다: {sql[pos]!r}", line, col)
        kind, text = m.lastgroup, m.group()

        if kind == "UNCLOSED":
            raise SqlSyntaxError("작은따옴표가 닫히지 않았습니다", line, col)
        if kind == "STRING":
            tokens.append(Token("STRING", text[1:-1].replace("''", "'"), line, col))
        elif kind == "NUMBER":
            tokens.append(Token("INT", _to_int(text, line, col), line, col))
        elif kind == "NAME":
            word = text.upper()
            if word in KEYWORDS:
                tokens.append(Token("KEYWORD", word, line, col))
            else:
                tokens.append(Token("NAME", text, line, col))
        elif kind == "SYMBOL":
            tokens.append(Token("SYMBOL", text, line, col))
        # SPACE, NEWLINE, COMMENT는 토큰으로 남기지 않는다

        # 줄 번호: 줄바꿈 토큰뿐 아니라 여러 줄짜리 문자열 안의 줄바꿈도 센다
        newlines = text.count("\n")
        if newlines:
            line += newlines
            line_start = pos + text.rfind("\n") + 1
        pos = m.end()

    tokens.append(Token("EOF", None, line, pos - line_start + 1))
    return tokens


def _to_int(text, line, col):
    body = text.lstrip("-")
    if not body.replace(".", "").isdigit():  # 25abc, 0x10, 1e5 처럼 글자가 섞임
        raise SqlSyntaxError(f"잘못된 숫자입니다: {text[:30]}", line, col)
    if "." in text:
        raise SqlSyntaxError(f"소수는 지원하지 않습니다(정수만 가능): {text}", line, col)
    # 자릿수를 먼저 본다: 파이썬 int()는 4300자리가 넘는 문자열을 ValueError로 거부해서, 범위 검사까지 가지도 못한다
    # (앞의 0은 빼고 센다: 0000...01도 1이다)
    digits = text.lstrip("-").lstrip("0") or "0"
    if len(digits) > 19:
        raise SqlSyntaxError(f"정수 범위(64비트)를 벗어났습니다: {text[:30]}...", line, col)
    value = -int(digits) if text.startswith("-") else int(digits)
    if not INT_MIN <= value <= INT_MAX:
        raise SqlSyntaxError(f"정수 범위(64비트)를 벗어났습니다: {text}", line, col)
    return value
