"""In-memory B+Tree mapping integer IDs to byte offsets in a table file."""
from bisect import bisect_left, bisect_right

class _Node:
    def __init__(self, leaf): self.leaf = leaf; self.keys = []; self.values = []; self.children = []; self.next = None

class BPlusTree:
    def __init__(self, max_keys=31):
        if max_keys < 3: raise ValueError("max_keys must be at least 3")
        self.max_keys = max_keys; self.root = _Node(True); self.size = 0; self.last_visits = 0
    def get(self, key):
        node = self.root; visits = 0
        while True:
            visits += 1
            if node.leaf:
                i = bisect_left(node.keys, key); self.last_visits = visits
                return node.values[i] if i < len(node.keys) and node.keys[i] == key else None
            node = node.children[bisect_right(node.keys, key)]
    def insert(self, key, value):
        if not isinstance(key, int) or isinstance(key, bool): raise TypeError("B+Tree keys must be integers")
        if self.get(key) is not None: raise ValueError(f"duplicate key: {key}")
        split = self._insert(self.root, key, value)
        if split is not None:
            separator, right = split; root = _Node(False); root.keys = [separator]; root.children = [self.root, right]; self.root = root
        self.size += 1
    def _insert(self, node, key, value):
        if node.leaf:
            i = bisect_left(node.keys, key); node.keys.insert(i, key); node.values.insert(i, value)
            if len(node.keys) <= self.max_keys: return None
            middle = (len(node.keys) + 1) // 2; right = _Node(True)
            right.keys, node.keys = node.keys[middle:], node.keys[:middle]
            right.values, node.values = node.values[middle:], node.values[:middle]
            right.next = node.next; node.next = right
            return right.keys[0], right
        i = bisect_right(node.keys, key); split = self._insert(node.children[i], key, value)
        if split is None: return None
        separator, right = split; node.keys.insert(i, separator); node.children.insert(i + 1, right)
        if len(node.keys) <= self.max_keys: return None
        middle = len(node.keys) // 2; promoted = node.keys[middle]; right_node = _Node(False)
        right_node.keys, node.keys = node.keys[middle + 1:], node.keys[:middle]
        right_node.children, node.children = node.children[middle + 1:], node.children[:middle + 1]
        return promoted, right_node
    def items(self):
        node = self.root
        while not node.leaf: node = node.children[0]
        while node is not None:
            yield from zip(node.keys, node.values); node = node.next
