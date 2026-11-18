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
        ]
        for raw in bad:
            with self.assertRaises(SchemaError, msg=raw):
                Database(make_db(self, raw=raw))


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.db = Database(make_db(self, {"users": {"name": "TEXT", "age": "INT"}}))
        self.file = self.db.path("users")

    def write_raw(self, data):
        with open(self.file, "wb") as f:
            f.write(data)

    def test_empty_table_without_file(self):
        self.assertEqual(list(self.db.scan("users")), [])

    def test_round_trip_tricky_values(self):
        rows = [["홍길동", 25], ['lee, "jr"', -3], ["줄\n바꿈\t탭", 0], ["", 2**63 - 1], ["\\ 역슬래시", 1]]
        for row in rows:
            self.db.append("users", row)
        self.assertEqual(list(self.db.scan("users")), rows)
        with open(self.file, encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), len(rows))  # 한 줄 = 한 행 (값 안의 줄바꿈도 \n 두 글자로 적힌다)
        self.assertEqual(lines[0], '["홍길동", 25]')  # 한글이 그대로 보인다

    def test_data_survives_reopen(self):
        self.db.append("users", ["a", 1])
        reopened = Database(self.db.directory)  # 프로그램을 다시 켠 것과 같다
        self.assertEqual(list(reopened.scan("users")), [["a", 1]])

    def test_append_after_missing_trailing_newline(self):
        # 마지막 줄에 줄바꿈이 없던 파일(손으로 고침)에 붙여 써도 두 행이 한 줄로 붙지 않는다
        self.write_raw('["a", 1]'.encode("utf-8"))
        self.db.append("users", ["b", 2])
        self.assertEqual(list(self.db.scan("users")), [["a", 1], ["b", 2]])

    def test_blank_lines_are_skipped(self):
        self.write_raw(b'["a", 1]\n\n  \r\n["b", 2]\n')
        self.assertEqual(list(self.db.scan("users")), [["a", 1], ["b", 2]])

    def test_corrupt_rows_raise_with_line_number(self):
        bad_lines = [
            b'["a", 1',  # 쓰다가 꺼져 잘린 줄
            b"not json",
            b'{"name": "a"}',  # 배열이 아님
            b'["a"]',  # 컬럼 수가 다름
            b'["a", 1, 2]',
            b'["a", "1"]',  # INT 칸에 문자열
            b'["a", true]',  # true는 파이썬에서 1과 같지만 정수가 아니다
            b'["a", 1.5]',
            b'[1, 1]',  # TEXT 칸에 정수
            b'["\xff", 1]',  # UTF-8이 아님
        ]
        for bad in bad_lines:
            self.write_raw(b'["ok", 1]\n' + bad + b"\n")
            with self.assertRaises(StorageError, msg=bad) as ctx:
                list(self.db.scan("users"))
            self.assertIn("2번째 줄", str(ctx.exception), bad)


if __name__ == "__main__":
    unittest.main()
