# [bptree.py] 메모리 기반 B+ 트리 — 키(id) → 값(데이터 파일 안의 바이트 위치)
#
#                          [ 40 | 80 ]                    ← 안쪽 노드(_Inner): 키 = 길잡이, 자식 = 키 수 + 1 개
#                  ┌───────────┼────────────┐
#            [10|20|30]    [40|50|60]    [80|90]          ← 잎 노드(_Leaf): (키, 값) 을 정렬해서 저장
#                 └─ next ───▶ └─ next ────▶              ← 잎끼리 오른쪽으로 이어져 있다 → 범위 검색이 빠르다
#
# ■ 규칙 (order = 노드 하나가 가질 수 있는 최대 키 수, 기본 64)
#   - 자식 i 에 있는 키는 모두  keys[i-1] <= 키 < keys[i]   (길잡이 키는 "오른쪽 자식의 가장 작은 키")
#   - 모든 잎은 같은 깊이에 있다 → 어떤 키든 찾는 데 같은 단계 수 = 높이 (100만 개 · order 64 → 높이 4)
#   - 루트가 아닌 노드는 키를 최소 order // 2 개 가진다 (반은 차 있다)
#     예외: 맨 오른쪽 잎 — 아래 "오른쪽 치우침 분할" 때문에 덜 찰 수 있다
#
# ■ 넣기(insert): 잎까지 내려가 정렬 위치에 끼운다. 키가 order 를 넘으면 쪼갠다(분할).
#   잎 분할: 반으로 나누고, 오른쪽 잎의 첫 키를 부모에 "복사" 해서 길잡이로 둔다 (값은 잎에만 있다)
#   안쪽 분할: 가운데 키를 부모로 "올린다" (안쪽 노드에서는 빠진다). 루트가 쪼개지면 새 루트가 생겨 높이 + 1.
#
# ■ 오른쪽 치우침 분할 (append_split, 기본 켬) — id 는 항상 1씩 커지며 들어온다
#   보통 분할은 반반이라 그 뒤로 왼쪽 잎에는 다시 아무것도 안 들어오고, 잎이 영원히 반만 찬다 (메모리 2배).
#   그래서 "맨 오른쪽 잎의 맨 끝에 넣다가 넘친" 경우에는 왼쪽을 꽉 채운 채 두고, 새 키 하나만 새 잎으로 보낸다.
#   (PostgreSQL · SQLite 도 순서대로 늘어나는 키에 같은 방법을 쓴다.) 잎 수가 약 절반이 된다 — bench 에서 측정.
#
# ■ 한꺼번에 쌓기(bulk_load): 이미 정렬된 (키, 값) 을 왼쪽부터 잎에 고르게 채운 뒤 위로 쌓는다. 하나씩 넣기보다 빠르다.
#   엔진이 켜질 때 데이터 파일을 훑어 인덱스를 다시 만드는 데 쓴다 (인덱스는 메모리에만 있으므로).
#
# ■ 삭제는 없다 — SQL 에 DELETE 가 요구사항에 없다 (있으면 노드 합치기 · 빌려 오기가 필요하다).
# ■ 스레드에 안전하지 않다. 엔진의 테이블 락(읽기-쓰기 락)이 감싼다.

from bisect import bisect_left, bisect_right


class _Leaf:
    __slots__ = ("keys", "values", "next")  # 노드가 수만 개라 __dict__ 를 없애 메모리를 줄인다

    def __init__(self, keys=None, values=None, next=None):
        self.keys = keys if keys is not None else []
        self.values = values if values is not None else []
        self.next = next  # 오른쪽 이웃 잎 (맨 오른쪽이면 None)


class _Inner:
    __slots__ = ("keys", "children")

    def __init__(self, keys, children):
        self.keys = keys
        self.children = children


