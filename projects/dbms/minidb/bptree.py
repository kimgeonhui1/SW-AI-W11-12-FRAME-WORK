# [bptree.py] 메모리 기반 B+ 트리 — 키(id) → 값(그 행이 파일에서 시작하는 바이트 위치, offset)
#
# ■ 모양 (order = 4 예시: 노드 하나에 키 최대 3개)
#                 [ 30 | 60 ]                    ← 내부 노드: 길 안내용 키만 (값 없음). 자식은 키 수 + 1개
#              /       |       \
#     [10|20] → [30|40|50] → [60|70|80]          ← 잎: 키 + 값. 옆 잎과 연결(next)되어 키 순서대로 훑을 수 있다
#
#   - 값은 잎에만 있다. 내부 노드의 keys[i]는 "children[i+1] 아래에서 가장 작은 키"다
#     → key < keys[i]면 왼쪽, key >= keys[i]면 오른쪽으로 내려간다 (bisect_right)
#   - 모든 잎의 깊이가 같다(항상 균형). 트리는 아래가 아니라 위로 자란다 (루트가 넘치면 새 루트를 만든다)
#
# ■ 노드에 키를 여러 개 넣는 이유: 높이를 낮추려고. order 64면 높이 3에 약 26만 개, 4에 약 1,700만 개
#   (이진 트리면 100만 개에 약 20단계). 실제 DBMS는 노드 하나 = 디스크 페이지 하나라서 "몇 번 내려가나 = 디스크를 몇 번 읽나"다.
#   이 과제는 메모리 기반(과제 조건)이라 디스크 이점은 없지만 구조와 O(log n)은 같다
#
# ■ 넘치면 나눈다(split)
#   잎:       반으로 나누고 오른쪽 잎의 첫 키를 부모에 "복사"해 올린다 (그 키의 값은 잎에 그대로 있어야 하므로)
#   내부 노드: 반으로 나누고 가운데 키를 부모로 "옮긴다" (내부 키는 안내판이라 두 곳에 있을 필요가 없다)
#
# ■ 삭제는 아직 없다 (과제의 SQL은 INSERT / SELECT뿐. DELETE는 추가 구현 때)

from bisect import bisect_left, bisect_right


class _Leaf:
    __slots__ = ("keys", "values", "next")

    def __init__(self, keys, values, next_leaf=None):
        self.keys = keys
        self.values = values
        self.next = next_leaf  # 오른쪽 이웃 잎 (마지막 잎이면 None)


class _Internal:
    __slots__ = ("keys", "children")

    def __init__(self, keys, children):
        self.keys = keys
        self.children = children


class BPlusTree:
    def __init__(self, order=64):
        # order: 노드 하나의 자식 수 최대값. 키는 최대 order - 1개. 3보다 작으면 나눌 때 빈 노드가 생긴다
        if isinstance(order, bool) or not isinstance(order, int) or order < 3:
            raise ValueError("order는 3 이상의 정수여야 합니다")
        self.max_keys = order - 1
        self.root = _Leaf([], [])
        self.height = 1  # 루트부터 잎까지의 단계 수 (잎 하나뿐이면 1)
        self._size = 0

    def __len__(self):
        return self._size

    # key의 값. 없으면 default. 루트에서 잎까지 height번만 내려간다 (O(log n))
    def get(self, key, default=None):
        node = self.root
        while isinstance(node, _Internal):
            node = node.children[bisect_right(node.keys, key)]
        i = bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:
            return node.values[i]
        return default

    # 새 키 넣기. 이미 있는 키면 KeyError (id는 겹치면 안 된다). 실패하면 트리는 그대로다
    def insert(self, key, value):
        split = self._insert(self.root, key, value)
        if split is not None:  # 루트가 나뉘었다 → 새 루트를 만들어 트리가 한 단계 자란다
            separator, right = split
            self.root = _Internal([separator], [self.root, right])
            self.height += 1
        self._size += 1

    # node 아래에 넣는다. node가 넘쳐 나뉘었으면 (부모에 올릴 키, 새로 생긴 오른쪽 노드), 아니면 None
    def _insert(self, node, key, value):
        if isinstance(node, _Leaf):
            i = bisect_left(node.keys, key)
            if i < len(node.keys) and node.keys[i] == key:
                raise KeyError(f"이미 있는 키입니다: {key!r}")  # 아무것도 바꾸기 전에 확인한다
            node.keys.insert(i, key)
            node.values.insert(i, value)
            if len(node.keys) <= self.max_keys:
                return None
            mid = len(node.keys) // 2
            right = _Leaf(node.keys[mid:], node.values[mid:], node.next)
            del node.keys[mid:]
            del node.values[mid:]
            node.next = right  # 잎 연결 유지: 왼쪽 → 새 오른쪽 → 원래 다음 잎
            return right.keys[0], right  # 복사해서 올린다 (값은 잎에 남는다)

        i = bisect_right(node.keys, key)
        split = self._insert(node.children[i], key, value)
        if split is None:
            return None
        separator, right_child = split
        node.keys.insert(i, separator)
        node.children.insert(i + 1, right_child)
        if len(node.keys) <= self.max_keys:
            return None
        mid = len(node.keys) // 2
        up = node.keys[mid]
        right = _Internal(node.keys[mid + 1:], node.children[mid + 1:])
        del node.keys[mid:]  # 가운데 키는 부모로 옮긴다 (왼쪽 · 오른쪽 어디에도 남기지 않는다)
        del node.children[mid + 1:]
        return up, right

    # (키, 값)을 키 순서대로. 맨 왼쪽 잎까지 내려간 뒤 잎 연결(next)만 따라간다 (범위 검색의 바탕)
    def items(self):
        node = self.root
        while isinstance(node, _Internal):
            node = node.children[0]
        while node is not None:
            yield from zip(node.keys, node.values)
            node = node.next
