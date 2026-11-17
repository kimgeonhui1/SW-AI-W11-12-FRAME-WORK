# [test_bptree.py] B+ 트리 — 넣을 때마다 규칙(check)을 확인하고, 결과를 파이썬 dict · sorted 와 대조한다
#
# 분할 버그는 "키 하나가 사라짐" 처럼 조용히 나타나므로, 작은 order(3 · 4)로 트리를 깊게 만들어 분할을 많이 일으킨다.

import random
import unittest

from mini_dbms.bptree import BPlusTree


class BPlusTreeTest(unittest.TestCase):
    def fill(self, keys, order=4, append_split=True, check_each=True):
        tree, model = BPlusTree(order, append_split), {}
        for k in keys:
            tree.insert(k, k * 10)
            model[k] = k * 10
            if check_each:
                tree.check()
        return tree, model

    def assert_same(self, tree, model):
        tree.check()
        self.assertEqual(len(tree), len(model))
        self.assertEqual(list(tree.range()), sorted(model.items()))
        for k in list(model)[:200]:
            self.assertEqual(tree.search(k), model[k])

    def test_empty_and_small(self):
        tree = BPlusTree(3)
        tree.check()
        self.assertEqual((len(tree), tree.search(1), list(tree.range()), tree.height()), (0, None, [], 1))
        tree.insert(5, "a")
        self.assertEqual((tree.search(5), tree.search(4, "없음")), ("a", "없음"))

    def test_split_boundaries(self):
        # order 4: 키 4개까지는 잎 하나, 5번째에서 첫 분할 → 높이 2
        tree, model = self.fill(range(1, 5))
        self.assertEqual(tree.height(), 1)
        tree.insert(5, 50)
        tree.check()
        self.assertEqual(tree.height(), 2)

    def test_orders_random_sequential_reverse(self):
        rnd = random.Random(7)
        for order in (3, 4, 5, 64):
            for name, keys in [("무작위", rnd.sample(range(10_000), 600)), ("순서대로", range(600)), ("역순", range(600, 0, -1))]:
                for append_split in (True, False):
                    tree, model = self.fill(keys, order, append_split, check_each=order < 10)
                    self.assert_same(tree, model)

    def test_duplicate_key_rejected(self):
        tree, model = self.fill(range(20))
        self.assertRaises(KeyError, tree.insert, 7, 0)
        self.assert_same(tree, model)  # 실패한 넣기는 아무것도 바꾸지 않는다

    def test_range(self):
        tree, _ = self.fill(range(0, 200, 2), order=4)  # 짝수만
        keys = lambda **kw: [k for k, _ in tree.range(**kw)]  # noqa: E731
        self.assertEqual(keys(lo=10, hi=20), [10, 12, 14, 16, 18, 20])
        self.assertEqual(keys(lo=10, hi=20, include_lo=False, include_hi=False), [12, 14, 16, 18])
        self.assertEqual(keys(lo=11, hi=15), [12, 14])  # 없는 키로 시작 · 끝
        self.assertEqual(keys(hi=4), [0, 2, 4])
        self.assertEqual(keys(lo=195), [196, 198])
        self.assertEqual(keys(lo=500), [])
        self.assertEqual(keys(lo=20, hi=10), [])
        self.assertEqual(keys(lo=9.5, hi=12.5), [10, 12])  # 정수 키에 소수 경계도 된다

    def test_append_split_halves_leaves(self):
        # id 처럼 순서대로 들어오면 오른쪽 치우침 분할은 잎을 꽉 채운다 → 잎 수가 약 절반
        biased, _ = self.fill(range(10_000), order=64, append_split=True, check_each=False)
        normal, _ = self.fill(range(10_000), order=64, append_split=False, check_each=False)
        biased.check()
        normal.check()
        self.assertGreater(biased.stats()["leaf_fill"], 0.95)
        self.assertLess(normal.stats()["leaf_fill"], 0.55)
        self.assertLess(biased.stats()["leaves"], normal.stats()["leaves"] * 0.6)

    def test_bulk_load(self):
        for order in (3, 4, 64):
            for n in (0, 1, 2, order, order + 1, 2 * order + 1, 1000):
                tree = BPlusTree(order)
                keys = list(range(1, n + 1))
                tree.bulk_load(keys, [k * 10 for k in keys])
                self.assert_same(tree, {k: k * 10 for k in keys})
                tree.insert(n + 1, 0)  # 한꺼번에 쌓은 뒤에도 이어서 넣을 수 있다
                tree.check()
        self.assertRaises(ValueError, BPlusTree(4).bulk_load, [1, 3, 2], [0, 0, 0])  # 정렬 안 됨
        self.assertRaises(ValueError, BPlusTree(4).bulk_load, [1, 1], [0, 0])  # 겹침
        full = BPlusTree(4)
        full.insert(1, 1)
        self.assertRaises(ValueError, full.bulk_load, [2], [2])  # 빈 트리에만

    def test_height_is_logarithmic(self):
        tree = BPlusTree(64)
        keys = list(range(100_000))
        tree.bulk_load(keys, keys)
        self.assertEqual(tree.height(), 3)  # 64 × 65 × 65 > 10만

    def test_bad_order(self):
        for bad in (2, 0, "64", 3.5):
            self.assertRaises(ValueError, BPlusTree, bad)


if __name__ == "__main__":
    unittest.main()
