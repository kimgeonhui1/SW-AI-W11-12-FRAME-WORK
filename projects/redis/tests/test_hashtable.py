# [test_hashtable.py] HashTable 단위 테스트 — 실행: projects/redis 에서 python -m unittest
#
# 설계 문서 10장의 계획대로 확인한다
#   기본 동작 : 저장 · 조회 · 덮어쓰기 · 삭제 · len · in
#   충돌      : 같은 칸에 들어가는 키를 일부러 골라 체이닝이 각 값을 지키는지
#   리사이즈  : 부하율 0.75 "초과" 에서만 2배, 리사이즈 뒤에도 모든 키가 찾아지는지
#   무작위    : 저장 · 삭제를 섞은 2,000번을 파이썬 dict 와 대조 (dict 는 정답 확인용으로 테스트에서만 쓴다)
#   경계      : 한글 · 빈 문자열 · 반쪽 문자 키, 문자열이 아닌 키, 잘못된 capacity, FNV-1a 표준 값
#
# 칸 수는 capacity() 로 본다. 충돌한 칸의 길이(t._buckets)만 내부 값을 테스트에서 들여다본다

import random
import unittest

from mini_redis.hashtable import HashTable, fnv1a


def colliding_keys(capacity, count):
    """칸이 capacity 개일 때 같은 칸에 들어가는 서로 다른 키 count 개를 찾는다"""
    groups = [[] for _ in range(capacity)]
    i = 0
    while True:
        key = f"k{i}"
        group = groups[fnv1a(key) % capacity]
        group.append(key)
        if len(group) == count:
            return group
        i += 1


class HashTableBasicTest(unittest.TestCase):
    def test_set_get_len(self):
        t = HashTable()
        t.set("user:1", "Nameisme")
        t.set("user:2", {"lv": 200})
        self.assertEqual((t.get("user:1"), t.get("user:2"), len(t)), ("Nameisme", {"lv": 200}, 2))

    def test_overwrite_keeps_size(self):
        # 같은 키 → 값만 바뀌고 항목 수는 그대로 (설계 5-1 의 6단계)
        t = HashTable()
        t.set("a", 1)
        t.set("a", 2)
        self.assertEqual((t.get("a"), len(t)), (2, 1))

    def test_missing_key_returns_default(self):
        t = HashTable()
        self.assertEqual((t.get("없음"), t.get("없음", "기본")), (None, "기본"))

    def test_none_value_is_found_by_in(self):
        # None 으로 저장한 키는 get 으로는 "없음" 과 구별이 안 되지만 in 으로는 구별된다
        t = HashTable()
        t.set("a", None)
        self.assertEqual(("a" in t, "b" in t, len(t)), (True, False, 1))

    def test_delete(self):
        t = HashTable()
        t.set("a", 1)
        self.assertEqual((t.delete("a"), t.delete("a"), "a" in t, len(t)), (True, False, False, 0))

    def test_delete_missing_on_empty(self):
        self.assertFalse(HashTable().delete("x"))


class HashTableCollisionTest(unittest.TestCase):
    def test_colliding_keys_keep_own_values(self):
        # 같은 칸의 세 키 → 각자 값을 지키고, 가운데를 지워도 앞뒤가 남아야 한다
        t = HashTable(capacity=64)
        k1, k2, k3 = colliding_keys(64, 3)
        for k in (k1, k2, k3):
            t.set(k, k.upper())
        self.assertEqual(len(t._buckets[t._index(k1)]), 3)  # 정말 한 칸에 줄 섰는지
        t.delete(k2)
        t.set(k3, "덮어씀")
        self.assertEqual((t.get(k1), t.get(k2), t.get(k3), len(t)), (k1.upper(), None, "덮어씀", 2))

    def test_collisions_survive_resize(self):
        # 충돌한 키들도 리사이즈 뒤 새 칸에서 그대로 찾아져야 한다
        t = HashTable(capacity=64)
        group = colliding_keys(64, 4)
        for k in group:
            t.set(k, k)
        for i in range(100):  # 64 × 0.75 = 48 개를 넘겨 리사이즈를 일으킨다
            t.set(f"extra{i}", i)
        self.assertGreater(t.capacity(), 64)
        self.assertTrue(all(t.get(k) == k for k in group))
        self.assertEqual(len(t), 104)


