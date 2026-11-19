# [test_storage.py] 스키마 읽기 검사, 행 추가 · 읽기, 손상된 파일 처리

import json
import os
import tempfile
import unittest

from minidb.storage import Database, SchemaError, StorageError


def make_db(case, schema=None, raw=None):
    """임시 폴더(테스트가 끝나면 지움)에 schema.json을 만들고 폴더 경로를 돌려준다. raw를 주면 그 문자열을 그대로 쓴다"""
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    directory = tmp.name
    with open(os.path.join(directory, "schema.json"), "w", encoding="utf-8") as f:
        f.write(raw if raw is not None else json.dumps(schema))
    return directory


class SchemaTest(unittest.TestCase):
    def test_order_and_type_case(self):
        db = Database(make_db(self, {"users": {"name": "text", "age": "INT"}, "t": {"x": "Int"}}))
        self.assertEqual(db.tables, {"users": [("name", "TEXT"), ("age", "INT")], "t": [("x", "INT")]})

    def test_bom_is_ok(self):
        db = Database(make_db(self, raw='\ufeff{"t": {"x": "INT"}}'))  # 메모장으로 저장한 UTF-8 파일
        self.assertIn("t", db.tables)

    def test_missing_schema(self):
        with tempfile.TemporaryDirectory() as empty, self.assertRaises(SchemaError):
            Database(empty)

    def test_db_path_must_be_a_folder(self):
        # 파일이나 없는 경로를 DB 폴더로 주면 "DB 폴더가 아닙니다" (전에는 "...\\q.sql\\schema.json이 없습니다", 자체 점검)
        directory = make_db(self, {"t": {"x": "INT"}})
        for path in [os.path.join(directory, "schema.json"), os.path.join(directory, "없는폴더")]:
            with self.assertRaises(SchemaError) as ctx:
                Database(path)
            self.assertIn("DB 폴더가 아닙니다", str(ctx.exception))

    def test_bad_schemas(self):
        bad = [
            "{깨진 json",
            "[]",
            "{}",  # 테이블이 하나도 없음
            '{"t": {}}',  # 컬럼 없음
            '{"t": ["x"]}',
            '{"t": {"x": "FLOAT"}}',  # 지원하지 않는 타입
            '{"t": {"x": 1}}',
            '{"t": {"x": "INT", "x": "TEXT"}}',  # 같은 컬럼 두 번 (json은 조용히 뒤의 것만 남긴다)
            '{"t": {"x": "INT"}, "t": {"y": "INT"}}',
            '{"../evil": {"x": "INT"}}',  # 경로 문자 → 테이블 파일이 DB 폴더 밖으로 나감
            '{"a b": {"x": "INT"}}',
            '{"1t": {"x": "INT"}}',
            '{"select": {"x": "INT"}}',  # 키워드는 SQL에서 부를 수 없다
            '{"t": {"from": "INT"}}',
            '{"t": {"이름": "TEXT"}}',
            '{"Users": {"x": "INT"}, "users": {"x": "INT"}}',  # Windows에서 같은 파일
            '{"con": {"x": "INT"}}',  # Windows 장치 이름
            '{"COM1": {"x": "INT"}}',
            '{"%s": {"x": "INT"}}' % ("t" * 65),  # 64자 초과: Windows 경로 길이를 넘어 INSERT가 OSError로 실패하던 것 (자체 점검)
            '{"t": {"%s": "INT"}}' % ("c" * 65),
        ]
        for raw in bad:
            with self.assertRaises(SchemaError, msg=raw):
                Database(make_db(self, raw=raw))


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(make_db(self, {"users": {"name": "TEXT", "age": "INT"}}))
        self.addCleanup(self.db.close)  # 열어 둔 테이블 파일을 닫아야 임시 폴더를 지울 수 있다 (Windows)
        self.file = self.db.path("users")

    def write_raw(self, data):
        with open(self.file, "wb") as f:
            f.write(data)

    def reopen(self):
        """프로그램을 다시 켠 것과 같다: 새 Database가 파일을 읽어 인덱스를 다시 만든다"""
        self.db.close()
        db = Database(self.db.directory)
        self.addCleanup(db.close)
        return db

    def test_empty_table_without_file(self):
        self.assertEqual((list(self.db.scan("users")), self.db.get("users", 1)), ([], None))

    def test_round_trip_tricky_values(self):
        values = [["홍길동", 25], ['lee, "jr"', -3], ["줄\n바꿈\t탭", 0], ["", 2**63 - 1], ["\\ 역슬래시", 1], ["a" + chr(0x2028) + "b", 2]]
        ids = [self.db.append("users", v) for v in values]
        self.assertEqual(ids, [1, 2, 3, 4, 5, 6])  # id는 1부터 자동
        expected = [[i] + v for i, v in zip(ids, values)]
        self.assertEqual(list(self.db.scan("users")), expected)
        self.assertEqual([self.db.get("users", i) for i in ids], expected)  # 인덱스로 찾아도 같다 (한글 등 여러 바이트 글자 뒤의 offset 포함)
        with open(self.file, "rb") as f:
            lines = f.read().split(b"\n")[:-1]
        self.assertEqual(len(lines), len(values))  # 한 줄 = 한 행 (값 안의 줄바꿈도 \n 두 글자로 적힌다)
        self.assertEqual(lines[0].decode("utf-8"), '[1, "홍길동", 25]')  # 한글이 그대로 보인다

    def test_data_and_ids_survive_reopen(self):
        self.db.append("users", ["a", 1])
        self.db.append("users", ["b", 2])
        db = self.reopen()
        self.assertEqual(list(db.scan("users")), [[1, "a", 1], [2, "b", 2]])
        self.assertEqual(db.get("users", 2), [2, "b", 2])
        self.assertEqual(db.append("users", ["c", 3]), 3)  # 다음 id = 가장 큰 id + 1
        self.assertEqual(db.get("users", 3), [3, "c", 3])

    def test_rows_added_after_reader_opened_are_found(self):
        # id 검색용 파일을 한 번 연 뒤에 덧붙인 행도 찾아야 한다 (읽기 파일을 열어 두고 다시 쓰므로)
        self.db.append("users", ["a", 1])
        self.assertEqual(self.db.get("users", 1), [1, "a", 1])  # 여기서 읽기용 파일이 열린다
        self.db.append("users", ["b", 2])
        self.assertEqual(self.db.get("users", 2), [2, "b", 2])

    def test_autoflush_off_still_reads_own_rows_and_saves_on_close(self):
        # 대량 적재 모드: INSERT마다 flush하지 않지만, 검색은 버퍼에 남은 행까지 보고, 닫으면 파일에 남는다
        self.db.close()
        db = Database(self.db.directory, autoflush=False)
        for i in range(1, 6):
            db.append("users", [f"u{i}", i])
        self.assertEqual(len(list(db.scan("users"))), 5)  # 전체 탐색이 먼저 (검색이 먼저 flush하면 가려진다)
        db.append("users", ["u6", 6])
        self.assertEqual(db.get("users", 6), [6, "u6", 6])
        db.append("users", ["u7", 7])
        self.assertEqual(len(list(db.scan("users"))), 7)
        db.close()
        self.assertEqual(len(list(self.reopen().scan("users"))), 7)

    def test_unordered_file_still_builds_index(self):
        # 보통은 정렬된 채로 한 번에 쌓지만(bulk load), id 순서가 섞인 파일은 하나씩 넣어 만든다
        self.write_raw(b'[3, "c", 3]\n[1, "a", 1]\n[2, "b", 2]\n')
        db = self.reopen()
        self.assertEqual([db.get("users", i) for i in (1, 2, 3)], [[1, "a", 1], [2, "b", 2], [3, "c", 3]])
        self.assertEqual(db.append("users", ["d", 4]), 4)

    def test_next_id_follows_largest_id(self):
        # 손으로 고친 파일처럼 id 순서가 섞이거나 비어 있어도, 다음 id는 가장 큰 id + 1이다
        self.write_raw(b'[5, "e", 5]\n[2, "b", 2]\n')
        db = self.reopen()
        self.assertEqual(db.get("users", 2), [2, "b", 2])
        self.assertEqual(db.append("users", ["f", 6]), 6)

    def test_append_after_missing_trailing_newline(self):
        # 마지막 줄에 줄바꿈이 없던 파일(손으로 고침)에 붙여 써도 두 행이 한 줄로 붙지 않고, 새 행의 offset도 정확하다
        for tail in [b'[1, "a", 1]', b'[1, "a", 1]\n   ']:  # 줄바꿈 없음 / 공백만 있는 마지막 줄
            self.write_raw(tail)
            db = self.reopen()
            self.assertEqual(db.append("users", ["b", 2]), 2)
            self.assertEqual(list(db.scan("users")), [[1, "a", 1], [2, "b", 2]])
            self.assertEqual(db.get("users", 2), [2, "b", 2])  # 줄을 끊으려고 넣은 1바이트만큼 뒤의 위치
            self.assertEqual(self.reopen().get("users", 2), [2, "b", 2])  # 다시 켜서 만든 인덱스도 같은 위치

    def test_blank_lines_are_skipped(self):
        self.write_raw(b'[1, "a", 1]\n\n  \r\n[2, "b", 2]\n')
        db = self.reopen()
        self.assertEqual(list(db.scan("users")), [[1, "a", 1], [2, "b", 2]])
        self.assertEqual(db.get("users", 2), [2, "b", 2])  # 빈 줄의 바이트도 offset에 들어간다

    def test_corrupt_rows_raise_with_line_number(self):
        bad_lines = [
            b'[2, "a", 1',  # 쓰다가 꺼져 잘린 줄
            b"not json",
            b'{"name": "a"}',  # 배열이 아님
            b'[2, "a"]',  # 컬럼 수가 다름
            b'[2, "a", 1, 2]',
            b'["a", 1]',  # id 없음 (Phase 1 형식)
            b'[2, "a", "1"]',  # INT 칸에 문자열
            b'[2, "a", true]',  # true는 파이썬에서 1과 같지만 정수가 아니다
            b'[2, "a", 1.5]',
            b'[2, 1, 1]',  # TEXT 칸에 정수
            b'[2, "\xff", 1]',  # UTF-8이 아님
            b'[2, "a", 9223372036854775808]',  # INT 64비트 범위 밖 (SQL로는 넣을 수 없는 값, Gemini 리뷰)
            b'[2, "a", -9223372036854775809]',
            b'[0, "a", 1]',  # id는 1 이상
            b'[-3, "a", 1]',
            b'["2", "a", 1]',  # id는 정수
            b'[true, "a", 1]',
        ]
        for bad in bad_lines:
            self.write_raw(b'[1, "ok", 1]\n' + bad + b"\n")
            db = self.reopen()
            with self.assertRaises(StorageError, msg=bad) as ctx:
                list(db.scan("users"))
            self.assertIn("2번째 줄", str(ctx.exception), bad)
            with self.assertRaises(StorageError, msg=bad):  # 인덱스를 만들 때(첫 INSERT · id 검색)도 같은 손상을 알린다
                db.get("users", 1)

    def test_id_overflow_is_refused_before_writing(self):
        # 가장 큰 id가 64비트 최대값이면 다음 INSERT는 거부하고, 파일은 그대로 둔다 (전에는 범위 밖 id를 써서 테이블이 손상됨)
        self.write_raw(b'[9223372036854775807, "max", 1]\n')
        db = self.reopen()
        with self.assertRaises(StorageError):
            db.append("users", ["over", 1])
        self.assertEqual(list(db.scan("users")), [[2**63 - 1, "max", 1]])

    def test_duplicate_id_in_file(self):
        self.write_raw(b'[1, "a", 1]\n[1, "b", 2]\n')
        with self.assertRaises(StorageError) as ctx:
            self.reopen().append("users", ["c", 3])
        self.assertIn("이미 있습니다", str(ctx.exception))

    def test_index_detects_file_changed_by_others(self):
        self.db.append("users", ["a", 1])
        self.db.append("users", ["b", 2])
        with open(self.file, "r+b") as f:  # 다른 프로그램이 첫 줄을 다른 id로 바꿔 씀 (길이는 같게)
            f.write(b'[9, "a", 1]')
        with self.assertRaises(StorageError):
            self.db.get("users", 1)

    def test_schema_cannot_define_id(self):
        for raw in ['{"t": {"id": "INT"}}', '{"t": {"ID": "TEXT"}}']:
            with self.assertRaises(SchemaError, msg=raw):
                Database(make_db(self, raw=raw))


if __name__ == "__main__":
    unittest.main()
