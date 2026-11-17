# [table.py] 테이블 하나 = 데이터 파일 하나 (JSON Lines) + id 인덱스 (B+ 트리)
#
# ■ 파일 모양: 한 줄 = 한 행 = JSON 배열, 열 순서는 스키마 순서
#     data/users.jsonl
#       [1,"김준우",25,"kim@example.com"]
#       [2,"O'Brien",null,"ob@example.com"]
#       [3,"줄바꿈\n있음",30,null]          ← 값 안의 줄바꿈은 json 이 \n 두 글자로 적는다 → 항상 "한 줄 = 한 행"
#   CSV 와 달리 값 안의 쉼표 · 따옴표 · 줄바꿈을 따로 처리할 필요가 없고, 숫자 / 문자열 / null 타입이 그대로 남는다.
#
# ■ 인덱스: id → 그 행이 파일에서 시작하는 바이트 위치(offset)
#   INSERT 때 파일 끝에 붙이기 직전의 위치를 기억해 등록 → id 로 찾을 때는 그 위치에서 한 줄만 읽는다 (파일 전체를 안 읽음).
#   인덱스는 메모리에만 있다 (과제: 메모리 기반 B+ 트리). 그래서 테이블을 열 때마다 파일을 한 번 훑어 다시 만든다.
#
# ■ 쓰기 순서 (실패해도 파일과 인덱스가 어긋나지 않게)
#   1) 지금 파일 크기 기억  2) 행들을 한 번에 붙이고 flush  3) 성공한 뒤에만 인덱스에 등록 · 다음 id 올리기
#   2) 에서 실패하면(디스크 가득 등) 파일을 1) 의 크기로 잘라 되돌린다 → "둘 다 쓰였거나, 둘 다 안 쓰였거나"
#
# ■ 켤 때 마지막 줄이 반쯤 쓰여 있으면 (쓰다가 전원이 꺼짐) 그 줄을 잘라 내고 경고를 남긴다.
#   중간 줄이 망가져 있으면 DataError — 조용히 넘어가면 그 뒤 행들을 잃으므로, 시작을 거부한다.
#
# ■ 동시성: 이 클래스는 락을 모른다. 엔진이 "읽기는 여럿 · 쓰기는 혼자" 락을 잡은 채로 부른다.
#   그래도 읽기끼리 겹쳐도 안전하게: id 로 읽기는 os.pread(파일 위치를 공유하지 않는 읽기),
#   훑기는 부를 때마다 자기 파일 핸들을 따로 연다. 훑기는 시작할 때의 파일 크기까지만 읽는다.

import json
import os

from .bptree import BPlusTree
from .errors import DataError, SqlError

_PREAD = getattr(os, "pread", None)  # Windows 에는 없다 → 그때는 읽을 때마다 파일을 열어 seek