class HashTableResizeTest(unittest.TestCase):
    def test_boundary_is_strictly_greater_than_load_factor(self):
        # 6 / 8 = 0.75 → 그대로 8칸, 7 / 8 > 0.75 가 되는 순간 16칸 (기준이 ">" 임을 확인)
        t = HashTable(capacity=8)
        for i in range(6):
            t.set(f"k{i}", i)
        self.assertEqual(t.capacity(), 8)
        t.set("k6", 6)
        self.assertEqual(t.capacity(), 16)

    def test_overwrite_does_not_resize(self):
        # 덮어쓰기는 항목 수가 늘지 않으므로 리사이즈가 일어나면 안 된다
        t = HashTable(capacity=8)
        for i in range(6):
            t.set(f"k{i}", i)
        for i in range(6):
            t.set(f"k{i}", -i)
        self.assertEqual(t.capacity(), 8)

    def test_capacity_one_resizes_on_first_insert(self):
        # 최소 칸 수 1 → 첫 항목에서 부하율 1.0 > 0.75 → 바로 2칸
        t = HashTable(capacity=1)
        t.set("a", 1)
        self.assertEqual((t.capacity(), t.get("a")), (2, 1))

    def test_many_items_keep_load_factor_and_values(self):
        t = HashTable()
        for i in range(1000):
            t.set(f"key{i}", i)
        self.assertLessEqual(len(t) / t.capacity(), 0.75)
        self.assertTrue(all(t.get(f"key{i}") == i for i in range(1000)))

    def test_shrink_is_not_done(self):
        # 설계 4장: 지워도 칸 수는 줄이지 않는다
        t = HashTable()
        for i in range(100):
            t.set(str(i), i)
        grown = t.capacity()
        for i in range(100):
            t.delete(str(i))
        self.assertEqual((len(t), t.capacity()), (0, grown))


class HashTableRandomTest(unittest.TestCase):
    def test_random_operations_match_dict(self):
        # 저장 · 덮어쓰기 · 삭제 · 조회를 무작위로 2,000번 섞어 dict(정답)와 매번 비교한다.
        # 키 종류를 300개로 좁혀 같은 키에 대한 덮어쓰기 · 삭제가 자주 일어나게 한다
        rng = random.Random(42)  # 시드 고정 → 실패해도 같은 순서로 다시 재현된다
        t, expected = HashTable(capacity=2), {}
        for step in range(2000):
            key = f"key{rng.randrange(300)}"
            op = rng.random()
            if op < 0.5:
                t.set(key, step)
                expected[key] = step
            elif op < 0.8:
                self.assertEqual(t.delete(key), expected.pop(key, None) is not None, key)
            else:
                self.assertEqual(t.get(key, "없음"), expected.get(key, "없음"), key)
            self.assertEqual(len(t), len(expected))
        self.assertEqual(sorted(t.keys()), sorted(expected))


class HashTableEdgeTest(unittest.TestCase):
    def test_unicode_empty_and_slash_keys(self):
        t = HashTable()
        for k in ["메이플", "char:a/b", "", "😀"]:
            t.set(k, k)
        self.assertEqual(sorted(t.keys()), sorted(["메이플", "char:a/b", "", "😀"]))
        self.assertEqual(t.get(""), "")

    def test_lone_surrogate_key(self):
        # 짝 없는 반쪽 문자도 파이썬 str 이다. 그냥 utf-8 로 바꾸면 오류라 surrogatepass 로 해시한다
        t = HashTable()
        t.set("\ud800", 1)
        self.assertEqual((t.get("\ud800"), "\ud800" in t, t.delete("\ud800")), (1, True, True))

    def test_keys_returns_copy(self):
        # keys() 는 새 리스트라 돌면서 지워도(리사이즈와 무관하게) 빠지는 키가 없어야 한다
        t = HashTable()
        for i in range(20):
            t.set(str(i), i)
        for k in t.keys():
            t.delete(k)
        self.assertEqual((len(t), t.keys()), (0, []))

    def test_non_string_key_raises_type_error(self):
        t = HashTable()
        for bad in [123, None, b"bytes", ("a",)]:
            for call in (lambda: t.set(bad, 1), lambda: t.get(bad), lambda: t.delete(bad), lambda: bad in t):
                with self.assertRaises(TypeError, msg=repr(bad)):
                    call()
        self.assertEqual(len(t), 0)  # 실패한 set 이 항목을 남기면 안 된다

    def test_invalid_capacity(self):
        for bad in [0, -1, 1.5, "8", True, None]:
            with self.assertRaises(ValueError, msg=repr(bad)):
                HashTable(capacity=bad)

    def test_fnv1a_standard_values(self):
        # FNV-1a 64비트 표준 테스트 값 — 실행할 때마다 같아야 한다 (파이썬 hash() 와 다른 점)
        self.assertEqual((fnv1a(""), fnv1a("a"), fnv1a("foobar")), (0xCBF29CE484222325, 0xAF63DC4C8601EC8C, 0x85944171F73967E8))


if __name__ == "__main__":
    unittest.main()
