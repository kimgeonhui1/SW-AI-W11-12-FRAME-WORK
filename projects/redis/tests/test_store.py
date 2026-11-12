# [test_store.py] MiniRedis 단위 테스트 — 실행: projects/redis 에서 python -m unittest
#
# 설계 문서 10장의 계획대로 확인한다
#   기본      : 저장 · 조회 · 덮어쓰기 · 삭제 · exists · len, None 값, get_with_ttl
#   만료      : ttl 의 -1 / -2 / 남은 초(올림), 소수 ttl, 만료 뒤 get · exists · delete · expire · ttl · get_with_ttl, 만료 "순간" 경계
#   SET 규칙  : ttl 없이 덮어쓰면 기존 만료가 사라짐
#   sweep     : 아무도 안 읽은 만료 키를 지우고 개수를 돌려줌
#   입력 검사 : 잘못된 ttl → ValueError, 그때 기존 데이터는 그대로
#   동시성    : 여러 스레드가 동시에 set · delete · sweep 해도 개수가 정확
#
# ■ 시간은 기다리지 않는다
#   MiniRedis(clock=가짜 시계) 로 만들고 clock.advance(초) 로 시간을 원하는 만큼 흘린다 (dev 와 같은 방식).

import threading
import unittest
from mini_redis.store import MiniRedis


class FakeClock:
    """테스트용 시계. advance() 로 시간을 흘린다 (실제로 기다리지 않음)"""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StoreTestCase(unittest.TestCase):
    """모든 테스트가 가짜 시계 위에서 돈다"""

    def setUp(self):
        self.clock = FakeClock()
        self.r = MiniRedis(clock=self.clock)


class BasicTest(StoreTestCase):
    def test_set_get(self):
        self.assertTrue(self.r.set("user:1", {"name": "철수", "lv": 200}))
        self.assertEqual(self.r.get("user:1"), {"name": "철수", "lv": 200})

    def test_overwrite(self):
        self.r.set("a", 1)
        self.r.set("a", 2)
        self.assertEqual((self.r.get("a"), len(self.r)), (2, 1))

    def test_missing_key(self):
        r = self.r
        self.assertEqual((r.get("없음"), r.exists("없음"), r.delete("없음"), r.ttl("없음")), (None, False, False, -2))

    def test_delete(self):
        self.r.set("a", 1)
        self.assertEqual((self.r.delete("a"), self.r.delete("a"), self.r.get("a"), self.r.exists("a")), (True, False, None, False))

    def test_none_value_exists(self):
        # get 은 None 이라 "없음" 과 같아 보이지만 exists 로 구별된다
        self.r.set("a", None)
        self.assertEqual((self.r.get("a"), self.r.exists("a"), self.r.ttl("a")), (None, True, -1))

    def test_get_with_ttl(self):
        # 값과 ttl 을 락 하나 안에서 함께 읽는다 (서버 GET 응답이 사용)
        self.r.set("forever", "a")
        self.r.set("short", "b", ttl=10)
        self.assertEqual(
            (self.r.get_with_ttl("forever"), self.r.get_with_ttl("short"), self.r.get_with_ttl("없음")),
            (("a", -1), ("b", 10), (None, -2)),
        )


class TtlTest(StoreTestCase):
    def test_ttl_rules(self):
        self.r.set("forever", 1)
        self.r.set("short", 1, ttl=10)
        self.assertEqual((self.r.ttl("forever"), self.r.ttl("short"), self.r.ttl("없음")), (-1, 10, -2))

    def test_ttl_rounds_up(self):
        # 0.3초 남아도 살아 있으므로 1 (내림이면 0 이 되어 "곧 없어짐" 과 헷갈린다)
        self.r.set("a", 1, ttl=5)
        self.clock.advance(4.7)
        self.assertEqual(self.r.ttl("a"), 1)
        self.clock.advance(0.2999)
        self.assertEqual((self.r.ttl("a"), self.r.get("a")), (1, 1))

    def test_expired_exactly_at_expire_time(self):
        # 만료 시각과 같은 순간 = 이미 만료 (ttl=1 로 저장하고 정확히 1초 뒤에는 없어야 한다)
        self.r.set("a", 1, ttl=1)
        self.clock.advance(1)
        self.assertEqual((self.r.get("a"), self.r.exists("a"), self.r.ttl("a")), (None, False, -2))

    def test_expired_key_is_gone_for_every_command(self):
        for check in ("get", "exists", "delete", "expire", "ttl", "get_with_ttl"):
            r = MiniRedis(clock=self.clock)
            r.set("a", "값", ttl=2)
            self.clock.advance(3)
            result = {
                "get": lambda: r.get("a"),
                "exists": lambda: r.exists("a"),
                "delete": lambda: r.delete("a"),
                "expire": lambda: r.expire("a", 100),
                "ttl": lambda: r.ttl("a"),
                "get_with_ttl": lambda: r.get_with_ttl("a"),
            }[check]()
            expected = {"get": None, "exists": False, "delete": False, "expire": False, "ttl": -2, "get_with_ttl": (None, -2)}
            self.assertEqual(result, expected[check], check)
            # 값 · 만료 시각 두 테이블 모두에서 지워져야 한다
            self.assertEqual((len(r._data), len(r._expires)), (0, 0), f"{check} 가 지연 삭제를 하지 않음")

    def test_expire_sets_and_resets(self):
        self.r.set("a", 1)
        self.assertTrue(self.r.expire("a", 5))
        self.assertEqual(self.r.ttl("a"), 5)
        self.clock.advance(3)
        self.assertTrue(self.r.expire("a", 10))  # 다시 부르면 지금부터 새로 센다
        self.clock.advance(9)
        self.assertEqual((self.r.get("a"), self.r.ttl("a")), (1, 1))

    def test_expire_missing_key(self):
        self.assertFalse(self.r.expire("없음", 5))
        self.assertFalse(self.r.exists("없음"))  # 없는 키에 expire 를 해도 키가 생기면 안 된다

    def test_set_without_ttl_clears_expire(self):
        # 실제 Redis SET 규칙: ttl 없이 덮어쓰면 만료가 사라진다
        self.r.set("a", 1, ttl=5)
        self.r.set("a", 2)
        self.clock.advance(100)
        self.assertEqual((self.r.get("a"), self.r.ttl("a")), (2, -1))

    def test_set_with_new_ttl_replaces_old(self):
        self.r.set("a", 1, ttl=100)
        self.r.set("a", 2, ttl=3)
        self.assertEqual(self.r.ttl("a"), 3)

    def test_fractional_ttl(self):
        # 소수 ttl 도 받는다 (최소 1ms). 남은 시간은 올림이라 0.1초 → 1
        self.r.set("a", 1, ttl=0.1)
        self.assertEqual(self.r.ttl("a"), 1)
        self.clock.advance(0.1)
        self.assertEqual(self.r.get("a"), None)
        self.r.set("b", 1, ttl=0.001)  # 최솟값은 받는다
        self.assertTrue(self.r.exists("b"))

    def test_huge_ttl_accepted(self):
        self.r.set("a", 1, ttl=10**12)
        self.assertEqual(self.r.ttl("a"), 10**12)


