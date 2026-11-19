# [storage.py] 파일 기반 저장소 — 스키마 읽기, 행 추가(INSERT), 행 읽기(SELECT), id 인덱스(B+ 트리) — 처리 흐름의 4단계
#
# ■ 폴더 하나 = DB 하나
#   schema.json : 테이블과 컬럼 정의. 미리 만들어 두고(과제 조건: 스키마·테이블은 이미 있음), CREATE TABLE로 테이블을 더할 수 있다
#                 {"users": {"name": "TEXT", "age": "INT"}}   ← 컬럼 순서 = 적힌 순서, 타입은 INT 또는 TEXT
#   users.jsonl : users 테이블의 데이터. 테이블 하나 = 파일 하나, 한 줄 = 한 행 (id와 값을 스키마 순서대로 JSON 배열로)
#                 [1, "홍길동", 25]
#                 [2, "lee, \"jr\"\n", 30]
#
# ■ id (Phase 2): 모든 테이블의 첫 열은 자동으로 붙는 id(INT, 1부터 1씩 증가)다. 스키마에는 적지 않는다.
#   행을 하나로 가리키는 기본키이고, B+ 트리 인덱스의 키다
#
# ■ 왜 JSON Lines(.jsonl)인가 (CSV와 비교)
#   - CSV는 값에 쉼표·따옴표·줄바꿈이 있으면 따옴표로 감싸는 규칙이 복잡하고, 줄바꿈이 든 값은 한 행이 여러 줄이 된다
#   - JSON은 줄바꿈을 \n 두 글자로 적으므로 "한 줄 = 한 행"이 항상 지켜진다 → 줄 단위로 읽고 쓰기만 하면 된다
#     → "이 행이 파일의 몇 번째 바이트에서 시작하나(offset)"를 인덱스에 담고, 그 위치로 바로 가서 한 줄만 읽을 수 있다
#   - 정수와 문자열이 구분되어 저장된다 (CSV는 전부 문자열이라 읽을 때마다 다시 바꿔야 한다)
#   - 사람이 메모장으로 열어 확인할 수 있다
#
# ■ 여러 스레드 (Phase 3): 읽기끼리는 동시에 해도 안전하게 만들었다 (인덱스 첫 생성, id 검색 핸들).
#   INSERT와 다른 작업이 겹치지 않게 하는 것은 엔진(engine.py)의 테이블별 읽기-쓰기 락이 맡는다
#
# ■ INSERT는 파일 끝에 한 줄을 덧붙이기만 한다(append, 힙 파일). 기존 줄을 고치지 않으므로 빠르고, 앞의 행이 망가질 일이 없다
#
# ■ 인덱스 (Phase 2, 과제 조건: 메모리 기반 B+ 트리)
#   테이블을 처음 쓸 때 파일을 한 번 끝까지 읽으며 (id → 그 줄의 offset)을 B+ 트리에 넣는다 (프로그램을 다시 켜면 다시 만든다).
#   WHERE id = 값 은 트리에서 offset을 찾아 그 위치로 seek → 한 줄만 읽는다 (O(log n)). 다른 열은 처음부터 끝까지 읽는다 (O(n))

import json
import os
import re
import threading

from .bptree import BPlusTree
from .tokenizer import INT_MAX, INT_MIN, KEYWORDS

TYPES = {"INT", "TEXT"}
ID = "id"  # 자동으로 붙는 기본키 열 이름
INDEX_ORDER = 64  # B+ 트리 노드 하나의 자식 수 최대값 (100만 행이면 높이 4)
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")  # SQL에서 쓸 수 있는 이름 = 토크나이저의 NAME 규칙
# Windows에서는 이 이름의 파일이 장치(콘솔, 프린터 등)를 가리켜서, 테이블 파일 이름으로 쓰면 데이터가 엉뚱한 곳으로 간다
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL"} | {f"{d}{i}" for d in ("COM", "LPT") for i in range(1, 10)}


class SchemaError(ValueError):
    """schema.json이 없거나 잘못됨"""


class StorageError(ValueError):
    """테이블 파일이 손상됨"""


class _TableState:
    """테이블 하나의 실행 중 상태. 파일을 처음 쓸 때 한 번 만든다"""

    def __init__(self):
        self.index = BPlusTree(order=INDEX_ORDER)  # id → offset
        self.next_id = 1
        self.size = 0  # 파일 크기 = 다음 행이 들어갈 offset
        self.needs_newline = False  # 마지막 줄이 줄바꿈 없이 끝났는가 (손으로 고친 파일 등)
        self.writer = None  # 덧붙이기용으로 열어 둔 파일 (INSERT마다 열고 닫지 않으려고)
        self.reader = None  # id 검색용으로 열어 둔 파일 (검색마다 열고 닫으면 열기 비용이 검색 시간의 절반을 넘었다)
        # reader는 하나를 여러 스레드가 함께 쓴다. seek와 readline 사이에 다른 스레드가 seek하면 남의 줄을 읽으므로 둘을 묶어 잠근다 (Phase 3)
        self.reader_lock = threading.Lock()


