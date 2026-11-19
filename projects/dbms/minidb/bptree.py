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
# ■ 맨 오른쪽에 덧붙일 때는 반반이 아니라 "왼쪽을 꽉 채우고" 나눈다
#   id는 1, 2, 3 ... 으로 늘기만 해서, 반반으로 나누면 왼쪽 노드에는 다시는 키가 오지 않아 모든 노드가 절반만 찬 채로 남았다
#   (100만 행에서 잎 약 31,000개). 트리의 맨 오른쪽 노드 끝에 키가 붙어 넘친 경우에만, 왼쪽은 꽉 찬 채로 두고
#   새 키만 오른쪽으로 보낸다 → 노드가 거의 꽉 차서 노드 수가 약 절반이 된다. 실제 DB도 순서대로 늘어나는 키에 같은 최적화를 한다
#   그 밖의 경우(중간에 끼어든 키)는 원래대로 반반 → 양쪽 모두 다음 키가 들어올 빈자리가 있다
#
# ■ 삭제(DELETE, 추가 구현): 잎에서 키와 값만 뺀다. 노드를 합치거나 이웃에게서 빌려 오는 재균형은 하지 않는다
#   - 잎이 반 아래로 줄거나 비어도, 내부 노드의 안내 키는 여전히 "왼쪽 < 경계 ≤ 오른쪽"을 지키므로 검색 결과는 맞다
#   - id는 늘기만 하고 지운 id는 다시 들어오지 않아서, 빈자리가 채워지지 않을 뿐 트리가 틀려지지는 않는다
#   - 실제 DB도 지울 때 바로 합치지 않는 경우가 많다 (PostgreSQL B-tree는 완전히 빈 페이지만 나중에 정리한다)

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

    # 이미 오름차순(중복 없음)인 키로 트리를 한 번에 만든다 (bulk load) — 프로그램을 다시 켤 때 인덱스 재구성용
    # 하나씩 insert하면 키마다 루트부터 내려가고 분할을 반복하지만, 이렇게 아래(잎)부터 위로 쌓으면 각 노드를 한 번씩만 만든다 (O(n)).
    # 실제 DB도 인덱스를 처음 만들 때(CREATE INDEX) 정렬 후 이렇게 쌓는다
    #   1) 잎: 키를 max_keys개씩 잘라 꽉 찬 잎을 만들고 옆으로 연결한다
    #   2) 위층: 아래 노드를 order개씩 묶어 내부 노드를 만든다. 안내 키 = 둘째 자식부터 각 자식 아래의 가장 작은 키
    #   3) 노드가 하나 남을 때까지 반복 → 그것이 루트
    @classmethod
    def bulk_load(cls, keys, values, order=64):
        tree = cls(order)
        if len(keys) != len(values):
            raise ValueError("키와 값의 개수가 다릅니다")
        if any(a >= b for a, b in zip(keys, keys[1:])):
            raise ValueError("키가 오름차순이 아니거나 겹칩니다")
        if not keys:
            return tree
        step = tree.max_keys
        level = [_Leaf(keys[i:i + step], values[i:i + step]) for i in range(0, len(keys), step)]
        for left, right in zip(level, level[1:]):
            left.next = right
        lows = [leaf.keys[0] for leaf in level]  # 각 노드 아래에서 가장 작은 키
        height = 1
        while len(level) > 1:
            sizes = [order] * (len(level) // order)
            if len(level) % order:
                sizes.append(len(level) % order)
            if sizes[-1] == 1:  # 자식 1개짜리 내부 노드(안내 키 0개)는 만들지 않는다 → 앞 노드에서 하나 가져온다
                sizes[-2] -= 1
                sizes[-1] = 2
            parents, parent_lows, start = [], [], 0
            for size in sizes:
                parents.append(_Internal(lows[start + 1:start + size], level[start:start + size]))
                parent_lows.append(lows[start])
                start += size
            level, lows = parents, parent_lows
            height += 1
        tree.root, tree.height, tree._size = level[0], height, len(keys)
        return tree

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
        split = self._insert(self.root, key, value, True)
        if split is not None:  # 루트가 나뉘었다 → 새 루트를 만들어 트리가 한 단계 자란다
            separator, right = split
            self.root = _Internal([separator], [self.root, right])
            self.height += 1
        self._size += 1

    # node 아래에 넣는다. node가 넘쳐 나뉘었으면 (부모에 올릴 키, 새로 생긴 오른쪽 노드), 아니면 None
    # rightmost: node가 트리의 맨 오른쪽 가장자리에 있는가 (루트부터 늘 마지막 자식으로만 내려온 노드)
    def _insert(self, node, key, value, rightmost):
        if isinstance(node, _Leaf):
            i = bisect_left(node.keys, key)
            if i < len(node.keys) and node.keys[i] == key:
                raise KeyError(f"이미 있는 키입니다: {key!r}")  # 아무것도 바꾸기 전에 확인한다
            node.keys.insert(i, key)
            node.values.insert(i, value)
            if len(node.keys) <= self.max_keys:
                return None
            if rightmost and i == len(node.keys) - 1:  # 트리 전체에서 가장 큰 키가 맨 끝에 붙었다
                mid = self.max_keys  # 왼쪽은 꽉 찬 채로(max_keys개), 오른쪽은 새 키 하나
            else:
                mid = len(node.keys) // 2
            right = _Leaf(node.keys[mid:], node.values[mid:], node.next)
            del node.keys[mid:]
            del node.values[mid:]
            node.next = right  # 잎 연결 유지: 왼쪽 → 새 오른쪽 → 원래 다음 잎
            return right.keys[0], right  # 복사해서 올린다 (값은 잎에 남는다)

        i = bisect_right(node.keys, key)
        split = self._insert(node.children[i], key, value, rightmost and i == len(node.children) - 1)
        if split is None:
            return None
        separator, right_child = split
        node.keys.insert(i, separator)
        node.children.insert(i + 1, right_child)
        if len(node.keys) <= self.max_keys:
            return None
        if rightmost and i == len(node.keys) - 1:  # 맨 오른쪽 자식이 나뉘어 새 키가 맨 끝에 붙었다
            mid = self.max_keys - 1  # 왼쪽은 자식 order - 1개로 채우고, 오른쪽은 키 1개 · 자식 2개 (키 없는 내부 노드를 만들지 않게)
        else:
            mid = len(node.keys) // 2
        up = node.keys[mid]
        right = _Internal(node.keys[mid + 1:], node.children[mid + 1:])
        del node.keys[mid:]  # 가운데 키는 부모로 옮긴다 (왼쪽 · 오른쪽 어디에도 남기지 않는다)
        del node.children[mid + 1:]
        return up, right

    # key 지우기 → 있어서 지웠으면 True, 없으면 False. get과 같은 길로 잎까지 내려가 그 잎에서만 뺀다 (재균형 없음, 맨 위 설명)
    def delete(self, key):
        node = self.root
        while isinstance(node, _Internal):
            node = node.children[bisect_right(node.keys, key)]
        i = bisect_left(node.keys, key)
        if i == len(node.keys) or node.keys[i] != key:
            return False
        del node.keys[i]
        del node.values[i]
        self._size -= 1
        return True

    # (키, 값)을 키 순서대로. 맨 왼쪽 잎까지 내려간 뒤 잎 연결(next)만 따라간다 (범위 검색의 바탕)
    def items(self):
        node = self.root
        while isinstance(node, _Internal):
            node = node.children[0]
        while node is not None:
            yield from zip(node.keys, node.values)
            node = node.next
