# [tokenizer.py] SQL 글자 → 토큰 (단어 · 숫자 · 문자열 · 기호)
#
#   "SELECT name FROM users WHERE age >= 20;"
#     → KEYWORD(SELECT) IDENT(name) KEYWORD(FROM) IDENT(users) KEYWORD(WHERE) IDENT(age) SYM(>=) INT(20) SYM(;)
#
# ■ 정규식 하나로 자른다: 이름 붙은 그룹을 | 로 이어 두고 finditer 로 앞에서부터 하나씩 맞춘다.
#   글자를 하나씩 도는 파이썬 반복문보다 훨씬 빠르다 — 100만 행 INSERT 는 수천만 글자라 이 차이가 크다.
#   위에 있는 그룹이 먼저 맞춰진다: 주석 → 숫자 → 문자열 → 단어 → 기호 → 아무것도 아니면 BAD(오류).
#
# ■ 토큰마다 줄 · 칸 번호를 단다 → 파서 오류가 "3번째 줄 18칸: …" 처럼 위치를 알려 준다.
# ■ 제너레이터라 필요한 만큼만 만든다. 파서가 문장 하나씩 받아 가므로, 100만 행 파일도 토큰을 한꺼번에 들고 있지 않는다.
#
# ■ 규칙
#   - 키워드는 대소문자 무시 (select = SELECT). 이름(테이블 · 열)은 소문자로 맞춘다. 이름은 64자 이하.
#   - 문자열은 작은따옴표. 안의 작은따옴표는 두 번 ('O''Brien' → O'Brien) — SQL 표준
#   - 주석: -- 줄 끝까지, /* 여러 줄 */
#   - 정수는 64비트 범위만, 소수는 무한대가 되는 큰 수를 거부

import math
import re
from collections import namedtuple

from .catalog import INT_MAX, INT_MIN
from .errors import SqlError

Token = namedtuple("Token", "kind value line col")  # kind: KEYWORD · IDENT · INT · FLOAT · STRING · SYM

KEYWORDS = frozenset(
    "SELECT FROM WHERE AND INSERT INTO VALUES NULL ORDER BY ASC DESC LIMIT EXPLAIN".split()
)

_PATTERN = re.compile(
    r"""
     (?P<WS>\s+)
    |(?P<LINE_COMMENT>--[^\n]*)
    |(?P<BLOCK_COMMENT>/\*.*?\*/)
    |(?P<UNCLOSED_COMMENT>/\*)
    |(?P<FLOAT>-?\d+\.\d+)
    |(?P<INT>-?\d+)
    |(?P<STRING>'(?:[^']|'')*')
    |(?P<UNCLOSED_STRING>')
    |(?P<WORD>[A-Za-z_][A-Za-z0-9_]*)
    |(?P<SYM><=|>=|<>|!=|[=<>(),;*])
    |(?P<BAD>.)
    """,
    re.VERBOSE | re.DOTALL,
)

_SKIP = ("WS", "LINE_COMMENT", "BLOCK_COMMENT")


def tokenize(text):
    """SQL 글자 → Token 을 하나씩. 틀린 글자를 만나면 그 자리에서 SqlError"""
    line, line_start = 1, 0  # 지금 줄 번호 · 그 줄이 시작하는 글자 위치 (칸 번호 계산용)
    for m in _PATTERN.finditer(text):
        kind = m.lastgroup
        value = m.group()
        start = m.start()
        tok_line, tok_col = line, start - line_start + 1
        if kind in _SKIP or kind == "STRING":  # 여러 줄에 걸칠 수 있는 것만 줄바꿈을 센다
            newlines = value.count("\n")
            if newlines:
                line += newlines
                line_start = start + value.rindex("\n") + 1
            if kind != "STRING":
                continue
            yield Token("STRING", value[1:-1].replace("''", "'"), tok_line, tok_col)
        elif kind == "WORD":
            upper = value.upper()
            if upper in KEYWORDS:
                yield Token("KEYWORD", upper, tok_line, tok_col)
            elif len(value) > 64:
                raise SqlError(f"이름이 너무 깁니다 ({len(value)}자, 최대 64자)", tok_line, tok_col)
            else:
                yield Token("IDENT", value.lower(), tok_line, tok_col)
        elif kind == "SYM":
            yield Token("SYM", value, tok_line, tok_col)
        elif kind == "INT":
            number = int(value)
            if not INT_MIN <= number <= INT_MAX:
                raise SqlError(f"정수가 너무 큽니다 (64비트 범위 {INT_MIN} ~ {INT_MAX})", tok_line, tok_col)
            yield Token("INT", number, tok_line, tok_col)
        elif kind == "FLOAT":
            number = float(value)
            if math.isinf(number):
                raise SqlError("소수가 너무 큽니다", tok_line, tok_col)
            yield Token("FLOAT", number, tok_line, tok_col)
        elif kind == "UNCLOSED_STRING":
            raise SqlError("문자열이 닫히지 않았습니다 (끝의 ' 가 없음)", tok_line, tok_col)
        elif kind == "UNCLOSED_COMMENT":
            raise SqlError("주석이 닫히지 않았습니다 (끝의 */ 가 없음)", tok_line, tok_col)
        else:  # BAD
            raise SqlError(f"알 수 없는 글자 {value!r}", tok_line, tok_col)
