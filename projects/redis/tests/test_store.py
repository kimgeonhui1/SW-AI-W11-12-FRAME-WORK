# [test_store.py] MiniRedis 단위 테스트 — 저장/조회/삭제, 만료(TTL), 동시성

import threading
import unittest

from mini_redis.store import MiniRedis


class FakeClock:
    """테스트용 시계. advance()로 시간을 원하는 만큼 흘린다 (실제로 기다리지 않음)"""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class BasicTest(unittest.TestCase):
    """2단계: 저장 / 조회 / 삭제"""

    def setUp(self):
        self.r = MiniRedis()

    def test_set_get(self):
        self.r.set("a", {"name": "철수", "lv": 200})
        self.assertEqual(self.r.get("a"), {"name": "철수", "lv": 200})

    def test_overwrite(self):
        self.r.set("a", 1)
        self.r.set("a", 2)
        self.assertEqual((self.r.get("a"), len(self.r)), (2, 1))

    def test_missing_key(self):
        self.assertEqual((self.r.get("없음"), self.r.exists("없음"), self.r.delete("없음")), (None, False, False))

    def test_delete(self):
        self.r.set("a", 1)
        self.assertEqual((self.r.delete("a"), self.r.get("a"), self.r.exists("a"), len(self.r)), (True, None, False, 0))

    def test_none_value_vs_missing(self):
        # get만으로는 "None을 저장함"과 "없음"이 같아 보인다 → exists로 구분
        self.r.set("a", None)
        self.assertEqual((self.r.get("a"), self.r.exists("a")), (None, True))

    def test_non_string_key(self):
        with self.assertRaises(TypeError):
            self.r.set(1, "x")


class TtlTest(unittest.TestCase):
    """3단계: 만료(TTL)"""

    def setUp(self):
        self.clock = FakeClock()
        self.r = MiniRedis(clock=self.clock)

    def test_expires_exactly_at_ttl(self):
        self.r.set("a", 1, ttl=10)
        self.clock.advance(9.5)
        self.assertEqual((self.r.get("a"), self.r.ttl("a")), (1, 1))  # 0.5초 남음 → 올림해서 1
        self.clock.advance(0.5)  # 정확히 만료 시각 → 만료
        self.assertEqual((self.r.get("a"), self.r.exists("a"), self.r.ttl("a")), (None, False, -2))

    def test_lazy_delete_frees_memory_on_read(self):
        # 읽는 순간 만료를 확인해 실제로 지운다 (지연 삭제)
        self.r.set("a", 1, ttl=1)
        self.clock.advance(2)
        self.assertEqual(len(self.r), 1)  # 아직 아무도 안 읽어서 남아 있음
        self.r.get("a")
        self.assertEqual(len(self.r), 0)

    def test_ttl_codes(self):
        self.r.set("forever", 1)
        self.assertEqual((self.r.ttl("forever"), self.r.ttl("없음")), (-1, -2))

    def test_set_clears_previous_ttl(self):
        self.r.set("a", 1, ttl=5)
        self.r.set("a", 2)  # 실제 Redis처럼 SET은 TTL을 지운다
        self.clock.advance(10)
        self.assertEqual((self.r.get("a"), self.r.ttl("a")), (2, -1))

    def test_set_with_new_ttl_replaces_old_ttl(self):
        self.r.set("a", 1, ttl=5)
        self.r.set("a", 2, ttl=100)
        self.clock.advance(10)
        self.assertEqual(self.r.get("a"), 2)

    def test_expire(self):
        self.assertFalse(self.r.expire("없음", 5))
        self.r.set("a", 1)
        self.assertTrue(self.r.expire("a", 5))
        self.assertEqual(self.r.ttl("a"), 5)
        self.clock.advance(5)
        self.assertIsNone(self.r.get("a"))

    def test_expired_key_cannot_be_revived(self):
        # 만료된 키에 expire를 다시 걸거나 지우려 해도 "없는 키"로 동작해야 한다
        self.r.set("a", 1, ttl=1)
        self.clock.advance(2)
        self.assertEqual((self.r.expire("a", 100), self.r.delete("a"), self.r.get("a")), (False, False, None))

    def test_delete_removes_ttl_too(self):
        # 지웠다가 같은 키를 TTL 없이 다시 저장하면 이전 TTL이 남아 있으면 안 된다
        self.r.set("a", 1, ttl=5)
        self.r.delete("a")
        self.r.set("a", 2)
        self.clock.advance(10)
        self.assertEqual(self.r.get("a"), 2)

    def test_sweep_removes_only_expired(self):
        # 주기 삭제: 아무도 읽지 않은 만료 키도 정리
        self.r.set("short", 1, ttl=1)
        self.r.set("long", 1, ttl=100)
        self.r.set("forever", 1)
        self.clock.advance(2)
        self.assertEqual((self.r.sweep(), len(self.r), self.r.sweep()), (1, 2, 0))

    def test_invalid_ttl(self):
        # 1e-14: 시각에 더해도 부동소수점에서 사라져 바로 만료되던 값 → 최소 1ms로 막는다 (리뷰 반영)
        for bad in [0, -1, True, "5", float("inf"), float("nan"), 1e-14, 0.0009, 10**400]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.r.set("a", 1, ttl=bad)
        for bad in [0, -1, None, "5"]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.r.expire("a", bad)

    def test_min_ttl_is_not_expired_immediately(self):
        self.r.set("a", 1, ttl=0.001)
        self.assertEqual(self.r.get("a"), 1)
        self.clock.advance(0.001)
        self.assertIsNone(self.r.get("a"))

    def test_expire_extends_and_shortens_existing_ttl(self):
        # 이미 TTL이 있는 키에 expire를 다시 걸면 만료 시각을 덮어쓴다 (리뷰 반영)
        self.r.set("long", 1, ttl=5)
        self.r.expire("long", 100)  # 연장
        self.r.set("short", 1, ttl=100)
        self.r.expire("short", 5)  # 단축
        self.clock.advance(10)
        self.assertEqual((self.r.get("long"), self.r.get("short")), (1, None))

    def test_get_with_ttl(self):
        # 값과 ttl을 한 번에 (서버의 GET이 사용. 따로 읽으면 사이에 끼어든 요청 때문에 어긋날 수 있다)
        self.r.set("a", 1, ttl=10)
        self.r.set("b", 2)
        self.assertEqual((self.r.get_with_ttl("a"), self.r.get_with_ttl("b"), self.r.get_with_ttl("없음")), ((1, 10), (2, -1), (None, -2)))
        self.clock.advance(10)
        self.assertEqual(self.r.get_with_ttl("a"), (None, -2))

    def test_float_ttl(self):
        self.r.set("a", 1, ttl=0.5)
        self.clock.advance(0.4)
        self.assertEqual(self.r.get("a"), 1)
        self.clock.advance(0.1)
        self.assertIsNone(self.r.get("a"))