class Database:
    # autoflush: INSERT마다 파일 버퍼를 운영체제로 넘길지. 기본 True (프로그램이 갑자기 꺼져도 끝난 INSERT는 남는다)
    # 대량 적재(성능 측정의 100만 행 INSERT)는 False로 → 행마다 약 9µs 들던 flush를 건너뛰고, 검색 · 닫기 직전에 한 번에 넘긴다
    def __init__(self, directory, autoflush=True):
        # 폴더가 아니면(파일 경로를 줌) "…\schema.json이 없다"는 헷갈리는 메시지 대신 바로 알려 준다 (자체 점검)
        if not os.path.isdir(directory):
            raise SchemaError(f"DB 폴더가 아닙니다: {directory}")
        self.directory = directory
        # 테이블 이름 → [(컬럼, 타입), ...]  (id는 빼고 스키마에 적힌 열만)
        self.tables = load_schema(os.path.join(directory, "schema.json"))
        self._states = {}
        self._states_lock = threading.Lock()  # 두 스레드가 같은 테이블을 처음 동시에 쓸 때 인덱스를 한 번만 만들게 (Phase 3)
        self.autoflush = autoflush

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # 열어 둔 파일을 닫는다 (Windows는 열린 파일을 지울 수 없고, 닫아야 버퍼가 확실히 비워진다)
    def close(self):
        for state in self._states.values():
            for name in ("writer", "reader"):
                f = getattr(state, name)
                if f is not None:
                    f.close()
                    setattr(state, name, None)

    def path(self, table):
        return os.path.join(self.directory, f"{table}.jsonl")

    # CREATE TABLE: schema.json을 새 내용으로 바꾼 "뒤에" 메모리에 반영한다 → 파일 저장이 실패하면 아무것도 바뀌지 않는다
    # 같은 이름을 동시에 만드는 경쟁은 호출하는 쪽(엔진의 스키마 락)이 막는다
    def create_table(self, table, columns):
        columns = _check_table(table, columns, self.tables)
        # 스키마에 없는 예전 데이터 파일이 남아 있으면, 새 테이블에 열 구성이 다른 옛 행이 섞인다
        if os.path.exists(self.path(table)):
            raise SchemaError(f"{table}.jsonl 파일이 이미 있습니다 (스키마에 없는 예전 데이터). 옮기거나 지운 뒤 다시 만드세요")
        schema = {name: dict(cols) for name, cols in self.tables.items()}
        schema[table] = dict(columns)
        _write_atomic(os.path.join(self.directory, "schema.json"), json.dumps(schema, ensure_ascii=False, indent=2) + "\n")
        self.tables[table] = columns

    # 테이블의 전체 열: id + 스키마의 열
    def columns(self, table):
        return [(ID, "INT")] + self.tables[table]

    # 행 하나를 파일 끝에 추가하고 인덱스에 등록 → 부여한 id. values는 스키마 순서의 값 목록 (검사는 실행기가 끝낸 상태)
    def append(self, table, values):
        state = self._state(table)
        row_id = state.next_id
        # 쓰기 "전에" 막는다: 파일의 가장 큰 id가 64비트 최대값이면 다음 id는 범위 밖이라, 써 버리면 그 줄이 손상으로 읽혀
        # 테이블 전체를 못 쓰게 됐다 (자체 점검으로 재현)
        if row_id > INT_MAX:
            raise StorageError(f"{table}: 더 이상 부여할 id가 없습니다 (64비트 정수 범위 초과)")
        data = (json.dumps([row_id] + values, ensure_ascii=False) + "\n").encode("utf-8")  # ensure_ascii=False: 한글을 그대로
        if state.needs_newline:
            # 마지막 줄이 줄바꿈 없이 끝났으면 새 행이 그 줄에 붙어 둘 다 망가진다 → 줄을 먼저 끊는다.
            # 이 1바이트만큼 새 행의 시작 위치(offset)도 뒤로 간다
            data = b"\n" + data
        if state.writer is None:
            state.writer = open(self.path(table), "ab")
        offset = state.size + (1 if state.needs_newline else 0)
        state.writer.write(data)
        if self.autoflush:
            # 매번 운영체제로 넘긴다: 프로그램이 갑자기 꺼져도 끝난 INSERT는 남고, 다른 열린 파일(검색)에서도 바로 보인다
            state.writer.flush()
        state.size += len(data)
        state.needs_newline = False
        state.index.insert(row_id, offset)
        state.next_id += 1
        return row_id

    # 모든 행을 파일 순서대로 하나씩 돌려준다 (선형 탐색의 재료). 파일이 없으면 아직 INSERT가 없던 빈 테이블
    def scan(self, table):
        types = [kind for _, kind in self.columns(table)]
        self._flush(table)  # autoflush=False로 아직 버퍼에 남은 행도 읽히게
        try:
            f = open(self.path(table), "rb")
        except FileNotFoundError:
            return
        with f:
            for number, raw in enumerate(f, 1):
                if raw.strip():  # 빈 줄(편집기가 끝에 넣은 줄 등)은 행이 아니다
                    yield self._decode(table, raw, number, types)

    # id로 행 하나 찾기 (인덱스 사용) → 행 또는 None. 트리에서 offset을 얻어 그 위치로 바로 가서 한 줄만 읽는다
    def get(self, table, row_id):
        state = self._state(table)
        offset = state.index.get(row_id)
        if offset is None:
            return None
        self._flush(table)
        with state.reader_lock:
            if state.reader is None:
                state.reader = open(self.path(table), "rb")
            state.reader.seek(offset)  # 버퍼를 비우고 그 위치로 옮긴다 → 덧붙인 행도 다시 읽힌다
            raw = state.reader.readline()
        row = self._decode(table, raw, f"{offset}바이트 위치", [kind for _, kind in self.columns(table)])
        if row[0] != row_id:  # 인덱스를 만든 뒤 다른 프로그램이 파일을 바꿨다
            raise StorageError(f"{self.path(table)}: 인덱스와 파일이 맞지 않습니다 (id {row_id})")
        return row

    def _flush(self, table):
        state = self._states.get(table)
        if state is not None and state.writer is not None:
            state.writer.flush()

    # 인덱스 정보 (성능 측정 출력용)
    def index_height(self, table):
        return self._state(table).index.height

    # 테이블을 처음 쓸 때: 파일을 끝까지 한 번 읽어 인덱스(id → offset)를 만들고 다음 id를 정한다
    def _state(self, table):
        state = self._states.get(table)
        if state is not None:  # 대부분은 여기서 끝난다 (락 없이)
            return state
        with self._states_lock:
            state = self._states.get(table)  # 기다리는 동안 다른 스레드가 만들었을 수 있다
            if state is None:
                state = self._build_state(table)
                self._states[table] = state
            return state

    def _build_state(self, table):
        state = _TableState()
        types = [kind for _, kind in self.columns(table)]
        ids, offsets, numbers = [], [], []
        try:
            f = open(self.path(table), "rb")
        except FileNotFoundError:
            f = None
        if f is not None:
            with f:
                offset, raw = 0, b""
                for number, raw in enumerate(f, 1):  # 바이너리 모드: 줄은 \n으로만 나뉘고, len(raw)는 정확한 바이트 수다
                    if raw.strip():
                        ids.append(self._decode(table, raw, number, types)[0])  # 행 전체를 검사해 손상을 켤 때 바로 알린다
                        offsets.append(offset)
                        numbers.append(number)
                    offset += len(raw)
                state.size = offset
                state.needs_newline = offset > 0 and not raw.endswith(b"\n")
        try:
            # 보통 파일은 id가 1, 2, 3 ... 순서라 정렬된 채로 한 번에 쌓는다 (100만 행: 하나씩 넣기보다 훨씬 빠름)
            state.index = BPlusTree.bulk_load(ids, offsets, order=INDEX_ORDER)
        except ValueError:
            # 손으로 고친 파일처럼 순서가 섞였으면 하나씩 넣는다. 같은 id가 두 번 있으면 몇 번째 줄인지 알린다
            for row_id, offset, number in zip(ids, offsets, numbers):
                try:
                    state.index.insert(row_id, offset)
                except KeyError:
                    raise StorageError(f"{self.path(table)} {number}번째 줄: id {row_id}이(가) 이미 있습니다") from None
        state.next_id = max(ids, default=0) + 1
        return state

    # 파일의 한 줄 → 행. 손상됐으면 StorageError. where: 에러에 적을 위치 (줄 번호 또는 "N바이트 위치")
    def _decode(self, table, raw, where, types):
        where = f"{where}번째 줄" if isinstance(where, int) else f"{where}의 줄"
        try:
            # json.loads(bytes)는 줄마다 인코딩을 추측(UTF-8/16/32)해서 느렸다 → UTF-8로 직접 풀고 해석기를 바로 부른다
            row = _decode_json(raw.decode("utf-8"))
        except ValueError:  # JSON이 아님, UTF-8이 아님 (UnicodeDecodeError도 ValueError)
            raise StorageError(f"{self.path(table)} {where}이 손상되었습니다") from None
        # id는 1 이상이어야 한다 (자동 부여는 1부터)
        if not _row_matches(row, types) or row[0] < 1:
            raise StorageError(f"{self.path(table)} {where}이 스키마와 다릅니다: {raw[:80]!r}")
        return row


