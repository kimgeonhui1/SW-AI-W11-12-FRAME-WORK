# [test_hashtable.py] HashTable 단위 테스트 — 실행: projects/redis 에서 python -m unittest

import unittest

from mini_redis.hashtable import HashTable, fnv1a


def colliding_keys(capacity, count=2):
    """같은 칸(fnv1a % capacity)에 들어가는 서로 다른 키 count개를 찾는다"""
    groups = {}
    i = 0
    while True:
        key = f"k{i}"
        group = groups.setdefault(fnv1a(key) % capacity, [])
        group.append(key)
        if len(group) == count:
            return group
        i += 1


class HashTableTest(unittest.TestCase):
    def test_set_get(self):
        t = HashTable()
        t.set("a", 1)
        t.set("b", {"lv": 200})
        self.assertEqual((t.get("a"), t.get("b"), len(t)), (1, {"lv": 200}, 2))

    def test_overwrite_keeps_size(self):
        t = HashTable()
        t.set("a", 1)
        t.set("a", 2)  # 같은 키 → 값만 바뀌고 개수는 그대로
        self.assertEqual((t.get("a"), len(t)), (2, 1))

    def test_missing_key_returns_default(self):
        t = HashTable()
        self.assertEqual((t.get("없음"), t.get("없음", "기본")), (None, "기본"))

    def test_none_value_is_distinguishable(self):
        t = HashTable()
        t.set("a", None)
        self.assertEqual(("a" in t, "b" in t), (True, False))

    def test_delete(self):
        t = HashTable()
        t.set("a", 1)
        self.assertEqual((t.delete("a"), t.delete("a"), "a" in t, len(t)), (True, False, False, 0))

    def test_collision_chaining(self):
        # 같은 칸에 들어가는 두 키도 각자 값을 지키고, 하나를 지워도 다른 하나는 남아야 한다
        t = HashTable(capacity=64)
        k1, k2 = colliding_keys(64)
        t.set(k1, "첫째")
        t.set(k2, "둘째")
        self.assertEqual((t.get(k1), t.get(k2)), ("첫째", "둘째"))
        t.delete(k1)
        self.assertEqual((t.get(k1), t.get(k2), len(t)), (None, "둘째", 1))

    def test_collision_swap_delete_overwrite_then_resize(self):
        # 같은 칸에 3개 → 첫 항목 삭제(마지막 항목이 그 자리로 옮겨짐) → 옮겨진 항목 덮어쓰기 → 리사이즈 후에도 정확해야 한다 (리뷰 반영)
        t = HashTable(capacity=64)
        k1, k2, k3 = colliding_keys(64, count=3)
        for k in (k1, k2, k3):
            t.set(k, k)
        t.delete(k1)
        t.set(k3, "덮어씀")
        self.assertEqual((len(t), t.get(k1), t.get(k2), t.get(k3)), (2, None, k2, "덮어씀"))
        for i in range(100):  # 리사이즈를 일으킨다 (64칸 × 0.75 = 48개 초과)
            t.set(f"extra{i}", i)
        self.assertGreater(t.capacity(), 64)
        self.assertEqual((len(t), t.get(k1), t.get(k2), t.get(k3)), (102, None, k2, "덮어씀"))

    def test_resize_keeps_all_items(self):
        t = HashTable()
        for i in range(1000):
            t.set(f"key{i}", i)
        # 칸이 늘어났고, 부하율 0.75 이하를 지키며, 모든 값이 새 칸에서도 찾아진다
        self.assertGreater(t.capacity(), 8)
        self.assertLessEqual(len(t) / t.capacity(), 0.75)
        self.assertTrue(all(t.get(f"key{i}") == i for i in range(1000)))

    def test_keys_unicode_and_empty_key(self):
        t = HashTable()
        for k in ["메이플", "char:a/b", ""]:
            t.set(k, 1)
        self.assertEqual(sorted(t.keys()), sorted(["메이플", "char:a/b", ""]))

    def test_delete_while_iterating_keys(self):
        # keys()는 복사본이라 돌면서 지워도 빠지는 키가 없어야 한다
        t = HashTable()
        for i in range(20):
            t.set(str(i), i)
        for k in t.keys():
            t.delete(k)
        self.assertEqual(len(t), 0)

    def test_invalid_capacity(self):
        for bad in [0, -1, 1.5, "8", True]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                HashTable(capacity=bad)

    def test_non_string_key_raises_type_error(self):
        t = HashTable()
        for bad in [123, None, b"bytes"]:
            with self.assertRaises(TypeError, msg=repr(bad)):
                t.set(bad, 1)
            with self.assertRaises(TypeError, msg=repr(bad)):
                bad in t
            with self.assertRaises(TypeError, msg=repr(bad)):
                t.get(bad)
            with self.assertRaises(TypeError, msg=repr(bad)):
                t.delete(bad)

    def test_lone_surrogate_key(self):
        # 짝 없는 반쪽 문자도 파이썬 str이므로 저장·조회·삭제가 되어야 한다 (리뷰 반영)
        t = HashTable()
        t.set("\ud800", 1)
        self.assertEqual((t.get("\ud800"), t.delete("\ud800")), (1, True))

    def test_resize_boundary_exactly_at_load_factor(self):
        # 부하율이 정확히 0.75(6/8)면 그대로, 넘는 순간(7/8)에 2배 → 기준이 ">"임을 확인 (리뷰 반영)
        t = HashTable(capacity=8)
        for i in range(6):
            t.set(f"k{i}", i)
        self.assertEqual(t.capacity(), 8)
        t.set("k6", 6)
        self.assertEqual(t.capacity(), 16)

    def test_capacity_one_resizes_on_first_insert(self):
        # 최소 칸 수 1에서는 첫 항목만 넣어도 부하율 1.0 > 0.75 → 바로 2칸으로 (경계값)
        t = HashTable(capacity=1)
        t.set("a", 1)
        self.assertEqual((t.capacity(), t.get("a")), (2, 1))

    def test_fnv1a_is_deterministic(self):
        # 실행할 때마다 같은 값이어야 한다 (파이썬 hash()와 다른 점). FNV-1a 표준 테스트 값
        self.assertEqual(fnv1a("a"), 0xAF63DC4C8601EC8C)


if __name__ == "__main__":
    unittest.main()