class ConcurrencyTest(unittest.TestCase):
    """4단계: 여러 스레드가 동시에 사용"""

    def test_concurrent_writes_with_resize(self):
        # 8개 스레드가 동시에 쓰고 읽어도(리사이즈 포함) 키가 빠지거나 개수가 틀리지 않아야 한다
        r = MiniRedis()

        def worker(t):
            for i in range(2000):
                r.set(f"{t}:{i}", i)
                r.get(f"{t}:{i}")

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(r), 8 * 2000)
        self.assertTrue(all(r.get(f"{t}:{i}") == i for t in range(8) for i in range(2000)))

    def test_concurrent_mixed_ops_with_sweep(self):
        # 쓰기·삭제·만료 설정·sweep이 동시에 일어나도 예외 없이 끝나고, 남은 키 상태가 일관돼야 한다
        clock = FakeClock()
        r = MiniRedis(clock=clock)
        errors = []
        swept = []

        def writer(t):
            try:
                for i in range(1000):
                    key = f"{t}:{i}"
                    r.set(key, i, ttl=1 if i % 2 else None)
                    if i % 3 == 0:
                        r.delete(key)
            except Exception as e:  # 스레드 안의 예외는 테스트로 전달되지 않아서 모아 둔다
                errors.append(e)

        def sweeper():
            # 도는 동안 시간을 흘려서, 쓰기·삭제가 진행되는 중에 sweep이 "실제로" 만료 키를 지우게 한다 (리뷰 반영)
            try:
                for _ in range(200):
                    clock.advance(0.05)
                    swept.append(r.sweep())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)] + [threading.Thread(target=sweeper)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertGreater(sum(swept), 0, "sweep이 동시 실행 중에 한 번도 키를 지우지 않음")
        clock.advance(2)  # 이제 TTL 1초짜리는 전부 만료
        r.sweep()
        # 남아야 하는 것: 짝수 i 중 3의 배수가 아닌 것 (TTL 없음, 삭제 안 됨)
        expected = sum(1 for i in range(1000) if i % 2 == 0 and i % 3 != 0) * 4
        self.assertEqual(len(r), expected)


if __name__ == "__main__":
    unittest.main()