class SweepTest(StoreTestCase):
    def test_sweep_removes_only_expired(self):
        self.r.set("forever", 1)
        self.r.set("long", 1, ttl=100)
        for i in range(5):
            self.r.set(f"short{i}", i, ttl=1)
        self.clock.advance(2)
        self.assertEqual(len(self.r), 7)  # 아무도 안 읽었으니 아직 메모리에 있다
        self.assertEqual(self.r.sweep(), 5)
        self.assertEqual((sorted(self.r._data.keys()), self.r._expires.keys()), (["forever", "long"], ["long"]))
        self.assertEqual(self.r.sweep(), 0)  # 두 번째는 지울 것이 없다

    def test_sweep_on_empty(self):
        self.assertEqual(self.r.sweep(), 0)


class InvalidTtlTest(StoreTestCase):
    BAD = [0, -1, 0.0001, -0.5, True, False, "5", None, [], 10**400, float("inf"), float("-inf"), float("nan")]

    def test_set_rejects_bad_ttl_and_keeps_old_value(self):
        self.r.set("a", "원래 값", ttl=50)
        for bad in self.BAD:
            if bad is None:
                continue  # set 에서 ttl=None 은 "만료 없음" 이라 올바른 값
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.r.set("a", "바뀌면 안 됨", ttl=bad)
        self.assertEqual((self.r.get("a"), self.r.ttl("a")), ("원래 값", 50))

    def test_expire_rejects_bad_ttl_and_keeps_old_expire(self):
        self.r.set("a", 1, ttl=50)
        for bad in self.BAD:
            with self.assertRaises(ValueError, msg=repr(bad)):
                self.r.expire("a", bad)
        self.assertEqual(self.r.ttl("a"), 50)

    def test_non_string_key_raises_type_error(self):
        # 키 검사는 해시 테이블이 한다 (문자열만)
        for call in (lambda: self.r.set(1, "x"), lambda: self.r.get(None), lambda: self.r.delete(b"a")):
            with self.assertRaises(TypeError):
                call()


class ConcurrencyTest(unittest.TestCase):
    """실제 시계 + 실제 스레드. 락이 없으면 리사이즈 도중 다른 스레드의 set 이 사라질 수 있다"""

    def test_concurrent_sets_keep_every_key(self):
        r = MiniRedis()
        threads = [threading.Thread(target=lambda t=t: [r.set(f"t{t}:{i}", i) for i in range(500)]) for t in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(r), 8 * 500)
        self.assertTrue(all(r.get(f"t{t}:{i}") == i for t in range(8) for i in range(500)))

    def test_concurrent_set_delete_sweep(self):
        # 같은 키들에 저장 · 삭제를 동시에 하며 sweep 도 계속 돈다 → 예외 없이 끝나고 개수가 실제 키와 맞아야 한다
        r = MiniRedis()
        errors = []

        def worker(t):
            try:
                for i in range(300):
                    key = f"k{i % 50}"
                    r.set(key, t, ttl=60) if i % 3 else r.delete(key)
                    r.sweep()
            except Exception as e:  # 스레드 안의 예외는 테스트로 전해지지 않으므로 모아 둔다
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(r), sum(r.exists(f"k{i}") for i in range(50)))


if __name__ == "__main__":
    unittest.main()
