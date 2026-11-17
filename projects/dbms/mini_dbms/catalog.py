# [catalog.py] 카탈로그 — 어떤 테이블이 있고, 각 테이블에 어떤 열(이름 · 타입)이 있는지
#
# ■ 과제 조건: "schema 및 table 은 이미 존재한다고 가정" → CREATE TABLE 은 만들지 않는다.
#   대신 데이터 폴더에 테이블마다 스키마 파일을 미리 둔다:
#     data/users.schema.json   {"columns": [{"name": "id", "type": "INT"}, {"name": "name", "type": "TEXT"}, …]}
#   엔진이 켜질 때 *.schema.json 을 모두 읽어 테이블 목록을 만든다. 파일 이름(users)이 테이블 이름이다.
#
# ■ 규칙
#   - 첫 열은 반드시 id INT — 레코드를 넣을 때 자동으로 1, 2, 3 … 이 붙고, B+ 트리 인덱스의 키가 된다.
#   - 타입은 INT(64비트 정수) · FLOAT(소수) · TEXT(문자열) 셋. 모든 열(id 제외)은 NULL 을 받는다.
#   - 이름(테이블 · 열)은 [a-z_][a-z0-9_]* 64자 이하. 테이블 이름이 곧 데이터 파일 이름이라,
#     "../" 같은 글자를 막아 데이터 폴더 밖 파일을 건드리지 못하게 한다 (경로 공격 차단).
#     SQL 에서 온 이름은 이 카탈로그의 사전에서 찾기만 하고, 그 글자로 경로를 만들지 않는다 — 이중 안전.

import json
import re
from pathlib import Path

from .errors import DataError, SqlError

NAME_RE = re.compile(r"[a-z_][a-z0-9_]{0,63}\Z")
TYPES = ("INT", "FLOAT", "TEXT")
INT_MIN, INT_MAX = -(2**63), 2**63 - 1  # INT = 64비트 부호 있는 정수 (다른 DB 의 BIGINT 와 같은 범위)
SCHEMA_SUFFIX = ".schema.json"


def kind_of(value):
    """값의 종류를 사람이 읽는 이름으로 (오류 문구용)"""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "불리언"
    if isinstance(value, int):
        return "정수"
    if isinstance(value, float):
        return "소수"
    if isinstance(value, str):
        return "문자열"
    return type(value).__name__


class TableSchema:
    """테이블 하나의 열 정보. columns = [(이름, 타입), …] — 0번은 항상 ("id", "INT")"""

    def __init__(self, name, columns):
        self.name = name
        self.columns = columns
        self.names = [c[0] for c in columns]
        self.types = [c[1] for c in columns]
        self.position = {n: i for i, n in enumerate(self.names)}  # 열 이름 → 행 안의 위치

    def column(self, name, line=None, col=None):
        """열 이름 → 위치. 없으면 있는 열 목록을 알려 주는 SqlError"""
        i = self.position.get(name)
        if i is None:
            raise SqlError(f"테이블 '{self.name}' 에 열 '{name}' 이 없습니다 (있는 열: {', '.join(self.names)})", line, col)
        return i

    def check_value(self, i, value, line=None, col=None, row_no=None):
        """i 번 열에 넣을 값 검사 → 저장할 값. 정수를 FLOAT 열에 넣으면 소수로 바꾼다. 틀리면 SqlError
        소수를 INT 열에 넣는 것은 거부한다 (25.5 를 25 로 몰래 자르면 데이터가 바뀐다)."""
        if value is None:
            return None
        t = self.types[i]
        if t == "INT" and type(value) is int:
            return value
        if t == "FLOAT" and type(value) in (int, float):
            return float(value)
        if t == "TEXT" and type(value) is str:
            return value
        prefix = f"{row_no}번째 행: " if row_no is not None else ""
        raise SqlError(f"{prefix}열 '{self.names[i]}' 은 {t} 인데 {kind_of(value)} 값 {value!r} 이 왔습니다", line, col)


class Catalog:
    """데이터 폴더의 스키마 파일 전부. tables = {이름: TableSchema} (이름 순)"""

    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        if not self.dir.is_dir():
            raise DataError(f"데이터 폴더가 없습니다: {self.dir}")
        self.tables = {}
        for path in sorted(self.dir.glob("*" + SCHEMA_SUFFIX)):
            name = path.name[: -len(SCHEMA_SUFFIX)]
            self.tables[name] = load_schema(path, name)

    def get(self, name, line=None, col=None):
        """테이블 이름 → 스키마. 없으면 있는 테이블 목록을 알려 주는 SqlError"""
        schema = self.tables.get(name)
        if schema is None:
            have = ", ".join(self.tables) or "없음"
            raise SqlError(f"테이블 '{name}' 이 없습니다 (있는 테이블: {have})", line, col)
        return schema

    def data_path(self, name):
        """테이블의 데이터 파일 경로 — 카탈로그에 등록된(검사를 통과한) 이름만 들어온다"""
        return self.dir / f"{name}.jsonl"


def load_schema(path, name):
    """스키마 파일 하나를 읽고 검사한다. 틀리면 DataError (무엇이 왜 틀렸는지)"""
    bad = lambda why: DataError(f"스키마 파일이 잘못됐습니다: {path} ({why})")  # noqa: E731
    if not NAME_RE.match(name):
        raise bad(f"테이블 이름 '{name}' 은 [a-z_][a-z0-9_]* 64자 이하여야 합니다")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise bad(f"JSON 으로 읽을 수 없음: {e}")
    cols = data.get("columns") if isinstance(data, dict) else None
    if not isinstance(cols, list) or not cols:
        raise bad('{"columns": [...]} 모양이어야 합니다')
    columns = []
    for c in cols:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or c.get("type") not in TYPES:
            raise bad(f"열은 {{\"name\": 이름, \"type\": {' / '.join(TYPES)}}} 이어야 합니다: {c!r}")
        if not NAME_RE.match(c["name"]):
            raise bad(f"열 이름 '{c['name']}' 은 [a-z_][a-z0-9_]* 64자 이하여야 합니다")
        columns.append((c["name"], c["type"]))
    if columns[0] != ("id", "INT"):
        raise bad("첫 열은 id INT 여야 합니다 (자동 부여 · 인덱스 키)")
    names = [c[0] for c in columns]
    if len(set(names)) != len(names):
        raise bad("열 이름이 겹칩니다")
    return TableSchema(name, columns)