class BPlusTree:
    def __init__(self, order=64, append_split=True):
        if type(order) is not int or order < 3:
            raise ValueError("order 는 3 이상의 정수여야 합니다")  # 2 이하면 분할한 노드가 비어 버린다
        self.order = order
        self.append_split = append_split
        self.root = _Leaf()
        self._size = 0

    def __len__(self):
        return self._size

    # ── 찾기 ──────────────────────────────────────────────────────────

    def _leaf_for(self, key):
        """key 가 있을(들어갈) 잎. 안쪽 노드에서는 bisect_right — 길잡이와 같은 키는 오른쪽 자식에 있으므로"""
        node = self.root
        while type(node) is _Inner:
            node = node.children[bisect_right(node.keys, key)]
        return node

    def search(self, key, default=None):
        """key 의 값. 없으면 default — O(log n): 높이만큼 내려가고, 노드 안에서는 이진 탐색(bisect)"""
        leaf = self._leaf_for(key)
        i = bisect_left(leaf.keys, key)
        if i < len(leaf.keys) and leaf.keys[i] == key:
            return leaf.values[i]
        return default

    def range(self, lo=None, hi=None, include_lo=True, include_hi=True):
        """lo ~ hi 사이의 (키, 값) 을 키 순서로 하나씩 (None = 그쪽 끝 없음)
        lo 가 있는 잎을 한 번 찾은 뒤에는 잎의 next 를 따라 오른쪽으로만 간다 → O(log n + 결과 수)"""
        if lo is None:
            leaf, i = self._leftmost()[0], 0
        else:
            leaf = self._leaf_for(lo)
            i = (bisect_left if include_lo else bisect_right)(leaf.keys, lo)
        while leaf is not None:
            keys = leaf.keys
            while i < len(keys):
                k = keys[i]
                if hi is not None and (k > hi or (k == hi and not include_hi)):
                    return
                yield k, leaf.values[i]
                i += 1
            leaf, i = leaf.next, 0

    def _leftmost(self):
        """맨 왼쪽 잎과 루트에서 거기까지의 단계 수 (잎 하나뿐이면 1)"""
        node, h = self.root, 1
        while type(node) is _Inner:
            node, h = node.children[0], h + 1
        return node, h

    def height(self):
        """루트에서 잎까지의 단계 수"""
        return self._leftmost()[1]

    # ── 넣기 ──────────────────────────────────────────────────────────

    def insert(self, key, value):
        """key → value 등록. 이미 있는 키면 KeyError (id 는 겹치지 않아야 한다)"""
        path = []  # 내려온 길: (안쪽 노드, 내려간 자식 번호) — 분할을 위로 올려 보낼 때 쓴다
        node = self.root
        while type(node) is _Inner:
            i = bisect_right(node.keys, key)
            path.append((node, i))
            node = node.children[i]
        i = bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:
            raise KeyError(f"이미 있는 키입니다: {key!r}")
        node.keys.insert(i, key)
        node.values.insert(i, value)
        self._size += 1
        if len(node.keys) <= self.order:
            return  # 넘치지 않음 — 대부분 여기서 끝난다

        # 잎 분할
        n = len(node.keys)
        if self.append_split and node.next is None and i == n - 1:
            mid = n - 1  # 오른쪽 치우침: 왼쪽은 꽉 찬 채로, 새 키 하나만 새 잎으로
        else:
            mid = n // 2  # 보통: 반반
        right = _Leaf(node.keys[mid:], node.values[mid:], node.next)
        del node.keys[mid:], node.values[mid:]
        node.next = right
        sep = right.keys[0]  # 오른쪽 잎의 첫 키를 부모에 "복사"

        # 부모로 올라가며 길잡이 끼우기 — 부모도 넘치면 다시 분할
        while path:
            parent, ci = path.pop()
            parent.keys.insert(ci, sep)
            parent.children.insert(ci + 1, right)
            if len(parent.keys) <= self.order:
                return
            mid = len(parent.keys) // 2
            sep = parent.keys[mid]  # 가운데 키는 부모로 "올라가고" 이 노드에서는 빠진다
            right = _Inner(parent.keys[mid + 1 :], parent.children[mid + 1 :])
            del parent.keys[mid:], parent.children[mid + 1 :]
            node = parent
        self.root = _Inner([sep], [node, right])  # 루트까지 쪼개졌다 → 새 루트, 높이 + 1

    def bulk_load(self, keys, values):
        """빈 트리에 정렬된 키 · 값을 한꺼번에 쌓는다. keys 는 겹치지 않고 커지는 순서여야 한다
        잎을 왼쪽부터 고르게(모두 반 이상) 채우고, 그 위로 안쪽 노드를 한 층씩 쌓는다 → O(n)"""
        if self._size:
            raise ValueError("bulk_load 는 빈 트리에만 할 수 있습니다")
        if len(keys) != len(values):
            raise ValueError("keys 와 values 의 길이가 다릅니다")
        for a, b in zip(keys, keys[1:]):
            if not a < b:
                raise ValueError(f"키가 커지는 순서가 아닙니다: {a!r} 다음 {b!r}")
        if not keys:
            return
        leaves = [_Leaf(keys[s:e], values[s:e]) for s, e in _even_slices(len(keys), self.order)]
        for a, b in zip(leaves, leaves[1:]):
            a.next = b
        level, firsts = leaves, [leaf.keys[0] for leaf in leaves]  # firsts[i] = level[i] 아래의 가장 작은 키
        while len(level) > 1:
            up, up_firsts = [], []
            for s, e in _even_slices(len(level), self.order + 1):  # 안쪽 노드는 자식을 order + 1 개까지
                up.append(_Inner(firsts[s + 1 : e], level[s:e]))  # 길잡이 = 둘째 자식부터 각 자식의 첫 키
                up_firsts.append(firsts[s])
            level, firsts = up, up_firsts
        self.root = level[0]
        self._size = len(keys)

    # ── 검사 · 통계 (테스트 · 벤치마크용) ─────────────────────────────

    def check(self):
        """B+ 트리의 모든 규칙을 확인한다. 어긋나면 AssertionError (무엇이 어디서)
        테스트가 넣기를 할 때마다 불러, 분할 버그로 키를 잃거나 순서가 꼬이는 것을 바로 잡아낸다."""
        leaves = []
        minimum = self.order // 2

        def walk(node, lo, hi, depth):
            keys = node.keys
            assert all(a < b for a, b in zip(keys, keys[1:])), f"노드 안 키가 정렬돼 있지 않음: {keys[:5]}…"
            assert all((lo is None or lo <= k) and (hi is None or k < hi) for k in keys), f"키가 길잡이 범위 밖: {keys[:5]}… 범위 [{lo}, {hi})"
            assert len(keys) <= self.order, f"키가 order({self.order}) 보다 많음: {len(keys)}"
            if type(node) is _Leaf:
                assert len(node.values) == len(keys), "잎의 키 수와 값 수가 다름"
                leaves.append((node, depth))
                return
            assert len(node.children) == len(keys) + 1, "안쪽 노드의 자식 수가 키 수 + 1 이 아님"
            if node is not self.root:
                assert len(keys) >= minimum, f"안쪽 노드가 반도 안 참: {len(keys)} < {minimum}"
            else:
                assert len(keys) >= 1, "루트가 안쪽 노드인데 키가 없음"
            for i, child in enumerate(node.children):
                walk(child, keys[i - 1] if i else lo, keys[i] if i < len(keys) else hi, depth + 1)

        walk(self.root, None, None, 1)
        depths = {d for _, d in leaves}
        assert len(depths) == 1, f"잎의 깊이가 다름: {sorted(depths)}"
        for leaf, _ in leaves[:-1]:  # 맨 오른쪽 잎은 오른쪽 치우침 분할 때문에 덜 찰 수 있다
            if leaf is not self.root:
                assert len(leaf.keys) >= minimum, f"잎이 반도 안 참: {len(leaf.keys)} < {minimum}"
        node = self._leftmost()[0]  # 잎 연결을 따라가면 왼쪽부터 모든 잎을 정확히 한 번씩
        for leaf, _ in leaves:
            assert node is leaf, "잎 연결(next)이 트리 순서와 다름"
            node = leaf.next
        assert node is None, "맨 오른쪽 잎의 next 가 None 이 아님"
        total = sum(len(leaf.keys) for leaf, _ in leaves)
        assert total == self._size, f"키 수가 다름: 잎 {total} · 기록 {self._size}"

    def stats(self):
        """{높이, 잎 수, 안쪽 노드 수, 잎이 평균 몇 % 찼나}"""
        leaves = inner = 0
        stack = [self.root]
        while stack:
            node = stack.pop()
            if type(node) is _Leaf:
                leaves += 1
            else:
                inner += 1
                stack.extend(node.children)
        fill = self._size / (leaves * self.order) if leaves else 0.0
        return {"height": self.height(), "leaves": leaves, "inner": inner, "leaf_fill": round(fill, 3)}


def _even_slices(n, cap):
    """n 개를 cap 개 이하씩, 최대한 고르게 나눈 (시작, 끝) 목록. 묶음이 둘 이상이면 각 묶음은 cap 의 반 이상"""
    groups = -(-n // cap)  # 올림 나눗셈
    base, extra = divmod(n, groups)
    bounds = [g * base + min(g, extra) for g in range(groups + 1)]  # 앞쪽 extra 묶음이 하나씩 더 가진다
    return list(zip(bounds, bounds[1:]))
