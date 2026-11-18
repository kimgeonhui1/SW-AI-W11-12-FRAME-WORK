# [test_bptree.py] B+ 트리: 찾기 · 넣기 · 분할이 맞는지, 그리고 매번 B+ 트리의 규칙(균형 · 정렬 · 안내 키)이 지켜지는지

import random
import unittest

from minidb.bptree import BPlusTree, _Internal, _Leaf


def check_invariants(test, tree):
    """B+ 트리 규칙을 전부 확인한다. 깨진 곳이 있으면 테스트 실패"""
    leaves = []

    def walk(node, depth, low, high):
        # low <= 이 노드 아래의 모든 키 < high (부모의 안내 키가 정한 범위)
        test.assertLessEqual(len(node.keys), tree.max_keys)
        test.assertEqual(node.keys, sorted(node.keys))
        for k in node.keys:
            test.assertTrue((low is None or low <= k) and (high is None or k < high), (k, low, high))
        if isinstance(node, _Leaf):
            test.assertEqual(len(node.keys), len(node.values))
            leaves.append((depth, node))
            return
        test.assertIsInstance(node, _Internal)
        test.assertEqual(len(node.children), len(node.keys) + 1)
        bounds = [low] + node.keys + [high]
        for i, child in enumerate(node.children):
            walk(child, depth + 1, bounds[i], bounds[i + 1])

    walk(tree.root, 1, None, None)
    test.assertEqual({d for d, _ in leaves}, {tree.height})  # 모든 잎의 깊이가 같다 = 높이
    for (_, left), (_, right) in zip(leaves, leaves[1:]):
        test.assertIs(left.next, right)  # 잎 연결이 왼쪽 → 오른쪽 순서와 같다
    test.assertIsNone(leaves[-1][1].next)
    if len(leaves) > 1:  # 루트가 아닌 잎은 비어 있지 않다 (나눌 때 반씩 나눈다)
        test.assertTrue(all(node.keys for _, node in leaves))
    keys = [k for k, _ in tree.items()]
    test.assertEqual(keys, sorted(keys))
    test.assertEqual(len(keys), len(tree))


class BPlusTreeTest(unittest.TestCase):
    def test_empty(self):
        tree = BPlusTree(order=4)
        self.assertEqual((len(tree), tree.get(1), tree.get(1, "없음"), list(tree.items()), tree.height), (0, None, "없음", [], 1))

    def test_sequential_inserts_split_and_grow(self):
        # id처럼 1, 2, 3 ... 순서로 넣으면 항상 맨 오른쪽 잎에 들어가며 나뉜다
        tree = BPlusTree(order=4)
        for k in range(1, 1001):
            tree.insert(k, k * 10)
        check_invariants(self, tree)
        self.assertEqual([tree.get(k) for k in (1, 500, 1000)], [10, 5000, 10000])
        self.assertIsNone(tree.get(0))
        self.assertIsNone(tree.get(1001))
        self.assertGreater(tree.height, 3)

    def test_random_order_inserts(self):
        keys = list(range(5000))
        random.Random(1).shuffle(keys)
        for order in (3, 4, 5, 64):  # 3: 가장 작은 order (나눌 때 가장 자주 나뉜다)
            tree = BPlusTree(order=order)
            for k in keys:
                tree.insert(k, -k)
            check_invariants(self, tree)
            self.assertTrue(all(tree.get(k) == -k for k in range(5000)), order)
            self.assertEqual([k for k, _ in tree.items()], list(range(5000)))

    def test_small_example_from_study(self):
        # 공부할 때 그린 그림 그대로: order 4에 10 ~ 100 → 루트 [70], 그 아래 [30|50] · [90]
        tree = BPlusTree(order=4)
        for k in range(10, 101, 10):
            tree.insert(k, k)
        self.assertEqual(tree.root.keys, [70])
        self.assertEqual([c.keys for c in tree.root.children], [[30, 50], [90]])
        self.assertEqual(tree.height, 3)

    def test_duplicate_key_rejected_and_tree_unchanged(self):
        tree = BPlusTree(order=4)
        for k in range(20):
            tree.insert(k, k)
        with self.assertRaises(KeyError):
            tree.insert(7, "다른 값")
        self.assertEqual((len(tree), tree.get(7)), (20, 7))
        check_invariants(self, tree)

    def test_height_stays_low(self):
        # order 64면 10만 개도 높이 3이면 충분하다 (64 * 32 * 32 이상)
        tree = BPlusTree(order=64)
        for k in range(100_000):
            tree.insert(k, k)
        self.assertLessEqual(tree.height, 4)
        self.assertEqual(tree.get(99_999), 99_999)

    def test_bad_order(self):
        for order in (2, 0, -1, 2.5, True, "64"):
            with self.assertRaises(ValueError, msg=repr(order)):
                BPlusTree(order=order)


if __name__ == "__main__":
    unittest.main()
