# [helpers.py] 테스트 공통 — 임시 데이터 폴더(스키마만 있는) 만들기
#
# 테스트는 저장소의 data/ 를 건드리지 않는다: 테스트마다 빈 임시 폴더에 스키마 파일을 쓰고, 끝나면 지운다.

import json
import shutil
import tempfile
from pathlib import Path

USERS = [("id", "INT"), ("name", "TEXT"), ("age", "INT"), ("email", "TEXT")]
PRODUCTS = [("id", "INT"), ("name", "TEXT"), ("price", "FLOAT")]


def make_data_dir(test, tables=None):
    """임시 데이터 폴더 → Path. tables = {이름: [(열, 타입), …]} (기본 users · products). 테스트가 끝나면 지운다"""
    path = Path(tempfile.mkdtemp(prefix="mini_dbms_test_"))
    test.addCleanup(shutil.rmtree, path, ignore_errors=True)
    for name, columns in (tables or {"users": USERS, "products": PRODUCTS}).items():
        schema = {"columns": [{"name": n, "type": t} for n, t in columns]}
        (path / f"{name}.schema.json").write_text(json.dumps(schema), encoding="utf-8")
    return path
