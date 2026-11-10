# [test_persistence.py] 스냅샷 저장/복구 테스트 — 서버가 꺼졌다 켜져도 데이터가 남는지

import json
import os
import tempfile
import time
import unittest

from mini_redis import persistence
from mini_redis.persistence import SnapshotError, load_snapshot, save_snapshot, start_periodic_snapshot
from mini_redis.store import MiniRedis


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "sub", "dump.json")  # 없는 폴더도 만들어서 저장해야 한다
        # "벽시계"(재시작해도 이어지는 시각)를 테스트가 정한다 → 서버가 꺼져 있던 시간을 흉내 낸다
        self.wall = FakeClock(1_700_000_000.0)
        self.addCleanup(setattr, persistence, "_wall_clock", persistence._wall_clock)
        persistence._wall_clock = self.wall

    def test_round_trip_all_value_types(self):
        r = MiniRedis()
        values = {"str": "메이플", "int": 1, "float": 3.5, "bool": False, "list": [1, "a"], "dict": {"lv": 200}, "none": None}
        for k, v in values.items():
            r.set(k, v)
        self.assertEqual(save_snapshot(r, self.path), len(values))

        restored = MiniRedis()  # "재시작한 서버"
        self.assertEqual(load_snapshot(restored, self.path), len(values))
        self.assertEqual({k: restored.get(k) for k in values}, values)
        self.assertTrue(restored.exists("none"))  # None 값도 "있음"으로 복구
        self.assertEqual(restored.ttl("str"), -1)  # 만료 없던 키는 계속 만료 없음

    def test_ttl_counts_downtime(self):
        clock = FakeClock()
        r = MiniRedis(clock=clock)
        r.set("long", 1, ttl=100)
        r.set("short", 1, ttl=10)
        save_snapshot(r, self.path)

        self.wall.now += 30  # 서버가 30초 동안 꺼져 있었다
        restored = MiniRedis()
        self.assertEqual(load_snapshot(restored, self.path), 1)  # short(10초)는 꺼져 있는 동안 만료 → 복구 안 함
        self.assertEqual((restored.exists("short"), restored.ttl("long")), (False, 70))

    def test_expired_keys_are_not_saved(self):
        clock = FakeClock()
        r = MiniRedis(clock=clock)
        r.set("a", 1, ttl=1)
        r.set("b", 2)
        clock.now += 5  # a는 만료됐지만 아직 sweep 전이라 메모리에는 있다
        self.assertEqual(save_snapshot(r, self.path), 1)

    def test_missing_file_starts_empty(self):
        self.assertEqual(load_snapshot(MiniRedis(), self.path), 0)

    def test_corrupt_file_raises_and_is_kept(self):
        # 손상된 파일은 에러로 알린다 (조용히 빈 서버로 시작하면 다음 저장이 이 파일을 덮어써 데이터가 사라진다)
        os.makedirs(os.path.dirname(self.path))
        for content in ["{깨진 json", '{"format": 99, "entries": []}', '{"format": 1, "saved_at": 0, "entries": [1]}', "[]"]:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write(content)
            with self.assertRaises(SnapshotError, msg=content):
                load_snapshot(MiniRedis(), self.path)
            with open(self.path, encoding="utf-8") as f:
                self.assertEqual(f.read(), content)  # 파일은 그대로

    def test_failed_save_keeps_previous_snapshot(self):
        # JSON으로 못 바꾸는 값이 있어 저장이 실패해도 → 이전 스냅샷은 온전하고 임시 파일도 남지 않는다
        r = MiniRedis()
        r.set("ok", 1)
        save_snapshot(r, self.path)
        r.set("bad", {1, 2})  # set은 JSON으로 못 바꾼다 (파이썬 코드로 직접 넣은 경우)
        with self.assertRaises(TypeError):
            save_snapshot(r, self.path)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual([e["key"] for e in json.load(f)["entries"]], ["ok"])
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_periodic_snapshot_and_final_save_on_stop(self):
        r = MiniRedis()
        stop = start_periodic_snapshot(r, self.path, interval=0.05)
        r.set("a", 1)
        time.sleep(0.2)  # 주기 저장이 몇 번 돈다
        with open(self.path, encoding="utf-8") as f:
            self.assertIn("a", [e["key"] for e in json.load(f)["entries"]])
        r.set("b", 2)  # 다음 주기 전에 종료
        stop()
        restored = MiniRedis()
        load_snapshot(restored, self.path)
        self.assertEqual((restored.get("a"), restored.get("b")), (1, 2))  # 종료 직전 값까지 남음


if __name__ == "__main__":
    unittest.main()
