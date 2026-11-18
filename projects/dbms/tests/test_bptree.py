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
        test.assertGreaterEqual(len(node.keys), 1)  # 자식 1개짜리(안내 키 0개) 내부 노드는 쓸모없는 한 층이다
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

    def leaves(self, tree):
        node = tree.root
        while isinstance(node, _Internal):
            node = node.children[0]
        result = []
        while node is not None:
            result.append(node.keys)
            node = node.next
        return result

    def test_sequential_inserts_fill_left_nodes(self):
        # 순서대로 늘어나는 키(id)는 맨 오른쪽에서 나뉠 때 왼쪽을 꽉 채운다 (반반이면 모든 잎이 절반만 찼다)
        # order 4에 10 ~ 100: 반반이었다면 루트 [70], 높이 3 (공부 때 그린 그림) → 이제 높이 2
        tree = BPlusTree(order=4)
        for k in range(10, 101, 10):
            tree.insert(k, k)
        self.assertEqual(tree.root.keys, [40, 70, 100])
        self.assertEqual(self.leaves(tree), [[10, 20, 30], [40, 50, 60], [70, 80, 90], [100]])
        self.assertEqual(tree.height, 2)
        check_invariants(self, tree)

    def test_middle_insert_still_splits_in_half(self):
        # 중간에 끼어든 키로 넘치면 원래대로 반반 (연습 문제 2와 같은 규칙): [5|15|25]에 10 → [5|10] [15|25], 루트 [15]
        tree = BPlusTree(order=4)
        for k in (5, 15, 25, 10):
            tree.insert(k, k)
        self.assertEqual(tree.root.keys, [15])
        self.assertEqual(self.leaves(tree), [[5, 10], [15, 25]])

    def test_sequential_leaves_are_full_at_scale(self):
        # 100만 행 규모의 모양: order 64에 10만 개를 순서대로 → 마지막 잎만 빼고 모두 63개로 꽉 참
        tree = BPlusTree(order=64)
        for k in range(1, 100_001):
            tree.insert(k, k)
        sizes = [len(keys) for keys in self.leaves(tree)]
        self.assertTrue(all(s == 63 for s in sizes[:-1]))
        self.assertEqual(len(sizes), -(-100_000 // 63))  # 올림 나눗셈: 1,588개 (반반이었다면 약 3,125개)
        # 내부 노드도 층마다 마지막(맨 오른쪽) 노드만 빼고 자식이 63개로 찬다
        # (64개가 아닌 이유: 나눌 때 오른쪽 새 내부 노드에도 키를 1개 남겨, 키 없는 내부 노드를 만들지 않으려고)
        level = [tree.root]
        while isinstance(level[0], _Internal):
            self.assertTrue(all(len(n.children) == 63 for n in level[:-1]), [len(n.children) for n in level])
            level = [c for n in level for c in n.children]
        self.assertEqual(tree.height, 3)  # 1,588개 잎 → 25개 → 1개 (반반이었다면 높이 4)
        check_invariants(self, tree)

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

    def test_bulk_load_matches_rules_and_accepts_more_inserts(self):
        # 정렬된 키로 한 번에 만든 트리도 B+ 트리 규칙을 지키고, 그 뒤에 넣는 키(끝에 덧붙이기 · 중간)도 제대로 들어간다
        for order in (3, 4, 5, 64):
            for n in (0, 1, 2, order - 1, order, order + 1, order * order - 1, order * order, order * order + 1, 3000):
                keys = list(range(1, 2 * n + 1, 2))  # 홀수: 사이에 짝수를 끼워 넣을 자리가 있다
                tree = BPlusTree.bulk_load(keys, [k * 10 for k in keys], order=order)
                check_invariants(self, tree)
                self.assertEqual(list(tree.items()), [(k, k * 10) for k in keys], (order, n))
                for k in (0, (n // 2) * 2, 2 * n, 2 * n + 1, 2 * n + 3):  # 맨 앞 · 중간(짝수) · 맨 뒤
                    if tree.get(k) is None:
                        tree.insert(k, -k)
                check_invariants(self, tree)
                self.assertEqual([k for k, _ in tree.items()], sorted(k for k, _ in tree.items()))

    def test_bulk_load_rejects_unsorted_or_duplicate_keys(self):
        for keys in ([2, 1], [1, 1], [1, 3, 2]):
            with self.assertRaises(ValueError, msg=keys):
                BPlusTree.bulk_load(keys, keys, order=4)
        with self.assertRaises(ValueError):
            BPlusTree.bulk_load([1, 2], [1], order=4)

    def test_bad_order(self):
        for order in (2, 0, -1, 2.5, True, "64"):
            with self.assertRaises(ValueError, msg=repr(order)):
                BPlusTree(order=order)


if __name__ == "__main__":
    unittest.main()
