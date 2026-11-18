# [storage.py] 파일 기반 저장소 — 스키마 읽기, 행 추가(INSERT), 행 읽기(SELECT) — 처리 흐름의 4단계
#
# ■ 폴더 하나 = DB 하나
#   schema.json : 테이블과 컬럼 정의. CREATE TABLE이 없으므로 미리 만들어 둔다 (과제 조건: 스키마·테이블은 이미 있음)
#                 {"users": {"name": "TEXT", "age": "INT"}}   ← 컬럼 순서 = 적힌 순서, 타입은 INT 또는 TEXT
#   users.jsonl : users 테이블의 데이터. 테이블 하나 = 파일 하나, 한 줄 = 한 행 (값만 스키마 순서대로 JSON 배열로)
#                 ["홍길동", 25]
#                 ["lee, \"jr\"\n", 30]
#
# ■ 왜 JSON Lines(.jsonl)인가 (CSV와 비교)
#   - CSV는 값에 쉼표·따옴표·줄바꿈이 있으면 따옴표로 감싸는 규칙이 복잡하고, 줄바꿈이 든 값은 한 행이 여러 줄이 된다
#   - JSON은 줄바꿈을 \n 두 글자로 적으므로 "한 줄 = 한 행"이 항상 지켜진다 → 줄 단위로 읽고 쓰기만 하면 된다
#     (Phase 2에서 "이 행이 파일의 몇 번째 바이트에서 시작하나(offset)"를 인덱스에 담을 때도 이 성질이 필요하다)
#   - 정수와 문자열이 구분되어 저장된다 (CSV는 전부 문자열이라 읽을 때마다 다시 바꿔야 한다)
#   - 사람이 메모장으로 열어 확인할 수 있다
#
# ■ INSERT는 파일 끝에 한 줄을 덧붙이기만 한다(append). 기존 줄을 고치지 않으므로 빠르고, 앞의 행이 망가질 일이 없다

import json
import os
import re

from .tokenizer import KEYWORDS

TYPES = {"INT", "TEXT"}
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")  # SQL에서 쓸 수 있는 이름 = 토크나이저의 NAME 규칙
# Windows에서는 이 이름의 파일이 장치(콘솔, 프린터 등)를 가리켜서, 테이블 파일 이름으로 쓰면 데이터가 엉뚱한 곳으로 간다
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{i}" for d in ("COM", "LPT") for i in range(1, 10)}


class SchemaError(ValueError):
    """schema.json이 없거나 잘못됨"""


class StorageError(ValueError):
    """테이블 파일이 손상됨"""


class Database:
    def __init__(self, directory):
        self.directory = directory
        # 테이블 이름 → [(컬럼, 타입), ...]
        self.tables = load_schema(os.path.join(directory, "schema.json"))

    def path(self, table):
        return os.path.join(self.directory, f"{table}.jsonl")

    # 행 하나를 파일 끝에 추가. row는 스키마 순서의 값 목록 (검사는 실행기가 끝낸 상태)
    def append(self, table, row):
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")  # ensure_ascii=False: 한글을 그대로 적어 읽기 쉽게
        with open(self.path(table), "a+b") as f:  # a 모드: 어디를 읽었든 쓰기는 항상 파일 끝에
            f.seek(0, os.SEEK_END)
            if f.tell() > 0:
                f.seek(-1, os.SEEK_END)
                # 마지막 줄이 줄바꿈 없이 끝났으면(손으로 고친 파일, 쓰다가 꺼진 파일) 새 행이 그 줄에 붙어 둘 다 망가진다 → 줄을 먼저 끊는다
                if f.read(1) != b"\n":
                    data = b"\n" + data
            f.write(data)

    # 모든 행을 파일 순서대로 하나씩 돌려준다 (선형 탐색의 재료). 파일이 없으면 아직 INSERT가 없던 빈 테이블
    def scan(self, table):
        columns = self.tables[table]
        try:
            f = open(self.path(table), "rb")
        except FileNotFoundError:
            return
        with f:
            for number, raw in enumerate(f, 1):
                if not raw.strip():  # 빈 줄(편집기가 끝에 넣은 줄 등)은 행이 아니다
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:  # JSON이 아님, UTF-8이 아님
                    raise StorageError(f"{self.path(table)} {number}번째 줄이 손상되었습니다") from None
                if not _row_matches(row, columns):
                    raise StorageError(f"{self.path(table)} {number}번째 줄이 스키마와 다릅니다: {raw[:80]!r}")
                yield row


def _row_matches(row, columns):
    if not isinstance(row, list) or len(row) != len(columns):
        return False
    # type(v) is int: JSON의 true는 파이썬에서 True(== 1)라서 isinstance(v, int)로는 걸러지지 않는다
    return all(type(v) is int if t == "INT" else type(v) is str for v, (_, t) in zip(row, columns))


def load_schema(path):
    try:
        with open(path, encoding="utf-8-sig") as f:  # -sig: 메모장이 붙이는 BOM(파일 앞 보이지 않는 3바이트)을 건너뛴다
            data = json.load(f, object_pairs_hook=_no_duplicates)
    except FileNotFoundError:
        raise SchemaError(f"스키마 파일이 없습니다: {path}") from None
    except (OSError, ValueError) as e:
        raise SchemaError(f"스키마 파일을 읽을 수 없습니다: {path} ({e})") from None

    if not isinstance(data, dict) or not data:
        raise SchemaError('스키마는 {"테이블": {"컬럼": "타입", ...}} 모양이어야 합니다')
    tables, seen = {}, set()
    for table, columns in data.items():
        _check_name(table, "테이블")
        # Windows 파일 이름은 대소문자를 구분하지 않아서 Users와 users가 같은 파일을 쓰게 된다
        if table.upper() in seen:
            raise SchemaError(f"대소문자만 다른 테이블이 있습니다: {table}")
        if table.upper() in _WINDOWS_DEVICES:
            raise SchemaError(f"테이블 이름으로 쓸 수 없습니다 (Windows 장치 이름): {table}")
        seen.add(table.upper())
        if not isinstance(columns, dict) or not columns:
            raise SchemaError(f"{table}: 컬럼이 하나 이상 있어야 합니다")
        for column, kind in columns.items():
            _check_name(column, f"{table}의 컬럼")
            if not isinstance(kind, str) or kind.upper() not in TYPES:
                raise SchemaError(f"{table}.{column}: 타입은 INT 또는 TEXT여야 합니다 ({kind!r})")
        tables[table] = [(column, kind.upper()) for column, kind in columns.items()]
    return tables


# 이름 규칙을 지켜야 SQL에서 부를 수 있고, 파일 이름으로 써도 안전하다 (../ 같은 경로 문자가 들어갈 수 없다)
def _check_name(name, what):
    if not _NAME_RE.match(name) or name.upper() in KEYWORDS:
        raise SchemaError(f"{what} 이름이 올바르지 않습니다: {name!r} (영문·숫자·_, 키워드 불가)")


# json은 같은 키가 두 번 나오면 조용히 뒤의 것만 남긴다 → 컬럼이 사라지는 실수를 막으려고 에러로 바꾼다
def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"스키마에 같은 이름이 두 번 있습니다: {key}")
        result[key] = value
    return result