class Table:
    def __init__(self, schema, path, order=64, sync=False):
        self.schema = schema
        self.path = path
        self.sync = sync  # True 면 쓸 때마다 fsync (디스크까지 확실히, 대신 아주 느림)
        self.index = BPlusTree(order)
        self.next_id = 1
        self.size = 0  # 지금까지 쓴 파일 크기(바이트) = 다음 행이 들어갈 위치
        self.warnings = []
        self._open()

    def __len__(self):
        return len(self.index)

    # ── 열기: 파일을 훑어 인덱스를 다시 만든다 ─────────────────────────

    def _open(self):
        if not self.path.exists():
            self.path.write_bytes(b"")
        keys, offsets = [], []
        ncols = len(self.schema.columns)
        offset = 0
        with open(self.path, "rb") as f:
            for line_no, raw in enumerate(f, 1):
                if not raw.endswith(b"\n"):  # 줄바꿈 없이 끝난 마지막 줄 = 쓰다가 끊김
                    os.truncate(self.path, offset)
                    self.warnings.append(f"{self.path.name} 마지막 줄이 반쯤 쓰여 있어 잘라 냈습니다 ({len(raw)}바이트)")
                    break
                try:
                    row = json.loads(raw)
                except ValueError:
                    raise DataError(f"{self.path} {line_no}번째 줄이 JSON 이 아닙니다 (파일 손상)")
                # shortcut: 열 수 · id 만 확인하고 각 값의 타입은 다시 검사하지 않는다 (100만 행을 열 때마다 검사하면 느림) → 사람이 파일을 직접 고치는 일이 생기면 타입 검사를 켠다
                if not isinstance(row, list) or len(row) != ncols or type(row[0]) is not int or (keys and row[0] <= keys[-1]):
                    raise DataError(f"{self.path} {line_no}번째 줄의 모양이 스키마와 다르거나 id 순서가 어긋났습니다")
                keys.append(row[0])
                offsets.append(offset)
                offset += len(raw)
        self.index.bulk_load(keys, offsets)  # id 는 파일 순서대로 커지므로 정렬된 채 → 한꺼번에 쌓기
        self.next_id = keys[-1] + 1 if keys else 1
        self.size = offset
        self._writer = open(self.path, "ab")
        self._fd = os.open(self.path, os.O_RDONLY) if _PREAD else None

    def close(self):
        self._writer.close()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    # ── 쓰기 ──────────────────────────────────────────────────────────

    def insert_rows(self, rows):
        """id 를 뺀 행들(이미 타입 검사가 끝난 값)을 붙인다 → (첫 id, 마지막 id). 실패하면 아무것도 안 쓴 상태로 SqlError"""
        start, first = self.size, self.next_id
        lines, offsets, pos = [], [], start
        try:
            for i, row in enumerate(rows):
                line = (json.dumps([first + i, *row], ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                offsets.append(pos)
                pos += len(line)
                lines.append(line)
        except UnicodeEncodeError:  # 짝 없는 반쪽 문자("\ud800") — JSON 본문으로는 들어올 수 있지만 UTF-8 로 못 쓴다
            raise SqlError("UTF-8 로 저장할 수 없는 문자(짝 없는 서로게이트)가 들어 있습니다")
        try:
            self._writer.write(b"".join(lines))
            self._writer.flush()
            if self.sync:
                os.fsync(self._writer.fileno())
        except OSError as e:
            self._rollback(start)
            raise SqlError(f"데이터 파일에 쓰지 못했습니다 (아무 행도 저장되지 않음): {e}")
        for i, off in enumerate(offsets):  # 파일에 다 쓴 "뒤에" 인덱스 등록 — 인덱스가 아직 없는 줄을 가리키는 순간이 없다
            self.index.insert(first + i, off)
        self.size = pos
        self.next_id = first + len(rows)
        return first, self.next_id - 1

    def _rollback(self, size):
        """쓰다가 실패 → 파일을 쓰기 전 크기로 자르고 쓰기 핸들을 새로 연다"""
        try:
            self._writer.close()  # 버퍼에 남은 조각을 쓰려다 또 실패할 수 있다 — 어차피 아래에서 잘라 낸다
        except OSError:
            pass
        os.truncate(self.path, size)
        self._writer = open(self.path, "ab")

    # ── 읽기 ──────────────────────────────────────────────────────────

    def get(self, id_):
        """id 로 한 행 (인덱스 → 위치 → 한 줄). 없으면 None"""
        offset = self.index.search(id_)
        return None if offset is None else self._read_at(offset)

    def range_rows(self, lo=None, hi=None, include_lo=True, include_hi=True):
        """id 범위의 행들을 id 순서로 (인덱스의 잎 연결을 따라가며 위치마다 한 줄씩)"""
        for _, offset in self.index.range(lo, hi, include_lo, include_hi):
            yield self._read_at(offset)

    def scan(self):
        """모든 행을 파일 순서(= id 순서)로 — 인덱스를 쓰지 않는 선형 탐색"""
        end = self.size  # 지금 크기까지만: 훑는 도중 다른 곳에서 붙인 줄은 보지 않는다
        pos = 0
        with open(self.path, "rb") as f:
            for raw in f:
                if pos >= end:
                    return
                pos += len(raw)
                yield json.loads(raw)

    def _read_at(self, offset):
        """offset 에서 시작하는 한 줄 → 행. 보통 4KB 한 번에 끝난다 (줄이 길면 이어서 읽음)"""
        if self._fd is None:
            with open(self.path, "rb") as f:
                f.seek(offset)
                return json.loads(f.readline())
        parts = []
        while True:
            chunk = _PREAD(self._fd, 4096, offset)
            cut = chunk.find(b"\n")
            if cut >= 0 or not chunk:
                parts.append(chunk if cut < 0 else chunk[:cut])
                return json.loads(b"".join(parts))
            parts.append(chunk)
            offset += len(chunk)