_decode_json = json.JSONDecoder().decode


# types: 열마다 "INT" / "TEXT". 행마다 불리므로 제너레이터(all(...)) 대신 단순 반복문으로 쓴다 (전체 탐색 시간의 약 1/4이었다)
def _row_matches(row, types):
    if type(row) is not list or len(row) != len(types):
        return False
    for v, t in zip(row, types):
        if t == "INT":
            # type(v) is int: JSON의 true는 파이썬에서 True(== 1)라서 isinstance(v, int)로는 걸러지지 않는다
            # INT는 64비트 범위까지 (SQL로는 그 밖의 값을 넣을 수 없으므로, 파일에 있으면 손으로 고친 손상이다: Gemini 리뷰)
            if type(v) is not int or not INT_MIN <= v <= INT_MAX:
                return False
        elif type(v) is not str:
            return False
    return True


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
    tables = {}
    for table, columns in data.items():
        if not isinstance(columns, dict):
            raise SchemaError(f"{table}: 컬럼이 하나 이상 있어야 합니다")
        tables[table] = _check_table(table, list(columns.items()), tables)
    return tables


# 테이블 정의 하나를 검사해 [(컬럼, 타입 대문자)]로 돌려준다. schema.json을 읽을 때와 CREATE TABLE이 같은 규칙을 쓴다
# existing: 이미 있는 테이블들 (같은 이름 · 대소문자만 다른 이름을 막는 데 쓴다)
def _check_table(table, columns, existing):
    _check_name(table, "테이블")
    # Windows 파일 이름은 대소문자를 구분하지 않아서 Users와 users가 같은 파일을 쓰게 된다
    clash = next((t for t in existing if t.upper() == table.upper()), None)
    if clash is not None:
        raise SchemaError(f"이미 있는 테이블입니다: {table}" if clash == table else f"대소문자만 다른 테이블이 있습니다: {table}")
    if table.upper() in _WINDOWS_DEVICES:
        raise SchemaError(f"테이블 이름으로 쓸 수 없습니다 (Windows 장치 이름): {table}")
    if not columns:
        raise SchemaError(f"{table}: 컬럼이 하나 이상 있어야 합니다")
    seen = set()
    for column, kind in columns:
        _check_name(column, f"{table}의 컬럼")
        if column.lower() == ID:
            raise SchemaError(f"{table}: id는 자동으로 붙는 열이라 스키마에 적을 수 없습니다")
        # schema.json은 JSON을 읽을 때(_no_duplicates) 막히지만, CREATE TABLE의 컬럼 목록은 여기서 막아야 한다
        if column in seen:
            raise SchemaError(f"{table}: 같은 컬럼이 두 번 있습니다: {column}")
        seen.add(column)
        if not isinstance(kind, str) or kind.upper() not in TYPES:
            raise SchemaError(f"{table}.{column}: 타입은 INT 또는 TEXT여야 합니다 ({kind!r})")
    return [(column, kind.upper()) for column, kind in columns]


# 임시 파일에 끝까지 쓰고 디스크에 기록(fsync)한 뒤 한 번에 바꿔치기 → 쓰는 도중 꺼져도 원래 파일은 온전히 남는다
def _write_atomic(path, text):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise SchemaError(f"스키마 파일을 저장하지 못했습니다: {e}") from None


# 이름 규칙을 지켜야 SQL에서 부를 수 있고, 파일 이름으로 써도 안전하다 (../ 같은 경로 문자가 들어갈 수 없다)
def _check_name(name, what):
    # 64자: MySQL의 이름 길이 상한과 같다. 길이 제한이 없으면 Windows 경로 길이를 넘어 INSERT가 OSError로 실패했다 (자체 점검)
    if not _NAME_RE.match(name) or name.upper() in KEYWORDS or len(name) > 64:
        raise SchemaError(f"{what} 이름이 올바르지 않습니다: {name[:70]!r} (영문·숫자·_ 64자 이하, 키워드 불가)")


# json은 같은 키가 두 번 나오면 조용히 뒤의 것만 남긴다 → 컬럼이 사라지는 실수를 막으려고 에러로 바꾼다
def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError(f"스키마에 같은 이름이 두 번 있습니다: {key}")
        result[key] = value
    return result
